import json
from pathlib import Path
def stat(p):
    return {k:int(v) for k,v in (line.split() for line in p.read_text().splitlines())}
def verify(case,directory):
    d=Path(directory);r=json.loads((d/'report.json').read_bytes())
    assert r['threads']==2 and r['iterations']==[400000000,400000000] and len(r['results'])==2
    assert all(0<int(v)<2**64 for v in r['results']) and r['results'][0]!=r['results'][1]
    assert r['wall_ns']>0 and r['process_cpu_ns']>0
    quota={'half':50000,'one':100000,'two':200000}[case]
    assert (d/'cpu.max').read_text().strip()==f'{quota} 100000'
    assert (d/'memory.max').read_text().strip()=='134217728' and (d/'cpuset.cpus.effective').read_text().strip()
    before=stat(d/'before-cpu.stat');after=stat(d/'after-cpu.stat')
    delta={k:after[k]-before[k] for k in ['usage_usec','user_usec','system_usec','nr_periods','nr_throttled','throttled_usec']}
    assert all(v>=0 for v in delta.values()) and delta['usage_usec']>0 and delta['nr_throttled']<=delta['nr_periods']
    if case=='half':assert delta['nr_throttled']>0 and delta['throttled_usec']>0
    return {'case':case,'quota_cores':quota/100000,**r,**delta,'wall_ms':r['wall_ns']/1e6,'process_cpu_ms':r['process_cpu_ns']/1e6,'avg_cgroup_cores':delta['usage_usec']*1000/r['wall_ns'],'passed':True}
