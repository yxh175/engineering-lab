import re
def verify(r,folder):
    mode=r['case'];assert mode in {'stop-only','stop-and-done','running-control'}
    assert r['pid']>0 and (r['go'],r['os'],r['arch'],r['gomaxprocs'])==('go1.25.4','windows','amd64',1)
    assert (r['ticker_interval_ms'],r['observe_window_ms'])==(20,100)
    assert r['ticks_before_action']>=1 and r['ticks_at_probe']>=r['ticks_before_action']
    assert r['joined_after_cleanup'] and r['ticks_after_join']>=r['ticks_at_probe']
    requested=mode=='stop-and-done';stopped=mode!='running-control'
    assert r['exit_requested_before_probe'] is requested and r['ticker_stopped_before_probe'] is stopped
    assert r['observed_done'] is requested
    probe=(folder/'probe.stack.txt').read_text(encoding='utf-8');joined=(folder/'joined.stack.txt').read_text(encoding='utf-8')
    assert 'main.worker(' not in joined
    if requested:
        assert 0<=r['observation_elapsed_ms']<100 and 'main.worker(' not in probe
    else:
        assert 100<=r['observation_elapsed_ms']<2000 and 'main.worker(' in probe
        if mode=='stop-only':
            assert re.search(r'goroutine \d+ \[select\]:\nmain\.worker\(',probe)
        else:assert r['ticks_at_probe']>r['ticks_before_action']
    return {'case':mode,'pid':r['pid'],'observed_done':r['observed_done'],
            'observation_elapsed_ms':r['observation_elapsed_ms'],'ticks_before_action':r['ticks_before_action'],
            'ticks_at_probe':r['ticks_at_probe'],'joined_after_cleanup':True,'passed':True}
