import json
from pathlib import Path
def verify(case,directory):
    d=Path(directory);r=json.loads((d/'report.json').read_bytes());assert r['case']==case and r['manual_assign']
    production=json.loads((d/'production-acks.json').read_bytes());received=json.loads((d/'received.json').read_bytes())
    business=[json.loads(s) for s in (d/'business.jsonl').read_text().splitlines()]
    assert len(production)==len(received)==len(business)==4 and r['production_order']==[1,2,3,4]
    single=case=='single-control';receive_order=[1,2,3,4] if single else [2,4,1,3]
    assert r['receive_order']==receive_order==[x['seq'] for x in received]
    assert [x['seq'] for x in production]==[1,2,3,4]
    byseq={x['seq']:x for x in production}
    for x in production:
        seq=x['seq'];assert x['topic']==r['topic'] and x['key']=='customer-42' and x['value']==str(seq)
        assert (x['partition'],x['offset'])==((0,seq-1) if single else ((seq-1)%2,(seq-1)//2))
    for x in received:assert all(x[k]==byseq[x['seq']][k] for k in ['seq','topic','partition','offset','key','value'])
    assert all(production[i]['ns']<production[i+1]['ns'] for i in range(3))
    assert all(received[i]['received_ns']<received[i+1]['received_ns'] for i in range(3))
    schedule=json.loads((d/'assignments.json').read_bytes());assert [x['partition'] for x in schedule]==([0] if single else [1,0]) and all(x['from_offset']==0 for x in schedule)
    assert json.loads((d/'watermarks.json').read_bytes())==({'0':[0,4]} if single else {'0':[0,2],'1':[0,2]})
    expected=[];buffer={};next_seq=1
    for x in received:
        if case=='sequence-gate':
            buffer[x['seq']]=x
            while next_seq in buffer:expected.append(buffer.pop(next_seq));next_seq+=1
        else:expected.append(x)
    assert not buffer and all({k:v for k,v in b.items() if k!='applied_ns'}==x for b,x in zip(business,expected))
    assert all(x['applied_ns']>=x['received_ns'] for x in business) and all(business[i]['applied_ns']<business[i+1]['applied_ns'] for i in range(3))
    order=[x['seq'] for x in business];assert r['business_order']==order==([2,4,1,3] if case=='partition-first' else [1,2,3,4])
    return {**r,'in_order':order==[1,2,3,4],'passed':True}
