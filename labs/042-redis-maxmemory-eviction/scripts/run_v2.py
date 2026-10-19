from pathlib import Path
import json
import re
import sys
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify_v2 import verify
IMAGE='redis:7.4-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'
e=Evidence(LAB,'redis-maxmemory',[LAB/p for p in ['compose-noeviction.yml', 'compose-lru.yml', 'compose-control.yml', 'src/cases.json', 'src/resp.py', 'src/scenario.py', 'src/verify.py', 'scripts/run.py', 'src/snapshot.lua', 'src/scenario_v2.py', 'src/verify_v2.py', 'scripts/run_v2.py']],{'redis_version':'7.4.11','rounds':10,'fresh_container_each_trial':True,'sets':200,'payload_bytes':8192,'snapshot_readonly':True})
failure=None
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=engineering-lab.lab=042']).strip()
    e.require('docker-version',['docker','version']);e.require('compose-version',['docker','compose','version']);e.require('image-inspect',['docker','image','inspect',IMAGE])
    cases=json.loads((LAB/'src/cases.json').read_bytes())
    for round_id in range(1,11):
        for case in (cases if round_id%2 else list(reversed(cases))):
            label=f'{case["case"]}-{round_id:02}';project='engineering-lab-042-'+label
            compose=['docker','compose','-p',project,'-f',str(LAB/case['compose'])];owned=False
            try:
                assert not e.require(label+'-preflight',['docker','ps','-aq','--filter','label=com.docker.compose.project='+project]).strip()
                owned=True;e.require(label+'-startup',compose+['up','-d','--wait','--wait-timeout','90'],timeout=120)
                cid=e.require(label+'-container-id',compose+['ps','-q','redis']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',cid)
                inspect=json.loads(e.require(label+'-inspect',['docker','inspect',cid]))[0]
                assert inspect['Config']['Labels']['com.docker.compose.project']==project and inspect['Config']['Labels']['engineering-lab.lab']=='042'
                assert inspect['HostConfig']['NanoCpus']==1000000000 and inspect['HostConfig']['Memory']==134217728
                bind=inspect['NetworkSettings']['Ports']['6379/tcp'];assert len(bind)==1 and bind[0]['HostIp']=='127.0.0.1';port=int(bind[0]['HostPort'])
                info=e.require(label+'-info',['docker','exec',cid,'redis-cli','INFO','server']);assert b'redis_version:7.4.11' in info
                directory=e.dest/'wire-artifacts'/label
                output=e.require(label,[sys.executable,str(LAB/'src/scenario_v2.py'),'--port',str(port),'--case',case['case'],'--out',str(directory)],timeout=60)
                checked=verify(case['case'],directory);assert json.loads(output)==checked
                e.data['trials'].append({'round':round_id,'label':label,'project':project,**checked})
                print(f'{label}: OK={checked["accepted_sets"]}, OOM={checked["oom_rejections"]}, retained={checked["retained_data_keys"]}, evicted={checked["evicted_keys"]}',flush=True)
                e.require(label+'-logs',compose+['logs','--no-color','redis'])
            finally:
                if owned:
                    e.require(label+'-cleanup',compose+['down','-v','--remove-orphans'],timeout=60)
                    for kind,argv in [('containers',['docker','ps','-aq']),('volumes',['docker','volume','ls','-q']),('networks',['docker','network','ls','-q'])]:
                        assert not e.require(label+'-after-'+kind,argv+['--filter','label=com.docker.compose.project='+project]).strip()
except Exception as exc:failure=repr(exc);raise
finally:e.seal(failure)
