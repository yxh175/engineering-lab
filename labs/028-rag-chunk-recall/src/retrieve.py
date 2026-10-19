import argparse,hashlib,json,os,platform,socket,time
from pathlib import Path
import numpy as np
import torch
import transformers
from transformers import AutoModel,AutoTokenizer
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--round',type=int,required=True);p.add_argument('--bootstrap',required=True);a=p.parse_args()
OUT=Path(a.out);OUT.mkdir(exist_ok=False);bootstrap=Path(a.bootstrap);meta=json.loads(bootstrap.read_text(encoding='utf-8'));CACHE=Path(meta['parameters']['cache']);tick=time.monotonic()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
files=json.loads((bootstrap.parent/'downloads.json').read_text(encoding='utf-8'))
for f in files:
    if 'file' in f:assert sha(CACHE/f['file'])==f['sha256']
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
attempts=[]
def denied(*args,**kwargs):attempts.append(repr(args[1:]));raise RuntimeError('offline inference forbids socket connection')
socket.socket.connect=denied;socket.socket.connect_ex=denied
torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(20261004);torch.use_deterministic_algorithms(True)
tokenizer=AutoTokenizer.from_pretrained(CACHE,local_files_only=True);model=AutoModel.from_pretrained(CACHE,local_files_only=True);model.eval()
assert model.config.hidden_size==512 and model.config.max_position_embeddings==512 and str(next(model.parameters()).device)=='cpu'
docs=json.loads((LAB/'data/corpus.json').read_text(encoding='utf-8'));queries=json.loads((LAB/'data/qrels.json').read_text(encoding='utf-8'));bydoc={d['doc_id']:d for d in docs}
assert len(docs)==16 and len(queries)==24 and len(bydoc)==len(docs)
for q in queries:
    assert len(q['relevant_doc_ids'])==1 and len(q['evidence'])==1
    ev=q['evidence'][0];assert ev['doc_id']==q['relevant_doc_ids'][0] and bydoc[ev['doc_id']]['text'][ev['start']:ev['end']]==ev['text']
def encode(texts):
    vectors=[];counts=[]
    for start in range(0,len(texts),8):
        batch=texts[start:start+8];raw=tokenizer(batch,padding=False,truncation=False);counts.extend(map(len,raw['input_ids']));assert max(map(len,raw['input_ids']))<=512
        batch=tokenizer(batch,padding=True,truncation=False,return_tensors='pt')
        with torch.inference_mode():
            outputs=model(**batch).last_hidden_state[:,0];outputs=torch.nn.functional.normalize(outputs,p=2,dim=1)
        vectors.append(outputs.cpu().numpy())
    result=np.concatenate(vectors).astype(np.float32);assert np.isfinite(result).all() and result.shape==(len(texts),512) and np.allclose(np.linalg.norm(result,axis=1),1,atol=2e-6)
    return result,counts
instruction='为这个句子生成表示以用于检索相关文章：'
qvectors,qtokens=encode([instruction+q['query'] for q in queries]);np.save(OUT/'query-vectors.npy',qvectors,allow_pickle=False)
policies=[('char64-overlap0',64,0),('char192-overlap0',192,0),('char192-overlap96',192,96),('char384-overlap0',384,0)];rotation=(a.round-1)%len(policies);policies=policies[rotation:]+policies[:rotation];summary=[]
def union_size(intervals):
    end=-1;total=0
    for start,stop in sorted(intervals):total+=max(0,stop-max(start,end));end=max(end,stop)
    return total
