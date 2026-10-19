from pathlib import Path
import hashlib
import json
import sys
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify
EXE=LAB/'.work/lab035.exe';EXE.parent.mkdir(exist_ok=True)
e=Evidence(LAB,'native-http-budget',[LAB/p for p in ['go.mod', 'src/main.go', 'src/verify.py', 'scripts/run.py']],
           {'cases':['attempt-only','shared-budget','normal'],'rounds':10,'attempt_ms':200,'total_ms':250,'delay_ms':120,'backoff_ms':30,'max_attempts':3})
failure=None
try:
    assert b'go1.25.4 windows/amd64' in e.require('go-version',['go','version'])
    e.require('go-env',['go','env','-json','GOOS','GOARCH','GOVERSION','CGO_ENABLED','GOTOOLCHAIN'])
    e.require('build',['go','build','-trimpath','-o',EXE,'./src'])
    e.require('vet',['go','vet','./src'])
    for name in ['context.WithTimeout','http.NewRequestWithContext','http.Request.Context','http.Server.Shutdown']:
        e.require('doc-'+name.replace('.','-'),['go','doc',name])
    (e.dest/'binary.json').write_text(json.dumps({'sha256':hashlib.sha256(EXE.read_bytes()).hexdigest(),'size':EXE.stat().st_size})+'\n',encoding='utf-8',newline='\n')
    (e.dest/'actors').mkdir()
    for round_id in range(1,11):
        for mode in e.data['parameters']['cases']:
            label=f'{mode}-{round_id:02}';folder=e.dest/'actors'/label
            raw=e.require(label,[EXE,'-case',mode,'-outdir',folder],timeout=10)
            r=json.loads(raw);assert r==json.loads((folder/'result.json').read_bytes())
            e.data['trials'].append({'round':round_id,'label':label,**verify(r)})
        print(f'Round {round_id}: actual HTTP retries and server cancellation verified',flush=True)
except Exception as exc:
    failure=repr(exc);raise
finally:e.seal(failure)
