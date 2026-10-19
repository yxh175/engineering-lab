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
COUNTER="SELECT `COUNT` FROM information_schema.innodb_metrics WHERE NAME='lock_deadlocks' AND STATUS='enabled';"

def tuple_hash(rows):return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()

def main():
    e=Evidence(LAB,'docker',[LAB/'docker-compose.yml',LAB/'src/cases.json',LAB/'sql/init.sql',LAB/'sql/reset.sql',LAB/'sql/waits.sql',LAB/'sql/locks.sql',Path(__file__)],
               {'expected_version':'8.4.11','repeats_per_case':10,'cases':[c['case'] for c in CASES],
                'initial_rows':[[1,0],[2,0]],'business_contract':'two increments per actor in one transaction; two completed actors produce2/2',
                'actor_mysql_force':True,'deadlock_counter':'INFORMATION_SCHEMA.INNODB_METRICS.lock_deadlocks (enabled)','observer_mysql_force':False,'sql_fault_check':'immediate SHOW WARNINGS plus full stderr after session closure',
                'wait_edge_budget_seconds':2,'server_lock_wait_timeout_seconds':8,'order':'forward odd, reversed even',
                'retry_timing':'after confirmed survivor COMMIT; same victim connection, fresh transaction'})
    e.data['shared_source_sha256']['shared/scripts/mysql_session.py']=sha(ROOT/'shared/scripts/mysql_session.py')
    compose=['docker','compose','-p','engineering-lab-015','-f',str(LAB/'docker-compose.yml')]
    container=None;failure=None
    def cli(force=False):
        argv=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered']
        return argv+(['--force'] if force else [])+['engine_lab_015']
    def sql(label,text,database=True):
        argv=cli() if database else cli()[:-1]
        rec,out,err=e.run(label,argv,stdin=text.encode(),timeout=60)
        (e.dest/label/'input.sql').write_bytes(text.encode());assert rec['exit_code']==0 and not err
        return out
    def second_query(row):
        return f"UPDATE accounts SET value=value+1 WHERE id={row}; SHOW WARNINGS; SELECT 'SECOND_DONE';"
    def second_result(out):
        lines=out.decode().splitlines();assert lines and lines[-1]=='SECOND_DONE'
        if len(lines)==1:return 0
        assert len(lines)==2,lines
        fields=lines[0].split('\t');assert len(fields)==3 and fields[0]=='Error' and fields[1]=='1213',fields
        return 1213
    try:
        e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
        e.require('image-inspect',['docker','image','inspect',IMAGE])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
        container=e.require('container-id',compose+['ps','-q','mysql']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',container)
        e.require('container-inspect',['docker','inspect',container])
        metadata=sql('metadata','SELECT VERSION(),@@innodb_buffer_pool_size,@@innodb_deadlock_detect,@@innodb_print_all_deadlocks,@@innodb_rollback_on_timeout,@@autocommit;',False)
        assert metadata.strip()==b'8.4.11\t134217728\t1\t1\t0\t1'
        assert sql('initialize',(LAB/'sql/init.sql').read_text(encoding='utf-8'),False).strip()==b'1\t0\n2\t0'
        sql('structure','SHOW CREATE TABLE accounts; SHOW INDEX FROM accounts; EXPLAIN FORMAT=JSON UPDATE accounts SET value=value+1 WHERE id=1;')
        for trial in range(1,11):
            for c in CASES if trial%2 else list(reversed(CASES)):
                label=f'{c["case"]}-{trial:02d}';sessions=[];details={};error='';victim_session=None
                try:
                    a=MySQLSession(e,label+'-a',cli(True));sessions.append(a)
                    b=MySQLSession(e,label+'-b',cli(True));sessions.append(b)
                    o=MySQLSession(e,label+'-observer',cli());sessions.append(o)
                    ids=[int(s.execute(label+'-'+role+'-id','SELECT CONNECTION_ID();').strip()) for s,role in zip(sessions,['a','b','observer'])]
                    assert len(set(ids))==3;details['connection_ids']=ids
                    assert o.execute(label+'-reset',(LAB/'sql/reset.sql').read_text(encoding='utf-8')).strip()==b'1\t0\n2\t0'
                    before=int(o.execute(label+'-counter-before',COUNTER).strip());details['deadlocks_before']=before
                    for s,role in [(a,'a'),(b,'b')]:
                        config=s.execute(label+'-'+role+'-settings','SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ; SET SESSION innodb_lock_wait_timeout=8; SELECT @@transaction_isolation,@@innodb_lock_wait_timeout,@@autocommit;')
                        assert config.strip()==b'REPEATABLE-READ\t8\t1'
                    first=lambda row:f'START TRANSACTION; UPDATE accounts SET value=value+1 WHERE id={row}; SELECT ROW_COUNT(),value FROM accounts WHERE id={row};'
                    assert a.execute(label+'-a-first',first(1)).strip()==b'1\t1'
                    poll=0
                    def wait(requester,blocker,row):
                        nonlocal poll
                        start=time.monotonic();values=[]
                        while not values:
                            poll+=1
                            out=o.execute(f'{label}-wait-{poll:02d}',WAITS.format(requester=requester,blocker=blocker))
                            values=[line.split('\t') for line in out.decode().splitlines()]
                            for v in values:
                                assert len(v)==14 and [int(v[0]),int(v[1])]==[requester,blocker]
                                assert v[2:7]==['PRIMARY','RECORD','X,REC_NOT_GAP','WAITING',str(row)]
                                assert v[7:12]==['PRIMARY','RECORD','X,REC_NOT_GAP','GRANTED',str(row)]
                            if time.monotonic()-start>2:raise AssertionError('required record wait edge not observed')
                            if not values:time.sleep(.02)
                        assert len(values)==1
                        return values
                    if c['order']=='opposite':
                        assert b.execute(label+'-b-first',first(2)).strip()==b'1\t1'
                        details['locks_before_cycle']=[line.split('\t') for line in o.execute(label+'-locks-before-cycle',LOCKS.format(actor_a=ids[0],actor_b=ids[1])).decode().splitlines()]
                        a.send(label+'-a-second',second_query(2))
                        details['observed_pre_cycle_edge']=wait(ids[0],ids[1],2)
                        b.send(label+'-b-second',second_query(1))
                        results=[second_result(s.finish(timeout=12)) for s in [a,b]]
                        assert sorted(results)==[0,1213],results
                        victim=results.index(1213);survivor=1-victim
                        victim_session=sessions[victim]
                        details.update(second_error_numbers=results,victim_role=['a','b'][victim],victim_connection_id=ids[victim],survivor_connection_id=ids[survivor])
                        # No COMMIT/ROLLBACK/close on either actor before the victim probe.
                        probe=victim_session.execute(label+'-victim-before-survivor-commit','SELECT CONNECTION_ID(),id,value FROM accounts ORDER BY id;')
                        victim_rows=[tuple(map(int,line.split('\t'))) for line in probe.decode().splitlines()]
                        assert victim_rows==[(ids[victim],1,0),(ids[victim],2,0)],victim_rows
                        details['victim_rows_before_survivor_commit']=victim_rows
                        status=o.execute(label+'-deadlock-status','SHOW ENGINE INNODB STATUS;').decode()
                        assert 'LATEST DETECTED DEADLOCK' in status
                        section=status.split('LATEST DETECTED DEADLOCK',1)[1].split('\nTRANSACTIONS\n',1)[0]
                        for actor_id in ids[:2]:assert re.search(r'MySQL thread id '+str(actor_id)+r'\b',section)
                        for row in [1,2]:assert f'UPDATE accounts SET value=value+1 WHERE id={row}' in section
                        match=re.search(r'\*\*\* \(1\) TRANSACTION:([\s\S]*?)\*\*\* \(2\) TRANSACTION:([\s\S]*?)\*\*\* WE ROLL BACK TRANSACTION \((\d)\)',section)
                        assert match,'unrecognized actual deadlock status layout'
                        log_ids=[int(re.search(r'MySQL thread id (\d+)',match.group(i)).group(1)) for i in [1,2]]
                        assert log_ids[int(match.group(3))-1]==ids[victim]
                        details['server_log_transaction_connection_ids']=log_ids;details['server_log_rollback_number']=int(match.group(3))
                        sessions[survivor].execute(label+'-survivor-commit','COMMIT;')
                        intermediate=o.execute(label+'-after-survivor','SELECT id,value FROM accounts ORDER BY id;')
                        assert intermediate.strip()==b'1\t1\n2\t1';details['after_survivor_rows']=[[1,1],[2,1]]
                        expected=[1,1]
                        if c['retry']!='none':
                            first_row=victim+1;second_row=2-victim
                            chosen=[first_row,second_row] if c['retry']=='whole_transaction' else [second_row]
                            query='START TRANSACTION;\n'+''.join(f'UPDATE accounts SET value=value+1 WHERE id={row}; SELECT ROW_COUNT();\n' for row in chosen)+'COMMIT; SELECT CONNECTION_ID();'
                            retry=victim_session.execute(label+'-victim-retry',query)
                            assert retry.decode().splitlines()==['1']*len(chosen)+[str(ids[victim])]
                            expected=[2,2] if c['retry']=='whole_transaction' else ([1,2] if victim==0 else [2,1])
                            details['retried_rows']=chosen
                    else:
                        b.send(label+'-b-first',first(1))
                        details['observed_pre_cycle_edge']=wait(ids[1],ids[0],1)
                        assert second_result(a.execute(label+'-a-second',second_query(2)))==0
                        a.execute(label+'-a-commit','COMMIT;')
                        assert b.finish(timeout=12).strip()==b'1\t2'
                        assert second_result(b.execute(label+'-b-second',second_query(2)))==0
                        b.execute(label+'-b-commit','COMMIT;')
                        details.update(second_error_numbers=[0,0],victim_role=None,after_survivor_rows=None)
                        expected=[2,2]
                    final=o.execute(label+'-final','SELECT id,value FROM accounts ORDER BY id;')
                    rows=[tuple(map(int,line.split('\t'))) for line in final.decode().splitlines()]
                    assert rows==[(1,expected[0]),(2,expected[1])],rows
                    after=int(o.execute(label+'-counter-after',COUNTER).strip())
                    assert after-before==(1 if c['order']=='opposite' else 0)
                    remaining=o.execute(label+'-waits-final',"SELECT COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.data_locks r ON r.ENGINE=w.ENGINE AND r.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID WHERE r.OBJECT_SCHEMA='engine_lab_015';")
                    assert remaining.strip()==b'0'
                    details.update(final_rows=rows,final_tuple_sha256=tuple_hash(rows),business_complete=rows==[(1,2),(2,2)],deadlocks_after=after,deadlocks_delta=after-before)
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    for s in sessions:
                        code=s.close();stderr=(s.directory/'stderr.txt').read_bytes()
                        if s is victim_session:
                            valid=code in [0,1] and b'ERROR 1213 (40001)' in stderr and stderr.count(b'ERROR ')==1
                        else:valid=code==0 and not stderr
                        valid=valid and s.record['all_sql_markers_completed'] and not s.record['forced_host_client_kill']
                        if not valid:error=error or f'{s.name}: unexpected exit, SQL error, incomplete marker or kill'
                    details['session_exit_codes']=[s.record['exit_code'] for s in sessions]
                e.data['trials'].append({'case':c['case'],'trial':trial,'passed':not error,'verification_error':error,**details})
                print(f'{label}: {"FAIL" if error else "PASS"} errors={details.get("second_error_numbers")} victim={details.get("victim_role")} rows={details.get("final_rows")} exits={details.get("session_exit_codes")} {error}',flush=True)
                if error:raise RuntimeError(f'{label}: {error}; stop following trials')
        e.require('server-logs',compose+['logs','--no-color','mysql'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if container:e.run('failure-server-logs',compose+['logs','--no-color','mysql'])
    if len(e.data['trials'])!=40:failure=failure or 'incomplete four-by-ten matrix'
    fields=['case','trial','passed','victim_role','deadlocks_delta','business_complete','final_tuple_sha256']
    with (e.dest/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1

if __name__=='__main__':raise SystemExit(main())
