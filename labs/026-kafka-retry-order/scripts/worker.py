import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from confluent_kafka import Consumer,Producer,TopicPartition,version,libversion
from settings import MYSQL,BROKER,config
p=argparse.ArgumentParser();p.add_argument('mode',choices=['async-retry-topic','partition-block','retry']);p.add_argument('topic');p.add_argument('retry_topic');p.add_argument('group');p.add_argument('case_id');p.add_argument('dest',type=Path);a=p.parse_args()
for v in [a.topic,a.retry_topic,a.group,a.case_id]:assert re.fullmatch('[a-z0-9-]+',v)
a.dest.mkdir(parents=True,exist_ok=False);tick=time.monotonic();sqlnum=0
def emit(event,**kw):print(json.dumps({'event':event,'pid':os.getpid(),'utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-tick,**kw},sort_keys=True),flush=True)
def sql(label,statement,expect_failure=False):
    global sqlnum
    sqlnum+=1;d=a.dest/f'{sqlnum:02d}-{label}';d.mkdir();(d/'input.sql').write_bytes(statement.encode());started=datetime.now(timezone.utc).isoformat();st=time.monotonic()
    r=subprocess.run(MYSQL,input=statement.encode(),capture_output=True,timeout=15)
    (d/'stdout.txt').write_bytes(r.stdout);(d/'stderr.txt').write_bytes(r.stderr);(d/'command.json').write_text(json.dumps({'argv':MYSQL,'started_utc':started,'ended_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-st,'exit_code':r.returncode,'expected_failure':expect_failure},indent=2)+'\n',encoding='utf-8',newline='\n')
    if expect_failure:assert r.returncode==1 and b'ERROR 1644 (45000)' in r.stderr
    else:assert r.returncode==0 and b'ERROR' not in r.stderr
    return r.stdout.decode().strip()
def apply(msg):
    payload=json.loads(msg.value());assert payload['case_id']==a.case_id and msg.key()==a.case_id.encode();seq=payload['seq'];event=payload['event_id'];assert re.fullmatch('[a-z0-9]+',event)
    attempt=int(sql(f'attempt-{seq}',f"INSERT INTO attempts VALUES ('{a.case_id}','{event}',1) ON DUPLICATE KEY UPDATE attempts=attempts+1; SELECT attempts FROM attempts WHERE case_id='{a.case_id}' AND event_id='{event}';\n"))
    if seq==2 and attempt==1:
        sql('controlled-failure',"SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='lab026 controlled first attempt failure';\n",True)
        emit('business_failure',seq=seq,event_id=event,attempt=attempt,sql_exit=1,sql_error=1644);return False
    assert attempt==(2 if seq==2 else 1)
    result=sql(f'complete-{seq}',f"START TRANSACTION; INSERT INTO completed(case_id,seq,event_id) VALUES ('{a.case_id}',{seq},'{event}'); COMMIT; SELECT id,seq,event_id FROM completed WHERE case_id='{a.case_id}' ORDER BY id;\n")
    rows=[{'id':int(v[0]),'seq':int(v[1]),'event_id':v[2]} for line in result.splitlines() for v in [line.split('\t')]]
    emit('business_committed',seq=seq,event_id=event,attempt=attempt,rows=rows);return True
def assigned(c,parts):emit('assigned',parts=[{'topic':v.topic,'partition':v.partition,'offset':v.offset} for v in parts])
def revoked(c,parts):emit('revoked',parts=[{'topic':v.topic,'partition':v.partition,'offset':v.offset} for v in parts])
c=Consumer(config(a.group));emit('boot',mode=a.mode,topic=a.topic,group=a.group,case_id=a.case_id,config=config(a.group),client=version(),librdkafka=libversion());c.subscribe([a.topic],on_assign=assigned,on_revoke=revoked)
expected=[2] if a.mode=='retry' else [1,2,3]
for seq in expected:
    deadline=time.monotonic()+40;msg=None
    while time.monotonic()<deadline:
        msg=c.poll(.2)
        if msg is not None:
            if msg.error():raise RuntimeError(str(msg.error()))
            break
    assert msg is not None and json.loads(msg.value())['seq']==seq
    cp=c.committed([TopicPartition(a.topic,0)],timeout=10)[0];assert not cp.error
    emit('received',topic=msg.topic(),partition=msg.partition(),offset=msg.offset(),key=msg.key().decode(),value=msg.value().decode(),seq=seq,position=c.position([TopicPartition(a.topic,0)])[0].offset,committed=cp.offset,member_id=c.memberid())
    ok=apply(msg)
    if not ok:
        if a.mode=='async-retry-topic':
            producer=Producer({'bootstrap.servers':BROKER,'acks':'all','enable.idempotence':True});acks=[]
            def ack(err,r):
                if err:raise RuntimeError(str(err))
                acks.append({'topic':r.topic(),'partition':r.partition(),'offset':r.offset(),'key':r.key().decode(),'value':msg.value().decode()})
            producer.produce(a.retry_topic,key=msg.key(),value=msg.value(),on_delivery=ack);assert producer.flush(15)==0 and len(acks)==1;emit('retry_published',ack=acks[0])
        else:
            emit('retry_blocked',seq=seq,position=c.position([TopicPartition(a.topic,0)])[0].offset,committed=c.committed([TopicPartition(a.topic,0)],timeout=10)[0].offset)
            assert sys.stdin.buffer.read(1)==b'C';emit('retry_released',seq=seq);assert apply(msg)
    parts=c.commit(message=msg,asynchronous=False);assert len(parts)==1 and all(not v.error for v in parts)
    emit('offset_committed',seq=seq,parts=[{'topic':v.topic,'partition':v.partition,'offset':v.offset,'error':str(v.error) if v.error else None} for v in parts])
c.close();emit('closed')
