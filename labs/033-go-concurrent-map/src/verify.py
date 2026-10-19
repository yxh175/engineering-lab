import hashlib
import json
def verify(mode,code,out,err,folder):
    events=[json.loads(l) for l in out.decode().splitlines()]
    s=events[0];writers=1 if mode=='single-writer' else 4
    assert s['event']=='start' and s['case']==mode and s['pid']>0
    assert (s['go'],s['os'],s['arch'],s['gomaxprocs'],s['writers'],s['total'])==('go1.25.4','windows','amd64',2,writers,100000)
    assert events[1]=={'event':'barrier','ready_writers':writers}
    fatal=mode=='bad'
    if fatal:
        assert code==2 and len(events)==2 and not (folder/'entries.tsv').exists()
        text=err.decode();assert 'fatal error: concurrent map writes' in text and 'main.main.func1' in text
        entries=0;digest=None
    else:
        assert code==0 and not err and len(events)==3 and events[2]['event']=='completed'
        raw=(folder/'entries.tsv').read_bytes()
        expected=b''.join(f'{i}\t{i*3+7}\n'.encode() for i in range(100000))
        assert raw==expected
        digest=hashlib.sha256(raw).hexdigest();entries=100000
        assert events[2]['entries']==entries and events[2]['writers_completed']==writers and events[2]['entries_sha256']==digest
    return {'case':mode,'pid':s['pid'],'writers':writers,'exit_code':code,'fatal':fatal,
            'recovered':False,'entries':entries,'entries_sha256':digest,'passed':True}
