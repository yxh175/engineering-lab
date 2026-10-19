import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from verify import verify
a=argparse.ArgumentParser();a.add_argument('--container',required=True);a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
assert args.case in ['bad-old-set','atomic','locked-read','single-control']
args.out.mkdir(parents=True,exist_ok=False);events=[];sessions=[]
def event(kind,who,text):events.append({'ns':time.monotonic_ns(),'kind':kind,'session':who,'text':text})
class Session:
    def __init__(self,name):
        self.name=name;self.q=queue.Queue();self.stdout=[];self.inputs=[]
        self.argv=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',args.container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered','engine_lab_038']
        self.p=subprocess.Popen(self.argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start();sessions.append(self)
        self.send("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ; SET SESSION innodb_lock_wait_timeout=5; SELECT 'READY',CONNECTION_ID(),@@transaction_isolation;")
        self.ready=self.until('READY');self.cid=int(self.ready[1]);assert self.ready[2]=='REPEATABLE-READ'
    def read(self):
        for line in iter(self.p.stdout.readline,b''):
            self.stdout.append(line);self.q.put(line);event('recv',self.name,line.decode().strip())
        self.q.put(None)
    def send(self,text):
        data=(text+'\n').encode();self.inputs.append(data);event('send',self.name,text);self.p.stdin.write(data);self.p.stdin.flush()
    def until(self,marker):
        deadline=time.monotonic()+8
        while True:
            line=self.q.get(timeout=max(.001,deadline-time.monotonic()))
            assert line is not None,f'{self.name} EOF before {marker}'
            p=line.decode().strip().split('\t')
            if p[0]==marker:return p
            assert time.monotonic()<deadline
    def close(self):
        try:self.p.stdin.close();self.p.wait(timeout=8)
        except Exception:self.p.kill();self.p.wait(timeout=5)
        self.reader.join(timeout=2);err=self.p.stderr.read();assert not self.reader.is_alive()
        (args.out/(self.name+'.input.sql')).write_bytes(b''.join(self.inputs))
        (args.out/(self.name+'.stdout.txt')).write_bytes(b''.join(self.stdout))
        (args.out/(self.name+'.stderr.txt')).write_bytes(err)
        (args.out/(self.name+'.process.json')).write_text(json.dumps({'argv':self.argv,'exit_code':self.p.returncode},indent=2)+'\n',encoding='utf-8',newline='\n')
def read(s,lock=False):
    s.send(f"SELECT 'READ_{s.name}',stock,version FROM inventory WHERE id=1"+(' FOR UPDATE;' if lock else ';'))
    return int(s.until('READ_'+s.name)[1])
def write(s,stock=None):
    expression='stock-1' if stock is None else str(stock-1)
    s.send(f"UPDATE inventory SET stock={expression},version=version+1 WHERE id=1 AND stock>0; SELECT 'WRITE_{s.name}',ROW_COUNT();")
def commit(s):s.send(f"COMMIT; SELECT 'COMMIT_{s.name}';");s.until('COMMIT_'+s.name)
def wait_lock(observer,a,b):
    end=time.monotonic()+5
    while time.monotonic()<end:
        observer.send(f"SELECT 'LOCKWAIT',COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.threads r ON r.THREAD_ID=w.REQUESTING_THREAD_ID JOIN performance_schema.threads b ON b.THREAD_ID=w.BLOCKING_THREAD_ID WHERE r.PROCESSLIST_ID={b.cid} AND b.PROCESSLIST_ID={a.cid};")
        count=int(observer.until('LOCKWAIT')[1])
        if count:return count
        time.sleep(.01)
    raise RuntimeError('No actual B-waits-A witness')
failure=None
try:
    observer=Session('O');a=Session('A');b=Session('B');assert len({s.cid for s in sessions})==3
    observer.send("UPDATE inventory SET stock=10,version=0 WHERE id=1; SELECT 'RESET',id,stock,version FROM inventory ORDER BY id;");assert observer.until('RESET')[1:]==['1','10','0']
    a.send('BEGIN;');av=read(a,args.case=='locked-read');assert av==10
    if args.case in ['bad-old-set','atomic']:
        b.send('BEGIN;');bv=read(b);assert bv==10
        write(a,av if args.case=='bad-old-set' else None);assert a.until('WRITE_A')[1]=='1'
        write(b,bv if args.case=='bad-old-set' else None);wait_lock(observer,a,b)
        commit(a);assert b.until('WRITE_B')[1]=='1';commit(b)
    elif args.case=='locked-read':
        b.send("BEGIN; SELECT 'READ_B',stock,version FROM inventory WHERE id=1 FOR UPDATE;")
        wait_lock(observer,a,b);write(a,av);assert a.until('WRITE_A')[1]=='1';commit(a)
        bv=int(b.until('READ_B')[1]);assert bv==9;write(b,bv);assert b.until('WRITE_B')[1]=='1';commit(b)
    else:write(a);assert a.until('WRITE_A')[1]=='1';commit(a)
    observer.send("SELECT 'FINAL',id,stock,version FROM inventory ORDER BY id;");observer.until('FINAL')
except Exception as exc:failure=repr(exc);raise
finally:
    for s in sessions:s.close()
    (args.out/'events.json').write_text(json.dumps(events,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.out/'status.json').write_text(json.dumps({'case':args.case,'failure':failure})+'\n',encoding='utf-8',newline='\n')
checked=verify(args.case,args.out);print(json.dumps(checked))
