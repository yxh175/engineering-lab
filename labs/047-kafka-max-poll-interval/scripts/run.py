import json
import re
import sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify
PROJECT='engineering-lab-047';PYTHON=ROOT/'.work/kafka-venv/Scripts/python.exe'
compose=['docker','compose','-p',PROJECT,'-f',str(LAB/'docker-compose.yml')]
e=Evidence(LAB,'kafka-poll',[LAB/p for p in ['docker-compose.yml', 'src/worker.py', 'src/scenario.py', 'src/verify.py', 'scripts/run.py']],{'rounds':10,'max_poll_ms':2000,'session_ms':1000,'bad_no_poll_seconds':3,'good_processing_seconds':.2,'good_schedule':'finish commit and close A before B joins; not a simultaneous-rebalance Good proof'})
failure=None;owned=False
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=com.docker.compose.project='+PROJECT]).strip()
    e.require('client-version',[PYTHON,'-c','import confluent_kafka as k;print(k.version(),k.libversion())'])
    owned=True;e.require('startup',compose+['up','-d','--wait','--wait-timeout','120'],timeout=150)
    cid=e.require('container-id',compose+['ps','-q','kafka']).decode().strip();assert re.fullmatch('[a-f0-9]{64}',cid)
    inspect=json.loads(e.require('container-inspect',['docker','inspect',cid]))[0];assert inspect['HostConfig']['NanoCpus']==2000000000 and inspect['HostConfig']['Memory']==1073741824
    e.require('broker-version',['docker','exec',cid,'/opt/kafka/bin/kafka-topics.sh','--version'])
    for n in range(1,11):
        for case in (['overdue','bounded'] if n%2 else ['bounded','overdue']):
            label=f'{case}-{n:02}';d=e.dest/'consumer-artifacts'/label
            out=e.require(label,[PYTHON,str(LAB/'src/scenario.py'),'--case',case,'--out',str(d)],timeout=90)
            checked=verify(case,d);assert json.loads(out)==json.loads((d/'report.json').read_bytes())
            e.data['trials'].append({'round':n,'label':label,**checked})
            print(f'{label}: Acommit={checked["a_commit_success"]}, AaliveTransfer={checked["a_alive_after_transfer"]}, Boffsets={checked["b_received"]}',flush=True)
    e.require('broker-logs',compose+['logs','--no-color','kafka'])
except Exception as exc:failure=repr(exc);raise
finally:
    if owned:
        try:
            e.require('cleanup',compose+['down','-v','--remove-orphans'],timeout=90)
            for kind,argv in [('containers',['docker','ps','-aq']),('volumes',['docker','volume','ls','-q']),('networks',['docker','network','ls','-q'])]:assert not e.require('after-owned-'+kind,argv+['--filter','label=com.docker.compose.project='+PROJECT]).strip()
        except Exception as exc:failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
