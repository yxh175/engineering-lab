import argparse
import json
from pathlib import Path
from resp import Connection
from verify import verify,payload
a=argparse.ArgumentParser();a.add_argument('--port',type=int,required=True);a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
assert args.case in ['noeviction-small','lru-small','capacity-control'];args.out.mkdir(parents=True,exist_ok=False)
events=[];c=None;failure=None
try:
    c=Connection('client',args.port,args.out,events);assert c.command('FLUSHDB')=='OK'
    assert c.command('SET','lab042:sentinel','important')=='OK';assert c.command('PTTL','lab042:sentinel')==-1
    config=c.command('CONFIG','GET','maxmemory','maxmemory-policy')
    before_memory=c.command('INFO','memory');before_stats=c.command('INFO','stats')
    replies=[]
    for i in range(200):replies.append(c.command('SET',f'lab042:k{i:04}',payload(i)))
    after_memory=c.command('INFO','memory');after_stats=c.command('INFO','stats')
    keys=sorted(c.command('KEYS','lab042:*'));values=c.command('MGET',*keys) if keys else []
    ttl=c.command('PTTL','lab042:sentinel')
    (args.out/'observations.json').write_text(json.dumps({'config':config,'set_replies':replies,'keys':keys,'sentinel_pttl':ttl},indent=2)+'\n',encoding='utf-8',newline='\n')
except Exception as exc:failure=repr(exc);raise
finally:
    if c:c.close()
    (args.out/'events.json').write_text(json.dumps(events,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.out/'status.json').write_text(json.dumps({'case':args.case,'failure':failure})+'\n',encoding='utf-8',newline='\n')
print(json.dumps(verify(args.case,args.out)))
