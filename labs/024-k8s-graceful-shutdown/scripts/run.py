import hashlib
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path
from settings import LAB,ROOT,KIND,KUBE,CLUSTER,IMAGE,FINALIZER,deployment,service,harness
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,utc
e=Evidence(LAB,'kind-rollout',[LAB/'go.mod', LAB/'src/main.go', LAB/'Dockerfile', LAB/'kind.yml', LAB/'scripts/settings.py', Path(__file__)],{'cases':['exit-now','drain'],'repeats':10,'inflight_requests':6,'task_finish_after_TERM_seconds':2,'shutdown_timeout_seconds':6,'pod_grace_seconds':8,'maxSurge':1,'maxUnavailable':0,'observe_old_pod_finalizer':FINALIZER,'cluster':CLUSTER})
failure=None;stream=None
def call(label,args,**kwargs):return e.require(label,KUBE+args,**kwargs)
def document(name,value):
    p=e.dest/'configs'/name;p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n');return p
def ctl(label,hname,target):
    raw=json.loads(call(label,['exec',hname,'-n','lab024','--','/app','-role','control','-target',target]))
    assert raw['status']==200 and raw['bytes']==len(raw['body'].encode())
    return json.loads(raw['body'])
def start_stream(label,pname):
    argv=KUBE+['logs','-f',pname,'-n','lab024']
    return {'label':label,'argv':argv,'started_utc':utc(),'tick':time.monotonic(),'process':subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)}
def finish_stream(s):
    p=s['process']
    try:out,err=p.communicate(timeout=20);code=p.returncode
    except subprocess.TimeoutExpired:p.kill();out,err=p.communicate(timeout=10);err+=b'\nRUNNER_STREAM_TIMEOUT\n';code=124
    target=e.dest/s['label'];target.mkdir(parents=True,exist_ok=False);(target/'stdout.txt').write_bytes(out);(target/'stderr.txt').write_bytes(err)
    e.data['commands'].append({'label':s['label'],'argv':s['argv'],'started_utc':s['started_utc'],'ended_utc':utc(),'elapsed_seconds':time.monotonic()-s['tick'],'exit_code':code,'timeout_cleanup':None})
    assert code==0,f'stream actual exit {code}'
    return [json.loads(l) for l in out.splitlines() if l]
