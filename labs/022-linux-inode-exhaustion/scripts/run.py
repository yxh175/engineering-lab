import json
import sys
import traceback
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
IMAGE='golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb'
cases=[('inode-32','inode-full',32),('inode-128','inode-full',128),('bytes-256','bytes-full',256)]
e=Evidence(LAB,'docker-linux',[LAB/'go.mod', LAB/'docker-compose.yml', LAB/'src/main_linux.go', Path(__file__)],{'cases':cases,'repeats':10,'tmpfs_bytes':1048576,'noswap':True,'runtime_memory':'128m','cpu':'1','fault_mount':'/scratch','cleanup_restores_baseline':True})
failure=None
try:
    (LAB/'.work').mkdir(exist_ok=True)
    compose=['docker','compose','-p','engineering-lab-022','-f',str(LAB/'docker-compose.yml')]
    e.require('docker-version',['docker','version']);e.require('compose-config',compose+['config']);e.require('image-inspect',['docker','image','inspect',IMAGE]);e.require('linux-vet-build',compose+['run','--rm','--no-deps','builder'],timeout=180)
    for case,kind,limit in cases:
        for repeat in range(1,11):
            label=f'{case}-{repeat:02d}';name='lab022-'+label;target=e.dest/'cases'/label
            argv=['docker','run','--rm','--name',name,'--network','none','--memory','128m','--cpus','1','--label','com.docker.compose.project=engineering-lab-022','--tmpfs',f'/scratch:rw,size=1m,nr_inodes={limit},mode=0700,noswap','--mount',f'type=bind,source={LAB},target=/lab','--workdir','/lab',IMAGE,'/lab/.work/lab022-linux','-case',kind,'-inodes',str(limit),'-out','/lab/'+target.relative_to(LAB).as_posix()]
            rec,out,err=e.run(label,argv,timeout=30,container=name)
            t={'case':case,'kind':kind,'inode_limit':limit,'trial':repeat,'command':label,'report':target.relative_to(e.dest).as_posix()+'/report.json','passed':False};e.data['trials'].append(t)
            assert rec['exit_code']==0,f'{label}: exit {rec["exit_code"]}'
            d=json.loads(out);assert d==json.loads((target/'report.json').read_text()) and d['passed'] and not d['failure'] and d['expected_inodes']==limit and d['pid']==1
            assert all(q['df_exit']==[0,0,0] for q in d['snapshots'])
            errors=[q for q in d['operations'] if q['errno']];assert errors and all(q['errno']==28 for q in errors)
            t.update(passed=True,initial_created=d['initial_created'],data_written=d['data_written'],actual_ENOSPC=len(errors),snapshots=len(d['snapshots']))
            print(f'{label}: PASS files={d["initial_created"]} written={d["data_written"]} real_ENOSPC={len(errors)}',flush=True)
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8',newline='\n')
finally:
    passed=e.seal(failure)
raise SystemExit(0 if passed else 1)
