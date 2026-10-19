import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from settings import LAB,ROOT,PYTHON,MYSQL
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha,utc
from process_handle import ProcessHandle

setup=[p for p in sorted((LAB/'results').glob('*-docker-setup/manifest.json')) if json.loads(p.read_text())['all_passed']][-1]
sources=[Path(__file__), LAB/'scripts/process_handle.py', LAB/'scripts/worker.py', LAB/'scripts/broker.py', LAB/'scripts/settings.py', LAB/'docker-compose.yml', LAB/'sql/schema.sql', LAB/'requirements.txt']
e=Evidence(LAB,'kafka-redelivery',sources,{'trials_per_case':10,'setup_manifest':setup.relative_to(ROOT).as_posix(),'setup_manifest_sha256':sha(setup),'forced_exit_platform':os.name})
nonce=uuid.uuid4().hex[:12];failure=None;active=None
def saved(n,d):
    p=e.dest/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8',newline='\n')
def broker(label,action,topic,group,event=None):
    args=[str(PYTHON),str(LAB/'scripts/broker.py'),action,topic,group]
    if event:args+=['--event',event]
    return json.loads(e.require(label,args,timeout=45))
def sql(label,text):
    r,out,err=e.run(label,MYSQL,stdin=text.encode(),timeout=15)
    (e.dest/label/'input.sql').write_bytes(text.encode())
    assert r['exit_code']==0 and b'ERROR' not in err,err
    return out.decode().strip()
def frames(label):return [json.loads(s) for s in (e.dest/label/'stdout.txt').read_text().splitlines() if s]
def crash_start(label,args):
    dest=e.dest/label;dest.mkdir(parents=True,exist_ok=False)
    start=utc();tick=time.monotonic();p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=LAB)
    q=queue.Queue();out=[];err=[]
    def readout():
        for line in iter(p.stdout.readline,b''):
            out.append(line)
            try:q.put(json.loads(line))
            except json.JSONDecodeError:q.put({'event':'invalid-json','line':line.decode(errors='replace')})
        q.put({'event':'eof'})
    def readerr():err.append(p.stderr.read())
    ts=[threading.Thread(target=readout),threading.Thread(target=readerr)]
    for t in ts:t.start()
    return {'process':p,'queue':q,'threads':ts,'out':out,'err':err,'dest':dest,'start':start,'tick':tick,'argv':args,'label':label}
def crash_finish(h,expected):
    p=h['process'];native=h.get('consumer_handle');before=native.state() if native else None
    if expected:assert before and before['exit_code']==259
    kill=utc();p.kill();p.wait(timeout=10)
    after=native.wait() if native else None
    if native:native.close()
    if expected:assert after['exit_code']!=259
    for t in h['threads']:t.join(timeout=10);assert not t.is_alive()
    p.stdin.close();p.stdout.close();p.stderr.close()
    (h['dest']/'stdout.txt').write_bytes(b''.join(h['out']));(h['dest']/'stderr.txt').write_bytes(b''.join(h['err']))
    rec={'label':h['label'],'argv':h['argv'],'started_utc':h['start'],'ended_utc':utc(),'elapsed_seconds':time.monotonic()-h['tick'],'exit_code':p.returncode,'timeout_cleanup':None,'forced_termination_utc':kill,'expected_forced_exit':expected,'pid':p.pid,'consumer_before_kill':before,'consumer_after_kill':after}
    e.data['commands'].append(rec)
    assert not expected or p.returncode==(1 if os.name=='nt' else -9),rec
    return rec
