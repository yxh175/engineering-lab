import argparse
import json
import os
import queue
import sys
import threading
import time
from confluent_kafka import Consumer, KafkaException
a=argparse.ArgumentParser();a.add_argument('role');a.add_argument('case');a.add_argument('topic');a.add_argument('group');args=a.parse_args()
config={'bootstrap.servers':'127.0.0.1:19047','group.id':args.group,'client.id':'lab047-'+args.role,
        'group.protocol':'classic','partition.assignment.strategy':'range','enable.auto.commit':False,
        'enable.auto.offset.store':False,'auto.offset.reset':'earliest','session.timeout.ms':1000,
        'heartbeat.interval.ms':300,'max.poll.interval.ms':2000,'debug':'cgrp'}
def emit(event,**kw):print(json.dumps({'event':event,'pid':os.getpid(),'ns':time.perf_counter_ns(),**kw}),flush=True)
def parts(xs):return [{'topic':x.topic,'partition':x.partition,'offset':x.offset,'error':str(x.error) if x.error else None} for x in xs]
c=Consumer(config);emit('boot',config=config)
c.subscribe([args.topic],on_assign=lambda c,p:emit('assigned',parts=parts(p)),on_revoke=lambda c,p:emit('revoked',parts=parts(p)))
gate=queue.Queue()
def read_gate():gate.put(sys.stdin.buffer.read(1))
if args.role=='b':threading.Thread(target=read_gate,daemon=True).start()
try:
    deadline=time.perf_counter()+25;received=[];assigned_at=None
    while time.perf_counter()<deadline:
        msg=c.poll(.1)
        if c.assignment() and assigned_at is None:assigned_at=time.perf_counter()
        if msg is not None:
            if msg.error():raise KafkaException(msg.error())
            emit('received',topic=msg.topic(),partition=msg.partition(),offset=msg.offset(),key=msg.key().decode(),value=msg.value().decode(),member=c.memberid())
            received.append(msg.offset())
            if args.role=='a':
                emit('processing')
                if args.case=='overdue':assert sys.stdin.buffer.read(1)==b'C'
                else:time.sleep(.2)
                try:
                    result=c.commit(message=msg,asynchronous=False)
                    emit('commit',success=all(not p.error for p in result),parts=parts(result),error=None)
                except KafkaException as exc:
                    error=exc.args[0];emit('commit',success=False,parts=[],error={'code':error.code(),'name':error.name(),'text':str(error)})
                break
            else:
                result=c.commit(message=msg,asynchronous=False);assert all(not p.error for p in result)
                emit('complete',received=received,parts=parts(result))
        if args.role=='b':
            if args.case=='bounded' and assigned_at is not None and time.perf_counter()-assigned_at>=1 and not received:
                emit('complete',received=[],parts=[]);assigned_at=None
            if not gate.empty():assert gate.get()==b'C';break
    else:raise AssertionError('worker deadline')
finally:c.close();emit('closed')
