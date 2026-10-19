import hashlib
import json
from pathlib import Path
import numpy as np
from evaluation import evaluate
WEIGHTS='354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026'
def verify(lab,directory):
    d=Path(directory);lab=Path(lab);fixture=json.loads((lab/'data/fixture.json').read_bytes());r=json.loads((d/'evaluation.json').read_bytes())
    assert len(fixture['docs'])==8 and len(fixture['queries'])==32
    assert len({q['id'] for q in fixture['queries']})==len({q['text'] for q in fixture['queries']})==32
    bydoc={x['id']:x['text'] for x in fixture['docs']}
    for q in fixture['queries']:
        if q['answerable']:assert len(q['relevant'])==1 and q['evidence']==bydoc[q['relevant'][0]]
        else:assert q['relevant']==[] and q['evidence']=='' and q['label_note']
    for split in ['calibration','test']:
        qs=[q for q in fixture['queries'] if q['split']==split];assert len(qs)==16 and sum(q['answerable'] for q in qs)==8
    dv=np.load(d/'doc-vectors.npy',allow_pickle=False);qv=np.load(d/'query-vectors.npy',allow_pickle=False);saved=np.load(d/'scores.npy',allow_pickle=False)
    assert dv.shape==(8,512) and qv.shape==(32,512) and dv.dtype==qv.dtype==np.float32
    assert np.isfinite(dv).all() and np.isfinite(qv).all() and np.allclose(np.linalg.norm(dv,axis=1),1,atol=2e-6) and np.allclose(np.linalg.norm(qv,axis=1),1,atol=2e-6)
    scores=qv@dv.T;assert np.allclose(scores,saved,rtol=0,atol=2e-7)
    checked=evaluate(fixture,saved)
    assert all(r[k]==v for k,v in checked.items())
    assert r['weights_sha256']==WEIGHTS and r['model_revision']=='7999e1d3359715c523056ef9478215996d62a620'
    assert r['fixture_sha256']==hashlib.sha256((lab/'data/fixture.json').read_bytes()).hexdigest() and r['device']=='cpu' and not r['socket_attempts'] and max(r['tokens'])<=512
    return [{'round':r['round'],'worker_pid':r['worker_pid'],**p,'passed':True} for p in checked['policies']]
