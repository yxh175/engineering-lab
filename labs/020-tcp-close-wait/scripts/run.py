"""Three cases x ten independent Linux processes; capture before/after raw TCP and FD data."""
import json
import sys
import traceback
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parents[1]
sys.path.insert(0, str(ROOT / 'shared/scripts'))
from evidence import Evidence

sources = [LAB/'go.mod', LAB/'Dockerfile', LAB/'docker-compose.yml', LAB/'src/main_linux.go', Path(__file__)]
e = Evidence(LAB, 'docker-linux', sources, {'cases': ['retain-eof','close-eof','reply-then-close'], 'repeats':10,'waves':3,'connections_per_wave':16,'hold_ms':500,'one_pid_both_endpoints':True,'runtime_memory':'128m','builder_memory':'512m','network':'none','scenario_definition':'scripts/run.py'})
failure = None
try:
    (LAB/'.work').mkdir(exist_ok=True)
    compose = ['docker','compose','-p','engineering-lab-020','-f',str(LAB/'docker-compose.yml')]
    e.require('docker-version',['docker','version'])
    e.require('compose-config',compose+['config'])
    e.require('image-build',compose+['build','builder'],timeout=600)
    e.require('image-inspect',['docker','image','inspect','engineering-lab-020:local'])
    e.require('linux-vet-build',compose+['run','--rm','--no-deps','builder'],timeout=180)
    for label, argv in [('kernel',['uname','-a']),('ss-version',['ss','-V']),('packages',['dpkg-query','-W','iproute2','libbpf1','libmnl0','libxtables12'])]:
        e.require(label,['docker','run','--rm','--network','none','--label','com.docker.compose.project=engineering-lab-020','engineering-lab-020:local',*argv])
    for case in e.data['parameters']['cases']:
        for repeat in range(1,11):
            label=f'{case}-{repeat:02d}';name='lab020-'+label
            target=e.dest/'cases'/label
            argv=compose+['run','--rm','--no-deps','--name',name,'runner','-case',case,'-n','16','-waves','3','-hold','500ms','-out','/lab/'+target.relative_to(LAB).as_posix()]
            rec,out,err=e.run(label,argv,timeout=30,container=name)
            trial={'case':case,'trial':repeat,'command':label,'report':target.relative_to(e.dest).as_posix()+'/report.json','passed':False}
            e.data['trials'].append(trial)
            assert rec['exit_code']==0, f'{label}: exit {rec["exit_code"]}'
            d=json.loads(out);assert d==json.loads((target/'report.json').read_text())
            assert d['passed'] and not d['failure'] and d['pid']==1 and d['n']==16 and d['waves']==3 and len(d['pairs'])==48
            snaps={s['phase']:s for s in d['snapshots']}
            counts=[snaps[f'wave{w}-after-policy']['server_close_wait'] for w in [1,2,3]]
            assert counts==([16,32,48] if case=='retain-eof' else [0,0,0])
            trial.update(passed=True,after_policy_close_wait=counts,after_policy_server_fd=[snaps[f'wave{w}-after-policy']['server_fd'] for w in [1,2,3]],snapshots=len(d['snapshots']),reply_bytes=sum(q['n'] for q in d['operations'] if q['action']=='peer-read-reply'))
            print(f'{label}: PASS CLOSE_WAIT={counts}',flush=True)
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}'
    (e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8',newline='\n')
finally:
    passed=e.seal(failure)
raise SystemExit(0 if passed else 1)
