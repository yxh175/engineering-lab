import hashlib,json,os,sys,time,traceback,urllib.request
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
REV='7999e1d3359715c523056ef9478215996d62a620';MODEL='BAAI/bge-small-zh-v1.5'
VENV=ROOT/'.work/rag-venv';PY=VENV/'Scripts/python.exe';CACHE=ROOT/'.work/models/bge-small-zh-v1.5'/REV
e=Evidence(LAB,'model-bootstrap',[Path(__file__), LAB/'requirements.txt'],{'model':MODEL,'revision':REV,'cache':str(CACHE),'torch':'2.6.0+cpu','transformers':'4.49.0'})
failure=None
def get(url,dest):
    tick=time.monotonic()
    with urllib.request.urlopen(url,timeout=60) as r:
        assert r.status==200
        with dest.open('wb') as f:
            while True:
                b=r.read(1048576)
                if not b:break
                f.write(b)
        return {'url':url,'final_url':r.url,'status':r.status,'elapsed_seconds':time.monotonic()-tick,'size':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
try:
    assert os.name=='nt' and sys.version_info[:2]==(3,12)
    assert not PY.exists(),'fresh bootstrap requires absent dedicated rag-venv'
    e.require('create-venv',[sys.executable,'-m','venv',str(VENV)],timeout=120)
    e.require('install-torch',[str(PY),'-m','pip','install','torch==2.6.0+cpu','--index-url','https://download.pytorch.org/whl/cpu','--report',str(e.dest/'torch-install-report.json'),'--retries','2'],timeout=360)
    e.require('install-transformers',[str(PY),'-m','pip','install','-r',str(LAB/'requirements.txt'),'--report',str(e.dest/'transformers-install-report.json'),'--retries','2'],timeout=240)
    e.require('pip-freeze',[str(PY),'-m','pip','freeze']);e.require('pip-check',[str(PY),'-m','pip','check'])
    downloads=[];downloads.append(get(f'https://huggingface.co/api/models/{MODEL}/revision/{REV}?blobs=true',e.dest/'model-api.json'))
    meta=json.loads((e.dest/'model-api.json').read_text());assert meta['sha']==REV
    siblings={v['rfilename']:v for v in meta['siblings']};files=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','model.safetensors','README.md','1_Pooling/config.json','sentence_bert_config.json','config_sentence_transformers.json']
    CACHE.mkdir(parents=True,exist_ok=False)
    for name in files:
        assert name in siblings,(name,'absent official repository file')
        dest=CACHE/name;dest.parent.mkdir(exist_ok=True);info=get(f'https://huggingface.co/{MODEL}/resolve/{REV}/{name}',dest);info['file']=name
        if 'lfs' in siblings[name]:assert info['sha256']==siblings[name]['lfs']['sha256'] and info['size']==siblings[name]['lfs']['size']
        downloads.append(info);print(f'{name} {info["size"]} bytes SHA {info["sha256"]}',flush=True)
    (e.dest/'downloads.json').write_text(json.dumps(downloads,indent=2)+'\n',encoding='utf-8',newline='\n')
    code='import torch,transformers,sys,json;from transformers import AutoModel,AutoTokenizer;p='+repr(str(CACHE))+';m=AutoModel.from_pretrained(p,local_files_only=True);t=AutoTokenizer.from_pretrained(p,local_files_only=True);print(json.dumps({"python":sys.version,"torch":torch.__version__,"transformers":transformers.__version__,"model_type":m.config.model_type,"hidden_size":m.config.hidden_size,"max_position_embeddings":m.config.max_position_embeddings,"parameters":sum(x.numel() for x in m.parameters()),"tokenizer_class":type(t).__name__,"cuda_available":torch.cuda.is_available()}))'
    version=json.loads(e.require('local-model-load',[str(PY),'-c',code],timeout=90));assert version['torch']=='2.6.0+cpu' and version['transformers']=='4.49.0' and version['hidden_size']==512 and not version['cuda_available']
    e.data['trials'].append({'case':'official-fixed-revision-local-model-loaded','passed':True})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'official-fixed-revision-local-model-loaded','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