for case,size,overlap in policies:
    started=time.monotonic();dest=OUT/case;dest.mkdir();chunks=[]
    for doc in docs:
        for start in range(0,len(doc['text']),size-overlap):
            end=min(start+size,len(doc['text']));chunks.append({'chunk_id':f'{doc["doc_id"]}:{start:05d}:{end:05d}','doc_id':doc['doc_id'],'start':start,'end':end,'text':doc['text'][start:end]})
            if end==len(doc['text']):break
    cvectors,ctokens=encode([c['text'] for c in chunks])
    for c,n in zip(chunks,ctokens):c['embedding_token_count']=n
    scores=qvectors@cvectors.T;np.save(dest/'chunk-vectors.npy',cvectors,allow_pickle=False);np.save(dest/'cosine-scores.npy',scores,allow_pickle=False)
    (dest/'chunks.json').write_text(json.dumps(chunks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    results=[]
    for qi,q in enumerate(queries):
        order=sorted(range(len(chunks)),key=lambda j:(-float(scores[qi,j]),chunks[j]['chunk_id']));ranked=[chunks[j] for j in order];rel=set(q['relevant_doc_ids']);ev=q['evidence'][0];top=ranked[:3]
        recalls={str(k):len({c['doc_id'] for c in ranked[:k]}&rel)/len(rel) for k in [1,3,5]}
        first=next((i for i,c in enumerate(ranked[:10],1) if c['doc_id'] in rel),None)
        single=any(c['doc_id']==ev['doc_id'] and c['start']<=ev['start'] and c['end']>=ev['end'] for c in top)
        clipped=[(max(c['start'],ev['start']),min(c['end'],ev['end'])) for c in top if c['doc_id']==ev['doc_id'] and max(c['start'],ev['start'])<min(c['end'],ev['end'])];covered=union_size(clipped)
        selected_chars=sum(len(c['text']) for c in top);unique_chars=sum(union_size([(c['start'],c['end']) for c in top if c['doc_id']==doc]) for doc in {c['doc_id'] for c in top})
        results.append({'query_id':q['query_id'],'query':q['query'],'ranking':[{'chunk_id':chunks[j]['chunk_id'],'score':float(scores[qi,j])} for j in order],'doc_recall':recalls,'first_relevant_rank_within10':first,'mrr10':1/first if first else 0,'single_complete_evidence_at3':single,'union_complete_evidence_at3':covered==ev['end']-ev['start'],'evidence_coverage_at3':covered/(ev['end']-ev['start']),'unique_docs_at3':len({c['doc_id'] for c in top}),'top3_chars':selected_chars,'top3_unique_chars':unique_chars})
    (dest/'per-query.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    item={'case':case,'round':a.round,'chunk_size_chars':size,'overlap_chars':overlap,'chunks':len(chunks),'total_chunk_chars':sum(len(c['text']) for c in chunks),'max_embedding_tokens':max(ctokens),'doc_recall_at1':sum(r['doc_recall']['1'] for r in results)/len(results),'doc_recall_at3':sum(r['doc_recall']['3'] for r in results)/len(results),'doc_recall_at5':sum(r['doc_recall']['5'] for r in results)/len(results),'mrr_at10':sum(r['mrr10'] for r in results)/len(results),'single_complete_evidence_at3':sum(r['single_complete_evidence_at3'] for r in results)/len(results),'union_complete_evidence_at3':sum(r['union_complete_evidence_at3'] for r in results)/len(results),'mean_top3_chars':sum(r['top3_chars'] for r in results)/len(results),'mean_top3_unique_chars':sum(r['top3_unique_chars'] for r in results)/len(results),'elapsed_seconds':time.monotonic()-started}
    summary.append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
assert not attempts
info={'pid':os.getpid(),'python':platform.python_version(),'platform':platform.platform(),'logical_cpus':os.cpu_count(),'torch':torch.__version__,'transformers':transformers.__version__,'numpy':np.__version__,'torch_threads':torch.get_num_threads(),'torch_interop_threads':torch.get_num_interop_threads(),'device':'cpu','model_type':model.config.model_type,'embedding_dim':512,'model_revision':meta['parameters']['revision'],'model_file_sha256':{f['file']:f['sha256'] for f in files if 'file' in f},'corpus_sha256':sha(LAB/'data/corpus.json'),'qrels_sha256':sha(LAB/'data/qrels.json'),'query_instruction':instruction,'query_token_counts':qtokens,'socket_connection_attempts':attempts,'elapsed_seconds':time.monotonic()-tick,'summary':summary}
(OUT/'worker.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
