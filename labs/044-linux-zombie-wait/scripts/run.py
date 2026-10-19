import json
import sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify
IMAGE='golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb'
e=Evidence(LAB,'linux-wait',[LAB/p for p in ['src/lab.c', 'src/verify.py', 'scripts/run.py']],{'rounds':10,'cases':['unreaped','immediate-wait','running-control'],'child_exit':42})
failure=None
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=engineering-lab.lab=044']).strip()
    e.require('docker-version',['docker','version']);e.require('image-inspect',['docker','image','inspect',IMAGE])
    e.require('toolchain',['docker','run','--rm','--network','none',IMAGE,'sh','-c','gcc --version && ps --version && uname -a'])
    build=e.dest/'build-bin';build.mkdir()
    e.require('build',['docker','run','--rm','--network','none','--cpus','2','--memory','512m','--mount',f'type=bind,source={LAB/"src"},target=/src,readonly','--mount',f'type=bind,source={build},target=/build',IMAGE,'gcc','-O2','-std=c11','-Wall','-Wextra','-Werror','/src/lab.c','-o','/build/lab'],timeout=90)
    cases=['unreaped','immediate-wait','running-control']
    for n in range(1,11):
        for case in (cases if n%2 else cases[::-1]):
            label=f'{case}-{n:02}';d=e.dest/'process-artifacts'/label;d.mkdir(parents=True)
            out=e.require(label,['docker','run','--rm','--init','--name','engineering-lab-044-'+label,'--label','engineering-lab.lab=044','--network','none','--cpus','1','--memory','128m','--pids-limit','32','--mount',f'type=bind,source={build},target=/binlab,readonly','--mount',f'type=bind,source={d},target=/out',IMAGE,'/binlab/lab',case],timeout=30,container='engineering-lab-044-'+label)
            checked=verify(case,d);assert json.loads(out)=={k:v for k,v in checked.items() if k!='passed'}
            e.data['trials'].append({'round':n,'label':label,**checked})
            print(f'{label}: before={checked["before"]} after={checked["after"]} exit={checked["exit_status"]}',flush=True)
except Exception as exc:failure=repr(exc);raise
finally:
    try:assert not e.require('after-owned',['docker','ps','-aq','--filter','label=engineering-lab.lab=044']).strip()
    except Exception as exc:failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
