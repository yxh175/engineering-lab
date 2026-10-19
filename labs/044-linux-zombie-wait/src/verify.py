import json
import re
from pathlib import Path

def verify(case, directory):
    d=Path(directory);r=json.loads((d/'report.json').read_bytes())
    assert r['case']==case and r['child']>r['parent']>1
    expected={'unreaped':'Z','immediate-wait':'-','running-control':'S'}[case]
    assert r['before']==expected and r['after']=='-'
    for phase,state in [('before',expected),('after','-')]:
        stat=(d/f'{phase}-stat.txt').read_text();status=(d/f'{phase}-status.txt').read_text()
        lines=(d/f'{phase}-ps.txt').read_text().splitlines()
        assert lines[0].split()==['PID','PPID','STAT','COMMAND','COMMAND']
        if state=='-':
            assert stat==status=='OPEN_ERROR errno=2\n' and len(lines)==1 and r[phase+'_ps_exit']==1
        else:
            match=re.fullmatch(r'(\d+) \(lab044-child\) ([A-Z]) (\d+) (.+)\n',stat)
            assert match and (int(match[1]),match[2],int(match[3]))==(r['child'],state,r['parent'])
            assert re.search(r'^State:\s+'+state+r'\b',status,re.M)
            assert len(lines)==2 and r[phase+'_ps_exit']==0
            fields=lines[1].split();assert (int(fields[0]),int(fields[1]),fields[2][0],fields[3])==(r['child'],r['parent'],state,'lab044-child')
    assert r['wait_pid']==r['child'] and r['wait_status']==42<<8 and r['exited'] and r['exit_status']==42
    assert r['second_wait']==-1 and r['second_errno']==10
    assert (d/'cpu.max').read_text().strip()=='100000 100000'
    assert (d/'memory.max').read_text().strip()=='134217728'
    return {**r,'passed':True}
