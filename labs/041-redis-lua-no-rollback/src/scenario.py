import argparse
import json
from pathlib import Path
from resp import Connection
from verify import verify
LAB=Path(__file__).resolve().parents[1]
a=argparse.ArgumentParser();a.add_argument('--port',type=int,required=True);a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
assert args.case in ['write-then-error','validate-type','normal-list'];args.out.mkdir(parents=True,exist_ok=False)
events=[];c=None;failure=None
def snapshot():
    keys=c.command('KEYS','*');assert sorted(keys)==['after','destination','state']
    kind=c.command('TYPE','destination')
    values=c.command('MGET','state','after')
    dest=c.command('LRANGE','destination','0','-1') if kind=='list' else c.command('GET','destination')
    return {'keys':sorted(keys),'type':kind,'state_after':values,'destination':dest}
try:
    c=Connection('client',args.port,args.out,events);assert c.command('FLUSHDB')=='OK'
    assert c.command('MSET','state','0','after','0')=='OK'
    if args.case=='normal-list':assert c.command('RPUSH','destination','old')==1
    else:assert c.command('SET','destination','wrong')=='OK'
    before=snapshot();script=(LAB/'src'/('bad.lua' if args.case=='write-then-error' else 'good.lua')).read_text(encoding='utf-8')
    reply=c.command('EVAL',script,'3','state','destination','after','payload')
    after=snapshot()
    (args.out/'snapshots.json').write_text(json.dumps({'before':before,'reply':reply,'after':after},indent=2)+'\n',encoding='utf-8',newline='\n')
except Exception as exc:failure=repr(exc);raise
finally:
    if c:c.close()
    (args.out/'events.json').write_text(json.dumps(events,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.out/'status.json').write_text(json.dumps({'case':args.case,'failure':failure})+'\n',encoding='utf-8',newline='\n')
print(json.dumps(verify(args.case,args.out)))
