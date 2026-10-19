import csv
import json
import re
import sys
import time
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'));sys.path.insert(0,str(LAB/'src'))
from evidence import Evidence,sha
from mysql_session import MySQLSession
from redis_session import RedisSession
from cache import CacheAside
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))
REDIS='redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'
MYSQL='mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d'

def main():
    e=Evidence(LAB,'docker',[LAB/'docker-compose.yml',LAB/'src/cases.json',LAB/'src/cache.py',LAB/'sql/init.sql',LAB/'sql/reset.sql',Path(__file__)],
        {'repeats_per_case':10,'order':'forward odd, reverse even','concurrency':1,'burst_requests':80,'missing_requests':60,'positive_controls':20,
         'positive_ids':{'1':'existing','2':''},'negative_ttl_ms':{'burst':10000,'create':1200},'positive_ttl_ms':60000,
         'origin':'actual MySQL SELECT HEX(payload), raw statements counted','redis':'actual RESP2 exact wire with command offsets',
         'create':'autocommit confirmed then TTL expiration or DEL; no atomicity claim','latency_benchmark':False})
    for name in ['mysql_session.py','redis_session.py']:e.data['shared_source_sha256']['shared/scripts/'+name]=sha(ROOT/'shared/scripts'/name)
    compose=['docker','compose','-p','engineering-lab-016','-f',str(LAB/'docker-compose.yml')]
    mysql=None;failure=None
    def cli(database=True):
        args=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',mysql,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered']
        return args+(['engine_lab_016'] if database else [])
    try:
        e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
        for name,img in [('redis',REDIS),('mysql',MYSQL)]:e.require(name+'-image',['docker','image','inspect',img])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
        ids={name:e.require(name+'-id',compose+['ps','-q',name]).decode().strip() for name in ['mysql','redis']}
        assert all(re.fullmatch('[a-f0-9]{64}',i) for i in ids.values());mysql=ids['mysql']
        e.require('container-inspect',['docker','inspect',*ids.values()])
        port=e.require('redis-port',compose+['port','redis','6379']).decode().strip()
        match=re.fullmatch(r'127\.0\.0\.1:(\d+)',port);assert match,port;port=int(match.group(1))
        info=e.require('redis-version',['docker','exec',ids['redis'],'redis-cli','INFO','server']).decode()
        version=re.search(r'redis_version:([^\r\n]+)',info).group(1);assert version.startswith('7.4.')
        e.data['parameters']['actual_redis_version']=version
        rec,out,err=e.run('initialize',cli(False),stdin=(LAB/'sql/init.sql').read_bytes())
        (e.dest/'initialize/input.sql').write_bytes((LAB/'sql/init.sql').read_bytes())
        assert rec['exit_code']==0 and not err and out==b'1\t6578697374696E67\n2\t\n',out
        rec,out,err=e.run('mysql-version',cli(),stdin=b'SELECT VERSION(),@@autocommit;')
        (e.dest/'mysql-version/input.sql').write_bytes(b'SELECT VERSION(),@@autocommit;')
        assert rec['exit_code']==0 and not err and out.strip()==b'8.4.11\t1'
        for trial in range(1,11):
            for c in CASES if trial%2 else list(reversed(CASES)):
                label=f'{c["case"]}-{trial:02d}';sessions=[];r=None;events=[];detail={};error=''
                try:
                    origin=MySQLSession(e,label+'-origin',cli());sessions.append(origin)
                    observer=MySQLSession(e,label+'-observer',cli());sessions.append(observer)
                    r=RedisSession(e,label,'127.0.0.1',port);e.data.setdefault('redis_sessions',[]).append(r.record)
                    assert r.call(label+'-ping','PING')==b'PONG'
                    assert r.call(label+'-reset','FLUSHDB')==b'OK'
                    assert observer.execute(label+'-reset',(LAB/'sql/reset.sql').read_text(encoding='utf-8'))==b'1\t6578697374696E67\n2\t\n'
                    origin_id=int(origin.execute(label+'-origin-id','SELECT CONNECTION_ID();').strip())
                    observer_id=int(observer.execute(label+'-observer-id','SELECT CONNECTION_ID(),@@autocommit;').split(b'\t')[0]);assert origin_id!=observer_id
                    detail.update(origin_connection_id=origin_id,observer_connection_id=observer_id)
                    app=CacheAside(r,origin,c['negative_cache'],c['negative_ttl_ms'])
                    def lookup(item_id,phase):
                        event=app.lookup(f'{label}-request-{len(events):03d}',item_id)
                        event.update(request=len(events),phase=phase);events.append(event);return event
                    if c['workload']!='create':
                        missing=0
                        for group in range(20):
                            for _ in range(3):
                                item_id=9000+missing if c['workload']=='unique' else 9000
                                assert lookup(item_id,'burst')['value'] is None;missing+=1
                            item_id=1 if group%2==0 else 2
                            assert lookup(item_id,'burst')['value']==('existing' if item_id==1 else '')
                        assert len(events)==80
                        ttl=r.call(label+'-negative-ttl','PTTL','lab016:item:9000')
                        assert (0<ttl<=10000) if c['negative_cache'] else ttl==-2
                        detail['negative_pttl_after_burst']=ttl
                        expected_entries=(62 if c['workload']=='unique' else 3) if c['negative_cache'] else 2
                        detail['stale_results']=0
                    else:
                        assert lookup(9000,'before-create')['value'] is None
                        ttl=r.call(label+'-negative-ttl-before','PTTL','lab016:item:9000');assert 0<ttl<=1200
                        detail['negative_pttl_before_create']=ttl
                        created=observer.execute(label+'-create',"INSERT INTO items VALUES(9000,'created'); SELECT ROW_COUNT(); SELECT id,HEX(payload) FROM items WHERE id=9000;")
                        assert created==b'1\n9000\t63726561746564\n'
                        ttl=r.call(label+'-negative-ttl-after-create','PTTL','lab016:item:9000');assert 0<ttl<=1200
                        detail['negative_pttl_after_create']=ttl
                        if c['invalidate']:
                            deleted=r.call(label+'-invalidate','DEL','lab016:item:9000');assert deleted==1;detail['del_result']=deleted
                        post=[lookup(9000,'after-create')['value'] for _ in range(10)]
                        if c['invalidate']:
                            assert post==['created']*10;detail['stale_results']=0
                        else:
                            assert post==[None]*10;detail['stale_results']=10
                            ttl=r.call(label+'-negative-ttl-after-stale','PTTL','lab016:item:9000');assert 0<ttl<=1200
                            detail['negative_pttl_after_stale']=ttl
                            tick=time.monotonic();samples=[]
                            while True:
                                ttl=r.call(f'{label}-ttl-wait-{len(samples):03d}','PTTL','lab016:item:9000')
                                samples.append({'pttl':ttl,'elapsed_seconds':time.monotonic()-tick})
                                if ttl==-2:break
                                assert 0<=ttl<=1200 and time.monotonic()-tick<5
                                time.sleep(.02)
                            detail['expiry_samples']=samples
                            assert r.call(label+'-expired-get','GET','lab016:item:9000') is None
                            assert lookup(9000,'after-expiry')['value']=='created'
                        expected_entries=1
                    calls=[q for q in origin.record['commands'] if re.search(r'-request-\d+-origin$',q['label'])]
                    assert len(calls)==app.origin_calls==c['expected_origin_queries']
                    assert all(q['completed'] for q in calls)
                    detail['origin_queries']=len(calls)
                    states={name:sum(x['state']==name for x in events) for name in ['MISS','NEGATIVE_HIT','VALUE_HIT']}
                    detail.update(request_count=len(events),**{name.lower():count for name,count in states.items()})
                    assert states['MISS']==len(calls)
                    keys=r.call(label+'-keys','KEYS','lab016:item:*');keys=sorted(k.decode() for k in keys)
                    assert len(keys)==expected_entries
                    snapshot=[]
                    for i,key in enumerate(keys):
                        val=r.call(f'{label}-snapshot-{i:03d}','GET',key)
                        ttl=r.call(f'{label}-snapshot-ttl-{i:03d}','PTTL',key);assert ttl>0
                        snapshot.append({'key':key,'value':json.loads(val),'pttl':ttl})
                    (e.dest/(label+'-cache-snapshot.json')).write_text(json.dumps(snapshot,indent=2)+'\n',encoding='utf-8',newline='\n')
                    detail['cache_entries']=len(keys)
                    truth=observer.execute(label+'-truth','SELECT id,HEX(payload) FROM items ORDER BY id;')
                    expected=b'1\t6578697374696E67\n2\t\n'+(b'9000\t63726561746564\n' if c['workload']=='create' else b'')
                    assert truth==expected
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    if r:r.close()
                    for s in sessions:
                        code=s.close()
                        if code!=0 or (s.directory/'stderr.txt').read_bytes() or not s.record['all_sql_markers_completed'] or s.record['forced_host_client_kill']:
                            error=error or s.name+': SQL/session did not complete cleanly'
                    (e.dest/(label+'-requests.jsonl')).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in events),encoding='utf-8',newline='\n')
                    detail['mysql_exit_codes']=[s.record['exit_code'] for s in sessions]
                e.data['trials'].append({'case':c['case'],'trial':trial,'passed':not error,'verification_error':error,**detail})
                print(f'{label}: {"FAIL" if error else "PASS"} sourceSQL={detail.get("origin_queries")} stale={detail.get("stale_results")} cacheKeys={detail.get("cache_entries")} {error}',flush=True)
                if error:raise RuntimeError(label+': '+error+'; stop remaining trials')
        e.require('server-logs',compose+['logs','--no-color'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if mysql:e.run('failure-server-logs',compose+['logs','--no-color'])
    if len(e.data['trials'])!=50:failure=failure or 'incomplete five-by-ten matrix'
    fields=['case','trial','passed','request_count','origin_queries','negative_hit','value_hit','stale_results','cache_entries']
    with (e.dest/'summary.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1

if __name__=='__main__':raise SystemExit(main())
