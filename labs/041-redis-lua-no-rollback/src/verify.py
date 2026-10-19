import hashlib
import json
from pathlib import Path
from resp import decode_all
LAB=Path(__file__).resolve().parents[1]
def verify(case,directory):
    p=Path(directory);assert json.loads((p/'status.json').read_bytes())=={'case':case,'failure':None}
    events=json.loads((p/'events.json').read_bytes());requests=decode_all((p/'client.requests.bin').read_bytes());responses=decode_all((p/'client.responses.bin').read_bytes())
    assert requests==[c for e in events if e['kind']=='send' for c in e['commands']]
    assert responses==[e['value'] for e in events if e['kind']=='recv'] and len(requests)==len(responses)
    assert all(events[i]['ns']<=events[i+1]['ns'] for i in range(len(events)-1))
    normal=case=='normal-list';bad=case=='write-then-error';assert case in ['write-then-error','validate-type','normal-list']
    script=(LAB/'src'/('bad.lua' if bad else 'good.lua')).read_text(encoding='utf-8');digest=hashlib.sha1(script.encode()).hexdigest()
    expected_init=[['FLUSHDB'],['MSET','state','0','after','0'],['RPUSH','destination','old'] if normal else ['SET','destination','wrong']]
    snap_commands=[['KEYS','*'],['TYPE','destination'],['MGET','state','after'],['LRANGE','destination','0','-1'] if normal else ['GET','destination']]
    assert requests==expected_init+snap_commands+[['EVAL',script,'3','state','destination','after','payload']]+snap_commands
    assert responses[:3]==['OK','OK',1 if normal else 'OK']
    def snap(offset):
        keys,kind,values,dest=responses[offset:offset+4]
        assert sorted(keys)==['after','destination','state']
        return {'keys':sorted(keys),'type':kind,'state_after':values,'destination':dest}
    before=snap(3);after=snap(8);reply=responses[7]
    assert before=={'keys':['after','destination','state'],'type':'list' if normal else 'string','state_after':['0','0'],'destination':['old'] if normal else 'wrong'}
    assert after=={'keys':['after','destination','state'],'type':'list' if normal else 'string','state_after':['1','1'] if normal else (['1','0'] if bad else ['0','0']),'destination':['payload','old'] if normal else 'wrong'}
    if normal:assert reply==1
    elif bad:assert isinstance(reply,dict) and 'WRONGTYPE' in reply['error'] and digest in reply['error'] and '@user_script:2' in reply['error']
    else:assert reply=={'error':'ERR DEST_NOT_LIST'}
    assert json.loads((p/'snapshots.json').read_bytes())=={'before':before,'reply':reply,'after':after}
    return {'case':case,'script_sha1':digest,'error_kind':'none' if normal else ('WRONGTYPE' if bad else 'DEST_NOT_LIST'),'final_state':int(after['state_after'][0]),'final_after':int(after['state_after'][1]),'destination_type':after['type'],'destination_values':after['destination'],'partial_write_retained':bad,'business_completed':normal,'passed':True}
