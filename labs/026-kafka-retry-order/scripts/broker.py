import argparse
import json
import time
from datetime import datetime, timezone
from confluent_kafka import Consumer,Producer,TopicPartition
from confluent_kafka.admin import AdminClient,NewTopic
from settings import BROKER,config
p=argparse.ArgumentParser();p.add_argument('action',choices=['create','observe']);p.add_argument('topic');p.add_argument('group');p.add_argument('--retry');p.add_argument('--events');a=p.parse_args()
tick=time.monotonic();d={'action':a.action,'topic':a.topic,'group':a.group,'started_utc':datetime.now(timezone.utc).isoformat()}
if a.action=='create':
    admin=AdminClient({'bootstrap.servers':BROKER});f=admin.create_topics([NewTopic(t,num_partitions=1,replication_factor=1) for t in [a.topic,a.retry]])
    for future in f.values():future.result(15)
    d['metadata']={}
    for topic in [a.topic,a.retry]:
        meta=admin.list_topics(topic,timeout=10).topics[topic];assert not meta.error and len(meta.partitions)==1
        d['metadata'][topic]={str(i):{'leader':v.leader,'replicas':v.replicas,'isrs':v.isrs} for i,v in meta.partitions.items()}
    producer=Producer({'bootstrap.servers':BROKER,'acks':'all','enable.idempotence':True});acks=[]
    for seq,event in enumerate(a.events.split(','),1):
        value=json.dumps({'case_id':a.group,'event_id':event,'seq':seq},sort_keys=True,separators=(',',':')).encode()
        def ack(err,msg,value=value):
            if err:raise RuntimeError(str(err))
            acks.append({'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode(),'value':value.decode()})
        producer.produce(a.topic,key=a.group.encode(),value=value,on_delivery=ack)
    assert producer.flush(15)==0 and len(acks)==3;d['acks']=acks
else:
    c=Consumer(config(a.group))
    try:
        cp=c.committed([TopicPartition(a.topic,0)],timeout=10)[0];assert not cp.error
        low,high=c.get_watermark_offsets(TopicPartition(a.topic,0),timeout=10,cached=False)
        d.update(committed=cp.offset,low=low,high=high,subscribed=False)
    finally:c.close()
d['ended_utc']=datetime.now(timezone.utc).isoformat();d['elapsed_seconds']=time.monotonic()-tick;print(json.dumps(d,sort_keys=True),flush=True)
