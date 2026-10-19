import base64
import csv
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha
from redis_session import RedisSession
GO=os.environ.get('LAB_GO','go')
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))
REDIS='redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'

def decode(wire):
    f=io.BytesIO(wire)
    def value():
        prefix=f.read(1);line=f.readline();assert line.endswith(b'\r\n');line=line[:-2]
        if prefix==b'+':return line
        if prefix==b'$':
            size=int(line)
            if size==-1:return None
            assert size>=0;b=f.read(size);assert len(b)==size and f.read(2)==b'\r\n';return b
        if prefix==b'*':
            size=int(line);assert size>=0;return [value() for _ in range(size)]
        raise AssertionError('unsupported/error frame')
    v=value();assert f.read()==b'';return v

def main():
    sources=[LAB/'docker-compose.yml',LAB/'Dockerfile',LAB/'go.mod',LAB/'src/main.go',LAB/'src/cases.json',LAB/'scripts/http_capture.py',Path(__file__)]
    e=Evidence(LAB,'docker-native',sources,{'repeats_per_case':10,'total_workers':32,'native_actor':'Go1.25.4; native OS reported per actor',
        'origin':'real Go HTTP server with controlled constant42; not a database','origin_delay_ms':20,
        'barrier':'all32 initial GET nil then32 /ready before work; cross-process origin gate2 before fill',
        'gates':{c['case']:c['origin_gate'] for c in CASES},'seed_expiry':'SET PX1 then actual PTTL=-2 and GET nil',
        'fill_ttl_ms':60000,'performance_claim':False,'order':'forward odd, reverse even'})
    e.data['shared_source_sha256']['shared/scripts/redis_session.py']=sha(ROOT/'shared/scripts/redis_session.py')
    compose=['docker','compose','-p','engineering-lab-017','-f',str(LAB/'docker-compose.yml')]
    exe=ROOT/'.work/017'/('actor.exe' if os.name=='nt' else 'actor');exe.parent.mkdir(parents=True,exist_ok=True)
    failure=None;started=False
    def http(label,url,body=None):
        args=[sys.executable,str(LAB/'scripts/http_capture.py'),url]
        if body is not None:args+=['--method','POST']
        data=json.dumps(body).encode() if body is not None else None
        rec,out,err=e.run(label,args,stdin=data)
        if data is not None:(e.dest/label/'input.json').write_bytes(data)
        assert rec['exit_code']==0 and not err
        return json.loads(out)
    try:
        version=e.require('native-go-version',[GO,'version']).decode();assert 'go1.25.4' in version
        e.require('native-env',[GO,'env','GOOS','GOARCH','CGO_ENABLED','GOTOOLCHAIN'])
        e.require('native-vet',[GO,'vet','./src'],cwd=LAB)
        e.require('native-build',[GO,'build','-trimpath','-o',str(exe),'./src'],cwd=LAB,timeout=120)
        e.data['parameters']['native_binary_sha256']=sha(exe)
        e.require('docker-version',['docker','version']);e.require('redis-image',['docker','image','inspect',REDIS])
        e.require('origin-build',compose+['build'],timeout=210)
        e.require('origin-image',['docker','image','inspect','engineering-lab-017-origin:local'])
        e.require('fixture-recreate',compose+['down','--volumes','--remove-orphans'])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','60'],timeout=90);started=True
        ids={name:e.require(name+'-id',compose+['ps','-q',name]).decode().strip() for name in ['redis','origin']}
        assert all(re.fullmatch('[a-f0-9]{64}',i) for i in ids.values())
        e.require('container-inspect',['docker','inspect',*ids.values()])
        ports={}
        for name,inner in [('redis','6379'),('origin','8080')]:
            value=e.require(name+'-port',compose+['port',name,inner]).decode().strip()
            assert re.fullmatch(r'127\.0\.0\.1:\d+',value) and not value.endswith(':0');ports[name]=value
        endpoint='http://'+ports['origin']
        info=e.require('redis-info',['docker','exec',ids['redis'],'redis-cli','INFO','server']).decode()
        assert 'redis_version:7.4.11' in info;e.data['parameters']['actual_redis_version']='7.4.11'
        e.require('origin-go-env',['docker','exec',ids['origin'],'go','env','GOOS','GOARCH','CGO_ENABLED','GOTOOLCHAIN'])
        e.require('linux-vet',['docker','run','--rm','--network','none','--cpus','2','--memory','512m','-e','CGO_ENABLED=0','-e','GOTOOLCHAIN=local','-e','GOMAXPROCS=2','-v',str(LAB)+':/lab:ro','-w','/lab','golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb','go','vet','./src'],timeout=120)
        for trial in range(1,11):
            for c in CASES if trial%2 else list(reversed(CASES)):
                label=f'{c["case"]}-{trial:02d}';error='';detail={};r=None
                try:
                    r=RedisSession(e,label,'127.0.0.1',int(ports['redis'].split(':')[1]))
                    e.data.setdefault('redis_sessions',[]).append(r.record)
                    assert r.call(label+'-flush','FLUSHDB')==b'OK'
                    assert r.call(label+'-seed','SET','lab017:hot','seed','PX','1')==b'OK'
                    tick=time.monotonic();samples=[]
                    while True:
                        ttl=r.call(f'{label}-expire-{len(samples):03d}','PTTL','lab017:hot');samples.append(ttl)
                        if ttl==-2:break
                        assert ttl>=0 and time.monotonic()-tick<3;time.sleep(.01)
                    assert r.call(label+'-expired-get','GET','lab017:hot') is None;detail['seed_pttl_samples']=samples
                    config={'run':label,'total':32,'gate':c['origin_gate'],'delay_ms':20}
                    assert http(label+'-configure',endpoint+'/configure',config)==config
                    def launch(index):
                        app='app'+str(index)
                        args=[str(exe),'-role','actor','-redis',ports['redis'],'-origin',endpoint,'-run',label,'-app',app,'-mode',c['mode'],'-workers',str(c['workers_per_process'])]
                        rec,out,err=e.run(label+'-'+app,args,timeout=60)
                        assert rec['exit_code']==0 and not err,(rec['exit_code'],err)
                        result=json.loads(out);assert result['run']==label and result['app']==app and result['mode']==c['mode']
                        assert result['go_version']=='go1.25.4' and result['goos']==('windows' if os.name=='nt' else 'linux')
                        assert len(result['operations'])==result['workers']==c['workers_per_process']
                        return result
                    with ThreadPoolExecutor(max_workers=c['processes']) as pool:
                        futures=[pool.submit(launch,i) for i in range(c['processes'])]
                        actors=[f.result() for f in futures]
                    assert len(set(a['pid'] for a in actors))==c['processes']
                    snapshot=http(label+'-snapshot',endpoint+'/snapshot')
                    assert snapshot['config']==config and snapshot['active']==snapshot['failed']==0
                    assert snapshot['go_version']=='go1.25.4' and snapshot['goos']=='linux'
                    fetches=snapshot['fetches'];ready=snapshot['ready']
                    assert len(fetches)==snapshot['completed']==c['expected_fetches'] and len(ready)==32
                    assert len({(x['app'],x['worker']) for x in ready})==32
                    by_ticket={f['ticket']:f for f in fetches};assert len(by_ticket)==len(fetches)
                    actual_source=0;recheck_hits=0;resp_commands=0
                    for actor in actors:
                        for op in actor['operations']:
                            assert op['error']=='' and op['initial_nil'] and op['ready'] and op['value']=='42'
                            assert {'app':actor['app'],'worker':op['worker']} in ready
                            for rec in op['resp']:
                                request=base64.b64decode(rec['request']);response=base64.b64decode(rec['response'])
                                assert decode(request)==[arg.encode() for arg in rec['args']]
                                value=decode(response);resp_commands+=1
                                if rec['phase']=='initial':assert value is None
                                elif rec['phase']=='recheck':assert value==(b'42' if op['recheck_hit'] else None)
                                else:assert rec['phase']=='fill' and value==b'OK' and rec['args']==['SET','lab017:hot','42','PX','60000']
                            assert [x['phase'] for x in op['resp']]==(['initial']+(['recheck'] if c['mode']=='recheck' else [])+(['fill'] if op['source_call'] else []))
                            if op['source_call']:
                                actual_source+=1;f=by_ticket[op['ticket']]
                                assert f['app']==actor['app'] and f['worker']==op['worker'] and f['completed'] and f['ended_ns']>f['started_ns']
                            else:assert op['ticket']==0 and op['recheck_hit']
                            recheck_hits+=int(op['recheck_hit'])
                    assert actual_source==len(fetches) and recheck_hits==32-actual_source
                    if c['processes']==2:assert all(sum(op['source_call'] for op in a['operations'])==1 for a in actors)
                    assert r.call(label+'-final-get','GET','lab017:hot')==b'42'
                    ttl=r.call(label+'-final-ttl','PTTL','lab017:hot');assert ttl>0
                    detail.update(actor_pids=[a['pid'] for a in actors],source_fetches=actual_source,recheck_hits=recheck_hits,
                                  completed_workers=32,source_peak=snapshot['peak'],source_active_final=snapshot['active'],
                                  actor_RESP_commands=resp_commands,final_value='42',final_pttl=ttl)
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    if r:r.close()
                e.data['trials'].append({'case':c['case'],'trial':trial,'passed':not error,'verification_error':error,**detail})
                print(f'{label}: {"FAIL" if error else "PASS"} fetches={detail.get("source_fetches")} recheckHits={detail.get("recheck_hits")} PIDs={detail.get("actor_pids")} {error}',flush=True)
                if error:raise RuntimeError(label+': '+error+'; stop remaining trials')
        e.require('server-logs',compose+['logs','--no-color'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if started:e.run('failure-server-logs',compose+['logs','--no-color'])
    if len(e.data['trials'])!=40:failure=failure or 'incomplete four-by-ten matrix'
    fields=['case','trial','passed','completed_workers','source_fetches','recheck_hits','source_peak','final_pttl']
    with (e.dest/'summary.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1

if __name__=='__main__':raise SystemExit(main())
