import json
from pathlib import Path
def verify(case,directory):
    p=Path(directory);process=json.loads((p/'process.json').read_bytes());assert process['exit_code']==0 and process['argv'][-1]=='engine_lab_039'
    assert process['argv'][0:3]==['docker','exec','-i'] and not (p/'stderr.txt').read_bytes().strip()
    assert json.loads((p/'status.json').read_bytes())=={'case':case,'failure':None}
    output=[l.split('\t') for l in (p/'stdout.txt').read_text().splitlines()];sql=(p/'input.sql').read_text();events=json.loads((p/'events.json').read_bytes())
    assert [e['text'].split('\t') for e in events if e['kind']=='recv']==output
    assert '\n'.join(e['text'] for e in events if e['kind']=='send')+'\n'==sql
    assert all(events[i]['ns']<=events[i+1]['ns'] for i in range(len(events)-1))
    normal=case=='checked-normal';rollback=case=='checked-missing';auto=case=='autocommit-missing';target=2 if normal else 999
    assert output[0][0]=='READY' and int(output[0][1])>0 and output[0][2]=='1'
    assert [r for r in output if r[0]=='INITIAL']==[['INITIAL','1','100'],['INITIAL','2','0']]
    assert [r for r in output if r[0]=='DEBIT']==[['DEBIT','1']]
    assert [r for r in output if r[0]=='CREDIT']==[['CREDIT','1' if normal else '0']]
    decision='ROLLBACK' if rollback else ('AUTOCOMMIT' if auto else 'COMMIT')
    assert [r for r in output if r[0]=='DECISION']==[['DECISION',decision]]
    assert ('BEGIN;' in sql) is (not auto)
    assert f'UPDATE accounts SET balance=balance+10 WHERE id={target};' in sql
    assert 'UPDATE accounts SET balance=balance-10 WHERE id=1 AND balance>=10;' in sql
    if not auto:assert decision+"; SELECT 'DECISION'" in sql
    a=100 if rollback else 90;b=10 if normal else 0;total=a+b
    assert [r for r in output if r[0]=='FINAL']==[['FINAL','1',str(a)],['FINAL','2',str(b)]]
    assert [r for r in output if r[0]=='SUM']==[['SUM',str(total),'2']] and output[-1]==['END']
    debit_recv=next(i for i,e in enumerate(events) if e['kind']=='recv' and e['text']=='DEBIT\t1')
    credit_send=next(i for i,e in enumerate(events) if e['kind']=='send' and 'balance=balance+10' in e['text'])
    credit_recv=next(i for i,e in enumerate(events) if e['kind']=='recv' and e['text'].startswith('CREDIT\t'))
    decision_send=next(i for i,e in enumerate(events) if e['kind']=='send' and "SELECT 'DECISION'" in e['text'])
    assert debit_recv<credit_send<credit_recv<decision_send
    return {'case':case,'debit_rows':1,'credit_rows':1 if normal else 0,'decision':decision,'sender_balance':a,'recipient_balance':b,'total_balance':total,'business_accepted':not rollback,'transfer_complete':normal,'conserved':total==100,'safe_result':rollback or normal,'passed':True}
