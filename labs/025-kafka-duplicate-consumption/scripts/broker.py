import argparse
import json
import time
from datetime import datetime, timezone
from confluent_kafka import Consumer, Producer, TopicPartition, version, libversion
from confluent_kafka.admin import AdminClient, NewTopic
from settings import BROKER, consumer_config

p=argparse.ArgumentParser();p.add_argument('action',choices=['create','observe','tail']);p.add_argument('topic');p.add_argument('group');p.add_argument('--event');a=p.parse_args()
started=datetime.now(timezone.utc).isoformat();tick=time.monotonic()
d={'action':a.action,'topic':a.topic,'group':a.group,'started_utc':started,'client':version(),'librdkafka':libversion()}
if a.action=='create':
    admin=AdminClient({'bootstrap.servers':BROKER})
    admin.create_topics([NewTopic(a.topic,num_partitions=1,replication_factor=1)])[a.topic].result(15)
    meta=admin.list_topics(a.topic,timeout=10);t=meta.topics[a.topic]
    assert not t.error and len(t.partitions)==1
    d['metadata']={str(i):{'leader':v.leader,'replicas':v.replicas,'isrs':v.isrs} for i,v in t.partitions.items()}
    payload=json.dumps({'case_id':a.group,'event_id':a.event,'amount':1},sort_keys=True,separators=(',',':')).encode()
    delivered=[]
    def ack(err,msg):
        if err:raise RuntimeError(str(err))
        delivered.append({'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode(),'value':payload.decode()})
    producer=Producer({'bootstrap.servers':BROKER,'acks':'all','enable.idempotence':True})
    producer.produce(a.topic,key=a.group.encode(),value=payload,on_delivery=ack)
    assert producer.flush(15)==0 and len(delivered)==1
    d['delivery']=delivered[0]
else:
    c=Consumer(consumer_config(a.group))
    try:
        cp=c.committed([TopicPartition(a.topic,0)],timeout=10)[0]
        assert not cp.error
        low,high=c.get_watermark_offsets(TopicPartition(a.topic,0),timeout=10,cached=False)
        d.update(committed=cp.offset,low=low,high=high,subscribed=False)
        if a.action=='tail':
            assert cp.offset>=0
            c.assign([TopicPartition(a.topic,0,cp.offset)])
            msg=c.poll(1)
            assert msg is None
            d.update(message=None,position=c.position([TopicPartition(a.topic,0)])[0].offset,manual_assignment_from_committed=cp.offset)
    finally:c.close()
d['elapsed_seconds']=time.monotonic()-tick;d['ended_utc']=datetime.now(timezone.utc).isoformat()
print(json.dumps(d,sort_keys=True),flush=True)
