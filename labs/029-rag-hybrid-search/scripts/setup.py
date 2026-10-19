import json,sys,traceback
from pathlib import Path
from settings import LAB,ROOT,COMPOSE,PSQL
sys.path.insert(0,str(ROOT/'shared/scripts'));sys.path.insert(0,str(LAB/'src'))
from evidence import Evidence
from search import init_sql,inputs
e=Evidence(LAB,'postgres-setup',[Path(__file__), LAB/'scripts/settings.py', LAB/'src/search.py', LAB/'input-spec.json', LAB/'docker-compose.yml'],{'project':'engineering-lab-029','fixed_image_digest':'feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966'});failure=None
try:
    spec,*_=inputs();(e.dest/'borrowed-inputs.json').write_text(json.dumps(spec,indent=2)+'\n',encoding='utf-8',newline='\n')
    assert not e.require('existing',['docker','ps','-a','-q','--filter','label=com.docker.compose.project=engineering-lab-029']).strip()
    e.require('compose-config',COMPOSE+['config']);e.require('up',COMPOSE+['up','-d','--wait','--wait-timeout','90'],timeout=120)
    c=json.loads(e.require('container',['docker','inspect','lab029-postgres']))[0];assert c['Config']['Labels']['com.docker.compose.project']=='engineering-lab-029' and c['State']['Health']['Status']=='healthy' and c['HostConfig']['Memory']==268435456 and c['HostConfig']['NanoCpus']==1000000000
    query=init_sql();(e.dest/'init.sql').write_text(query,encoding='utf-8',newline='\n');out=e.require('initialize',PSQL,stdin=query.encode(),timeout=30);lines=out.decode('utf-8').splitlines();version=json.loads(lines[0]);assert version['server_version'].startswith('17.') and version['vector_version']=='0.8.2' and version['rows']==16
    e.require('version',['docker','exec','lab029-postgres','postgres','--version']);e.require('kernel',['docker','exec','lab029-postgres','uname','-a']);e.require('logs',['docker','logs','lab029-postgres'])
    e.data['trials'].append({'case':'isolated-real-pgvector-with-frozen-embeddings','passed':True,'actual_versions':version})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'isolated-real-pgvector-with-frozen-embeddings','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
