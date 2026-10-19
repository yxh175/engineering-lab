import json
import sys
from pathlib import Path
from settings import LAB,ROOT,KIND,KUBE,CLUSTER,NODE
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'cleanup',[Path(__file__),LAB/'scripts/settings.py'],{'cluster':CLUSTER,'leave_shared_kind_network':True,'local_kubeconfig':True})
failure=None
try:
    assert not json.loads(e.require('final-owned-pods',KUBE+['get','pods','-n','lab023','-o','json']))['items']
    e.require('kernel',['docker','exec',NODE,'cat','/proc/version'])
    e.require('kubelet-config',['docker','exec',NODE,'cat','/var/lib/kubelet/config.yaml'])
    e.require('delete-cluster',[KIND,'delete','cluster','--name',CLUSTER,'--kubeconfig',str(LAB/'.work/kubeconfig')],timeout=120)
    assert not e.require('remaining-owned-nodes',['docker','ps','-a','-q','--filter','label=io.x-k8s.kind.cluster='+CLUSTER]).strip()
    clusters=e.require('kind-clusters',[KIND,'get','clusters']).decode().splitlines();assert CLUSTER not in clusters
    e.data['trials'].append({'case':'owned-cluster-cleanup','passed':True})
except BaseException as exc:failure=str(exc);e.data['trials'].append({'case':'owned-cluster-cleanup','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
