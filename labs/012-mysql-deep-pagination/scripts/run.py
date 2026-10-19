import csv
import hashlib
import json
import re
import sys
from pathlib import Path

LAB=Path(__file__).resolve().parents[1]
ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha
from mysql_cartesian import render

IMAGE='mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d'
CASES=json.loads((LAB/'src/cases.json').read_text(encoding='utf-8'))


def tables(value):
    out=[]
    if isinstance(value,dict):
        if 'table_name' in value:
            out.append({k:value[k] for k in ['table_name','access_type','key','using_index','rows_examined_per_scan'] if k in value})
        for v in value.values():out.extend(tables(v))
    elif isinstance(value,list):
        for v in value:out.extend(tables(v))
    return out


def verify(config,label,plan_raw,tree_raw,sample_raw):
    plan=json.loads(plan_raw)
    nodes=[]
    for line in tree_raw.decode().splitlines():
        m=re.search(r'\(actual time=([\deE.+-]+)\.\.([\deE.+-]+) rows=([\deE.+-]+) loops=(\d+)\)',line)
        if m:nodes.append({'text':line.strip(),'rows':float(m[3]),'loops':int(m[4])})
    assert nodes and nodes[0]['rows']==20 and nodes[0]['loops']==1
    scans=[n for n in nodes if 'scan on events' in n['text'].lower()]
    assert len(scans)==1 and scans[0]['loops']==1
    scan=scans[0]
    name=config['case']
    if name.startswith('offset-'):
        assert scan['rows']==config['offset']+20 and 'index scan' in scan['text'].lower()
        assert 'covering' not in scan['text'].lower()
    elif name=='deferred-deep':
        assert scan['rows']==500037 and 'covering index scan' in scan['text'].lower()
        lookups=[n for n in nodes if 'lookup on e using PRIMARY' in n['text']]
        assert len(lookups)==1 and lookups[0]['rows']==1 and lookups[0]['loops']==20
    elif name.startswith('seek-'):
        assert scan['rows']==20 and 'index range scan' in scan['text'].lower()
    lines=sample_raw.decode().splitlines()
    assert lines[0]=='BEGIN_ROWS' and 'END_ROWS' in lines
    end=lines.index('END_ROWS');texts=lines[1:end]
    assert len(texts)==20 and len(lines)==end+2
    actual=[]
    for line in texts:
        fields=line.split('\t');assert len(fields)==3
        actual.append((int(fields[0]),int(fields[1]),fields[2]))
    expected=[((i-1)//40,i,f'event-{i}'.ljust(128,'x')) for i in range(config['first_id'],config['first_id']+20)]
    assert actual==expected,'ordered full tuple mismatch'
    metrics=lines[-1].split('\t');assert len(metrics)==9 and metrics[0]=='PSSTAT'
    thread,event,timer,lock,sent,examined,errno=map(int,metrics[1:8])
    assert metrics[8]==f'/*lab012-{label}*/ '+config['query']
    assert thread>0 and event>0 and timer>0 and sent==20 and errno==0
    return {'tables':tables(plan),'nodes':nodes,'base_scan_rows':scan['rows'],'base_scan_text':scan['text'],
            'returned_rows':len(actual),'first_id':actual[0][1],'last_id':actual[-1][1],
            'correct_deep_page':config['same_deep_page'],'result_canonical_sha256':hashlib.sha256(json.dumps(actual,separators=(',',':')).encode()).hexdigest(),
            'result_text_bytes':sum(len((x+'\n').encode()) for x in texts),'ps_thread_id':thread,'ps_event_id':event,
            'ps_timer_wait_ps':timer,'ps_lock_time_ps':lock,'ps_rows_sent':sent,'ps_rows_examined':examined,'statement_ms':timer/1e9}


def main():
    e=Evidence(LAB,'docker',[LAB/'docker-compose.yml',LAB/'src/cases.json',LAB/'sql/init.sql',LAB/'sql/index.sql',Path(__file__)],
       {'mysql_expected_version':'8.4.11','row_count':1000000,'payload_bytes':128,'page_size':20,'repeats_per_case':10,
        'concurrency':1,'warmup_per_case':1,'order':'forward odd, reverse even','cold_cache':False,
        'pre_read':'EXPLAIN ANALYZE before each ordinary SELECT','timer':'completed SELECT P_S TIMER_WAIT picoseconds',
        'known_boundary':{'seq_no':12500,'id':500017},'boundary_discovery_cost_measured':False,'concurrent_writes':False})
    e.data['shared_source_sha256']['shared/scripts/mysql_cartesian.py']=sha(ROOT/'shared/scripts/mysql_cartesian.py')
    compose=['docker','compose','-p','engineering-lab-012','-f',str(LAB/'docker-compose.yml')]
    container,failure=None,None
    def sql(label,text,database=True,timeout=180):
        argv=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names','--comments']
        if database:argv.append('engine_lab_012')
        record,out,err=e.run(label,argv,stdin=text.encode(),timeout=timeout)
        (e.dest/label/'input.sql').write_bytes(text.encode())
        if record['exit_code']!=0:raise RuntimeError(f'{label} mysql exit {record["exit_code"]}')
        return out
    try:
        assert (LAB/'sql/init.sql').read_text(encoding='utf-8')==render('engine_lab_012',rows=1000000,payload_bytes=128)
        e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
        e.require('image-inspect',['docker','image','inspect',IMAGE])
        e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
        container=e.require('container-id',compose+['ps','-q','mysql']).decode().strip()
        assert re.fullmatch(r'[a-f0-9]{64}',container)
        e.require('container-inspect-before',['docker','inspect',container])
        metadata=sql('server-metadata','SELECT VERSION(),@@innodb_buffer_pool_size,@@innodb_stats_persistent_sample_pages,@@optimizer_switch,@@transaction_isolation,@@performance_schema;\n',database=False)
        assert metadata.decode().startswith('8.4.11\t536870912\t')
        init=sql('initialize-data',(LAB/'sql/init.sql').read_text(encoding='utf-8'),database=False,timeout=300)
        assert '1000000\t1000000\t0\t0\t128\t128' in init.decode().splitlines()
        sql('pagination-index',(LAB/'sql/index.sql').read_text(encoding='utf-8'),timeout=240)
        sql('setup-instrumentation',"UPDATE performance_schema.setup_consumers SET ENABLED='YES' WHERE NAME IN ('events_statements_current','events_statements_history');\nUPDATE performance_schema.setup_instruments SET ENABLED='YES',TIMED='YES' WHERE NAME='statement/sql/select';\nSELECT NAME,ENABLED FROM performance_schema.setup_consumers WHERE NAME LIKE '%statements%';\nSELECT NAME,ENABLED,TIMED FROM performance_schema.setup_instruments WHERE NAME='statement/sql/select';\nSELECT * FROM performance_schema.performance_timers;\n")
        for config in CASES:sql(config['case']+'-warmup',config['query']+';\n')
        for trial in range(1,11):
            for config in (CASES if trial%2 else list(reversed(CASES))):
                label=f'{config["case"]}-{trial:02d}'
                plan=sql(label+'-plan','EXPLAIN FORMAT=JSON '+config['query']+';\n')
                tree=sql(label+'-analyze','EXPLAIN ANALYZE FORMAT=TREE '+config['query']+';\n')
                tag=f'/*lab012-{label}*/'
                sample=sql(label+'-sample',"SELECT 'BEGIN_ROWS';\n"+tag+' '+config['query']+";\nSELECT 'END_ROWS';\nSELECT 'PSSTAT',THREAD_ID,EVENT_ID,TIMER_WAIT,LOCK_TIME,ROWS_SENT,ROWS_EXAMINED,MYSQL_ERRNO,SQL_TEXT FROM performance_schema.events_statements_history WHERE THREAD_ID=(SELECT THREAD_ID FROM performance_schema.threads WHERE PROCESSLIST_ID=CONNECTION_ID()) AND SQL_TEXT LIKE '"+tag+"%' ORDER BY EVENT_ID DESC LIMIT 1;\n")
                details,error={},''
                try:details=verify(config,label,plan,tree,sample)
                except (AssertionError,ValueError,KeyError,IndexError) as exc:error=str(exc) or type(exc).__name__
                e.data['trials'].append({'case':config['case'],'trial':trial,'passed':not error,'verification_error':error,**details})
                print(f'{label}: {"FAIL" if error else "PASS"} scan={details.get("base_scan_rows")} first={details.get("first_id")} ms={details.get("statement_ms")} {error}',flush=True)
        deep=[t for t in e.data['trials'] if t.get('correct_deep_page')]
        assert len(deep)==40 and all(t['passed'] for t in deep) and len({t['result_canonical_sha256'] for t in deep})==1
        naive=[t for t in e.data['trials'] if t['case']=='seek-missing-tie']
        assert len(naive)==10 and all(t['passed'] and t['first_id']==500041 and t['result_canonical_sha256']!=deep[0]['result_canonical_sha256'] for t in naive)
        e.require('server-logs',compose+['logs','--no-color','mysql']);e.require('container-inspect-after',['docker','inspect',container])
    except Exception as exc:
        failure=str(exc) or type(exc).__name__;print(failure,file=sys.stderr)
        if container:e.run('failure-server-logs',compose+['logs','--no-color','mysql'])
    if len(e.data['trials'])!=70:failure=failure or 'incomplete 70-case matrix'
    fields=['case','trial','passed','base_scan_rows','returned_rows','first_id','last_id','correct_deep_page','result_canonical_sha256','result_text_bytes','ps_timer_wait_ps','ps_rows_examined','statement_ms']
    with (e.dest/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:t.get(k,'') for k in fields} for t in e.data['trials'])
    return 0 if e.seal(failure) else 1


if __name__=='__main__':raise SystemExit(main())