def ready(p):return any(v['type']=='Ready' and v['status']=='True' for v in p.get('status',{}).get('conditions',[]))
try:
    setup=sorted((LAB/'results').glob('*-kind-setup/manifest.json'))[-1];env=json.loads(setup.read_text());assert env['all_passed']
    for n,v in env['source_sha256'].items():assert hashlib.sha256((LAB/n).read_bytes()).hexdigest()==v
    e.data['parameters']['setup_manifest']=setup.relative_to(ROOT).as_posix();e.data['parameters']['setup_manifest_sha256']=hashlib.sha256(setup.read_bytes()).hexdigest()
    e.require('kind-version',[KIND,'version']);call('server-version',['version','-o','json']);call('nodes',['get','nodes','-o','json'])
    img=json.loads(e.require('app-image-inspect',['docker','image','inspect',IMAGE]))[0];assert img['Id']==json.loads((setup.parent/'inspect-app-image/stdout.txt').read_text())[0]['Id']
    assert not json.loads(call('initial-pods',['get','pods','-n','lab024','-o','json']))['items']
    for mode in ['exit-now','drain']:
        for repeat in range(1,11):
            name=f'{mode}-{repeat:02d}';hname=name+'-harness';trial={'case':mode,'trial':repeat,'name':name,'passed':False};e.data['trials'].append(trial)
            config=document(name+'.json',{'apiVersion':'v1','kind':'List','items':[deployment(name,mode),service(name)]})
            call(name+'/create',['create','-f',str(config)])
            call(name+'/initial-rollout',['rollout','status','deployment/'+name,'-n','lab024','--timeout=60s'],timeout=75)
            oldlist=json.loads(call(name+'/initial-pods',['get','pods','-n','lab024','-l','app='+name,'-o','json']))['items'];assert len(oldlist)==1 and ready(oldlist[0])
            old=oldlist[0];oldname=old['metadata']['name'];olduid=old['metadata']['uid'];oldip=old['status']['podIP'];assert not old['metadata'].get('finalizers')
            finalizer=document(name+'-retain.json',{'metadata':{'finalizers':[FINALIZER]}})
            call(name+'/retain-old',['patch','pod',oldname,'-n','lab024','--type','merge','--patch-file',str(finalizer)])
            retained=json.loads(call(name+'/retained-pod',['get','pod',oldname,'-n','lab024','-o','json']));assert retained['metadata']['uid']==olduid and retained['metadata']['finalizers']==[FINALIZER]
            svc=json.loads(call(name+'/service',['get','service',name,'-n','lab024','-o','json']));backend='http://'+svc['spec']['clusterIP']+':8080'
            hs=document(name+'-harness.json',harness(hname,backend));call(name+'/create-harness',['create','-f',str(hs)])
            call(name+'/harness-ready',['wait','pod/'+hname,'-n','lab024','--for=condition=Ready','--timeout=60s'],timeout=75)
            stream=start_stream(name+'/old-log-stream',oldname)
            before_slices=json.loads(call(name+'/before-slices',['get','endpointslices','-n','lab024','-l','kubernetes.io/service-name='+name,'-o','json']))
            assert any(ep.get('targetRef',{}).get('uid')==olduid and ep['conditions'].get('ready') for sl in before_slices['items'] for ep in sl['endpoints'])
            assert ctl(name+'/start-requests',hname,'http://127.0.0.1:8081/run')['started']==6
            for j in range(1,61):
                state=ctl(name+f'/old-state-{j:02d}',hname,'http://'+oldip+':8080/state');assert state['pod_uid']==olduid
                if state['active']==6:break
                time.sleep(.2)
            else:raise AssertionError('Six actual old-Pod requests never became active')
            patch=document(name+'-rollout.json',{'spec':{'template':{'metadata':{'annotations':{'lab/revision':'new'}}}}})
            call(name+'/rollout-trigger',['patch','deployment',name,'-n','lab024','--type','merge','--patch-file',str(patch)])
            observations=[];start=time.monotonic();done=None;terminated=None
            for index in range(1,121):
                pods=json.loads(call(name+f'/pods-{index:03d}',['get','pods','-n','lab024','-l','app='+name,'-o','json']))['items']
                previous=next(p for p in pods if p['metadata']['uid']==olduid)
                others=[p for p in pods if p['metadata']['uid']!=olduid]
                slices=json.loads(call(name+f'/slices-{index:03d}',['get','endpointslices','-n','lab024','-l','kubernetes.io/service-name='+name,'-o','json']))
                responses=ctl(name+f'/responses-{index:03d}',hname,'http://127.0.0.1:8081/snapshot')
                terminated=(previous.get('status',{}).get('containerStatuses') or [{}])[0].get('state',{}).get('terminated')
                observations.append({'sample':index,'elapsed_ms':(time.monotonic()-start)*1000,'old_deletion_timestamp':previous['metadata'].get('deletionTimestamp'),'old_ready':ready(previous),'old_terminated':terminated,'new_pods':[{'uid':p['metadata']['uid'],'ready':ready(p)} for p in others],'completed':responses['completed'],'old_slice_conditions':[ep['conditions'] for sl in slices['items'] for ep in sl['endpoints'] if ep.get('targetRef',{}).get('uid')==olduid]})
                if terminated and responses['completed']==6 and any(ready(p) for p in others):done=responses;newpods=others;break
                time.sleep(.2)
            assert done is not None,'Rollout/requests did not finish within bounded observation'
            assert terminated['exitCode']==0
            assert len(done['results'])==6 and {r['ticket'] for r in done['results']}=={f'req{i}' for i in range(1,7)}
            assert all(not r['error'] and r['bytes']==len(r['body'].encode()) for r in done['results'])
            if mode=='exit-now':
                assert all(r['status']==502 and json.loads(r['body'])['upstream_error'] for r in done['results'])
            else:
                assert all(r['status']==200 and json.loads(r['body'])=={'ticket':r['ticket'],'value':42,'pod_uid':olduid} for r in done['results'])
            frames=finish_stream(stream);stream=None
            assert frames[0]['event']=='boot' and frames[0]['pid']==1 and all(v['pod_uid']==olduid for v in frames)
            enters=[v for v in frames if v['event']=='enter'];complete=[v for v in frames if v['event']=='complete'];signal=next(v for v in frames if v['event']=='signal')
            assert {v['ticket'] for v in enters}=={f'req{i}' for i in range(1,7)} and len(enters)==6 and signal['signal']=='terminated' and signal['active']==6
            assert all(v['uptime_ms']<signal['uptime_ms'] for v in enters)
            if mode=='drain':
                assert len(complete)==6 and all(not v['write_error'] for v in complete)
                assert frames[-2]['event']=='shutdown' and not frames[-2]['error'] and frames[-2]['active']==0 and frames[-1]['active']==0
            else:assert not complete and frames[-1]['active']==6
            logs=call(name+'/harness-log',['logs',hname,'-n','lab024']);hf=[json.loads(l) for l in logs.splitlines() if l];finishes=[v for v in hf if v['event']=='request-finish']
            assert len(finishes)==6 and {v['ticket'] for v in finishes}=={r['ticket'] for r in done['results']}
            call(name+'/old-final-pod',['get','pod',oldname,'-n','lab024','-o','json']);call(name+'/old-events',['get','events','-n','lab024','--field-selector','involvedObject.uid='+olduid,'-o','json'])
            release=document(name+'-release.json',{'metadata':{'finalizers':[]}})
            call(name+'/release-old',['patch','pod',oldname,'-n','lab024','--type','merge','--patch-file',str(release)])
            call(name+'/final-rollout',['rollout','status','deployment/'+name,'-n','lab024','--timeout=60s'],timeout=75)
            call(name+'/final-deployment',['get','deployment',name,'-n','lab024','-o','json']);call(name+'/replicasets',['get','replicasets','-n','lab024','-l','app='+name,'-o','json']);call(name+'/final-pods',['get','pods','-n','lab024','-l','app='+name,'-o','json']);call(name+'/final-slices',['get','endpointslices','-n','lab024','-l','kubernetes.io/service-name='+name,'-o','json'])
            (e.dest/name/'observations.json').write_text(json.dumps(observations,indent=2)+'\n',encoding='utf-8',newline='\n')
            call(name+'/delete-resources',['delete','deployment/'+name,'service/'+name,'pod/'+hname,'-n','lab024','--wait=true','--timeout=60s'],timeout=75)
            trial.update(passed=True,old_pod_uid=olduid,old_pod_name=oldname,new_pod_uids=[p['metadata']['uid'] for p in newpods],requests=6,status=502 if mode=='exit-now' else 200,old_exit_code=0,signal_uptime_ms=signal['uptime_ms'],exit_uptime_ms=frames[-1]['uptime_ms'],observations=len(observations))
            print(f'{name}: PASS six HTTP{trial["status"]}, old exit0',flush=True)
    # Deployment deletion can finish before background Pod deletion converges.
    cleanup_deadline=time.monotonic()+60
    cleanup_poll=0
    while True:
        pending=json.loads(call(f'final-pods-wait-{cleanup_poll:03}',
                                ['get','pods','-n','lab024','-o','json']))['items']
        if not pending:break
        if time.monotonic()>=cleanup_deadline:
            raise TimeoutError('Owned Pods remain after the cleanup deadline')
        cleanup_poll+=1
        time.sleep(.25)
    assert not json.loads(call('final-pods',['get','pods','-n','lab024','-o','json']))['items']
    assert not json.loads(call('final-deployments',['get','deployments','-n','lab024','-o','json']))['items']
except BaseException as exc:failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
    if stream is not None:
        try:finish_stream(stream)
        except BaseException as exc:failure=(failure or '')+'; stream cleanup: '+str(exc)
    passed=e.seal(failure)
raise SystemExit(0 if passed else 1)
