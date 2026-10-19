import argparse
import hashlib
import json
import os
import socket
import time
from pathlib import Path
import numpy as np
import torch
import transformers
from transformers import AutoModel,AutoTokenizer
from evaluation import evaluate
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
a=argparse.ArgumentParser();a.add_argument('--out',type=Path,required=True);a.add_argument('--round',type=int,required=True);args=a.parse_args()
d=args.out;d.mkdir(parents=True,exist_ok=False)
revision='7999e1d3359715c523056ef9478215996d62a620';cache=ROOT/'.work/models/bge-small-zh-v1.5'/revision
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
setup=next(p for p in sorted((ROOT/'labs/028-rag-chunk-recall/results').glob('*-model-bootstrap/manifest.json')) if json.loads(p.read_bytes())['all_passed'])
files=json.loads((setup.parent/'downloads.json').read_bytes())
for f in files:
    if 'file' in f:assert sha(cache/f['file'])==f['sha256']
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
attempts=[]
def denied(*args,**kwargs):attempts.append(repr(args[1:]));raise RuntimeError('offline socket prohibited')
socket.socket.connect=denied;socket.socket.connect_ex=denied
torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(20261004);torch.use_deterministic_algorithms(True)
tokenizer=AutoTokenizer.from_pretrained(cache,local_files_only=True);model=AutoModel.from_pretrained(cache,local_files_only=True);model.eval()
assert model.config.hidden_size==512 and str(next(model.parameters()).device)=='cpu'
fixture=json.loads((LAB/'data/fixture.json').read_bytes());instruction='为这个句子生成表示以用于检索相关文章：'
tokens=[]
def encode(texts):
    vectors=[]
    for n in range(0,len(texts),8):
        batch=texts[n:n+8];raw=tokenizer(batch,padding=False,truncation=False);counts=[len(x) for x in raw['input_ids']];tokens.extend(counts);assert max(counts)<=512
        inputs=tokenizer(batch,padding=True,truncation=False,return_tensors='pt')
        with torch.inference_mode():v=torch.nn.functional.normalize(model(**inputs).last_hidden_state[:,0],p=2,dim=1)
        vectors.append(v.cpu().numpy())
    return np.concatenate(vectors).astype(np.float32)
dv=encode([x['text'] for x in fixture['docs']]);qv=encode([instruction+x['text'] for x in fixture['queries']])
scores=qv@dv.T
for name,v in [('doc-vectors.npy',dv),('query-vectors.npy',qv),('scores.npy',scores)]:np.save(d/name,v,allow_pickle=False)
result=evaluate(fixture,scores)
result.update({'round':args.round,'worker_pid':os.getpid(),'model_revision':revision,'weights_sha256':sha(cache/'model.safetensors'),'fixture_sha256':sha(LAB/'data/fixture.json'),
               'torch':torch.__version__,'transformers':transformers.__version__,'numpy':np.__version__,'instruction':instruction,'tokens':tokens,'device':'cpu','socket_attempts':attempts})
assert not attempts
(d/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'round':args.round,'policies':result['policies']},ensure_ascii=False),flush=True)
