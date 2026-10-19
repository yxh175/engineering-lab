from pathlib import Path
import json
import re
import sys
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify,expected_data
PROJECT='engineering-lab-036'
IMAGE='mysql:8.4@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d'
compose=['docker','compose','-p',PROJECT,'-f',str(LAB/'docker-compose.yml')]
e=Evidence(LAB,'mysql-types',[LAB/p for p in ['docker-compose.yml', 'sql/init.sql', 'src/cases.json', 'src/verify.py', 'scripts/run.py']],
           {'mysql_version':'8.4.11','rows':50000,'rounds':10,'cases':['numeric','string','string-control'],'literal_queries':True,'concurrent_writes':False})
failure=None;owned=False;container=None
def sql(label,text,database=True):
    argv=['docker','exec','-i','-e','MYSQL_PWD=lab-only-password',container,'mysql','-uroot','--protocol=TCP','-h127.0.0.1','--batch','--raw','--skip-column-names']
    if database:argv.append('engine_lab_036')
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
    sql('schema','SHOW CREATE TABLE fixture;\nSHOW INDEX FROM fixture;\n')
    data=sql('full-fixture','SELECT id,HEX(code) FROM fixture ORDER BY id;\n');assert data==expected_data()
    cases=json.loads((LAB/'src/cases.json').read_bytes())
    for round_id in range(1,11):
        for case in (cases if round_id%2 else list(reversed(cases))):
            label=f"{case['case']}-{round_id:02}";query=case['query']
            plan=sql(label+'-plan','EXPLAIN FORMAT=JSON '+query+';\n')
            tree=sql(label+'-tree','EXPLAIN ANALYZE FORMAT=TREE '+query+';\n')
            rows=sql(label+'-rows',query+';\nSHOW WARNINGS;\n')
            checked=verify(case['case'],plan,tree,rows)
            e.data['trials'].append({'round':round_id,'label':label,**checked})
        print(f'Round {round_id}: real tuples, warnings and access work verified',flush=True)
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
