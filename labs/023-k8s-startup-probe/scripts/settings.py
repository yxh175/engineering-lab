import os
from pathlib import Path
LAB=Path(__file__).resolve().parents[1]
ROOT=LAB.parents[1]
CLUSTER='engineering-lab-023'
NODE=CLUSTER+'-control-plane'
NODE_IMAGE='kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48'
KIND=os.environ.get('LAB023_KIND','kind')
KUBE=['kubectl','--kubeconfig',str(LAB/'.work/kubeconfig'),'--request-timeout=10s']
IMAGE='engineering-lab-023:go1254'
def pod(name,case):
    probe=lambda path,n:{'httpGet':{'path':path,'port':8080},'periodSeconds':1,'timeoutSeconds':1,'failureThreshold':n}
    c={'name':'app','image':IMAGE,'imagePullPolicy':'Never','args':['-warm','15s'],'ports':[{'containerPort':8080}],
       'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'1','memory':'64Mi'}},
       'volumeMounts':[{'name':'tmp','mountPath':'/tmp'}],
       'livenessProbe':probe('/live',3),'readinessProbe':probe('/ready',1)}
    if case=='startup-gated':c['startupProbe']=probe('/start',30)
    else:assert case=='early-live'
    return {'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':'lab023','labels':{'lab':'023','case':case}},
            'spec':{'restartPolicy':'Always','terminationGracePeriodSeconds':1,'automountServiceAccountToken':False,
                    'securityContext':{'runAsUser':65532,'runAsGroup':65532,'fsGroup':65532},
                    'containers':[c],'volumes':[{'name':'tmp','emptyDir':{'medium':'Memory','sizeLimit':'1Mi'}}]}}
