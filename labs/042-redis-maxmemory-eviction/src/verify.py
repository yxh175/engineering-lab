import hashlib
import json
from pathlib import Path
from resp import decode_all
LAB=Path(__file__).resolve().parents[1]
def payload(i):
    assert 0<=i<200
    prefix=f'value-{i:04}:'
    return prefix+'x'*(8192-len(prefix))
def info(text):return {p[0]:p[1] for line in text.splitlines() if ':' in line and not line.startswith('#') for p in [line.split(':',1)]}
def verify(case,directory):
    p=Path(directory);assert json.loads((p/'status.json').read_bytes())=={'case':case,'failure':None}
    events=json.loads((p/'events.json').read_bytes());requests=decode_all((p/'client.requests.bin').read_bytes());responses=decode_all((p/'client.responses.bin').read_bytes())
    assert requests==[c for e in events if e['kind']=='send' for c in e['commands']]
    assert responses==[e['value'] for e in events if e['kind']=='recv'] and len(requests)==len(responses)
    assert all(events[i]['ns']<=events[i+1]['ns'] for i in range(len(events)-1))
    cfg=next(x for x in json.loads((LAB/'src/cases.json').read_bytes()) if x['case']==case)
    assert requests[:6]==[['FLUSHDB'],['SET','lab042:sentinel','important'],['PTTL','lab042:sentinel'],['CONFIG','GET','maxmemory','maxmemory-policy'],['INFO','memory'],['INFO','stats']]
    assert responses[:3]==['OK','OK',-1]
    config=dict(zip(responses[3][::2],responses[3][1::2]));assert int(config['maxmemory'])==cfg['maxmemory'] and config['maxmemory-policy']==cfg['policy']
    assert requests[6:206]==[['SET',f'lab042:k{i:04}',payload(i)] for i in range(200)]
    replies=responses[6:206];accepted=[i for i,r in enumerate(replies) if r=='OK'];rejected=[i for i,r in enumerate(replies) if isinstance(r,dict) and r['error'].startswith('OOM')]
    assert len(accepted)+len(rejected)==200
    assert requests[206:209]==[['INFO','memory'],['INFO','stats'],['KEYS','lab042:*']]
    before_m=info(responses[4]);before_s=info(responses[5]);after_m=info(responses[206]);after_s=info(responses[207]);keys=sorted(responses[208])
    assert keys and len(keys)==len(set(keys)) and requests[209]==['MGET',*keys] and requests[210]==['PTTL','lab042:sentinel'] and len(requests)==211
    values=responses[209];assert len(values)==len(keys) and all(v is not None for v in values)
    stored=dict(zip(keys,values));expected={f'lab042:k{i:04}':payload(i) for i in accepted};expected['lab042:sentinel']='important'
    assert stored.keys()<=expected.keys() and all(v==expected[k] for k,v in stored.items())
    evicted=int(after_s['evicted_keys'])-int(before_s['evicted_keys']);assert int(before_s['evicted_keys'])==0 and int(after_s['expired_keys'])==0
    if cfg['policy']=='allkeys-lru':
        assert len(accepted)==200 and not rejected and evicted>0 and len(stored)<201
    elif case=='noeviction-small':
        assert 0<len(accepted)<200 and rejected and evicted==0 and stored==expected
    else:assert case=='capacity-control' and len(accepted)==200 and not rejected and evicted==0 and len(stored)==201 and stored==expected
    ttl=responses[210];assert ttl==(-1 if 'lab042:sentinel' in stored else -2)
    assert json.loads((p/'observations.json').read_bytes())=={'config':responses[3],'set_replies':replies,'keys':keys,'sentinel_pttl':ttl}
    hashes={k:hashlib.sha256(v.encode()).hexdigest() for k,v in stored.items()}
    return {'case':case,'attempted_sets':200,'accepted_sets':len(accepted),'oom_rejections':len(rejected),'retained_data_keys':len(stored)-int('lab042:sentinel' in stored),'retained_sentinel':'lab042:sentinel' in stored,'sentinel_pttl':ttl,'evicted_keys':evicted,'expired_keys':0,'used_memory_before':int(before_m['used_memory']),'used_memory_after':int(after_m['used_memory']),'stored_value_sha256':hashes,'passed':True}
