import json
import sys
import traceback
from pathlib import Path
from settings import LAB,ROOT,COMPOSE
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'cleanup',[Path(__file__), LAB/'scripts/settings.py'],{'project':'engineering-lab-026'})
failure=None
try:
    containers=json.loads(e.require('owned-before',['docker','inspect','lab026-kafka','lab026-mysql']))
    assert all(v['Config']['Labels']['com.docker.compose.project']=='engineering-lab-026' for v in containers)
    volumes=[v['Name'] for c in containers for v in c['Mounts'] if v['Type']=='volume']
    (e.dest/'owned-volumes.json').write_text(json.dumps(volumes,indent=2)+'\n')
    e.require('down',COMPOSE+['down','--volumes'],timeout=60)
    for kind,command in [('containers',['docker','ps','-a','-q']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:
        assert not e.require(kind+'-after',command+['--filter','label=com.docker.compose.project=engineering-lab-026']).strip()
    allvolumes=e.require('all-volume-names-after',['docker','volume','ls','--format','{{.Name}}']).decode().splitlines()
    assert all(v not in allvolumes for v in volumes)
    e.data['trials'].append({'case':'owned-resources-removed','passed':True,'anonymous_volumes':volumes})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'owned-resources-removed','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
