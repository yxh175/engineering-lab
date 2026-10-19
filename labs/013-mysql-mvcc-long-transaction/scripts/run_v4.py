import csv
import json
import re
import sys
import time
from pathlib import Path

LAB=Path(__file__).resolve().parents[1]
ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha,utc
from mysql_session import MySQLSession

IMAGE='mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d'
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))
PROTOCOL=json.loads((LAB/'src/protocol-v4.json').read_text(encoding='utf-8'))
HISTORY="SELECT 'HISTORY',COUNT,STATUS FROM information_schema.innodb_metrics WHERE NAME='trx_rseg_history_len';\n"


def main():
    e=Evidence(LAB,'docker',[LAB/'docker-compose.yml',LAB/'src/cases.json',LAB/'sql/init.sql',LAB/'sql/control.sql',LAB/'src/protocol-v4.json',Path(__file__)],
               {**PROTOCOL,'mysql_expected_version':'8.4.11','cases':[c['case'] for c in CASES],'repeats_per_case':10,
                'order':'forward odd, reversed even','synchronization':'mysql response markers; writer follows reader setup completion'})
    e.data['shared_source_sha256']['shared/scripts/mysql_session.py']=sha(ROOT/'shared/scripts/mysql_session.py')
    compose=['docker','compose','-p','engineering-lab-013','-f',str(LAB/'docker-compose.yml')]
    container,failure=None,None
    all_samples=[]
    def cli():
        return ['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered','engine_lab_013']
    def sql(label,text,database=True):
        argv=cli() if database else cli()[:-1]
        rec,out,err=e.run(label,argv,stdin=text.encode(),timeout=60)
        (e.dest/label/'input.sql').write_bytes(text.encode())
        assert rec['exit_code']==0 and not err,f'{label}: mysql failed'
        return out
    try:
        e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
        e.require('image-inspect',['docker','image','inspect',IMAGE])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
        container=e.require('container-id',compose+['ps','-q','mysql']).decode().strip()
        assert re.fullmatch(r'[a-f0-9]{64}',container)
        e.require('container-inspect',['docker','inspect',container])
        meta=sql('server-metadata','SELECT VERSION(),@@innodb_buffer_pool_size,@@innodb_purge_threads,@@innodb_max_purge_lag,@@transaction_isolation,@@innodb_purge_batch_size,@@innodb_purge_rseg_truncate_frequency;\n',False)
        assert meta.decode().startswith('8.4.11\t134217728\t4\t')
        assert sql('configure-purge','SET GLOBAL innodb_purge_batch_size=20; SET GLOBAL innodb_purge_rseg_truncate_frequency=1; SELECT @@innodb_purge_threads,@@innodb_purge_batch_size,@@innodb_purge_rseg_truncate_frequency;\n',False).decode().strip()=='4\t20\t1'
        assert sql('initialize',(LAB/'sql/init.sql').read_text(encoding='utf-8'),False).decode().startswith('1\t0\t0\n')
        sql('initialize-control',(LAB/'sql/control.sql').read_text(encoding='utf-8'))
        for trial in range(1,11):
            for config in (CASES if trial%2 else list(reversed(CASES))):
                label=f'{config["case"]}-{trial:02d}'
                sessions=[];details={'samples':[],'control_pulses':[]};error=''
                try:
                    reader,writer,observer=[MySQLSession(e,label+'-'+role,cli()) for role in ['reader','writer','observer']]
                    sessions=[reader,writer,observer]
                    ids=[int(s.execute(label+'-'+role+'-id','SELECT CONNECTION_ID();').strip()) for s,role in zip(sessions,['reader','writer','observer'])]
                    assert len(set(ids))==3
                    details['connection_ids']=ids
                    for s,role in zip(sessions,['reader','writer','observer']):
                        assert s.execute(label+'-'+role+'-autocommit','SELECT @@autocommit;').strip()==b'1'
                    preparation='UPDATE account SET value=0 WHERE id=1;\n'+''.join('START TRANSACTION; UPDATE account SET value=value+1 WHERE id=1; COMMIT;\n' for _ in range(100))+'UPDATE account SET value=0 WHERE id=1; SELECT value FROM account WHERE id=1;'
                    assert writer.execute(label+'-preparation',preparation,timeout=30).strip()==b'0'
                    tick=time.monotonic();seq=0
                    def pulse(stage):
                        before=int(writer.execute(label+'-'+stage+'-before','SELECT value FROM purge_tick WHERE id=1;').strip())
                        query=''.join('START TRANSACTION; UPDATE purge_tick SET value=value+1 WHERE id=1; COMMIT;\n' for _ in range(100))+'SELECT value FROM purge_tick WHERE id=1;'
                        after=int(writer.execute(label+'-'+stage,query,timeout=30).strip())
                        assert after-before==100
                        details['control_pulses'].append({'stage':stage,'before':before,'after':after,'committed_increments':after-before,'elapsed_seconds':time.monotonic()-tick,'utc':utc()})
                    def sample(stage):
                        nonlocal seq
                        seq+=1
                        raw=observer.execute(f'{label}-history-{seq:03d}',HISTORY)
                        fields=raw.decode().strip().split('\t')
                        assert len(fields)==3 and fields[0]=='HISTORY' and fields[2]=='enabled'
                        point={'case':config['case'],'trial':trial,'stage':stage,'sample':seq,'elapsed_seconds':time.monotonic()-tick,'utc':utc(),'history_length':int(fields[1]),'raw_label':f'{label}-history-{seq:03d}'}
                        details['samples'].append(point);all_samples.append(point)
                        return point['history_length']
                    def bounded(stage):
                        start=time.monotonic()
                        while True:
                            value=sample(stage)
                            if value<=5:return time.monotonic()-start
                            if time.monotonic()-start>12:raise AssertionError(f'{stage}: history not <=5 within budget, last={value}')
                            time.sleep(.1)
                    pulse('baseline-pulse');bounded('baseline')
                    time.sleep(.1);bounded('baseline-confirmed')
                    baseline=details['samples'][-1]['history_length'];details['history_baseline']=baseline
                    begin=reader.execute(label+'-reader-begin',f'SET SESSION TRANSACTION ISOLATION LEVEL {config["isolation"]}; START TRANSACTION; SELECT CONNECTION_ID(),@@transaction_isolation;')
                    assert begin.decode().strip()==f'{ids[0]}\t{config["isolation"].replace(" ","-")}'
                    initial=None
                    if config['initial_read']:
                        initial=int(reader.execute(label+'-reader-initial','SELECT value FROM account WHERE id=1;').strip());assert initial==0
                    details['initial_read_value']=initial
                    if config['commit_before_writer']:reader.execute(label+'-reader-early-commit','COMMIT;')
                    observer.execute(label+'-trx-before-writes',f'SELECT trx_id,trx_state,trx_mysql_thread_id,trx_isolation_level,trx_rows_locked FROM information_schema.innodb_trx WHERE trx_mysql_thread_id={ids[0]};')
                    statements=''.join('START TRANSACTION; UPDATE account SET value=value+1 WHERE id=1; COMMIT;\n' for _ in range(100))
                    written=int(writer.execute(label+'-writer-commits',statements+'SELECT value FROM account WHERE id=1;',timeout=30).strip());assert written==100
                    details['writer_final_value']=written
                    first=sample('after_business_writes');details['history_after_writes']=first
                    pulse('reader-open-pulse')
                    observer.execute(label+'-status-after-writes','SHOW ENGINE INNODB STATUS;')
                    if config['hold_old_view']:
                        assert first>=100
                        time.sleep(1)
                        settled=sample('hold_old_view');assert settled>=200
                        settle_seconds=None
                    else:
                        settle_seconds=bounded('writer_done_reader_open');settled=details['samples'][-1]['history_length']
                    details.update(history_before_release=settled,settle_while_open_seconds=settle_seconds)
                    if config['commit_before_writer']:reader.execute(label+'-reader-new-transaction','START TRANSACTION;')
                    ordinary=int(reader.execute(label+'-reader-after','SELECT value FROM account WHERE id=1;').strip());details['ordinary_after']=ordinary
                    current=int(reader.execute(label+'-reader-current','SELECT value FROM account WHERE id=1 FOR SHARE;').strip());details['current_after']=current
                    again=int(reader.execute(label+'-reader-again','SELECT value FROM account WHERE id=1;').strip());details['ordinary_again']=again
                    assert ordinary==again==config['ordinary_after'] and current==100
                    observer.execute(label+'-trx-before-release',f'SELECT trx_id,trx_state,trx_mysql_thread_id,trx_isolation_level,trx_rows_locked FROM information_schema.innodb_trx WHERE trx_mysql_thread_id={ids[0]};')
                    reader.execute(label+'-reader-release','COMMIT;')
                    post=reader.execute(label+'-reader-post-commit','SELECT CONNECTION_ID(),value FROM account WHERE id=1;').decode().strip().split('\t')
                    assert int(post[0])==ids[0] and int(post[1])==100
                    details['post_commit_value']=int(post[1])
                    details['history_immediate_commit']=sample('reader_committed')
                    time.sleep(1);details['history_quiet_after_commit']=sample('reader_committed_quiet')
                    pulse('reader-released-pulse')
                    details['drain_after_release_pulse_seconds']=bounded('reader_released_pulse')
                    details['history_after_release']=details['samples'][-1]['history_length']
                    observer.execute(label+'-status-after-release','SHOW ENGINE INNODB STATUS;')
                    assert len(details['control_pulses'])==3
                except Exception as exc:error=str(exc) or type(exc).__name__
                finally:
                    for session in sessions:
                        code=session.close()
                        if code!=0 or session.record['stderr_bytes'] or not session.record['all_sql_markers_completed']:
                            error=error or f'{session.name}: exit={code}, stderr={session.record["stderr_bytes"]}, markers={session.record["all_sql_markers_completed"]}'
                e.data['trials'].append({'case':config['case'],'trial':trial,'passed':not error,'verification_error':error,**details})
                print(f'{label}: {"FAIL" if error else "PASS"} reads={details.get("ordinary_after")}/{details.get("current_after")}/{details.get("ordinary_again")} history={details.get("history_baseline")}/{details.get("history_before_release")}/{details.get("history_quiet_after_commit")}/{details.get("history_after_release")} {error}',flush=True)
                if error:raise RuntimeError(f'{label}: {error}; stop to avoid contaminating following trials')
        e.require('server-logs',compose+['logs','--no-color','mysql'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if container:e.run('failure-server-logs',compose+['logs','--no-color','mysql'])
    if len(e.data['trials'])!=40:failure=failure or 'incomplete 40-trial matrix'
    with (e.dest/'history.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['case','trial','stage','sample','elapsed_seconds','utc','history_length','raw_label'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(all_samples)
    fields=['case','trial','passed','initial_read_value','writer_final_value','ordinary_after','current_after','ordinary_again','post_commit_value','history_baseline','history_after_writes','history_before_release','history_immediate_commit','history_quiet_after_commit','history_after_release','settle_while_open_seconds','drain_after_release_pulse_seconds']
    with (e.dest/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1


if __name__=='__main__':raise SystemExit(main())
