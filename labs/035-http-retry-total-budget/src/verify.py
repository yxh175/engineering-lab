from collections import Counter
def verify(r):
    mode=r['case'];assert mode in {'attempt-only','shared-budget','normal'}
    assert r['pid']>0 and (r['go'],r['os'],r['arch'])==('go1.25.4','windows','amd64')
    assert r['listener'].startswith('127.0.0.1:') and r['server_joined']
    assert (r['attempt_timeout_ms'],r['total_budget_ms'],r['max_attempts'],r['backoff_ms'])==(200,250,3,30)
    normal=mode=='normal';shared=mode=='shared-budget'
    assert r['server_delay_ms']==(30 if normal else 120)
    a=r['attempts'];events=r['events']
    assert [v['seq'] for v in events]==list(range(1,len(events)+1))
    assert all(events[i]['at_ms']<=events[i+1]['at_ms'] for i in range(len(events)-1))
    count=1 if normal else 2 if shared else 3
    assert len(a)==count and [v['attempt'] for v in a]==list(range(1,count+1))
    for v in a:
        i=v['attempt'];assert v['url']==f"http://{r['listener']}/work?attempt={i}"
        assert v['end_ms']>=v['start_ms'] and abs(v['elapsed_ms']-(v['end_ms']-v['start_ms']))<1e-8
        assert not v['read_error'] and not v['close_error']
        es=[e for e in events if e.get('attempt')==i]
        assert Counter(e['event'] for e in es)=={'client_attempt_start':1,'client_attempt_end':1,'server_enter':1,('server_cancel' if shared and i==2 else 'server_response'):1}
        entered=next(e for e in es if e['event']=='server_enter')
        assert entered['method']=='GET' and entered['proto']=='HTTP/1.1' and entered['remote'].startswith('127.0.0.1:')
        start=next(e for e in es if e['event']=='client_attempt_start');end=next(e for e in es if e['event']=='client_attempt_end')
        assert abs(start['deadline_ms']-v['deadline_ms'])<1e-8 and end['status']==v['status'] and end['deadline_exceeded']==v['deadline_exceeded']
        assert start['at_ms']<=entered['at_ms']<=end['at_ms']
        if shared and i==2:
            assert v['status']==0 and v['body']=='' and v['deadline_exceeded'] and v['error'] and v['context_error']=='context deadline exceeded'
            assert next(e for e in es if e['event']=='server_cancel')['error']=='context canceled'
            assert abs(v['deadline_ms']-(r['operation_start_ms']+250))<2
        else:
            status=200 if normal else 503;body='{"value":42}\n' if normal else 'unavailable\n'
            assert v['status']==status and v['body']==body and not v['error'] and not v['context_error'] and not v['deadline_exceeded']
            response=next(e for e in es if e['event']=='server_response')
            assert response['status']==status and response['bytes']==len(body) and not response['write_error']
            assert entered['at_ms']<=response['at_ms']<=end['at_ms']
            assert 198<=v['deadline_ms']-v['start_ms']<=202
    assert r['business_success'] is normal
    assert r['parent_error']==('context deadline exceeded' if shared else '')
    elapsed=r['operation_elapsed_ms']
    if shared:assert 230<=elapsed<350
    elif normal:assert 25<=elapsed<200
    else:assert 380<=elapsed<1500
    assert Counter(e['event'] for e in events)['backoff_start']==(0 if normal else 1 if shared else 2)
    assert Counter(e['event'] for e in events)['backoff_end']==(0 if normal else 1 if shared else 2)
    return {'case':mode,'pid':r['pid'],'attempts':count,'elapsed_ms':elapsed,'business_success':normal,
            'server_cancellations':sum(e['event']=='server_cancel' for e in events),'server_responses':sum(e['event']=='server_response' for e in events),'passed':True}
