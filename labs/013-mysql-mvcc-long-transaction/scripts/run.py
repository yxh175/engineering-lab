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
WRITES=100
HISTORY="SELECT 'HISTORY',COUNT,STATUS FROM information_schema.innodb_metrics WHERE NAME='trx_rseg_history_len';\n"


def main():
    e=Evidence(LAB,'docker',[LAB/'docker-compose.yml',LAB/'src/cases.json',LAB/'sql/init.sql',Path(__file__)],
        {'mysql_expected_version':'8.4.11','cases':[c['case'] for c in CASES],'repeats_per_case':10,
         'updates_committed_per_trial':WRITES,'reader_writer_observer_connections':3,'history_baseline':0,
         'purge_observation_budget_seconds':12,'poll_interval_seconds':.1,'old_view_hold_seconds':1,
         'order':'forward odd, reversed even','synchronization':'mysql response markers, writer runs only after reader setup returns'})
    e.data['shared_source_sha256']['shared/scripts/mysql_session.py']=sha(ROOT/'shared/scripts/mysql_session.py')
    compose=['docker','compose','-p','engineering-lab-013','-f',str(LAB/'docker-compose.yml')]
    container,failure=None,None
    all_samples=[]
    def cli():
        return ['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--unbuffered','engine_lab_013']
    def sql(label,text,database=True):
        argv=cli()
        if not database:argv=argv[:-1]
        rec,out,err=e.run(label,argv,stdin=text.encode(),timeout=60)
        (e.dest/label/'input.sql').write_bytes(text.encode())
        assert rec['exit_code']==0 and not err, f'{label}: mysql failed'
        return out
    try:
        e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
        e.require('image-inspect',['docker','image','inspect',IMAGE])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
        container=e.require('container-id',compose+['ps','-q','mysql']).decode().strip()
        assert re.fullmatch(r'[a-f0-9]{64}',container)
        e.require('container-inspect',['docker','inspect',container])
        meta=sql('server-metadata','SELECT VERSION(),@@innodb_buffer_pool_size,@@innodb_purge_threads,@@innodb_max_purge_lag,@@transaction_isolation;\n',False)
        assert meta.decode().startswith('8.4.11\t134217728\t')
        assert sql('initialize',(LAB/'sql/init.sql').read_text(encoding='utf-8'),False).decode().startswith('1\t0\t0\n')
        for trial in range(1,11):
            for config in (CASES if trial%2 else list(reversed(CASES))):
                label=f'{config["case"]}-{trial:02d}'
                sessions=[];details={};error='';samples=[]
                try:
                    reader,writer,observer=[MySQLSession(e,label+'-'+role,cli()) for role in ['reader','writer','observer']]
                    sessions=[reader,writer,observer]
                    ids=[int(s.execute(label+'-'+role+'-id','SELECT CONNECTION_ID();\n').strip()) for s,role in zip(sessions,['reader','writer','observer'])]
                    assert len(set(ids))==3
                    writer.execute(label+'-reset','UPDATE account SET value=0 WHERE id=1;\n')
                    tick=time.monotonic();seq=0
                    def sample(stage):
                        nonlocal seq
                        seq+=1
                        raw=observer.execute(f'{label}-history-{seq:03d}',HISTORY)
                        fields=raw.decode().strip().split('\t')
                        assert len(fields)==3 and fields[0]=='HISTORY' and fields[2]=='enabled'
                        point={'case':config['case'],'trial':trial,'stage':stage,'sample':seq,'elapsed_seconds':time.monotonic()-tick,'utc':utc(),'history_length':int(fields[1]),'raw_label':f'{label}-history-{seq:03d}'}
                        samples.append(point);all_samples.append(point)
                        return point['history_length']
                    def drain(stage):
                        start=time.monotonic()
                        while True:
                            value=sample(stage)
                            if value==0:return time.monotonic()-start
                            if time.monotonic()-start>12:raise AssertionError(f'{stage}: history not zero within budget, last={value}')
                            time.sleep(.1)
                    drain('baseline')
                    begin=reader.execute(label+'-reader-begin',f'SET SESSION TRANSACTION ISOLATION LEVEL {config["isolation"]};\nSTART TRANSACTION;\nSELECT CONNECTION_ID(),@@transaction_isolation;\n')
                    assert begin.decode().strip()==f'{ids[0]}\t{config["isolation"].replace(" ","-")}'
                    initial=None
                    if config['initial_read']:
                        initial=int(reader.execute(label+'-reader-initial','SELECT value FROM account WHERE id=1;\n').strip());assert initial==0
                    if config['commit_before_writer']:reader.execute(label+'-reader-early-commit','COMMIT;\n')
                    observer.execute(label+'-trx-before-writes',f'SELECT trx_id,trx_state,trx_mysql_thread_id,trx_isolation_level,trx_rows_locked FROM information_schema.innodb_trx WHERE trx_mysql_thread_id={ids[0]};\n')
                    statements=''.join('START TRANSACTION;\nUPDATE account SET value=value+1 WHERE id=1;\nCOMMIT;\n' for _ in range(WRITES))
                    written=int(writer.execute(label+'-writer-commits',statements+'SELECT value FROM account WHERE id=1;\n',timeout=30).strip());assert written==100
                    h_first=sample('after_writes')
                    observer.execute(label+'-status-after-writes','SHOW ENGINE INNODB STATUS;\n')
                    if config['hold_old_view']:
                        assert h_first>=WRITES
                        time.sleep(1)
                        h_settled=sample('hold_old_view');assert h_settled>=WRITES
                        settle_seconds=None
                    else:
                        settle_seconds=drain('writer_done_reader_open');h_settled=samples[-1]['history_length'];assert h_settled==0
                    if config['commit_before_writer']:reader.execute(label+'-reader-new-transaction','START TRANSACTION;\n')
                    ordinary=int(reader.execute(label+'-reader-after','SELECT value FROM account WHERE id=1;\n').strip())
                    current=int(reader.execute(label+'-reader-current','SELECT value FROM account WHERE id=1 FOR SHARE;\n').strip())
                    ordinary_again=int(reader.execute(label+'-reader-again','SELECT value FROM account WHERE id=1;\n').strip())
                    assert ordinary==ordinary_again==config['ordinary_after'] and current==100
                    observer.execute(label+'-trx-before-release',f'SELECT trx_id,trx_state,trx_mysql_thread_id,trx_isolation_level,trx_rows_locked FROM information_schema.innodb_trx WHERE trx_mysql_thread_id={ids[0]};\n')
                    reader.execute(label+'-reader-release','COMMIT;\n')
                    post=reader.execute(label+'-reader-post-commit','SELECT CONNECTION_ID(),value FROM account WHERE id=1;\n').decode().strip().split('\t')
                    assert int(post[0])==ids[0]
                    released=int(post[1]);assert released==100
                    release_seconds=drain('reader_released')
                    observer.execute(label+'-status-after-release','SHOW ENGINE INNODB STATUS;\n')
                    details={'connection_ids':ids,'initial_read_value':initial,'writer_final_value':written,'ordinary_after':ordinary,'current_after':current,'ordinary_again':ordinary_again,'post_commit_value':released,
                             'history_after_writes':h_first,'history_before_release':h_settled,'history_after_release':samples[-1]['history_length'],'settle_while_open_seconds':settle_seconds,'drain_after_commit_seconds':release_seconds,'samples':samples}
                except Exception as exc:
                    error=str(exc) or type(exc).__name__
                finally:
                    for session in sessions:
                        code=session.close()
                        if code!=0 or session.record['stderr_bytes'] or not session.record['all_sql_markers_completed']:
                            error=error or f'{session.name}: exit={code}, stderr={session.record["stderr_bytes"]}, markers={session.record["all_sql_markers_completed"]}'
                e.data['trials'].append({'case':config['case'],'trial':trial,'passed':not error,'verification_error':error,**details})
                print(f'{label}: {"FAIL" if error else "PASS"} reads={details.get("ordinary_after")}/{details.get("current_after")}/{details.get("ordinary_again")} history={details.get("history_after_writes")}/{details.get("history_before_release")}/{details.get("history_after_release")} {error}',flush=True)
                if error:raise RuntimeError(f'{label}: {error}; stop to avoid contaminating following trials')
        e.require('server-logs',compose+['logs','--no-color','mysql'])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if container:e.run('failure-server-logs',compose+['logs','--no-color','mysql'])
    if len(e.data['trials'])!=40:failure=failure or 'incomplete 40-trial matrix'
    with (e.dest/'history.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['case','trial','stage','sample','elapsed_seconds','utc','history_length','raw_label'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(all_samples)
    fields=['case','trial','passed','initial_read_value','writer_final_value','ordinary_after','current_after','ordinary_again','post_commit_value','history_after_writes','history_before_release','history_after_release','settle_while_open_seconds','drain_after_commit_seconds']
    with (e.dest/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1


if __name__=='__main__':raise SystemExit(main())
