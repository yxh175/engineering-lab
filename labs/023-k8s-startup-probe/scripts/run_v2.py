import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from settings import LAB,ROOT,KIND,KUBE,CLUSTER,NODE,IMAGE,pod
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
sources=[LAB/'go.mod', LAB/'src/main.go', LAB/'Dockerfile', LAB/'kind.yml', LAB/'scripts/settings.py', Path(__file__)]
e=Evidence(LAB,'kind-probes',sources,{'cases':['early-live','startup-gated'],'repeats':10,'warm_seconds':15,'poll_sleep_seconds':.5,'liveness_period_seconds':1,'liveness_failure_threshold':3,'startup_period_seconds':1,'startup_failure_threshold':30,'grace_seconds':1,'cluster':CLUSTER})
failure=None
def call(label,args,**kwargs):return e.require(label,KUBE+args,**kwargs)
def frames(raw):
    values=[json.loads(line) for line in raw.splitlines() if line.strip()]
    assert values and values[0]['event']=='boot' and values[0]['pid']==1
    assert len({v['instance'] for v in values})==1
    return values
def state(p):
    c=(p.get('status',{}).get('containerStatuses') or [{}])[0]
    return c,any(c['type']=='Ready' and c['status']=='True' for c in p.get('status',{}).get('conditions',[]))
