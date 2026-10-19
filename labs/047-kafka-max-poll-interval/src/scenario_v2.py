import argparse
import ctypes
import os
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from confluent_kafka import Producer,Consumer,TopicPartition
from confluent_kafka.admin import AdminClient,NewTopic
a=argparse.ArgumentParser();a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
d=args.out;d.mkdir(parents=True,exist_ok=False);events=[];workers=[]
def save(name,value):(d/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')
def event(name,**kw):events.append({'event':name,'ns':time.perf_counter_ns(),**kw})
def start(role,topic,group):
    argv=[sys.executable,'-u',str(Path(__file__).with_name('worker.py')),role,args.case,topic,group]
    p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    h={'role':role,'p':p,'q':queue.Queue(),'out':[],'err':[],'argv':argv,'start_ns':time.perf_counter_ns()}
    def stdout():
        for line in iter(p.stdout.readline,b''):
            h['out'].append(line);frame=json.loads(line);event('worker-frame',role=role,frame=frame);h['q'].put(frame)
        h['q'].put({'event':'eof'})
    def stderr():h['err'].append(p.stderr.read())
    h['threads']=[threading.Thread(target=stdout),threading.Thread(target=stderr)]
    for t in h['threads']:t.start()
    workers.append(h);event('started',role=role,pid=p.pid);return h
def await_event(h,name):
    deadline=time.perf_counter()+30
    while True:
        v=h['q'].get(timeout=max(.01,deadline-time.perf_counter()))
        assert v['event']!='eof',h['role']
        if v['event']==name:return v
def release(h):h['p'].stdin.write(b'C');h['p'].stdin.flush();event('released',role=h['role'])
def finish(h):
    h['p'].wait(timeout=15);assert h['p'].returncode==0
    event('finished',role=h['role'],exit_code=0)
def actual_alive(pid):
    assert os.name=='nt'
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];k.OpenProcess.restype=ctypes.c_void_p
    k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=k.OpenProcess(0x1000,False,pid);assert handle,ctypes.get_last_error()
    value=ctypes.c_uint32()
    try:assert k.GetExitCodeProcess(handle,ctypes.byref(value))
    finally:k.CloseHandle(handle)
    return {'pid':pid,'active':value.value==259,'exit_code':value.value,'method':'Win32 GetExitCodeProcess on worker pid'}
def group_snapshot(admin,group):
    x=admin.describe_consumer_groups([group],request_timeout=10)[group].result(15)
    return {'group':x.group_id,'state':str(x.state),'members':[{'member_id':m.member_id,'client_id':m.client_id,'host':m.host,'assignment':[{'topic':p.topic,'partition':p.partition} for p in m.assignment.topic_partitions]} for m in x.members]}
broker='127.0.0.1:19047';admin=AdminClient({'bootstrap.servers':broker})
topic='lab047-'+args.case+'-'+uuid.uuid4().hex;group=topic
try:
    admin.create_topics([NewTopic(topic,num_partitions=1,replication_factor=1)])[topic].result(15)
    delivery=[]
    def ack(err,msg):
        assert err is None;delivery.append({'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset(),'key':msg.key().decode(),'value':msg.value().decode()})
    producer=Producer({'bootstrap.servers':broker,'acks':'all','enable.idempotence':True})
    producer.produce(topic,partition=0,key='job',value='42',on_delivery=ack);assert producer.flush(15)==0;save('delivery.json',delivery)
    wa=start('a',topic,group);received=await_event(wa,'received')
    save('initial-group.json',group_snapshot(admin,group))
    if args.case=='overdue':
        await_event(wa,'processing');event('begin-no-poll');time.sleep(3);event('end-no-poll')
    else:
        commit=await_event(wa,'commit');assert commit['success'];finish(wa)
    wb=start('b',topic,group);complete=await_event(wb,'complete')
    snapshot=group_snapshot(admin,group);save('new-owner-group.json',snapshot)
    event('a-liveness-at-new-owner',launcher_exit_code=wa['p'].poll(),**(actual_alive(received['pid']) if args.case=='overdue' else {'pid':received['pid'],'active':False,'exit_code':0,'method':'closed frame and launcher wait completed'}))
    if args.case=='overdue':
        assert wa['p'].poll() is None;release(wa);commit=await_event(wa,'commit');assert not commit['success'];finish(wa)
    release(wb);finish(wb)
    observer=Consumer({'bootstrap.servers':broker,'group.id':group,'enable.auto.commit':False})
    try:
        offset=observer.committed([TopicPartition(topic,0)],timeout=10)[0];assert not offset.error
        low,high=observer.get_watermark_offsets(TopicPartition(topic,0),timeout=10);save('final-offset.json',{'committed':offset.offset,'low':low,'high':high})
    finally:observer.close()
    report={'case':args.case,'topic':topic,'group':group,'a_pid':received['pid'],'b_pid':complete['pid'],'a_launcher_pid':wa['p'].pid,'b_launcher_pid':wb['p'].pid,'a_commit_success':commit['success'],'a_commit_error':commit['error'],'b_received':complete['received'],'committed':offset.offset}
    save('report.json',report);print(json.dumps(report),flush=True)
finally:
    for h in workers:
        p=h['p']
        if p.poll() is None:p.kill();p.wait(timeout=10);event('cleanup-kill',role=h['role'])
        for t in h['threads']:t.join(timeout=10);assert not t.is_alive()
        for f in [p.stdin,p.stdout,p.stderr]:f.close()
        (d/(h['role']+'.stdout.jsonl')).write_bytes(b''.join(h['out']));(d/(h['role']+'.stderr.txt')).write_bytes(b''.join(h['err']))
        save(h['role']+'.process.json',{'argv':h['argv'],'pid':p.pid,'worker_pid':json.loads(h['out'][0])['pid'],'exit_code':p.returncode,'start_ns':h['start_ns'],'end_ns':time.perf_counter_ns()})
    save('controller-events.json',events)
