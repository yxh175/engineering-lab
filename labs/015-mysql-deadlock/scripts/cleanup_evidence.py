import sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'cleanup',[LAB/'docker-compose.yml',Path(__file__)],{'project':'engineering-lab-015','scope':'only this project containers/networks/volumes'})
failure=None
try:
    e.require('cleanup',['docker','compose','-p','engineering-lab-015','-f',str(LAB/'docker-compose.yml'),'down','--volumes','--remove-orphans'])
    for kind,argv in [('containers',['docker','ps','-a','-q']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:
        out=e.require(kind,argv+['--filter','label=com.docker.compose.project=engineering-lab-015'])
        assert not out.strip(),kind
    e.data['trials'].append({'case':'only-lab-cleanup','passed':True})
except Exception as exc:
    failure=str(exc);e.data['trials'].append({'case':'only-lab-cleanup','passed':False,'error':failure})
raise SystemExit(0 if e.seal(failure) else 1)
