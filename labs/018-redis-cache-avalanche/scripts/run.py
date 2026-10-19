import csv
import json
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha
from redis_session import RedisSession
from http_capture import HTTPCapture
GO=os.environ.get('LAB_GO','go')
GOIMAGE='golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb'
REDIS='redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))
KEYS=[f'lab018:item:{i:03d}' for i in range(80)]
SEED=(LAB/'src/seed.lua').read_text(encoding='utf-8');SAMPLE=(LAB/'src/sample.lua').read_text(encoding='utf-8')
def time_us(v):return int(v[0])*1000000+int(v[1])
def ttls(c):
    if c['offset_mode']=='none':slots=[0]*80
    elif c['offset_mode']=='one-per-batch':slots=[random.Random(c['seed']).randrange(8)]*80
    else:
        rng=random.Random(c['seed']);slots=[rng.randrange(8) for _ in KEYS]
    return [c['base_ms']+slot*500 for slot in slots]
def write(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def main():
    sources=[LAB/'docker-compose.yml',LAB/'Dockerfile',LAB/'go.mod',LAB/'src/main.go',LAB/'src/cases.json',LAB/'src/seed.lua',LAB/'src/sample.lua',Path(__file__)]
    e=Evidence(LAB,'docker-python',sources,{'repeats_per_case':10,'keys':80,'origin_delay_ms':10,'HTTP_workers_max':8,
        'sampling_target_ms':200,'sampling':'EVAL performs 80 GET/PTTL plus server TIME; fill work can delay next sample',
        'seed':'server TIME reference with actual SET PXAT in one script','refill_ttl_ms':30000,
        'clock':'Redis TIME is wallclock, client elapsed monotonic; both captured','performance_claim':False,
        'expected_ttl_histogram':{c['case']:dict(sorted(Counter(ttls(c)).items())) for c in CASES},
        'order':'forward odd reverse even','origin':'real HTTP per-key fixed fresh:key; not a database'})
    for name in ['redis_session.py','http_capture.py']:e.data['shared_source_sha256']['shared/scripts/'+name]=sha(ROOT/'shared/scripts'/name)
    h=HTTPCapture(e);compose=['docker','compose','-p','engineering-lab-018','-f',str(LAB/'docker-compose.yml')]
    failure=None;started=False
    def http(label,url,body=None):
        return json.loads(h.call(label,url,method='POST' if body is not None else 'GET',body=json.dumps(body).encode() if body is not None else None))
    try:
        assert 'go1.25.4' in e.require('native-go-version',[GO,'version']).decode()
        e.require('native-env',[GO,'env','GOOS','GOARCH','CGO_ENABLED','GOTOOLCHAIN'])
        e.require('native-vet',[GO,'vet','./src'],cwd=LAB)
        e.require('docker-version',['docker','version']);e.require('redis-image',['docker','image','inspect',REDIS])
        e.require('origin-build',compose+['build'],timeout=210);e.require('origin-image',['docker','image','inspect','engineering-lab-018-origin:local'])
        e.require('fixture-recreate',compose+['down','--volumes','--remove-orphans'])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','60'],timeout=90);started=True
        ids={name:e.require(name+'-id',compose+['ps','-q',name]).decode().strip() for name in ['redis','origin']}
        assert all(re.fullmatch('[a-f0-9]{64}',i) for i in ids.values());e.require('container-inspect',['docker','inspect',*ids.values()])
        ports={}
        for name,inner in [('redis','6379'),('origin','8080')]:
            value=e.require(name+'-port',compose+['port',name,inner]).decode().strip()
            assert re.fullmatch(r'127\.0\.0\.1:\d+',value) and not value.endswith(':0');ports[name]=value
        endpoint='http://'+ports['origin'];info=e.require('redis-info',['docker','exec',ids['redis'],'redis-cli','INFO','server']).decode()
        assert 'redis_version:7.4.11' in info;e.data['parameters']['actual_redis_version']='7.4.11'
        e.require('linux-vet',['docker','run','--rm','--network','none','--cpus','2','--memory','512m','-e','CGO_ENABLED=0','-e','GOTOOLCHAIN=local','-e','GOMAXPROCS=2','-v',str(LAB)+':/lab:ro','-w','/lab',GOIMAGE,'go','vet','./src'],timeout=120)
        for trial in range(1,11):
            for c in CASES if trial%2 else list(reversed(CASES)):
                label=f'{c["case"]}-{trial:02d}';error='';detail={};r=None
                samples=[];events=[];filled=set()
                try:
                    r=RedisSession(e,label,'127.0.0.1',int(ports['redis'].split(':')[1]));e.data.setdefault('redis_sessions',[]).append(r.record)
                    assert r.call(label+'-flush','FLUSHDB')==b'OK'
                    config={'run':label,'total':80,'delay_ms':10};assert http(label+'-configure',endpoint+'/configure',config)==config
                    ttl_values=ttls(c);seed_tick=time.monotonic();seed=r.call(label+'-seed','EVAL',SEED,80,*KEYS,*ttl_values)
                    seed_us=time_us(seed);seed_ms=seed_us//1000
                    assert len(seed[2])==80
                    for key,ttl,row in zip(KEYS,ttl_values,seed[2]):
                        assert row[:4]==[key.encode(),ttl,seed_ms+ttl,b'OK'] and row[4]>0
                    write(e.dest/(label+'-seed.json'),{'server_time_us':seed_us,'ttls':ttl_values,'deadlines_ms':[seed_ms+x for x in ttl_values],
                                                       'rows':[[v.decode() if isinstance(v,bytes) else v for v in row] for row in seed[2]]})
                    def sample(index,phase='scan'):
                        value=r.call(f'{label}-{phase}-{index:03d}','EVAL',SAMPLE,80,*KEYS);server=time_us(value)
                        assert len(value[2])==80
                        rows=[];misses=[]
                        for key,row in zip(KEYS,value[2]):
                            assert row[0]==key.encode() and len(row)==3
                            payload,pttl=row[1:]
                            if payload is None:
                                assert pttl==-2 and key not in filled;misses.append(key)
                            else:assert payload==('fresh:' if key in filled else 'cached:').encode()+key.encode() and pttl>=0
                            rows.append({'key':key,'value':payload.decode() if payload is not None else None,'pttl':pttl})
                        record={'index':index,'phase':phase,'server_time_us':server,'server_elapsed_ms':(server-seed_us)/1000,
                                'client_elapsed_seconds':time.monotonic()-seed_tick,'miss_count':len(misses),'rows':rows}
                        samples.append(record);return record,misses
                    while len(filled)<80:
                        assert time.monotonic()-seed_tick<15,'monotonic observation budget exceeded'
                        sample_tick=time.monotonic();record,misses=sample(len(samples))
                        if misses:
                            def fetch(key):
                                request_label=f'{label}-origin-{key.rsplit(":",1)[1]}'
                                response=http(request_label,endpoint+'/value?'+urlencode({'run':label,'key':key}))
                                assert response['run']==label and response['key']==key and response['payload']=='fresh:'+key and response['ticket']>0
                                return key,request_label,response
                            with ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(fetch,misses))
                            for key,request_label,response in responses:
                                assert key not in filled
                                assert r.call(label+'-fill-'+key.rsplit(':',1)[1],'SET',key,response['payload'],'PX',30000)==b'OK'
                                filled.add(key);events.append({'key':key,'sample_index':record['index'],'server_time_us':record['server_time_us'],
                                    'client_elapsed_seconds':record['client_elapsed_seconds'],'http_label':request_label,'ticket':response['ticket'],'payload':response['payload']})
                        if len(filled)<80:time.sleep(max(0,.2-(time.monotonic()-sample_tick)))
                    final,misses=sample(len(samples),'final');assert not misses and all(row['pttl']>0 and row['value']=='fresh:'+row['key'] for row in final['rows'])
                    snapshot=http(label+'-snapshot',endpoint+'/snapshot');assert snapshot['config']==config and snapshot['active']==snapshot['failed']==0
                    assert snapshot['completed']==len(snapshot['fetches'])==80 and snapshot['go_version']=='go1.25.4' and snapshot['goos']=='linux'
                    by_ticket={f['ticket']:f for f in snapshot['fetches']};assert len(by_ticket)==80 and {f['key'] for f in by_ticket.values()}==set(KEYS)
                    for event in events:
                        f=by_ticket[event['ticket']];assert f['key']==event['key'] and f['payload']==event['payload'] and f['completed'] and f['ended_ns']>f['started_ns']
                    max_miss=max(s['miss_count'] for s in samples);nonempty=sum(s['miss_count']>0 for s in samples)
                    assert len(events)==len(filled)==sum(s['miss_count'] for s in samples)==80
                    if c['offset_mode']!='one-per-key':assert max_miss==80 and nonempty==1
                    detail.update(source_fetches=80,max_misses_per_sample=max_miss,nonempty_miss_samples=nonempty,sample_count=len(samples),
                                  business_GETs_in_Lua=80*len(samples),origin_processing_peak=snapshot['peak'],
                                  first_miss_client_seconds=next(s['client_elapsed_seconds'] for s in samples if s['miss_count']),
                                  last_miss_client_seconds=[s['client_elapsed_seconds'] for s in samples if s['miss_count']][-1],
                                  server_TIME_backwards=sum(samples[i]['server_time_us']<samples[i-1]['server_time_us'] for i in range(1,len(samples))),
                                  final_pttl_min=min(row['pttl'] for row in final['rows']),final_pttl_max=max(row['pttl'] for row in final['rows']),
                                  per_key_reduction_observed=max_miss<80 if c['offset_mode']=='one-per-key' else None)
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    write(e.dest/(label+'-samples.json'),samples);write(e.dest/(label+'-events.json'),events)
                    if r:r.close()
                e.data['trials'].append({'case':c['case'],'trial':trial,'passed':not error,'verification_error':error,**detail})
                print(f'{label}: {"FAIL" if error else "PASS"} maxMISS={detail.get("max_misses_per_sample")} source={detail.get("source_fetches")} samples={detail.get("sample_count")} {error}',flush=True)
                if error:raise RuntimeError(label+': '+error+'; stop remaining trials')
        jitter=[t for t in e.data['trials'] if t['case']=='per-key-jitter'];assert sum(t['per_key_reduction_observed'] for t in jitter)>=8,'jitter reduction below eight of ten repeats'
        e.require('server-logs',compose+['logs','--no-color'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if started:e.run('failure-server-logs',compose+['logs','--no-color'])
    if len(e.data['trials'])!=30:failure=failure or 'incomplete three-by-ten matrix'
    fields=['case','trial','passed','source_fetches','max_misses_per_sample','nonempty_miss_samples','sample_count','business_GETs_in_Lua','origin_processing_peak','first_miss_client_seconds','last_miss_client_seconds','server_TIME_backwards']
    with (e.dest/'summary.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1
if __name__=='__main__':raise SystemExit(main())
