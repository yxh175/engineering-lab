import json
from pathlib import Path
def verify(case,directory):
    d=Path(directory);r=json.loads((d/'report.json').read_bytes())
    assert r['case']==case and r['a_pid']!=r['b_pid']
    delivery=json.loads((d/'delivery.json').read_bytes());assert delivery==[{'topic':r['topic'],'partition':0,'offset':0,'key':'job','value':'42'}]
    frames={role:[json.loads(s) for s in (d/(role+'.stdout.jsonl')).read_text().splitlines()] for role in ['a','b']}
    for role in ['a','b']:
        f=frames[role];assert f[0]['event']=='boot' and f[-1]['event']=='closed'
        assert all(v['pid']==r[role+'_pid'] for v in f)
        conf=f[0]['config'];assert conf['max.poll.interval.ms']==2000 and conf['session.timeout.ms']==1000 and conf['group.protocol']=='classic'
        assert conf['enable.auto.commit'] is False and conf['enable.auto.offset.store'] is False
        assert json.loads((d/(role+'.process.json')).read_bytes())['exit_code']==0
    ar=next(v for v in frames['a'] if v['event']=='received');assert all(ar[k]==delivery[0][k] for k in delivery[0])
    ac=next(v for v in frames['a'] if v['event']=='commit');bc=next(v for v in frames['b'] if v['event']=='complete')
    assert ac['success']==r['a_commit_success'] and ac['error']==r['a_commit_error'] and bc['received']==r['b_received']
    initial=json.loads((d/'initial-group.json').read_bytes());new=json.loads((d/'new-owner-group.json').read_bytes())
    for g,client in [(initial,'lab047-a'),(new,'lab047-b')]:
        assert g['group']==r['group'] and len(g['members'])==1
        m=g['members'][0];assert m['client_id']==client and m['assignment']==[{'topic':r['topic'],'partition':0}]
    e=json.loads((d/'controller-events.json').read_bytes())
    live=next(v for v in e if v['event']=='a-liveness-at-new-owner')
    if case=='overdue':
        assert live['exit_code'] is None and r['a_commit_success'] is False and r['b_received']==[0]
        assert 'MAXPOLL' in (d/'a.stderr.txt').read_text()
        br=next(v for v in frames['b'] if v['event']=='received');assert all(br[k]==delivery[0][k] for k in delivery[0])
        gap=next(v['ns'] for v in e if v['event']=='end-no-poll')-next(v['ns'] for v in e if v['event']=='begin-no-poll')
        assert gap>=3000000000
        assert bc['parts'][0]['offset']==1 and ac['error'] is not None
    else:
        assert case=='bounded' and live['exit_code']==0 and r['a_commit_success'] and r['b_received']==[]
        assert 'MAXPOLL' not in (d/'a.stderr.txt').read_text()
        assert ac['parts']==[{'topic':r['topic'],'partition':0,'offset':1,'error':None}]
        gap=ac['ns']-next(v['ns'] for v in frames['a'] if v['event']=='processing');assert 200000000<=gap<2000000000
    final=json.loads((d/'final-offset.json').read_bytes());assert final=={'committed':1,'low':0,'high':1} and r['committed']==1
    assert not any(v['event']=='cleanup-kill' for v in e)
    return {**r,'work_to_commit_ms':(ac['ns']-next(v['ns'] for v in frames['a'] if v['event']=='processing'))/1e6,'a_alive_after_transfer':live['exit_code'] is None,'passed':True}