try:
    e.require('containers-before',['docker','inspect','lab025-kafka','lab025-mysql'])
    e.require('client-version',[str(PYTHON),'-c','import confluent_kafka as k,json;print(json.dumps({"client":k.version(),"librdkafka":k.libversion()}))'])
    for mode in ['no-dedupe','txn-dedupe']:
        for i in range(1,11):
            group=f'lab025-{nonce}-{mode}-{i:02d}';topic=group;event=uuid.uuid4().hex;name=f'{mode}-{i:02d}'
            trial={'case':mode,'trial':i,'name':name,'topic':topic,'group':group,'event_id':event,'passed':False};e.data['trials'].append(trial)
            assert sql(name+'/init',f"INSERT INTO ledger VALUES ('{group}',0); SELECT balance FROM ledger WHERE case_id='{group}';\n")=='0'
            prod=broker(name+'/produce','create',topic,group,event);assert prod['delivery']['offset']==0
            e.require(name+'/topic-describe',['docker','exec','lab025-kafka','/opt/kafka/bin/kafka-topics.sh','--bootstrap-server','kafka:9092','--describe','--topic',topic])
            args=[str(PYTHON),'-u',str(LAB/'scripts/worker.py'),mode,'crash',topic,group,event,str(e.dest/name/'crash-sql')]
            active=crash_start(name+'/crash-worker',args);deadline=time.monotonic()+50
            while True:
                frame=active['queue'].get(timeout=max(.01,deadline-time.monotonic()))
                assert frame['event']!='eof',frame
                if frame['event']=='received':active['consumer_handle']=ProcessHandle(frame['pid'])
                if frame['event']=='await_offset_permission':break
                assert time.monotonic()<deadline
            beforedb=[int(x) for x in sql(name+'/db-before-kill',f"SELECT balance,(SELECT COUNT(*) FROM applied WHERE case_id='{group}') FROM ledger WHERE case_id='{group}';\n").split('\t')]
            assert beforedb==[1,int(mode=='txn-dedupe')]
            before=broker(name+'/offset-before-kill','observe',topic,group);assert before['committed']==-1001 and (before['low'],before['high'])==(0,1)
            e.require(name+'/group-before-kill',['docker','exec','lab025-kafka','/opt/kafka/bin/kafka-consumer-groups.sh','--bootstrap-server','kafka:9092','--describe','--group',group,'--members','--verbose'])
            killed=crash_finish(active,True);active=None
            restart=e.require(name+'/restart-worker',[str(PYTHON),'-u',str(LAB/'scripts/worker.py'),mode,'restart',topic,group,event,str(e.dest/name/'restart-sql')],timeout=60)
            after=broker(name+'/offset-after','observe',topic,group);assert (after['committed'],after['low'],after['high'])==(1,0,1)
            tail=broker(name+'/tail','tail',topic,group);assert tail['committed']==tail['manual_assignment_from_committed']==1 and tail['message'] is None and tail['position'] in [-1001,1]
            afterdb=[int(x) for x in sql(name+'/db-after',f"SELECT balance,(SELECT COUNT(*) FROM applied WHERE case_id='{group}') FROM ledger WHERE case_id='{group}';\n").split('\t')]
            assert afterdb==([2,0] if mode=='no-dedupe' else [1,1])
            e.require(name+'/group-after',['docker','exec','lab025-kafka','/opt/kafka/bin/kafka-consumer-groups.sh','--bootstrap-server','kafka:9092','--describe','--group',group])
            first=frames(name+'/crash-worker');second=frames(name+'/restart-worker')
            one=next(f for f in first if f['event']=='received');two=next(f for f in second if f['event']=='received')
            assert all(one[k]==two[k]==prod['delivery'][k] for k in ['topic','partition','offset','key','value'])
            assert one['pid']!=two['pid'] and one['member_id'] and two['member_id'] and one['member_id']!=two['member_id']
            assert one['committed']==two['committed']==-1001 and one['position']==two['position']==1
            assert not any(f['event'] in ['offset_committed','closed'] for f in first)
            b1=next(f for f in first if f['event']=='business_committed');b2=next(f for f in second if f['event']=='business_committed')
            assert [b1['balance'],b1['fresh'],b1['markers']]==[1,1,int(mode=='txn-dedupe')]
            assert [b2['balance'],b2['fresh'],b2['markers']]==([2,1,0] if mode=='no-dedupe' else [1,0,1])
            commit=next(f for f in second if f['event']=='offset_committed');assert commit['partitions']==[{'topic':topic,'partition':0,'offset':1,'error':None}]
            trial.update(passed=True,first_pid=one['pid'],second_pid=two['pid'],first_member_id=one['member_id'],second_member_id=two['member_id'],forced_exit_code=killed['exit_code'],consumer_exit_code=killed['consumer_after_kill']['exit_code'],launcher_pid=killed['pid'],balance_before=beforedb[0],balance_after=afterdb[0],markers_after=afterdb[1],restart_received_seconds=two['elapsed_seconds'],committed_before=before['committed'],committed_after=after['committed'])
            print(f'{name}: PASS balance {beforedb[0]}->{afterdb[0]} offset {before["committed"]}->{after["committed"]}',flush=True)
    e.require('containers-after',['docker','inspect','lab025-kafka','lab025-mysql']);e.require('kafka-logs',['docker','logs','lab025-kafka']);e.require('mysql-logs',['docker','logs','lab025-mysql'])
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
    if active is not None:
        try:crash_finish(active,False)
        except BaseException as exc:saved('cleanup-error.json',{'error':str(exc)})
raise SystemExit(0 if e.seal(failure) else 1)
