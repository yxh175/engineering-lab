import json
import sys
import traceback
from pathlib import Path
from settings import LAB,ROOT,COMPOSE,CONTAINERS
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'cleanup',[Path(__file__), LAB/'scripts/settings.py'],{'project':'engineering-lab-027'})
failure=None
try:
    cs=json.loads(e.require('owned-before',['docker','inspect',*CONTAINERS]));assert len(cs)==4 and all(c['Config']['Labels']['com.docker.compose.project']=='engineering-lab-027' for c in cs)
    assert all(c['State']['Running'] and not c['State']['Paused'] for c in cs)
    volumes=[v['Name'] for c in cs for v in c['Mounts'] if v['Type']=='volume'];(e.dest/'owned-volumes.json').write_text(json.dumps(volumes,indent=2)+'\n')
    e.require('kernel',['docker','exec','lab027-controller','uname','-a']);e.require('docker-version',['docker','version'])
    e.require('down',COMPOSE+['down','--volumes'],timeout=60)
    for kind,args in [('containers',['docker','ps','-a','-q']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:assert not e.require(kind+'-after',args+['--filter','label=com.docker.compose.project=engineering-lab-027']).strip()
    actual=e.require('all-volume-names-after',['docker','volume','ls','--format','{{.Name}}']).decode().splitlines();assert all(v not in actual for v in volumes)
    e.data['trials'].append({'case':'owned-resources-removed','passed':True,'anonymous_volumes':volumes})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'owned-resources-removed','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
