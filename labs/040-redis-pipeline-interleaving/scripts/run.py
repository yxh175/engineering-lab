from pathlib import Path
import json
import re
import sys
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify
PROJECT='engineering-lab-040';IMAGE='redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'
compose=['docker','compose','-p',PROJECT,'-f',str(LAB/'docker-compose.yml')]
e=Evidence(LAB,'redis-wire',[LAB/p for p in ['docker-compose.yml', 'src/resp.py', 'src/scenario.py', 'src/verify.py', 'scripts/run.py']],{'redis_version':'7.4.11','rounds':10,'cases':['split-pipeline','multi','mset-control'],'controlled_split':True})
failure=None;owned=False
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT]).strip()
    e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version']);e.require('image-inspect',['docker','image','inspect',IMAGE])
    owned=True;e.require('startup',compose+['up','-d','--wait','--wait-timeout','90'],timeout=120)
    container=e.require('container-id',compose+['ps','-q','redis']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',container)
    inspect=json.loads(e.require('container-inspect',['docker','inspect',container]))[0]
    assert inspect['Config']['Labels']['com.docker.compose.project']==PROJECT and inspect['HostConfig']['NanoCpus']==1000000000 and inspect['HostConfig']['Memory']==134217728
    binding=inspect['NetworkSettings']['Ports']['6379/tcp'];assert len(binding)==1 and binding[0]['HostIp']=='127.0.0.1';port=int(binding[0]['HostPort'])
    info=e.require('server-info',['docker','exec',container,'redis-cli','INFO','server']);assert b'redis_version:7.4.11' in info
    e.require('memory-config',['docker','exec',container,'redis-cli','CONFIG','GET','maxmemory','maxmemory-policy'])
    cases=['split-pipeline','multi','mset-control']
    for round_id in range(1,11):
        for case in (cases if round_id%2 else list(reversed(cases))):
            label=f'{case}-{round_id:02}';directory=e.dest/'wire-artifacts'/label
            output=e.require(label,[sys.executable,str(LAB/'src/scenario.py'),'--port',str(port),'--case',case,'--out',str(directory)],timeout=30)
            checked=verify(case,directory);assert json.loads(output)==checked;e.data['trials'].append({'round':round_id,'label':label,**checked})
            print(f'{label}: middle={checked["middle_left"]}/{checked["middle_right"]}, partial={checked["partial_observed"]}',flush=True)
    e.require('server-logs',compose+['logs','--no-color','redis'])
except Exception as exc:failure=repr(exc);raise
finally:
    if owned:
        try:
            e.require('cleanup',compose+['down','-v','--remove-orphans'],timeout=60)
            for kind,argv in [('containers',['docker','ps','-aq']),('volumes',['docker','volume','ls','-q']),('networks',['docker','network','ls','-q'])]:
                assert not e.require('after-owned-'+kind,argv+['--filter','label=com.docker.compose.project='+PROJECT]).strip()
        except Exception as exc:failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
