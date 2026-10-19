from pathlib import Path
import json
import re
import sys
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify,expected_data,query
PROJECT='engineering-lab-037'
IMAGE='mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d'
compose=['docker','compose','-p',PROJECT,'-f',str(LAB/'docker-compose.yml')]
e=Evidence(LAB,'mysql-limit-sort',[LAB/p for p in ['docker-compose.yml', 'sql/init.sql', 'src/cases.json', 'sql/index.sql', 'src/verify.py', 'scripts/run.py']],
           {'mysql_version':'8.4.11','rows':50000,'rounds':10,'cases':['sort','ordered','ordered-control'],'literal_queries':True,'concurrent_writes':False})
failure=None;owned=False;container=None
def sql(label,text,database=True):
    argv=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names']
    if database:argv.append('engine_lab_037')
    c,out,err=e.run(label,argv,stdin=text.encode(),timeout=60)
    (e.dest/label/'input.sql').write_bytes(text.encode())
    if c['exit_code']!=0:raise RuntimeError(f'{label} SQL failed, see original stderr')
    return out
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT]).strip()
    e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version'])
    e.require('image-inspect',['docker','image','inspect',IMAGE])
    owned=True
    e.require('startup',compose+['up','-d','--wait','--wait-timeout','180'],timeout=210)
    container=e.require('container-id',compose+['ps','-q','mysql']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',container)
    inspect=json.loads(e.require('container-inspect',['docker','inspect',container]))[0]
    assert inspect['Config']['Labels']['com.docker.compose.project']==PROJECT
    assert inspect['HostConfig']['NanoCpus']==1000000000 and inspect['HostConfig']['Memory']==536870912
    metadata=sql('server-metadata','SELECT VERSION(),@@innodb_buffer_pool_size,@@sql_mode,@@collation_server,@@optimizer_switch;\n',False)
    assert metadata.startswith(b'8.4.11\t134217728\t')
    sql('initialize',(LAB/'sql/init.sql').read_text(encoding='utf-8'),False)
    sql('schema','SHOW CREATE TABLE events;\nSHOW INDEX FROM events;\n')
    data=sql('full-fixture','SELECT id,tenant_id,created_at,payload FROM events ORDER BY id;\n');assert data==expected_data()
    cases=json.loads((LAB/'src/cases.json').read_bytes())
    def trial(case,round_id):
        label=f"{case['case']}-{round_id:02}";text=query(case['tenant'])
        plan=sql(label+'-plan','EXPLAIN FORMAT=JSON '+text+';\n')
        tree=sql(label+'-tree','EXPLAIN ANALYZE FORMAT=TREE '+text+';\n')
        rows=sql(label+'-rows',text+';\n')
        checked=verify(case['case'],case['tenant'],plan,tree,rows)
        e.data['trials'].append({'round':round_id,'label':label,**checked})
        print(f"{label}: actual sort/work and complete tuples verified",flush=True)
    for round_id in range(1,11):trial(cases[0],round_id)
    sql('add-order-index',(LAB/'sql/index.sql').read_text(encoding='utf-8'))
    after=sql('full-fixture-after','SELECT id,tenant_id,created_at,payload FROM events ORDER BY id;\n')
    assert after==data
    for round_id in range(1,11):
        for case in (cases[1:] if round_id%2 else list(reversed(cases[1:]))):trial(case,round_id)
    assert len({t['rows_sha256'] for t in e.data['trials'] if t['tenant']==7})==1
    e.require('server-logs',compose+['logs','--no-color','mysql'])
except Exception as exc:
    failure=repr(exc);raise
finally:
    if owned:
        try:
            e.require('cleanup',compose+['down','-v','--remove-orphans'],timeout=60)
            assert not e.require('after-owned-containers',['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT]).strip()
            assert not e.require('after-owned-volumes',['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+PROJECT]).strip()
            assert not e.require('after-owned-networks',['docker','network','ls','-q','--filter','label=com.docker.compose.project='+PROJECT]).strip()
        except Exception as exc:
            failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
