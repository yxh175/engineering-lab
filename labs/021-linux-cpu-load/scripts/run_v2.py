import json
import sys
import traceback
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
sources=[LAB/'go.mod', LAB/'docker-compose_v2.yml', LAB/'src/actor.c', LAB/'src/observer_v2/main_linux.go', Path(__file__)]
e=Evidence(LAB,'docker-linux',sources,{'cases':['cpu-busy','pipe-read','clone-wait'],'repeats':10,'actors':4,'samples':10,'sample_interval_ms':150,'cpu_percent_scope':'all cgroup processes / one CPU','clone_wait_is_not_disk_IO':True})
failure=None
try:
    (LAB/'.work').mkdir(exist_ok=True)
    compose=['docker','compose','-p','engineering-lab-021','-f',str(LAB/'docker-compose_v2.yml')]
    e.require('docker-version',['docker','version']);e.require('compose-config',compose+['config'])
    e.require('image-inspect',['docker','image','inspect','golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb'])
    e.require('linux-vet-build',compose+['run','--rm','--no-deps','builder'],timeout=180)
    for case in e.data['parameters']['cases']:
        for repeat in range(1,11):
            label=f'{case}-{repeat:02d}';name='lab021-'+label;target=e.dest/'cases'/label
            rec,out,err=e.run(label,compose+['run','--rm','--no-deps','--name',name,'runner','-case',case,'-out','/lab/'+target.relative_to(LAB).as_posix()],timeout=30,container=name)
            t={'case':case,'trial':repeat,'command':label,'report':target.relative_to(e.dest).as_posix()+'/report.json','passed':False};e.data['trials'].append(t)
            assert rec['exit_code']==0,f'{label} exit {rec["exit_code"]}'
            d=json.loads(out);assert d==json.loads((target/'report.json').read_text()) and d['passed'] and d['all_reaped'] and len(d['actors'])==4 and len(d['samples'])==10
            want={'cpu-busy':'R','pipe-read':'S','clone-wait':'D'}[case]
            stable=sum(all(s['state']==want for s in q['target_states'] if s['role']=='parent') for q in d['samples'])
            t.update(passed=True,stable_snapshots=stable,one_core_cpu_percent=d['one_core_cpu_percent'],nr_throttled_delta=d['nr_throttled_delta'])
            print(f'{label}: PASS state={want} {stable}/10 CPU={d["one_core_cpu_percent"]:.3f}%',flush=True)
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8',newline='\n')
finally:
    passed=e.seal(failure)
raise SystemExit(0 if passed else 1)
