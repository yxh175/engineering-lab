import json
import sys
import time
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify,milli
CLUSTER='engineering-lab-046';NODE=CLUSTER+'-control-plane';IMAGE='engineering-lab-046:go1254'
NODE_IMAGE='kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48'
KIND='kind';CONFIG=LAB/'.work/kubeconfig'
KUBE=['kubectl','--kubeconfig',str(CONFIG),'--request-timeout=10s']
e=Evidence(LAB,'kind-requests',[LAB/p for p in ['go.mod', 'src/main.go', 'Dockerfile', 'kind.yml', 'src/verify.py', 'scripts/run.py']],{'rounds':10,'cluster':CLUSTER,'node_image':NODE_IMAGE,'reasonable_millicpu':20,'high_above_allocatable':1000,'cpu_sample_scope':'Linux VM shared /proc/stat, not per-node request availability'})
failure=None;owned=False
def call(label,args,**kw):return e.require(label,KUBE+args,**kw)
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=io.x-k8s.kind.cluster='+CLUSTER]).strip()
    e.require('kind-version',[KIND,'version']);e.require('kubectl-client',['kubectl','version','--client','-o','json'])
    e.require('node-image',['docker','image','inspect',NODE_IMAGE])
    e.require('build-app',['docker','build','--network','none','--tag',IMAGE,str(LAB)],timeout=180)
    e.require('app-image',['docker','image','inspect',IMAGE])
    CONFIG.parent.mkdir(exist_ok=True);owned=True
    e.require('cluster-create',[KIND,'create','cluster','--name',CLUSTER,'--image',NODE_IMAGE,'--config',str(LAB/'kind.yml'),'--kubeconfig',str(CONFIG),'--wait','120s'],timeout=300)
    call('server-version',['version','-o','json'])
    e.require('cluster-inspect',['docker','inspect',NODE])
    e.require('load-app',[KIND,'load','docker-image',IMAGE,'--name',CLUSTER],timeout=120)
    call('namespace',['create','namespace','lab046'])
    call('node-ready',['wait','--for=condition=Ready','node/'+NODE,'--timeout=90s'],timeout=100)
    nodes=json.loads(call('nodes',['get','nodes','-o','json']))['items'];assert len(nodes)==1
    alloc=milli(nodes[0]['status']['allocatable']['cpu']);assert alloc>1000
    call('node-describe',['describe','node',NODE])
    for n in range(1,11):
        for case in (['oversized','reasonable'] if n%2 else ['reasonable','oversized']):
            label=f'{case}-{n:02}';req=alloc+1000 if case=='oversized' else 20
            pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':label,'namespace':'lab046','labels':{'lab':'046','case':case}},
                'spec':{'automountServiceAccountToken':False,'restartPolicy':'Never','terminationGracePeriodSeconds':2,
                    'containers':[{'name':'app','image':IMAGE,'imagePullPolicy':'Never','resources':{'requests':{'cpu':f'{req}m','memory':'8Mi'},'limits':{'memory':'32Mi'}}}]}}
            cfg=e.dest/'configs'/f'{label}.json';cfg.parent.mkdir(exist_ok=True);cfg.write_text(json.dumps(pod,indent=2)+'\n',encoding='utf-8',newline='\n')
            call(label+'/create',['create','-f',str(cfg)])
            deadline=time.perf_counter()+60;uid=None;i=0
            while True:
                i+=1;p=json.loads(call(label+f'/poll-{i:03}',['get','pod',label,'-n','lab046','-o','json']))
                uid=uid or p['metadata']['uid'];assert p['metadata']['uid']==uid
                conditions={v['type']:v for v in p.get('status',{}).get('conditions',[])}
                if case=='oversized' and conditions.get('PodScheduled',{}).get('reason')=='Unschedulable':break
                if case=='reasonable' and conditions.get('Ready',{}).get('status')=='True':break
                assert time.perf_counter()<deadline,'Pod observation deadline';time.sleep(.25)
            call(label+'/final-pod',['get','pod',label,'-n','lab046','-o','json'])
            call(label+'/events',['get','events','-n','lab046','--field-selector','involvedObject.uid='+uid,'-o','json'])
            call(label+'/describe',['describe','pod',label,'-n','lab046'])
            if case=='reasonable':call(label+'/logs',['logs',label,'-n','lab046'])
            e.require(label+'/cpu-before',['docker','exec',NODE,'cat','/proc/stat'])
            time.sleep(1)
            e.require(label+'/cpu-after',['docker','exec',NODE,'cat','/proc/stat'])
            call(label+'/delete',['delete','pod',label,'-n','lab046','--wait=true','--timeout=20s'],timeout=30)
            call(label+'/after-delete',['get','pods','-n','lab046','-o','json'])
            checked=verify(case,e.dest,label,alloc);e.data['trials'].append({'round':n,'label':label,**checked})
            print(f'{label}: {checked["phase"]}, request={req}m alloc={alloc}m VMbusy={checked["vm_cpu_busy_fraction"]:.3%}',flush=True)
    call('final-all-pods',['get','pods','-A','-o','json'])
except Exception as exc:failure=repr(exc);raise
finally:
    if owned:
        try:
            e.require('cluster-delete',[KIND,'delete','cluster','--name',CLUSTER],timeout=120)
            assert not e.require('after-owned',['docker','ps','-aq','--filter','label=io.x-k8s.kind.cluster='+CLUSTER]).strip()
        except Exception as exc:failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
