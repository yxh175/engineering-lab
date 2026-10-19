import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from verify import verify
parser=argparse.ArgumentParser();parser.add_argument('--case',required=True);parser.add_argument('--container',required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
assert args.case in ['autocommit-missing','transaction-missing','checked-missing','checked-normal']
args.out.mkdir(parents=True,exist_ok=False);events=[];inputs=[];stdout=[];q=queue.Queue()
argv=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',args.container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered','engine_lab_039']
p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
def event(kind,text):events.append({'ns':time.perf_counter_ns(),'kind':kind,'text':text})
def reader():
    for line in iter(p.stdout.readline,b''):
        stdout.append(line);event('recv',line.decode().strip());q.put(line)
    q.put(None)
t=threading.Thread(target=reader,daemon=True);t.start()
def send(sql):inputs.append((sql+'\n').encode());event('send',sql);p.stdin.write(inputs[-1]);p.stdin.flush()
def until(marker):
    deadline=time.monotonic()+8
    while True:
        line=q.get(timeout=max(.001,deadline-time.monotonic()));assert line is not None
        fields=line.decode().strip().split('\t')
        if fields[0]==marker:return fields
        assert time.monotonic()<deadline
failure=None
try:
    send("SELECT 'READY',CONNECTION_ID(),@@autocommit; UPDATE accounts SET balance=CASE id WHEN 1 THEN 100 ELSE 0 END; SELECT 'INITIAL',id,balance FROM accounts ORDER BY id; SELECT 'RESET_DONE';")
    assert until('READY')[2]=='1';until('RESET_DONE')
    transaction=args.case!='autocommit-missing';checked=args.case.startswith('checked');target=2 if args.case=='checked-normal' else 999
    if transaction:send('BEGIN;')
    send("UPDATE accounts SET balance=balance-10 WHERE id=1 AND balance>=10; SELECT 'DEBIT',ROW_COUNT();")
    debit=int(until('DEBIT')[1])
    send(f"UPDATE accounts SET balance=balance+10 WHERE id={target}; SELECT 'CREDIT',ROW_COUNT();")
    credit=int(until('CREDIT')[1])
    decision='ROLLBACK' if checked and (debit!=1 or credit!=1) else ('COMMIT' if transaction else 'AUTOCOMMIT')
    if transaction:send(f"{decision}; SELECT 'DECISION','{decision}';")
    else:send("SELECT 'DECISION','AUTOCOMMIT';")
    until('DECISION')
    send("SELECT 'FINAL',id,balance FROM accounts ORDER BY id; SELECT 'SUM',SUM(balance),COUNT(*) FROM accounts; SELECT 'END';");until('END')
except Exception as exc:failure=repr(exc);raise
finally:
    try:p.stdin.close();p.wait(timeout=8)
    except Exception:p.kill();p.wait(timeout=5)
    t.join(timeout=2);err=p.stderr.read();assert not t.is_alive()
    (args.out/'input.sql').write_bytes(b''.join(inputs));(args.out/'stdout.txt').write_bytes(b''.join(stdout));(args.out/'stderr.txt').write_bytes(err)
    for name,value in [('process',{'argv':argv,'exit_code':p.returncode}),('events',events),('status',{'case':args.case,'failure':failure})]:
        (args.out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(verify(args.case,args.out)))
