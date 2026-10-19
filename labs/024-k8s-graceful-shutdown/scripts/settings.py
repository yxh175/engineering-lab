import os
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
CLUSTER='engineering-lab-024';NODE=CLUSTER+'-control-plane'
NODE_IMAGE='kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48'
KIND=os.environ.get('LAB024_KIND','kind')
KUBE=['kubectl','--kubeconfig',str(LAB/'.work/kubeconfig'),'--request-timeout=10s']
IMAGE='engineering-lab-024:go1254'
FINALIZER='engineering-lab.local/evidence'
def deployment(name,mode):
    c={'name':'app','image':IMAGE,'imagePullPolicy':'Never','args':['-role','app','-mode',mode],
       'env':[{'name':'POD_UID','valueFrom':{'fieldRef':{'fieldPath':'metadata.uid'}}}],
       'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'1','memory':'64Mi'}},
       'readinessProbe':{'httpGet':{'path':'/ready','port':8080},'periodSeconds':1,'failureThreshold':1}}
    return {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name,'namespace':'lab024'},
            'spec':{'replicas':1,'selector':{'matchLabels':{'app':name}},'strategy':{'type':'RollingUpdate','rollingUpdate':{'maxSurge':1,'maxUnavailable':0}},
            'template':{'metadata':{'labels':{'app':name},'annotations':{'lab/revision':'old'}},'spec':{'automountServiceAccountToken':False,'terminationGracePeriodSeconds':8,'containers':[c]}}}}
def service(name):
    return {'apiVersion':'v1','kind':'Service','metadata':{'name':name,'namespace':'lab024'},'spec':{'selector':{'app':name},'ports':[{'port':8080,'targetPort':8080}]}}
def harness(name,backend):
    return {'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':'lab024','labels':{'lab':'024','role':'harness'}},
            'spec':{'automountServiceAccountToken':False,'terminationGracePeriodSeconds':1,'containers':[{'name':'app','image':IMAGE,'imagePullPolicy':'Never','args':['-role','harness','-target',backend],'readinessProbe':{'httpGet':{'path':'/snapshot','port':8081},'periodSeconds':1},'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'1','memory':'64Mi'}}}]}}
