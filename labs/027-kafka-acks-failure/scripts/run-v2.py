import json
import sys
import time
import traceback
import uuid
from pathlib import Path
from settings import LAB,ROOT,PYTHON,BROKER,CONTAINERS
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha
setup=[p for p in sorted((LAB/'results').glob('*-docker-setup/manifest.json')) if json.loads(p.read_text())['all_passed']][-1]
e=Evidence(LAB,'kafka-acks-fault',[Path(__file__), LAB/'scripts/broker-v2.py', LAB/'scripts/settings.py', LAB/'docker-compose.yml', LAB/'requirements.txt'],{'trials_per_case':10,'setup_manifest':setup.relative_to(ROOT).as_posix(),'setup_manifest_sha256':sha(setup),'fixed_replicas':[1,2,3],'min_insync_replicas':2})
nonce=uuid.uuid4().hex[:10];failure=None;owned=False
def api(label,action,topic,bootstrap,extra=None):
    return json.loads(e.require(label,[str(PYTHON),str(LAB/'scripts/broker-v2.py'),action,topic,'--bootstrap',bootstrap,*(extra or [])],timeout=40))
def snapshot(label):
    cs=json.loads(e.require(label,['docker','inspect',*CONTAINERS]));assert all(c['Config']['Labels']['com.docker.compose.project']=='engineering-lab-027' for c in cs)
    return {c['Name'].lstrip('/'):c for c in cs}
def wait_meta(label,topic,bootstrap,predicate,seconds=45):
    deadline=time.monotonic()+seconds;samples=[]
    for i in range(100):
        value=api(label+f'-{i:03d}','metadata',topic,bootstrap);samples.append(value)
        meta=value['metadata'];part=meta['partitions'].get('0')
        if not meta['topic_error'] and part and not part['error'] and predicate(part):return value,len(samples)
        assert time.monotonic()<deadline,f'{label} state wait exceeded; actual last {meta}'
        time.sleep(.2)
    raise RuntimeError(label+' too many metadata polls')
