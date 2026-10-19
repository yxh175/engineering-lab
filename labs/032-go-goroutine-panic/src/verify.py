"""Verify fatal stderr, worker-local recovery, and explicit business results."""
import json
def verify(mode, code, stdout, stderr):
    events=[json.loads(line) for line in stdout.decode().splitlines()]
    assert events and events[0]['event']=='start'
    s=events[0]
    assert s['case']==mode and s['pid']>0 and (s['go'],s['os'],s['arch'])==('go1.25.4','windows','amd64')
    names=[v['event'] for v in events]
    fatal=mode=='parent-only'
    if fatal:
        assert code==2
        assert names==['start','parent_ready','worker_enter','job_before','worker_defer']
        text=stderr.decode()
        assert 'panic: lab032-job-fault' in text and 'main.job(' in text and 'created by main.main' in text
        assert 'parent_defer' not in names and 'completed' not in names
        recovered=False;business=False;joined=False
    else:
        assert code==0 and not stderr
        middle=['worker_recovered'] if mode=='worker-recover' else ['job_after']
        assert names==['start','parent_ready','worker_enter','job_before',*middle,'worker_result','worker_defer','completed','parent_defer']
        assert events[-1]['panic'] is None
        r=events[-2]
        assert r['worker_joined'] is True
        recovered=mode=='worker-recover';business=not recovered;joined=True
        if recovered:
            v=events[4]
            assert v['panic']=='lab032-job-fault' and 'main.safeJob.func1' in v['stack'] and 'main.job(' in v['stack']
            assert r['error']=='worker panic: lab032-job-fault' and r['value']==0 and not r['business_success']
        else:
            assert r['error']=='' and r['value']==42 and r['business_success']
    assert events[3]['fail'] is (mode!='normal')
    return {'case':mode,'pid':s['pid'],'exit_code':code,'event_count':len(events),'fatal':fatal,
            'worker_recovered':recovered,'worker_joined':joined,'business_success':business,'passed':True}
