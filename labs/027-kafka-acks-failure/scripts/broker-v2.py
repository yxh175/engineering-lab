import argparse
import json
import os
import time
from datetime import datetime, timezone
from confluent_kafka import Consumer,Producer,TopicPartition,version,libversion,KafkaError,KafkaException
from confluent_kafka.admin import AdminClient,NewTopic,ConfigResource,ResourceType
from settings import BROKER
p=argparse.ArgumentParser();p.add_argument('action',choices=['create','metadata','produce','read']);p.add_argument('topic');p.add_argument('--bootstrap',default=BROKER);p.add_argument('--unclean',choices=['true','false'],default='false');p.add_argument('--acks',choices=['1','all'],default='all');p.add_argument('--label');p.add_argument('--event');a=p.parse_args()
tick=time.monotonic();d={'action':a.action,'topic':a.topic,'bootstrap':a.bootstrap,'pid':os.getpid(),'started_utc':datetime.now(timezone.utc).isoformat(),'client':version(),'librdkafka':libversion()}
admin=AdminClient({'bootstrap.servers':a.bootstrap,'socket.timeout.ms':6000})
def metadata():
    m=admin.list_topics(a.topic,timeout=6);t=m.topics[a.topic]
    return {'cluster_id':m.cluster_id,'topic_error':str(t.error) if t.error else None,'brokers':{str(i):{'host':b.host,'port':b.port} for i,b in m.brokers.items()},'partitions':{str(i):{'leader':v.leader,'replicas':v.replicas,'isrs':v.isrs,'error':str(v.error) if v.error else None} for i,v in t.partitions.items()}}
if a.action=='create':
    cfg={'min.insync.replicas':'2','unclean.leader.election.enable':a.unclean}
    admin.create_topics([NewTopic(a.topic,num_partitions=1,replication_factor=-1,replica_assignment=[[1,2,3]],config=cfg)])[a.topic].result(15)
    resource=ConfigResource(ResourceType.TOPIC,a.topic)
    config_deadline=time.monotonic()+12;d['config_polls']=[]
    while True:
        try:
            vals=admin.describe_configs([resource],request_timeout=2)[resource].result(3)
            d['config_polls'].append({'error_code':0,'values':{n:vals[n].value for n in cfg},'elapsed_seconds':time.monotonic()-tick})
            break
        except KafkaException as exc:
            error=exc.args[0]
            d['config_polls'].append({'error_code':error.code(),'error_name':error.name(),'elapsed_seconds':time.monotonic()-tick})
            if error.code()!=KafkaError.UNKNOWN_TOPIC_OR_PART or time.monotonic()>=config_deadline:
                raise
            time.sleep(.25)
    d['configs']={n:{'value':vals[n].value,'source':str(vals[n].source),'is_default':vals[n].is_default} for n in cfg}
    assert {n:d['configs'][n]['value'] for n in cfg}==cfg
    d['metadata']=metadata()
elif a.action=='metadata':d['metadata']=metadata()
elif a.action=='produce':
    cfg={'bootstrap.servers':a.bootstrap,'acks':a.acks,'enable.idempotence':False,'retries':0,'message.timeout.ms':6000,'request.timeout.ms':3000,'socket.timeout.ms':6000}
    producer=Producer(cfg);acks=[];payload=json.dumps({'event_id':a.event,'label':a.label},sort_keys=True,separators=(',',':')).encode()
    def ack(err,msg):acks.append({'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode() if msg.key() else None,'value':payload.decode(),'error':{'code':err.code(),'name':err.name(),'string':str(err)} if err else None})
    producer.produce(a.topic,partition=0,key=a.event.encode(),value=payload,on_delivery=ack)
    remaining=producer.flush(10);assert remaining==0 and len(acks)==1
    d.update(config=cfg,delivery=acks[0],flush_remaining=remaining)
else:
    c=Consumer({'bootstrap.servers':a.bootstrap,'group.id':'lab027-observer-'+a.topic,'enable.auto.commit':False,'enable.auto.offset.store':False,'auto.offset.reset':'earliest','socket.timeout.ms':6000})
    try:
        low,high=c.get_watermark_offsets(TopicPartition(a.topic,0),timeout=10,cached=False);c.assign([TopicPartition(a.topic,0,low)]);messages=[];deadline=time.monotonic()+15
        while len(messages)<high-low and time.monotonic()<deadline:
            msg=c.poll(.2)
            if msg is None:continue
            if msg.error():raise RuntimeError(str(msg.error()))
            messages.append({'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode(),'value':msg.value().decode()})
        assert len(messages)==high-low and [m['offset'] for m in messages]==list(range(low,high))
        d.update(low=low,high=high,messages=messages,manual_assignment_from_actual_low=low,subscribed=False)
    finally:c.close()
d['ended_utc']=datetime.now(timezone.utc).isoformat();d['elapsed_seconds']=time.monotonic()-tick;print(json.dumps(d,sort_keys=True),flush=True)