def dump(label,topic):return e.require(label,['docker','exec','lab027-broker1','/opt/kafka/bin/kafka-dump-log.sh','--files',f'/tmp/kraft-combined-logs/{topic}-0/00000000000000000000.log','--print-data-log','--deep-iteration'],timeout=40).decode()
def records(read):return [json.loads(v['value']) for v in read['messages']]
try:
    cs=snapshot('containers-before');owned=True;assert all(c['State']['Running'] and not c['State']['Paused'] for c in cs.values())
    for case in ['acks1-isr1-unclean','acksall-isr1-reject','acksall-isr3-clean']:
        for i in range(1,11):
            name=f'{case}-{i:02d}';topic=f'lab027-{nonce}-{name}';baseline=uuid.uuid4().hex;marker=uuid.uuid4().hex;degraded=case!='acksall-isr3-clean';unclean='true' if degraded else 'false'
            trial={'case':case,'trial':i,'name':name,'topic':topic,'baseline_event_id':baseline,'marker_event_id':marker,'passed':False};e.data['trials'].append(trial)
            create=api(name+'/create','create',topic,'127.0.0.1:19027',['--unclean',unclean])
            initial,polls=wait_meta(name+'/initial-isr',topic,'127.0.0.1:19027',lambda p:p['leader']==1 and sorted(p['isrs'])==[1,2,3]);trial['initial_polls']=polls
            base=api(name+'/baseline-produce','produce',topic,'127.0.0.1:19027',['--acks','all','--label','baseline','--event',baseline]);assert base['delivery']['error'] is None and base['delivery']['offset']==0
            before=api(name+'/baseline-read','read',topic,'127.0.0.1:19027');assert records(before)==[{'event_id':baseline,'label':'baseline'}]
            if degraded:
                e.require(name+'/pause-followers',['docker','pause','lab027-broker2','lab027-broker3'])
                cs=snapshot(name+'/paused-containers');assert all(cs[f'lab027-broker{j}']['State']['Paused'] for j in [2,3]) and cs['lab027-controller']['State']['Running']
                fault,polls=wait_meta(name+'/degraded-isr',topic,'127.0.0.1:19027',lambda p:p['leader']==1 and p['isrs']==[1]);trial['degraded_polls']=polls
            else:fault,polls=wait_meta(name+'/full-isr',topic,'127.0.0.1:19027',lambda p:p['leader']==1 and sorted(p['isrs'])==[1,2,3])
            e.require(name+'/topic-before',['docker','exec','lab027-broker1','/opt/kafka/bin/kafka-topics.sh','--bootstrap-server','broker1:9092','--describe','--topic',topic])
            ack=api(name+'/marker-produce','produce',topic,'127.0.0.1:19027',['--acks','1' if case=='acks1-isr1-unclean' else 'all','--label','marker','--event',marker])
            rejected=case=='acksall-isr1-reject'
            if rejected:assert ack['delivery']['error'] and ack['delivery']['error']['code']==19,ack
            else:assert ack['delivery']['error'] is None and ack['delivery']['offset']==1,ack
            leaderread=api(name+'/leader-read-before-kill','read',topic,'127.0.0.1:19027');expected=[{'event_id':baseline,'label':'baseline'}]+([] if rejected else [{'event_id':marker,'label':'marker'}]);assert records(leaderread)==expected
            original=dump(name+'/old-leader-dump-before',topic);assert baseline in original and (marker in original)==(not rejected)
            prekill,polls=wait_meta(name+'/prekill-isr',topic,'127.0.0.1:19027',lambda p:p['leader']==1 and sorted(p['isrs'])==([1] if degraded else [1,2,3]));trial['prekill_polls']=polls
            e.require(name+'/kill-leader',['docker','kill','--signal','KILL','lab027-broker1'])
            cs=snapshot(name+'/killed-containers');assert not cs['lab027-broker1']['State']['Running'] and cs['lab027-broker1']['State']['ExitCode']==137 and cs['lab027-controller']['State']['Running']
            if degraded:e.require(name+'/unpause-followers',['docker','unpause','lab027-broker2','lab027-broker3'])
            recovered,polls=wait_meta(name+'/new-leader',topic,'127.0.0.1:19028,127.0.0.1:19029',lambda p:p['leader'] in [2,3] and bool(p['isrs']),seconds=60);trial['new_leader_polls']=polls
            post=api(name+'/new-leader-read','read',topic,'127.0.0.1:19028,127.0.0.1:19029');msgs=records(post);assert msgs and msgs[0]==expected[0] and all(v in expected for v in msgs)
            if not degraded:assert msgs==expected
            if rejected:assert msgs==expected
            survived=any(v['event_id']==marker for v in msgs)
            e.require(name+'/restart-old-leader',['docker','start','lab027-broker1'])
            restored,polls=wait_meta(name+'/restored-isr',topic,BROKER,lambda p:p['leader'] in [2,3] and sorted(p['isrs'])==[1,2,3],seconds=60);trial['restored_polls']=polls
            final=api(name+'/final-read','read',topic,BROKER);assert final['messages']==post['messages'] and final['high']==post['high']
            repaired=dump(name+'/old-leader-dump-restored',topic);assert baseline in repaired and (marker in repaired)==survived
            cs=snapshot(name+'/restored-containers');assert all(c['State']['Running'] and not c['State']['Paused'] for c in cs.values())
            e.require(name+'/topic-final',['docker','exec','lab027-broker1','/opt/kafka/bin/kafka-topics.sh','--bootstrap-server','broker1:9092','--describe','--topic',topic])
            trial.update(passed=True,ack_success=not rejected,marker_error=ack['delivery']['error'],marker_survived=survived,new_leader=recovered['metadata']['partitions']['0']['leader'],prekill_high=leaderread['high'],postfailover_high=post['high'],final_high=final['high'])
            print(f'{name}: PASS ack={not rejected} marker_survived={survived} high {leaderread["high"]}->{final["high"]}',flush=True)
    snapshot('containers-after')
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
    if failure and owned:
        try:
            cs=snapshot('failure-owned-containers')
            for name,c in cs.items():
                if c['State']['Paused']:e.require('failure-unpause-'+name,['docker','unpause',name])
                if not c['State']['Running']:e.require('failure-start-'+name,['docker','start',name])
        except BaseException as exc:(e.dest/'restore-error.txt').write_text(str(exc),encoding='utf-8')
    if owned:
        for name in CONTAINERS:e.run(name+'-logs',['docker','logs',name],timeout=40)
raise SystemExit(0 if e.seal(failure) else 1)
