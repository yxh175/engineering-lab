import json
from pathlib import Path
from resp import decode_all
def verify(case,directory):
    p=Path(directory);assert json.loads((p/'status.json').read_bytes())=={'case':case,'failure':None}
    events=json.loads((p/'events.json').read_bytes());assert all(events[i]['ns']<=events[i+1]['ns'] for i in range(len(events)-1))
    requests={};responses={}
    for name in ['writer','observer']:
        requests[name]=decode_all((p/(name+'.requests.bin')).read_bytes());responses[name]=decode_all((p/(name+'.responses.bin')).read_bytes())
        assert requests[name]==[c for e in events if e['kind']=='send' and e['connection']==name for c in e['commands']]
        assert responses[name]==[e['value'] for e in events if e['kind']=='recv' and e['connection']==name]
    assert requests['writer'][:2]==[['FLUSHDB'],['MSET','left','0','right','0']]
    assert all(c==['MGET','left','right'] for c in requests['observer'])
    observed=responses['observer'];assert observed[0]==['0','0'] and observed[-1]==['1','1']
    if case=='split-pipeline':
        assert requests['writer'][2:]==[['SET','left','1'],['SET','right','1']] and responses['writer']==['OK']*4
        assert observed[-2]==['1','0'] and all(v==['0','0'] for v in observed[1:-2])
        first=next(i for i,e in enumerate(events) if e['kind']=='send' and e['connection']=='writer' and e['commands']==[['SET','left','1']])
        witness=next(i for i,e in enumerate(events) if e['kind']=='recv' and e['connection']=='observer' and e['value']==['1','0'])
        second=next(i for i,e in enumerate(events) if e['kind']=='send' and e['connection']=='writer' and e['commands']==[['SET','right','1']])
        drain=next(i for i,e in enumerate(events) if i>first and e['kind']=='recv' and e['connection']=='writer')
        assert first<witness<second<drain
    elif case=='multi':
        assert requests['writer'][2:]==[['MULTI'],['SET','left','1'],['SET','right','1'],['EXEC']]
        assert responses['writer']==['OK','OK','OK','QUEUED','QUEUED',['OK','OK']] and observed==[['0','0'],['0','0'],['1','1']]
        assert [e['commands'] for e in events if e['kind']=='send' and e['connection']=='writer'][2:]==[[['MULTI'],['SET','left','1']],[['SET','right','1'],['EXEC']]]
    else:
        assert case=='mset-control' and requests['writer'][2:]==[['MSET','left','1','right','1']]
        assert responses['writer']==['OK']*3 and observed==[['0','0'],['0','0'],['1','1']]
    return {'case':case,'middle_left':int(observed[-2][0]),'middle_right':int(observed[-2][1]),'final_left':1,'final_right':1,'partial_observed':observed[-2]==['1','0'],'writer_commands':len(requests['writer']),'observer_commands':len(requests['observer']),'controlled_split':case=='split-pipeline','passed':True}
