import json
from pathlib import Path
from resp import decode_all
def clients(text):return {int(fields['id']):fields for line in text.splitlines() for fields in [dict(v.split('=',1) for v in line.split() if '=' in v)]}
def verify(case,directory):
    p=Path(directory);assert json.loads((p/'status.json').read_bytes())=={'case':case,'failure':None}
    events=json.loads((p/'events.json').read_bytes());assert all(events[i]['ns']<=events[i+1]['ns'] for i in range(len(events)-1));req={};res={}
    for name in ['writer','observer']:
        req[name]=decode_all((p/(name+'.requests.bin')).read_bytes());res[name]=decode_all((p/(name+'.responses.bin')).read_bytes())
        assert req[name]==[c for e in events if e['kind']=='send' and e['connection']==name for c in e['commands']]
        assert res[name]==[e['value'] for e in events if e['kind']=='recv' and e['connection']==name]
    assert req['writer'][0]==['CLIENT','ID'] and isinstance(res['writer'][0],int);cid=res['writer'][0]
    assert req['observer'][:2]==[['FLUSHDB'],['SET','answer','42']] and res['observer'][:2]==['OK','OK']
    normal=case=='nonblocking-control';separate=case=='separate';assert case in ['shared','separate','nonblocking-control']
    assert req['writer'][1:]==([['LPOP','queue'],['GET','answer']] if normal else ([['BLPOP','queue','0.4']] if separate else [['BLPOP','queue','0.4'],['GET','answer']]))
    assert res['writer'][1:]==([None] if separate else [None,'42'])
    binary=(p/'writer.responses.bin').read_bytes();assert (b'*-1\r\n' in binary) is (not normal);assert (b'$-1\r\n' in binary) is normal
    blocking_states=[]
    for command,value in zip(req['observer'][2:],res['observer'][2:]):
        if command==['CLIENT','LIST']:
            state=clients(value)[cid];blocking_states.append(state)
        else:assert separate and command==['GET','answer'] and value=='42'
    blocked=any('b' in s['flags'] and s['cmd']=='blpop' for s in blocking_states)
    assert blocked is (not normal)
    sends=[e for e in events if e['kind']=='send' and e['connection']=='writer'];start=sends[1]['ns']
    block_end=next(e['ns'] for e in events if e['kind']=='recv' and e['connection']=='writer' and e['value'] is None)
    if not normal:assert 350<=(block_end-start)/1e6<=5000
    if separate:
        get_send=next(i for i,e in enumerate(events) if e['kind']=='send' and e['connection']=='observer' and e['commands']==[['GET','answer']])
        get_recv=next(i for i,e in enumerate(events) if e['kind']=='recv' and e['connection']=='observer' and e['value']=='42')
        after=next(i for i,e in enumerate(events) if i>get_recv and e['kind']=='recv' and e['connection']=='observer')
        state=clients(events[after]['value'])[cid];assert 'b' in state['flags'] and state['cmd']=='blpop'
        ended=next(i for i,e in enumerate(events) if e['kind']=='recv' and e['connection']=='writer' and e['value'] is None)
        assert get_send<get_recv<after<ended
        get_ms=(events[get_recv]['ns']-events[get_send]['ns'])/1e6
        assert req['observer'][-2:]==[['GET','answer'],['CLIENT','LIST']]
    else:
        get_end=next(e['ns'] for e in events if e['kind']=='recv' and e['connection']=='writer' and e['value']=='42')
        get_ms=(get_end-start)/1e6
    return {'case':case,'client_id':cid,'get_reply':'42','blocked_witness':blocked,'get_completed_while_other_blocked':separate,'get_elapsed_ms':get_ms,'blocking_reply_elapsed_ms':(block_end-start)/1e6,'blocking_timeout_seconds':0 if normal else .4,'passed':True}
