import argparse
import json
import os
import time
import uuid
from pathlib import Path
from confluent_kafka import Producer,Consumer,TopicPartition,version,libversion
from confluent_kafka.admin import AdminClient,NewTopic
a=argparse.ArgumentParser();a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
d=args.out;d.mkdir(parents=True,exist_ok=False);broker='127.0.0.1:19048';topic='lab048-'+args.case+'-'+uuid.uuid4().hex;group=topic
single=args.case=='single-control';count=1 if single else 2
admin=AdminClient({'bootstrap.servers':broker});admin.create_topics([NewTopic(topic,num_partitions=count,replication_factor=1)])[topic].result(15)
metadata=admin.list_topics(topic,timeout=10).topics[topic];assert not metadata.error
def save(name,value):(d/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')
save('metadata.json',{str(n):{'leader':p.leader,'replicas':p.replicas,'isrs':p.isrs} for n,p in metadata.partitions.items()})
producer=Producer({'bootstrap.servers':broker,'acks':'all','enable.idempotence':True});acks=[]
for seq in range(1,5):
    partition=0 if single else (seq-1)%2
    def ack(err,msg,seq=seq):
        assert err is None;acks.append({'seq':seq,'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode(),'value':msg.value().decode(),'ns':time.perf_counter_ns()})
    producer.produce(topic,partition=partition,key='customer-42',value=str(seq),on_delivery=ack)
    assert producer.flush(10)==0 and len(acks)==seq
save('production-acks.json',acks)
c=Consumer({'bootstrap.servers':broker,'group.id':group,'enable.auto.commit':False,'enable.auto.offset.store':False,'auto.offset.reset':'earliest'})
received=[];business=[];buffer={};expected=1;assignments=[]
f=(d/'business.jsonl').open('w',encoding='utf-8',newline='\n')
def apply(row):
    record={**row,'applied_ns':time.perf_counter_ns()};f.write(json.dumps(record)+'\n');f.flush();os.fsync(f.fileno());business.append(record)
try:
    schedule=[0] if single else [1,0]
    for partition in schedule:
        c.assign([TopicPartition(topic,partition,0)]);assignments.append({'partition':partition,'from_offset':0,'ns':time.perf_counter_ns()})
        wanted=4 if single else 2;deadline=time.perf_counter()+20
        for j in range(wanted):
            while True:
                msg=c.poll(.1)
                if msg is not None:assert not msg.error();break
                assert time.perf_counter()<deadline
            row={'seq':int(msg.value()),'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode(),'value':msg.value().decode(),'received_ns':time.perf_counter_ns()}
            assert row['partition']==partition and row['offset']==j;received.append(row)
            if args.case=='sequence-gate':
                assert row['seq'] not in buffer;buffer[row['seq']]=row
                while expected in buffer:apply(buffer.pop(expected));expected+=1
            else:apply(row)
    assert not buffer and len(business)==4
    watermarks={str(p):list(c.get_watermark_offsets(TopicPartition(topic,p),timeout=10)) for p in range(count)}
    save('watermarks.json',watermarks)
finally:f.close();c.close()
save('received.json',received);save('assignments.json',assignments)
report={'case':args.case,'topic':topic,'group':group,'worker_pid':os.getpid(),'client':version(),'librdkafka':libversion(),'manual_assign':True,'production_order':[r['seq'] for r in acks],'receive_order':[r['seq'] for r in received],'business_order':[r['seq'] for r in business]}
save('report.json',report);print(json.dumps(report),flush=True)
