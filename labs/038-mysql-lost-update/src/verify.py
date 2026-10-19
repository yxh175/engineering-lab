import json
import re
from pathlib import Path
def verify(case,directory):
    p=Path(directory);events=json.loads((p/'events.json').read_bytes());status=json.loads((p/'status.json').read_bytes())
    assert status=={'case':case,'failure':None}
    assert all(events[i]['ns']<=events[i+1]['ns'] for i in range(len(events)-1))
    out={};inputs={};ids={}
    for name in ['A','B','O']:
        process=json.loads((p/(name+'.process.json')).read_bytes());assert process['exit_code']==0
        assert process['argv'][0:3]==['docker','exec','-i'] and process['argv'][-1]=='engine_lab_038'
        assert not (p/(name+'.stderr.txt')).read_bytes().strip()
        out[name]=[l.split('\t') for l in (p/(name+'.stdout.txt')).read_text().splitlines()]
        inputs[name]=(p/(name+'.input.sql')).read_text()
        assert 'SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;' in inputs[name]
        ready=out[name][0];assert ready[0]=='READY' and ready[2]=='REPEATABLE-READ';ids[name]=int(ready[1])
        receives=[e['text'].split('\t') for e in events if e['kind']=='recv' and e['session']==name]
        assert receives==out[name]
        assert '\n'.join(e['text'] for e in events if e['kind']=='send' and e['session']==name)+'\n'==inputs[name]
    assert len(set(ids.values()))==3
    single=case=='single-control';bad=case=='bad-old-set';locked=case=='locked-read'
    for name in (['A'] if single else ['A','B']):
        reads=[r for r in out[name] if r[0]=='READ_'+name];assert len(reads)==1
        expected=9 if locked and name=='B' else 10
        assert reads[0][1:]==[str(expected),'1' if locked and name=='B' else '0']
        assert [r for r in out[name] if r[0]=='WRITE_'+name]==[['WRITE_'+name,'1']]
        assert [r for r in out[name] if r[0]=='COMMIT_'+name]==[['COMMIT_'+name]]
        expression=str(expected-1) if bad or locked else 'stock-1'
        assert f'UPDATE inventory SET stock={expression},version=version+1 WHERE id=1 AND stock>0;' in inputs[name]
        assert ('FOR UPDATE' in inputs[name]) is locked
    assert [r for r in out['O'] if r[0]=='RESET']==[['RESET','1','10','0']]
    final=[r for r in out['O'] if r[0]=='FINAL'];assert final==[['FINAL','1','9' if bad or single else '8','1' if single else '2']]
    waits=[int(r[1]) for r in out['O'] if r[0]=='LOCKWAIT'];assert (any(w>0 for w in waits)) is (not single)
    if not single:
        assert f'r.PROCESSLIST_ID={ids["B"]} AND b.PROCESSLIST_ID={ids["A"]}' in inputs['O']
        witness=next(e['ns'] for e in events if e['kind']=='recv' and e['session']=='O' and e['text'].startswith('LOCKWAIT\t') and int(e['text'].split('\t')[1])>0)
        release=next(e['ns'] for e in events if e['kind']=='send' and e['session']=='A' and e['text'].startswith('COMMIT;'))
        second=next(e['ns'] for e in events if e['kind']=='recv' and e['session']=='B' and e['text'].startswith('READ_B\t' if locked else 'WRITE_B\t'))
        assert witness<release<second
    else:assert len(out['B'])==1 and 'BEGIN' not in inputs['B']
    accepted=1 if single else 2;stock=int(final[0][2]);expected=10-accepted
    return {'case':case,'final_stock':stock,'final_version':int(final[0][3]),'accepted_updates':accepted,'expected_stock':expected,'lost_decrements':stock-expected,'lock_wait_witness':not single,'read_a':10,'read_b':None if single else (9 if locked else 10),'business_correct':stock==expected,'passed':True}
