import json
from pathlib import Path
from decimal import Decimal
def milli(s):return int(Decimal(s[:-1])) if s.endswith('m') else int(Decimal(s)*1000)
def ticks(p):
    first=p.read_text().splitlines()[0].split();assert first[0]=='cpu'
    v=[int(s) for s in first[1:]];assert len(v)>=8
    return sum(v[:8]),v[3]+v[4]
def verify(case,base,label,alloc):
    d=Path(base);p=json.loads((d/label/'final-pod/stdout.txt').read_bytes());uid=p['metadata']['uid']
    events=json.loads((d/label/'events/stdout.txt').read_bytes())['items']
    assert events and all(v['involvedObject']['uid']==uid for v in events)
    assert p['metadata']['labels']['lab']=='046' and p['metadata']['namespace']=='lab046'
    c=p['spec']['containers'][0];req=milli(c['resources']['requests']['cpu'])
    assert c['image']=='engineering-lab-046:go1254' and c['imagePullPolicy']=='Never'
    assert c['resources']['limits']=={'memory':'32Mi'} and c['resources']['requests']['memory']=='8Mi'
    conditions={v['type']:v for v in p['status']['conditions']}
    if case=='oversized':
        assert req==alloc+1000 and p['status']['phase']=='Pending' and not p['spec'].get('nodeName')
        assert conditions['PodScheduled']['status']=='False' and conditions['PodScheduled']['reason']=='Unschedulable'
        assert 'Insufficient cpu' in conditions['PodScheduled']['message'] and not p['status'].get('containerStatuses')
        assert any(v['reason']=='FailedScheduling' and 'Insufficient cpu' in v['message'] for v in events)
        image_id='';ready=False
    else:
        assert case=='reasonable' and req==20 and p['status']['phase']=='Running'
        assert p['spec']['nodeName']=='engineering-lab-046-control-plane'
        assert conditions['PodScheduled']['status']=='True' and conditions['Ready']['status']=='True'
        status=p['status']['containerStatuses'][0];assert status['ready'] and status['restartCount']==0 and 'running' in status['state']
        assert any(v['reason']=='Scheduled' for v in events)
        logs=(d/label/'logs/stdout.txt').read_text().splitlines();assert logs==['{"event":"ready","work":"wait-signal"}']
        image_id=status['imageID'];assert 'sha256:' in image_id;ready=True
    t0,idle0=ticks(d/label/'cpu-before/stdout.txt');t1,idle1=ticks(d/label/'cpu-after/stdout.txt')
    assert t1>t0 and 0<=idle1-idle0<=t1-t0
    busy=1-(idle1-idle0)/(t1-t0)
    assert not json.loads((d/label/'after-delete/stdout.txt').read_bytes())['items']
    return {'case':case,'uid':uid,'request_millicpu':req,'allocatable_millicpu':alloc,'phase':p['status']['phase'],'ready':ready,'image_id':image_id,'vm_cpu_busy_fraction':busy,'passed':True}
