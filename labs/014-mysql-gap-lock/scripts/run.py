import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path

LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha
from mysql_session import MySQLSession

IMAGE='mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d'
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))
WAITS=(LAB/'sql/waits.sql').read_text(encoding='utf-8')
LOCKS=(LAB/'sql/locks.sql').read_text(encoding='utf-8')
EXPECTED=[(10,0),(15,1),(20,0),(30,0)]

def main():
    e=Evidence(LAB,'docker',[LAB/'docker-compose.yml',LAB/'src/cases.json',LAB/'sql/init.sql',LAB/'sql/waits.sql',LAB/'sql/locks.sql',Path(__file__)],
               {'version':'8.4.11','repeats_per_case':10,'cases':[c['case'] for c in CASES],
                'initial_keys':[10,20,30],'insert_key':15,'wait_edge_observation_budget_seconds':1.25,
                'release_case_hold_after_observed_edge_seconds':.2,'order':'forward odd, reversed even',
                'mysql_client_force_option':False,'expected_sql_fault':'ERROR1205/CLIexit1 in timeout cases, new-transaction retry after holder release'})
    e.data['shared_source_sha256']['shared/scripts/mysql_session.py']=sha(ROOT/'shared/scripts/mysql_session.py')
    compose=['docker','compose','-p','engineering-lab-014','-f',str(LAB/'docker-compose.yml')]
    container=None;failure=None
    def cli():
        return ['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered','engine_lab_014']
    def sql(label,query,database=True):
        rec,out,err=e.run(label,cli() if database else cli()[:-1],stdin=query.encode(),timeout=60)
        (e.dest/label/'input.sql').write_bytes(query.encode());assert rec['exit_code']==0 and not err
        return out
    try:
        e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
        e.require('image-inspect',['docker','image','inspect',IMAGE])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
        container=e.require('container-id',compose+['ps','-q','mysql']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',container)
        e.require('container-inspect',['docker','inspect',container])
        meta=sql('server-metadata','SELECT VERSION(),@@innodb_buffer_pool_size,@@performance_schema,@@innodb_rollback_on_timeout,@@innodb_deadlock_detect;\n',False)
        assert meta.strip()==b'8.4.11\t134217728\t1\t0\t1'
        assert sql('initialize',(LAB/'sql/init.sql').read_text(encoding='utf-8'),False).strip()==b'3\t0\t10,20,30'
        sql('structure','SHOW CREATE TABLE items; SHOW INDEX FROM items;')
        for c in CASES:sql('plan-'+c['case'],'EXPLAIN FORMAT=JSON '+c['query'])
        for trial in range(1,11):
            for c in CASES if trial%2 else list(reversed(CASES)):
                label=f'{c["case"]}-{trial:02d}';sessions=[];details={};error='';expected_bad_writer=None
                try:
                    holder,writer,observer=[MySQLSession(e,label+'-'+role,cli()) for role in ['holder','writer','observer']]
                    sessions=[holder,writer,observer]
                    ids=[int(s.execute(label+'-'+role+'-id','SELECT CONNECTION_ID();').strip()) for s,role in zip(sessions,['holder','writer','observer'])]
                    assert len(set(ids))==3;details['connection_ids']=ids
                    reset='DELETE FROM items; INSERT INTO items VALUES(10,0),(20,0),(30,0); SELECT COUNT(*),SUM(value),GROUP_CONCAT(id ORDER BY id) FROM items;'
                    assert observer.execute(label+'-reset',reset).strip()==b'3\t0\t10,20,30'
                    settings=writer.execute(label+'-writer-settings',f'SET SESSION innodb_lock_wait_timeout={c["lock_timeout_seconds"]}; SELECT @@innodb_lock_wait_timeout,@@autocommit;')
                    assert settings.strip()==f'{c["lock_timeout_seconds"]}\t1'.encode()
                    begin=holder.execute(label+'-holder-begin',f'SET SESSION TRANSACTION ISOLATION LEVEL {c["isolation"]}; START TRANSACTION; SELECT CONNECTION_ID(),@@transaction_isolation;')
                    assert begin.strip()==f'{ids[0]}\t{c["isolation"].replace(" ","-")}'.encode()
                    rows=[int(s) for s in holder.execute(label+'-holder-query',c['query']).decode().splitlines()]
                    assert rows==c['holder_rows'];details['holder_rows']=rows
                    def locks(stage):
                        out=observer.execute(label+'-'+stage,LOCKS.format(holder_id=ids[0]))
                        values=[s.split('\t') for s in out.decode().splitlines()]
                        assert all(len(v)==6 and int(v[0])==ids[0] for v in values)
                        return values
                    before=locks('holder-locks-before');details['holder_locks']=before
                    records=[v for v in before if v[2]=='RECORD']
                    if c['wait']:assert any(v[1:] == ['PRIMARY','RECORD',c['blocking_mode'],'GRANTED','20'] for v in records)
                    elif c['case']=='rr-unique-existing':assert records==[[str(ids[0]),'PRIMARY','RECORD','X,REC_NOT_GAP','GRANTED','10']]
                    else:assert not records
                    wait_sql=WAITS.format(writer_id=ids[1],holder_id=ids[0]);poll=0
                    def edge(stage):
                        nonlocal poll
                        poll+=1
                        out=observer.execute(f'{label}-{stage}-{poll:02d}',wait_sql)
                        values=[s.split('\t') for s in out.decode().splitlines()]
                        for v in values:
                            assert len(v)==12 and [int(v[0]),int(v[1])]==ids[:2][::-1]
                            assert v[2:7]==['PRIMARY','RECORD','X,GAP,INSERT_INTENTION','WAITING','20']
                            assert v[7:]==['PRIMARY','RECORD',c['blocking_mode'],'GRANTED','20']
                        return values
                    writer.send(label+'-writer-insert','START TRANSACTION; INSERT INTO items VALUES(15,1); SELECT ROW_COUNT();')
                    if c['wait']:
                        start=time.monotonic();edges=[]
                        while not edges:
                            edges=edge('wait-poll')
                            if time.monotonic()-start>1.25:raise AssertionError('no required wait edge within observation budget')
                            if not edges:time.sleep(.02)
                        details['wait_edges']=edges
                        observer.execute(label+'-status-waiting','SHOW ENGINE INNODB STATUS;')
                        if c['action']=='release':
                            time.sleep(.2);assert edge('wait-before-release')
                            holder.execute(label+'-holder-release','COMMIT;')
                            assert writer.finish(timeout=10).strip()==b'1'
                            writer.execute(label+'-writer-commit','COMMIT;')
                            details['writer_error_number']=0;details['retry_success']=False
                        else:
                            caught=''
                            try:writer.finish(timeout=10)
                            except RuntimeError as exc:caught=str(exc)
                            assert 'stdout EOF before marker' in caught
                            code=writer.close();stderr=(writer.directory/'stderr.txt').read_bytes()
                            assert code==1 and b'ERROR 1205 (HY000)' in stderr and stderr.count(b'ERROR ')==1
                            assert not writer.record['forced_host_client_kill'] and sum(not x['completed'] for x in writer.record['commands'])==1
                            expected_bad_writer=writer
                            details['writer_error_number']=1205;details['expected_marker_failure']=caught
                            assert observer.execute(label+'-after-timeout','SELECT COUNT(*) FROM items WHERE id=15;').strip()==b'0'
                            holder.execute(label+'-holder-release','COMMIT;')
                            retry=MySQLSession(e,label+'-retry',cli());sessions.append(retry)
                            retry_id=int(retry.execute(label+'-retry-id','SELECT CONNECTION_ID();').strip());assert retry_id not in ids
                            assert retry.execute(label+'-retry-insert','START TRANSACTION; INSERT INTO items VALUES(15,1); SELECT ROW_COUNT(); COMMIT;').strip()==b'1'
                            details.update(retry_success=True,retry_connection_id=retry_id)
                    else:
                        assert writer.finish(timeout=10).strip()==b'1'
                        details['wait_edges']=edge('wait-after-complete');assert not details['wait_edges']
                        writer.execute(label+'-writer-commit','COMMIT;')
                        holder.execute(label+'-holder-release','COMMIT;')
                        details.update(writer_error_number=0,retry_success=False)
                    details['insert_client_seconds']=next(x['elapsed_seconds'] for x in writer.record['commands'] if x['label']==label+'-writer-insert')
                    assert holder.execute(label+'-holder-post','SELECT CONNECTION_ID();').strip()==str(ids[0]).encode()
                    final=observer.execute(label+'-final','SELECT id,value FROM items ORDER BY id;')
                    tuples=[tuple(map(int,s.split('\t'))) for s in final.decode().splitlines()];assert tuples==EXPECTED
                    details['final_tuple_sha256']=hashlib.sha256(json.dumps(tuples,separators=(',',':')).encode()).hexdigest()
                    details['final_rows']=tuples;details['remaining_wait_edges']=edge('wait-final');assert not details['remaining_wait_edges']
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    for s in sessions:
                        code=s.close()
                        if s is expected_bad_writer:
                            valid=code==1 and not s.record['all_sql_markers_completed'] and not s.record['forced_host_client_kill']
                        else:valid=code==0 and s.record['stderr_bytes']==0 and s.record['all_sql_markers_completed'] and not s.record['forced_host_client_kill']
                        if not valid:error=error or f'{s.name}: unexpected exit/stderr/marker/kill state'
                    details['writer_process_exit']=writer.record.get('exit_code') if sessions else None
                e.data['trials'].append({'case':c['case'],'trial':trial,'passed':not error,'verification_error':error,**details})
                print(f'{label}: {"FAIL" if error else "PASS"} rows={details.get("holder_rows")} edges={len(details.get("wait_edges",[]))} error={details.get("writer_error_number")} insert={details.get("insert_client_seconds")} {error}',flush=True)
                if error:raise RuntimeError(f'{label}: {error}; stopping following trials')
        e.require('server-logs',compose+['logs','--no-color','mysql'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if container:e.run('failure-server-logs',compose+['logs','--no-color','mysql'])
    if len(e.data['trials'])!=60:failure=failure or 'incomplete six-by-ten matrix'
    fields=['case','trial','passed','writer_error_number','writer_process_exit','insert_client_seconds','retry_success','final_tuple_sha256']
    with (e.dest/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1

if __name__=='__main__':raise SystemExit(main())