try:
    setup=sorted((LAB/'results').glob('*-kind-setup/manifest.json'))[-1]
    environment=json.loads(setup.read_text(encoding='utf-8'));assert environment['all_passed']
    for name,value in environment['source_sha256'].items():assert hashlib.sha256((LAB/name).read_bytes()).hexdigest()==value
    e.data['parameters']['setup_manifest']=setup.relative_to(ROOT).as_posix()
    e.data['parameters']['setup_manifest_sha256']=hashlib.sha256(setup.read_bytes()).hexdigest()
    e.require('kind-version',[KIND,'version']);call('server-version',['version','-o','json']);call('nodes',['get','nodes','-o','json'])
    image=json.loads(e.require('app-image-inspect',['docker','image','inspect',IMAGE]))[0]
    expected=json.loads((setup.parent/'inspect-app-image/stdout.txt').read_text())[0]
    assert image['Id']==expected['Id'];e.data['parameters']['app_image_id']=image['Id']
    call('initial-pods',['get','pods','-n','lab023','-o','json'])
    for case in ['early-live','startup-gated']:
        for repeat in range(1,11):
            name=f'{case}-{repeat:02d}';trial={'case':case,'trial':repeat,'name':name,'passed':False}
            e.data['trials'].append(trial)
            config=e.dest/'configs'/f'{name}.json';config.parent.mkdir(exist_ok=True)
            config.write_text(json.dumps(pod(name,case),indent=2)+'\n',encoding='utf-8',newline='\n')
            call(name+'/create',['create','-f',str(config)])
            epoch=time.monotonic();observations=[];first=None;uid=None;index=0
            deadline=epoch+120
            while time.monotonic()<deadline:
                index+=1
                p=json.loads(call(name+f'/poll-{index:03d}',['get','pod',name,'-n','lab023','-o','json']))
                c,ready=state(p);observations.append({'poll':index,'elapsed_ms':(time.monotonic()-epoch)*1000,'restart_count':c.get('restartCount',0),'ready':ready,'started':c.get('started'),'state':c.get('state')})
                uid=uid or p['metadata']['uid'];assert p['metadata']['uid']==uid
                if case=='early-live':
                    assert not ready,'Unexpected successful initialization in early-live case'
                    if c.get('restartCount',0)>=1 and first is None:
                        first=frames(call(name+'/first-previous',['logs',name,'-n','lab023','--previous']))
                        assert any(v['event']=='signal' and v['signal']=='terminated' for v in first)
                        assert any(v['event']=='exit' and v['exit_code']==0 for v in first)
                        assert not any(v['event']=='probe' and v['status']==200 for v in first)
                    if c.get('restartCount',0)>=2:break
                elif ready:
                    assert c['restartCount']==0 and c['started'] is True
                    before=p;before_log=frames(call(name+'/before-logs',['logs',name,'-n','lab023']))
                    started=[v for v in before_log if v['event']=='probe' and v['path']=='/start']
                    assert any(v['status']==503 for v in started) and any(v['status']==200 for v in started)
                    gate=min(v['uptime_ms'] for v in started if v['status']==200)
                    assert gate>=15000 and all(v['uptime_ms']>=gate for v in before_log if v['event']=='probe' and v['path']!='/start')
                    for step in range(1,21):
                        before_log=frames(call(name+f'/healthy-logs-{step:02d}',['logs',name,'-n','lab023']))
                        if any(v['event']=='probe' and v['path']=='/live' and v['status']==200 for v in before_log):break
                        time.sleep(.2)
                    else:raise AssertionError('No actual healthy liveness response after Ready')
                    call(name+'/before-pod',['get','pod',name,'-n','lab023','-o','json'])
                    marker=json.loads(call(name+'/inject',['exec',name,'-n','lab023','--','/app','-poison']))
                    assert marker['poison_written'] is True
                    injected=(time.monotonic()-epoch)*1000
                    while time.monotonic()<deadline:
                        index+=1
                        p=json.loads(call(name+f'/poll-{index:03d}',['get','pod',name,'-n','lab023','-o','json']))
                        c,ready=state(p);observations.append({'poll':index,'elapsed_ms':(time.monotonic()-epoch)*1000,'restart_count':c.get('restartCount',0),'ready':ready,'started':c.get('started'),'state':c.get('state')})
                        if c.get('restartCount',0)>=1:break
                        time.sleep(.5)
                    assert c.get('restartCount',0)>=1,'Post-start liveness did not restart container'
                    trial.update(initial_ready_restart_count=before['status']['containerStatuses'][0]['restartCount'],first_startup_success_ms=gate,inject_observed_ms=injected)
                    break
                time.sleep(.5)
            else:raise AssertionError(f'{name} observation deadline exceeded')
            assert c.get('restartCount',0)>=(2 if case=='early-live' else 1)
            final=json.loads(call(name+'/after-pod',['get','pod',name,'-n','lab023','-o','json']))
            previous=frames(call(name+'/last-previous',['logs',name,'-n','lab023','--previous']))
            events=json.loads(call(name+'/events',['get','events','-n','lab023','--field-selector','involvedObject.uid='+uid,'-o','json']))
            assert all(v['involvedObject']['uid']==uid for v in events['items'])
            assert any(v['reason']=='Killing' and 'liveness' in v['message'] for v in events['items'])
            assert any(v['reason']=='Unhealthy' and 'Liveness' in v['message'] for v in events['items'])
            assert any(v['event']=='signal' and v['signal']=='terminated' for v in previous)
            assert any(v['event']=='exit' and v['exit_code']==0 for v in previous)
            terminated=final['status']['containerStatuses'][0]['lastState']['terminated']
            assert terminated['exitCode']==0
            if case=='early-live':
                assert not any(v['event']=='probe' and v['status']==200 for v in previous)
                assert first[0]['instance']!=previous[0]['instance']
            else:
                assert previous[0]['instance']==before_log[0]['instance']
                assert any(v['event']=='probe' and v['path']=='/live' and v['status']==503 and v['poisoned'] for v in previous)
            (e.dest/name/'observations.json').write_text(json.dumps(observations,indent=2)+'\n',encoding='utf-8',newline='\n')
            call(name+'/delete',['delete','pod',name,'-n','lab023','--wait=true','--timeout=30s'],timeout=45)
            trial.update(passed=True,pod_uid=uid,restart_count=final['status']['containerStatuses'][0]['restartCount'],previous_exit_code=terminated['exitCode'],previous_lifetime_ms=next(v['uptime_ms'] for v in previous if v['event']=='exit'),polls=index)
            print(f'{name}: PASS actual restarts={trial["restart_count"]}, previous_exit=0',flush=True)
    assert not json.loads(call('final-pods',['get','pods','-n','lab023','-o','json']))['items']
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
    passed=e.seal(failure)
raise SystemExit(0 if passed else 1)
