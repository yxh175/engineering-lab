import hashlib
import json
import sys
import traceback
import urllib.request
from pathlib import Path
from settings import LAB,ROOT,KIND,KUBE,CLUSTER,NODE,NODE_IMAGE,IMAGE
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'kind-setup',[Path(__file__), LAB/'scripts/settings.py', LAB/'Dockerfile', LAB/'kind.yml', LAB/'go.mod', LAB/'src/main.go'],{'cluster':CLUSTER,'node_image':NODE_IMAGE,'no_global_kubeconfig':True})
failure=None
try:
    (LAB/'.work').mkdir(exist_ok=True)
    e.require('kind-version',[KIND,'version']);e.require('kubectl-client',['kubectl','version','--client','-o','json']);e.require('docker-version',['docker','version'])
    if Path(KIND).is_file():
        url='https://github.com/kubernetes-sigs/kind/releases/download/v0.31.0/kind-'+('windows-amd64' if sys.platform=='win32' else 'linux-amd64')+'.sha256sum'
        b=urllib.request.urlopen(url,timeout=60).read();(e.dest/'official-kind-sha256.txt').write_bytes(b)
        actual=hashlib.sha256(Path(KIND).read_bytes()).hexdigest()
        assert actual==b.decode().split()[0]
        (e.dest/'kind-binary-provenance.json').write_text(json.dumps({'sha256':actual,'checksum_url':url,'download_url':url.removesuffix('.sha256sum')})+'\n')
    assert not e.require('existing-cluster-check',['docker','ps','-a','-q','--filter','label=io.x-k8s.kind.cluster='+CLUSTER]).strip(),'Do not reuse/delete an unexplained existing cluster'
    e.require('pull-node',['docker','pull',NODE_IMAGE],timeout=600)
    e.require('inspect-node-image',['docker','image','inspect',NODE_IMAGE])
    e.require('create-cluster',[KIND,'create','cluster','--name',CLUSTER,'--image',NODE_IMAGE,'--config',str(LAB/'kind.yml'),'--kubeconfig',str(LAB/'.work/kubeconfig'),'--wait','120s'],timeout=300)
    e.require('server-version',KUBE+['version','-o','json']);e.require('nodes',KUBE+['get','nodes','-o','json']);e.require('node-container-inspect',['docker','inspect',NODE])
    e.require('build-app',['docker','build','--tag',IMAGE,str(LAB)],timeout=180)
    e.require('inspect-app-image',['docker','image','inspect',IMAGE])
    e.require('load-app',[KIND,'load','docker-image',IMAGE,'--name',CLUSTER],timeout=120)
    e.require('node-cri-images',['docker','exec',NODE,'crictl','images','-o','json'])
    e.require('namespace',KUBE+['create','namespace','lab023'])
    e.data['trials'].append({'case':'isolated-kind-environment','passed':True})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
    e.data['trials'].append({'case':'isolated-kind-environment','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
