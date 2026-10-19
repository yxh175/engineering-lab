from pathlib import Path
import hashlib
import json
import sys
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify
EXE=LAB/'.work/lab032.exe';EXE.parent.mkdir(exist_ok=True)
e=Evidence(LAB,'native-go-panic',[LAB/p for p in ['go.mod', 'src/main.go', 'src/verify.py', 'scripts/run.py']],
           {'cases':['parent-only','worker-recover','normal'],'rounds':10,'panic':'lab032-job-fault','normal_value':42})
failure=None
try:
    assert b'go1.25.4 windows/amd64' in e.require('go-version',['go','version'])
    e.require('go-env',['go','env','-json','GOOS','GOARCH','GOVERSION','CGO_ENABLED','GOTOOLCHAIN'])
    e.require('build',['go','build','-trimpath','-o',EXE,'./src'])
    e.require('vet',['go','vet','./src'])
    e.require('doc-recover',['go','doc','builtin.recover'])
    (e.dest/'binary.json').write_text(json.dumps({'sha256':hashlib.sha256(EXE.read_bytes()).hexdigest(),'size':EXE.stat().st_size})+'\n',encoding='utf-8',newline='\n')
    for round_id in range(1,11):
        for mode in e.data['parameters']['cases']:
            label=f'{mode}-{round_id:02}'
            c,out,err=e.run(label,[EXE,'-case',mode],timeout=10)
            e.data['trials'].append({'round':round_id,'label':label,**verify(mode,c['exit_code'],out,err)})
        print(f'Round {round_id}: fatal, recovery and normal control verified',flush=True)
except Exception as exc:
    failure=repr(exc);raise
finally:e.seal(failure)
