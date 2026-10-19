import json
import sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path[:0]=[str(ROOT/'shared/scripts'),str(LAB/'src')]
from evidence import Evidence
from verify import verify
IMAGE='golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb'
e=Evidence(LAB,'cgroup-cpu',[LAB/p for p in ['src/lab.c', 'src/verify.py', 'scripts/run.py']],{'rounds':10,'threads':2,'iterations_per_thread':400000000,'quota_cores':[0.5,1,2]})
failure=None
try:
    assert not e.require('preflight-owned',['docker','ps','-aq','--filter','label=engineering-lab.lab=045']).strip()
    e.require('docker-version',['docker','version']);e.require('image-inspect',['docker','image','inspect',IMAGE])
    e.require('toolchain',['docker','run','--rm','--network','none',IMAGE,'sh','-c','gcc --version && uname -a'])
    build=e.dest/'build-bin';build.mkdir()
    e.require('build',['docker','run','--rm','--network','none','--cpus','2','--memory','512m','--mount',f'type=bind,source={LAB/"src"},target=/src,readonly','--mount',f'type=bind,source={build},target=/build',IMAGE,'gcc','-O2','-std=c11','-pthread','-Wall','-Wextra','-Werror','/src/lab.c','-o','/build/lab'],timeout=90)
    e.require('disassembly',['docker','run','--rm','--network','none','--mount',f'type=bind,source={build},target=/binlab,readonly',IMAGE,'objdump','-d','/binlab/lab'])
    cases=['half','one','two'];quotas={'half':'0.5','one':'1','two':'2'};reference=None
    for n in range(1,11):
        for case in (cases if n%2 else cases[::-1]):
            label=f'{case}-{n:02}';d=e.dest/'cpu-artifacts'/label;d.mkdir(parents=True)
            out=e.require(label,['docker','run','--rm','--init','--name','engineering-lab-045-'+label,'--label','engineering-lab.lab=045','--network','none','--cpus',quotas[case],'--memory','128m','--pids-limit','32','--mount',f'type=bind,source={build},target=/binlab,readonly','--mount',f'type=bind,source={d},target=/out',IMAGE,'/binlab/lab'],timeout=45,container='engineering-lab-045-'+label)
            checked=verify(case,d);assert json.loads(out)==json.loads((d/'report.json').read_bytes())
            if reference is None:reference=checked['results']
            assert checked['results']==reference
            e.data['trials'].append({'round':n,'label':label,**checked})
            print(f'{label}: wall={checked["wall_ms"]:.2f}ms CPU={checked["process_cpu_ms"]:.2f}ms throttle={checked["nr_throttled"]}',flush=True)
except Exception as exc:failure=repr(exc);raise
finally:
    try:assert not e.require('after-owned',['docker','ps','-aq','--filter','label=engineering-lab.lab=045']).strip()
    except Exception as exc:failure=failure or repr(exc);e.seal(failure);raise
    e.seal(failure)
