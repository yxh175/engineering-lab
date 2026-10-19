import sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'cleanup',[LAB/'docker-compose_v2.yml',Path(__file__)],{'project':'engineering-lab-022'})
failure=None
try:
    e.require('cleanup',['docker','compose','-p','engineering-lab-022','-f',str(LAB/'docker-compose_v2.yml'),'down','--volumes','--remove-orphans'])
    for kind,argv in [('containers',['docker','ps','-a','-q']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:assert not e.require(kind,argv+['--filter','label=com.docker.compose.project=engineering-lab-022']).strip()
    e.data['trials'].append({'case':'scoped-cleanup','passed':True})
except Exception as exc:failure=str(exc);e.data['trials'].append({'case':'scoped-cleanup','passed':False,'error':failure})
raise SystemExit(0 if e.seal(failure) else 1)
