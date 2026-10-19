import json
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
setup=[p for p in sorted((LAB/'results').glob('*-docker-setup/manifest.json')) if json.loads(p.read_text())['all_passed']][-1]
e=Evidence(LAB,'kafka-retry-order',[Path(__file__), LAB/'scripts/settings.py', LAB/'scripts/worker.py', LAB/'scripts/broker.py', LAB/'docker-compose.yml', LAB/'sql/schema.sql', LAB/'requirements.txt'],{'trials_per_case':10,'setup_manifest':setup.relative_to(ROOT).as_posix(),'setup_manifest_sha256':sha(setup),'retry_schedule':'Bad retry worker starts after source completes 3; Good source holds at 2 until observer releases'})
nonce=uuid.uuid4().hex[:10];failure=None;active=None
def broker(label,action,topic,group,extra=None):return json.loads(e.require(label,[str(PYTHON),str(LAB/'scripts/broker.py'),action,topic,group,*(extra or [])],timeout=45))
def db(label,case):
    statement=f"SELECT id,seq,event_id FROM completed WHERE case_id='{case}' ORDER BY id; SELECT event_id,attempts FROM attempts WHERE case_id='{case}' ORDER BY event_id;\n"
    rec,out,err=e.run(label,MYSQL,stdin=statement.encode());(e.dest/label/'input.sql').write_bytes(statement.encode());assert rec['exit_code']==0 and b'ERROR' not in err
    return out.decode().strip()
def dbrows(raw):
    lines=[line.split('\t') for line in raw.splitlines() if line]
    return ([{'id':int(v[0]),'seq':int(v[1]),'event_id':v[2]} for v in lines if len(v)==3],{v[0]:int(v[1]) for v in lines if len(v)==2})
def frames(label):return [json.loads(s) for s in (e.dest/label/'stdout.txt').read_text().splitlines() if s]
def args(mode,topic,retry,group,case,n):return [str(PYTHON),'-u',str(LAB/'scripts/worker.py'),mode,topic,retry,group,case,str(e.dest/n)]
def start(label,argv):
    dest=e.dest/label;dest.mkdir(parents=True,exist_ok=False);st=utc();tick=time.monotonic();p=subprocess.Popen(argv,cwd=LAB,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE);q=queue.Queue();out=[];err=[]
    def readout():
        for line in iter(p.stdout.readline,b''):
            out.append(line);q.put(json.loads(line))
        q.put({'event':'eof'})
    def readerr():err.append(p.stderr.read())
    ts=[threading.Thread(target=readout),threading.Thread(target=readerr)]
    for t in ts:t.start()
    return {'p':p,'q':q,'out':out,'err':err,'ts':ts,'dest':dest,'started':st,'tick':tick,'argv':argv,'label':label}
def finish(h,kill=False):
    p=h['p']
    if kill:p.kill()
    else:p.stdin.write(b'C');p.stdin.flush()
    p.wait(timeout=45)
    for t in h['ts']:t.join(timeout=10);assert not t.is_alive()
    p.stdin.close();p.stdout.close();p.stderr.close();(h['dest']/'stdout.txt').write_bytes(b''.join(h['out']));(h['dest']/'stderr.txt').write_bytes(b''.join(h['err']))
    e.data['commands'].append({'label':h['label'],'argv':h['argv'],'started_utc':h['started'],'ended_utc':utc(),'elapsed_seconds':time.monotonic()-h['tick'],'exit_code':p.returncode,'timeout_cleanup':None,'cleanup_kill':kill})
    if not kill:assert p.returncode==0
