import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from confluent_kafka import Consumer, TopicPartition, version, libversion
from settings import MYSQL, consumer_config

p=argparse.ArgumentParser();p.add_argument('mode',choices=['no-dedupe','txn-dedupe']);p.add_argument('phase',choices=['crash','restart']);p.add_argument('topic');p.add_argument('group');p.add_argument('event');p.add_argument('dest',type=Path);a=p.parse_args()
for s in [a.topic,a.group,a.event]:assert re.fullmatch('[a-z0-9-]+',s)
a.dest.mkdir(parents=True,exist_ok=False);tick=time.monotonic()
def emit(event,**kwargs):
    print(json.dumps({'event':event,'pid':os.getpid(),'utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-tick,**kwargs},sort_keys=True),flush=True)
def assigned(c,parts):emit('assigned',partitions=[{'topic':x.topic,'partition':x.partition,'offset':x.offset} for x in parts])
def revoked(c,parts):emit('revoked',partitions=[{'topic':x.topic,'partition':x.partition,'offset':x.offset} for x in parts])
c=Consumer(consumer_config(a.group));emit('boot',phase=a.phase,mode=a.mode,topic=a.topic,group=a.group,config=consumer_config(a.group),client=version(),librdkafka=libversion())
c.subscribe([a.topic],on_assign=assigned,on_revoke=revoked)
deadline=time.monotonic()+40;msg=None
while time.monotonic()<deadline:
    msg=c.poll(.2)
    if msg is not None:
        if msg.error():raise RuntimeError(str(msg.error()))
        break
assert msg is not None,'consumer poll timed out'
payload=json.loads(msg.value());assert payload=={'case_id':a.group,'event_id':a.event,'amount':1} and msg.key()==a.group.encode()
cp=c.committed([TopicPartition(a.topic,msg.partition())],timeout=10)[0];assert not cp.error
emit('received',topic=msg.topic(),partition=msg.partition(),offset=msg.offset(),key=msg.key().decode(),value=msg.value().decode(),position=c.position([TopicPartition(a.topic,msg.partition())])[0].offset,committed=cp.offset,member_id=c.memberid())
if a.mode=='txn-dedupe':
    sql=f"START TRANSACTION; INSERT IGNORE INTO applied VALUES ('{a.group}','{a.event}'); SET @fresh=ROW_COUNT(); UPDATE ledger SET balance=balance+@fresh WHERE case_id='{a.group}'; COMMIT; SELECT balance,@fresh,(SELECT COUNT(*) FROM applied WHERE case_id='{a.group}') FROM ledger WHERE case_id='{a.group}';\n"
else:
    sql=f"START TRANSACTION; UPDATE ledger SET balance=balance+1 WHERE case_id='{a.group}'; COMMIT; SELECT balance,1,(SELECT COUNT(*) FROM applied WHERE case_id='{a.group}') FROM ledger WHERE case_id='{a.group}';\n"
(a.dest/'input.sql').write_bytes(sql.encode());start=datetime.now(timezone.utc).isoformat();st=time.monotonic()
r=subprocess.run(MYSQL,input=sql.encode(),capture_output=True,timeout=15)
(a.dest/'stdout.txt').write_bytes(r.stdout);(a.dest/'stderr.txt').write_bytes(r.stderr)
(a.dest/'command.json').write_text(json.dumps({'argv':MYSQL,'started_utc':start,'ended_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-st,'exit_code':r.returncode},indent=2)+'\n',encoding='utf-8',newline='\n')
assert r.returncode==0 and b'ERROR' not in r.stderr,r.stderr
values=[int(x) for x in r.stdout.decode().strip().split('\t')];assert len(values)==3
emit('business_committed',balance=values[0],fresh=values[1],markers=values[2],mysql_exit=r.returncode)
if a.phase=='crash':
    emit('await_offset_permission')
    assert sys.stdin.buffer.read(1)==b'C','offset permission absent'
parts=c.commit(message=msg,asynchronous=False)
assert len(parts)==1 and all(not x.error for x in parts)
emit('offset_committed',partitions=[{'topic':x.topic,'partition':x.partition,'offset':x.offset,'error':str(x.error) if x.error else None} for x in parts])
c.close();emit('closed')
