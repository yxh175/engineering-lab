import json,sys,traceback
from pathlib import Path
from settings import LAB,ROOT,COMPOSE
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'cleanup',[Path(__file__), LAB/'scripts/settings.py'],{'project':'engineering-lab-029'});failure=None
try:
    c=json.loads(e.require('owned-before',['docker','inspect','lab029-postgres']))[0];assert c['State']['Running'] and c['Config']['Labels']['com.docker.compose.project']=='engineering-lab-029'
    volumes=[m['Name'] for m in c['Mounts'] if m['Type']=='volume'];(e.dest/'owned-volumes.json').write_text(json.dumps(volumes)+'\n')
    e.require('down',COMPOSE+['down','--volumes'],timeout=60)
    for kind,args in [('containers',['docker','ps','-a','-q']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:assert not e.require(kind+'-after',args+['--filter','label=com.docker.compose.project=engineering-lab-029']).strip()
    names=e.require('all-volume-names-after',['docker','volume','ls','--format','{{.Name}}']).decode().splitlines();assert not any(v in names for v in volumes)
    e.data['trials'].append({'case':'owned-resources-removed','passed':True,'owned_volumes':volumes})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'owned-resources-removed','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