try:
    e.require('containers-before',['docker','inspect','lab026-kafka','lab026-mysql'])
    for mode in ['async-retry-topic','partition-block']:
        for i in range(1,11):
            case=f'lab026-{nonce}-{mode}-{i:02d}';topic=case;retry=case+'-retry';rg=case+'-retrygroup';events=[uuid.uuid4().hex for _ in range(3)];n=f'{mode}-{i:02d}'
            trial={'case':mode,'trial':i,'name':n,'topic':topic,'retry_topic':retry,'source_group':case,'retry_group':rg,'event_ids':events,'passed':False};e.data['trials'].append(trial)
            prod=broker(n+'/produce','create',topic,case,['--retry',retry,'--events',','.join(events)]);assert [v['offset'] for v in prod['acks']]==[0,1,2]
            e.require(n+'/topics',['docker','exec','lab026-kafka','/opt/kafka/bin/kafka-topics.sh','--bootstrap-server','kafka:9092','--describe','--topic',topic+'|'+retry])
            if mode=='async-retry-topic':e.require(n+'/source-worker',args(mode,topic,retry,case,case,n+'/source-sql'),timeout=60)
            else:
                active=start(n+'/source-worker',args(mode,topic,retry,case,case,n+'/source-sql'));deadline=time.monotonic()+50
                while True:
                    f=active['q'].get(timeout=max(.01,deadline-time.monotonic()));assert f['event']!='eof'
                    if f['event']=='retry_blocked':break
                    assert time.monotonic()<deadline
            checkpoint=db(n+'/db-checkpoint',case)
            checkpoint_rows,checkpoint_attempts=dbrows(checkpoint)
            assert [v['seq'] for v in checkpoint_rows]==([1,3] if mode=='async-retry-topic' else [1])
            assert checkpoint_attempts==({events[0]:1,events[1]:1,events[2]:1} if mode=='async-retry-topic' else {events[0]:1,events[1]:1})
            source=broker(n+'/source-checkpoint','observe',topic,case);rcheck=broker(n+'/retry-checkpoint','observe',retry,rg)
            assert source['committed']==(3 if mode=='async-retry-topic' else 1) and source['high']==3 and rcheck['committed']==-1001 and rcheck['high']==int(mode=='async-retry-topic')
            if active:
                finish(active);active=None
            else:e.require(n+'/retry-worker',args('retry',retry,retry,rg,case,n+'/retry-sql'),timeout=60)
            finaldb=db(n+'/db-final',case);sourceafter=broker(n+'/source-final','observe',topic,case);retryafter=broker(n+'/retry-final','observe',retry,rg)
            final_rows,final_attempts=dbrows(finaldb)
            assert final_attempts=={events[0]:1,events[1]:2,events[2]:1}
            assert sourceafter['committed']==3 and retryafter['committed']==(1 if mode=='async-retry-topic' else -1001)
            sf=frames(n+'/source-worker');received=[f for f in sf if f['event']=='received'];assert len(received)==3 and [f['seq'] for f in received]==[1,2,3]
            assert all(all(r[k]==a[k] for k in ['topic','partition','offset','key','value']) for r,a in zip(received,prod['acks']))
            failed=[f for f in sf if f['event']=='business_failure'];assert len(failed)==1 and failed[0]['seq']==2 and failed[0]['attempt']==1
            successful=[f for f in sf if f['event']=='business_committed']
            if mode=='async-retry-topic':
                rf=frames(n+'/retry-worker');rmsg=next(f for f in rf if f['event']=='received');ack=next(f for f in sf if f['event']=='retry_published')['ack']
                assert all(rmsg[k]==ack[k] for k in ['topic','partition','offset','key','value']) and rmsg['value']==received[1]['value'] and rmsg['pid']!=received[0]['pid']
                successful+=[f for f in rf if f['event']=='business_committed']
            else:
                blocked=next(f for f in sf if f['event']=='retry_blocked');assert (blocked['position'],blocked['committed'])==(2,1)
                assert sf.index(next(f for f in sf if f['event']=='retry_released'))<sf.index(received[2])
            sequence=[v['seq'] for v in successful[-1]['rows']];expected=[1,3,2] if mode=='async-retry-topic' else [1,2,3];assert sequence==expected and len(successful)==3
            assert successful[-1]['rows']==final_rows
            assert all(v['attempt']==(2 if v['seq']==2 else 1) for v in successful)
            trial.update(passed=True,final_sequence=sequence,checkpoint_database_stdout=checkpoint,final_database_stdout=finaldb,source_pid=received[0]['pid'],source_member_id=received[0]['member_id'])
            print(f'{n}: PASS business order {sequence}',flush=True)
    e.require('containers-after',['docker','inspect','lab026-kafka','lab026-mysql']);e.require('kafka-logs',['docker','logs','lab026-kafka']);e.require('mysql-logs',['docker','logs','lab026-mysql'])
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
    if active:
        try:finish(active,True)
        except BaseException as exc:(e.dest/'cleanup-error.txt').write_text(str(exc))
raise SystemExit(0 if e.seal(failure) else 1)
