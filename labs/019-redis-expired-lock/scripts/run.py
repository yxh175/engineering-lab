import csv
import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha,utc
from redis_session import RedisSession
from http_capture import HTTPCapture
GO=os.environ.get('LAB_GO','go')
GOIMAGE='golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb'
REDIS='redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'
LOCK='lab019:lock';SEQ='lab019:sequence'
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))
ACQUIRE=(LAB/'src/acquire.lua').read_text(encoding='utf-8');UNLOCK=(LAB/'src/unlock.lua').read_text(encoding='utf-8');OBSERVE=(LAB/'src/observe.lua').read_text(encoding='utf-8')
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def main():
    sources=[LAB/'docker-compose.yml',LAB/'Dockerfile',LAB/'go.mod',LAB/'src/main.go',LAB/'src/cases.json',LAB/'src/acquire.lua',LAB/'src/unlock.lua',LAB/'src/observe.lua',Path(__file__)]
    e=Evidence(LAB,'docker-threads',sources,{'repeats_per_case':10,'A_ttl_ms':1200,'B_C_ttl_ms':30000,
        'actors':'two real threads in one Python process, separate RESP connections; C probe/Observer separate',
        'pause':'thread Event after A HTTP enter; no renewal; release only after actual nil/PTTL-2 and B2 write',
        'resource':'controlled Go in-memory resource; write fence check and state update under one Mutex',
        'fence':'successful acquire Lua INCR on one live volatile Redis; reset per trial; no failover proof',
        'HTTP409':'expected only for fenced stale A write; captured original metadata/body, shared tool unchanged',
        'order':'forward odd reverse even','observation_budget_seconds':8,'performance_claim':False})
    for name in ['redis_session.py','http_capture.py']:e.data['shared_source_sha256']['shared/scripts/'+name]=sha(ROOT/'shared/scripts'/name)
    h=HTTPCapture(e);compose=['docker','compose','-p','engineering-lab-019','-f',str(LAB/'docker-compose.yml')]
    failure=None;started=False
    def http(label,url,body=None,expected=200):
        try:payload=h.call(label,url,method='POST' if body is not None else 'GET',body=json.dumps(body).encode() if body is not None else None)
        except RuntimeError as exc:
            if expected!=409 or str(exc)!='HTTP status 409':raise
            folder=e.dest/'http-captures'/label;meta=json.loads((folder/'metadata.json').read_text())
            assert meta['status']==409 and not meta['completed'] and meta['error']=='HTTP status 409'
            payload=(folder/'response-body.bin').read_bytes()
        else:assert expected==200,'expected rejection but got HTTP200'
        return json.loads(payload)
    try:
        assert 'go1.25.4' in e.require('native-go-version',[GO,'version']).decode()
        e.require('native-env',[GO,'env','GOOS','GOARCH','CGO_ENABLED','GOTOOLCHAIN']);e.require('native-vet',[GO,'vet','./src'],cwd=LAB)
        e.require('docker-version',['docker','version']);e.require('redis-image',['docker','image','inspect',REDIS])
        e.require('resource-build',compose+['build'],timeout=210);e.require('resource-image',['docker','image','inspect','engineering-lab-019-resource:local'])
        e.require('fixture-recreate',compose+['down','--volumes','--remove-orphans']);e.require('startup',compose+['up','-d','--wait','--wait-timeout','60'],timeout=90);started=True
        ids={name:e.require(name+'-id',compose+['ps','-q',name]).decode().strip() for name in ['redis','resource']}
        assert all(re.fullmatch('[a-f0-9]{64}',v) for v in ids.values());e.require('container-inspect',['docker','inspect',*ids.values()])
        ports={}
        for name,inner in [('redis','6379'),('resource','8080')]:
            value=e.require(name+'-port',compose+['port',name,inner]).decode().strip();assert re.fullmatch(r'127\.0\.0\.1:\d+',value) and not value.endswith(':0');ports[name]=value
        endpoint='http://'+ports['resource'];info=e.require('redis-info',['docker','exec',ids['redis'],'redis-cli','INFO','server']).decode();assert 'redis_version:7.4.11' in info;e.data['parameters']['actual_redis_version']='7.4.11'
        e.require('linux-vet',['docker','run','--rm','--network','none','--cpus','2','--memory','512m','-e','CGO_ENABLED=0','-e','GOTOOLCHAIN=local','-e','GOMAXPROCS=2','-v',str(LAB)+':/lab:ro','-w','/lab',GOIMAGE,'go','vet','./src'],timeout=120)
        for trial in range(1,11):
            for c in CASES if trial%2 else list(reversed(CASES)):
                label=f'{c["case"]}-{trial:02d}';error='';detail={};sessions={};observations=[];actor_results={}
                owners={name:uuid.uuid4().hex for name in ['A','B','C']};assert len(set(owners.values()))==3
                releaseA=threading.Event();releaseB=threading.Event();enteredA=threading.Event();readyB=threading.Event();tick=time.monotonic()
                try:
                    for role in ['A','B','C','observer']:
                        r=RedisSession(e,label+'-'+role,'127.0.0.1',int(ports['redis'].split(':')[1]));sessions[role]=r;e.data.setdefault('redis_sessions',[]).append(r.record)
                    obs=sessions['observer'];probe=sessions['C']
                    observer_id=obs.call(label+'-observer-id','CLIENT','ID');C_id=probe.call(label+'-C-id','CLIENT','ID')
                    assert obs.call(label+'-flush','FLUSHDB')==b'OK';config={'run':label,'fenced':c['fenced']};assert http(label+'-configure',endpoint+'/configure',config)==config
                    def observe(phase):
                        value=obs.call(label+'-observe-'+phase,'EVAL',OBSERVE,2,LOCK,SEQ)
                        rec={'phase':phase,'server_time_us':int(value[0])*1000000+int(value[1]),'owner':value[2].decode() if value[2] is not None else None,
                            'pttl':value[3],'sequence':int(value[4]) if value[4] is not None else None,'client_elapsed_seconds':time.monotonic()-tick}
                        assert (rec['owner'] is None and rec['pttl']==-2) or (rec['owner'] is not None and rec['pttl']>=0)
                        observations.append(rec);return rec
                    def actor(role):
                        r=sessions[role];record={'role':role,'owner':owners[role],'pid':os.getpid(),'thread_id':threading.get_ident(),'native_thread_id':threading.get_native_id(),'started_utc':utc(),'error':''}
                        try:
                            record['redis_client_id']=r.call(label+'-'+role+'-id','CLIENT','ID')
                            result=r.call(label+'-'+role+'-acquire','EVAL',ACQUIRE,2,LOCK,SEQ,owners[role],1200 if role=='A' else 30000)
                            assert result==[1,1 if role=='A' else 2];record['fence']=result[1]
                            body={'run':label,'actor':role,'owner':owners[role],'fence':result[1]}
                            record['enter']=http(label+'-'+role+'-enter',endpoint+'/enter',body)
                            if role=='A':
                                enteredA.set();assert releaseA.wait(20),'A release barrier timed out'
                                record['unlock']=r.call(label+'-A-unlock','DEL',LOCK) if c['unlock']=='DEL' else r.call(label+'-A-unlock','EVAL',UNLOCK,1,LOCK,owners['A'])
                                record['write']=http(label+'-A-write',endpoint+'/write',{**body,'value':'A-stale'},expected=409 if c['fenced'] else 200)
                            else:
                                record['write']=http(label+'-B-write',endpoint+'/write',{**body,'value':'B-new'});assert record['write']['accepted']
                                readyB.set();assert releaseB.wait(20),'B release barrier timed out'
                                record['unlock']=r.call(label+'-B-unlock','EVAL',UNLOCK,1,LOCK,owners['B'])
                            record['leave']=http(label+'-'+role+'-leave',endpoint+'/leave',body)
                            return record
                        except Exception as exc:record['error']=str(exc) or type(exc).__name__;raise
                        finally:
                            record['ended_utc']=utc();write(e.dest/(label+'-'+role+'-actor.json'),record)
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        try:
                            futureA=pool.submit(actor,'A');assert enteredA.wait(20),'A enter barrier timed out'
                            initial=observe('initial-A');assert initial['owner']==owners['A'] and initial['pttl']>0 and initial['sequence']==1
                            initial_snapshot=http(label+'-snapshot-A-active',endpoint+'/snapshot');assert initial_snapshot['active']==1 and initial_snapshot['actors']['A']['running']
                            wait_tick=time.monotonic();expired_samples=0
                            while True:
                                state=observe(f'expiry-{expired_samples:03d}');expired_samples+=1
                                if state['owner'] is None:break
                                assert state['owner']==owners['A'] and time.monotonic()-wait_tick<8;time.sleep(.025)
                            assert state['pttl']==-2 and state['sequence']==1
                            futureB=pool.submit(actor,'B');assert readyB.wait(20),'B write barrier timed out'
                            B_owned=observe('B-owned');assert B_owned['owner']==owners['B'] and B_owned['pttl']>0 and B_owned['sequence']==2
                            overlap=http(label+'-snapshot-overlap',endpoint+'/snapshot')
                            assert overlap['active']==overlap['peak']==2 and all(a['running'] for a in overlap['actors'].values()) and len(overlap['actors'])==2
                            assert overlap['value']=='B-new' and overlap['highest_fence']==2 and len(overlap['writes'])==1 and overlap['writes'][0]['actor']=='B'
                            releaseA.set();A=futureA.result(timeout=20);actor_results['A']=A
                            afterA=observe('after-A');bad=c['unlock']=='DEL'
                            assert A['unlock']==(1 if bad else 0) and afterA['owner']==(None if bad else owners['B'])
                            assert A['write']['accepted'] is (not c['fenced']) and A['write']['status']==(409 if c['fenced'] else 200)
                            contender=probe.call(label+'-C-acquire','EVAL',ACQUIRE,2,LOCK,SEQ,owners['C'],30000)
                            assert contender==([1,3] if bad else [0,0]);afterC=observe('after-C');assert afterC['owner']==owners['C' if bad else 'B'] and afterC['pttl']>0
                            releaseB.set();B=futureB.result(timeout=20);actor_results['B']=B;assert B['unlock']==(0 if bad else 1)
                            afterB=observe('after-B');assert afterB['owner']==(owners['C'] if bad else None)
                            if bad:assert probe.call(label+'-C-unlock','EVAL',UNLOCK,1,LOCK,owners['C'])==1
                            final_lock=observe('final');assert final_lock['owner'] is None and final_lock['pttl']==-2 and final_lock['sequence']==(3 if bad else 2)
                        finally:releaseA.set();releaseB.set()
                    assert A['pid']==B['pid']==os.getpid() and A['native_thread_id']!=B['native_thread_id'] and A['thread_id']!=B['thread_id']
                    assert len({A['redis_client_id'],B['redis_client_id'],C_id,observer_id})==4
                    final=http(label+'-snapshot-final',endpoint+'/snapshot');expected='B-new' if c['fenced'] else 'A-stale'
                    assert final['config']==config and final['value']==expected and final['highest_fence']==2 and final['active']==0 and final['peak']==2
                    assert final['go_version']=='go1.25.4' and final['goos']=='linux' and len(final['writes'])==2
                    assert [w['actor'] for w in final['writes']]==['B','A'] and final['writes']==[B['write'],A['write']]
                    for role,record in actor_results.items():
                        a=final['actors'][role];assert a['owner']==owners[role] and a['fence']==record['fence'] and not a['running'] and a['left_ns']>a['entered_ns']
                    assert max(a['entered_ns'] for a in final['actors'].values())<min(a['left_ns'] for a in final['actors'].values())
                    detail.update(owners=owners,actor_native_thread_ids=[A['native_thread_id'],B['native_thread_id']],actor_pid=os.getpid(),
                        redis_client_ids=[A['redis_client_id'],B['redis_client_id'],C_id,observer_id],A_unlock=A['unlock'],B_unlock=B['unlock'],
                        A_stale_status=A['write']['status'],A_stale_accepted=A['write']['accepted'],C_acquired=bool(contender[0]),
                        final_resource_value=expected,workflow_peak=2,final_active=0,expiry_poll_samples=expired_samples,
                        lease_expired_client_seconds=state['client_elapsed_seconds'],
                        server_TIME_backwards=sum(observations[i]['server_time_us']<observations[i-1]['server_time_us'] for i in range(1,len(observations))))
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    releaseA.set();releaseB.set();write(e.dest/(label+'-observations.json'),observations)
                    for r in sessions.values():r.close()
                e.data['trials'].append({'case':c['case'],'trial':trial,'passed':not error,'verification_error':error,**detail})
                print(f'{label}: {"FAIL" if error else "PASS"} Aunlock={detail.get("A_unlock")} staleHTTP={detail.get("A_stale_status")} final={detail.get("final_resource_value")} C={detail.get("C_acquired")} {error}',flush=True)
                if error:raise RuntimeError(label+': '+error+'; stop remaining trials')
        e.require('server-logs',compose+['logs','--no-color'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if started:e.run('failure-server-logs',compose+['logs','--no-color'])
    if len(e.data['trials'])!=30:failure=failure or 'incomplete three-by-ten matrix'
    fields=['case','trial','passed','A_unlock','A_stale_status','A_stale_accepted','C_acquired','B_unlock','final_resource_value','workflow_peak','expiry_poll_samples','lease_expired_client_seconds','server_TIME_backwards']
    with (e.dest/'summary.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1
if __name__=='__main__':raise SystemExit(main())
