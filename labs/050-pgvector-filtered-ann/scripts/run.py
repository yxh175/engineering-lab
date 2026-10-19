import json
import re
import sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from query import sql
from verify import verify,snapshot
PROJECT='engineering-lab-050';compose=['docker','compose','-p',PROJECT,'-f',str(LAB/'docker-compose.yml')]
e=Evidence(LAB,'pgvector-filter',[LAB/p for p in ['docker-compose.yml', 'sql/schema.sql', 'src/query.py', 'src/verify.py', 'scripts/run.py']],{'rounds':10,'rows':10000,'matching_rows':100,'synthetic_vectors':'[id,0] integers, not model outputs','query_vector':[0,0],'ef_search':40,'iterative_max_scan_tuples':20000,'same_index_repeated_queries':True})
failure=None;owned=False
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT]).strip()
    owned=True;e.require('startup',compose+['up','-d','--wait','--wait-timeout','120'],timeout=150)
    cid=e.require('container-id',compose+['ps','-q','postgres']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',cid)
    inspect=json.loads(e.require('container-inspect',['docker','inspect',cid]))[0];assert inspect['HostConfig']['NanoCpus']==1000000000 and inspect['HostConfig']['Memory']==268435456
    psql=['docker','exec','-i',cid,'psql','-X','-q','-A','-t','-v','ON_ERROR_STOP=1','-U','lab050','-d','lab050']
    e.require('schema',psql,stdin=(LAB/'sql/schema.sql').read_bytes(),timeout=90)
    version=e.require('versions',psql,stdin=b"SELECT json_build_object('server',current_setting('server_version'),'vector',(SELECT extversion FROM pg_extension WHERE extname='vector'),'buffers',current_setting('shared_buffers'),'indexes',(SELECT json_agg(indexdef) FROM pg_indexes WHERE tablename='items'));\n")
    info=json.loads(version);assert info['server'].startswith('17.10') and info['vector']=='0.8.2' and info['buffers']=='32MB'
    full=b"SELECT json_agg(json_build_object('id',id,'category',category,'embedding',embedding::text) ORDER BY id) FROM items;\n"
    before=e.require('full-before',psql,stdin=full);snapshot(e.dest/'full-before/stdout.txt')
    cases=['ann-filtered','iterative-filtered','exact-filtered','unfiltered-control']
    for n in range(1,11):
        for case in (cases if n%2 else cases[::-1]):
            label=f'{case}-{n:02}';statement=sql(case)
            raw=e.require(label,psql,stdin=statement.encode(),timeout=30)
            (e.dest/label/'input.sql').write_text(statement,encoding='utf-8',newline='\n')
            checked=verify(case,raw);e.data['trials'].append({'round':n,'label':label,**checked})
            print(f'{label}: rows={checked["rows"]}, recall={checked["exact_top10_recall"]}, removed={checked["rows_removed_by_filter"]}',flush=True)
    after=e.require('full-after',psql,stdin=full);assert before==after;snapshot(e.dest/'full-after/stdout.txt')
    assert sum(t['rows']<10 for t in e.data['trials'] if t['case']=='ann-filtered')>=8
    e.require('logs',compose+['logs','--no-color','postgres'])
except Exception as exc:failure=repr(exc);raise
finally:
    if owned:
        try:
            e.require('cleanup',compose+['down','-v','--remove-orphans'],timeout=90)
            for kind,argv in [('containers',['docker','ps','-aq']),('volumes',['docker','volume','ls','-q']),('networks',['docker','network','ls','-q'])]:assert not e.require('after-owned-'+kind,argv+['--filter','label=com.docker.compose.project='+PROJECT]).strip()
        except Exception as exc:failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
