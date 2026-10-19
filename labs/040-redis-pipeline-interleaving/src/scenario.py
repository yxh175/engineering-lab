import argparse
import json
import time
from pathlib import Path
from resp import Connection
from verify import verify
a=argparse.ArgumentParser();a.add_argument('--port',type=int,required=True);a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
assert args.case in ['split-pipeline','multi','mset-control'];args.out.mkdir(parents=True,exist_ok=False)
events=[];connections=[];failure=None
try:
    w=Connection('writer',args.port,args.out,events);connections.append(w);o=Connection('observer',args.port,args.out,events);connections.append(o)
    assert w.command('FLUSHDB')=='OK';assert w.command('MSET','left','0','right','0')=='OK'
    assert o.command('MGET','left','right')==['0','0']
    if args.case=='split-pipeline':
        w.send(('SET','left','1'));deadline=time.monotonic()+5
        while True:
            middle=o.command('MGET','left','right')
            if middle==['1','0']:break
            assert middle==['0','0'] and time.monotonic()<deadline
        w.send(('SET','right','1'));assert w.receive()=='OK' and w.receive()=='OK'
    elif args.case=='multi':
        w.send(('MULTI',),('SET','left','1'));assert w.receive()=='OK' and w.receive()=='QUEUED'
        middle=o.command('MGET','left','right');assert middle==['0','0']
        w.send(('SET','right','1'),('EXEC',));assert w.receive()=='QUEUED' and w.receive()==['OK','OK']
    else:
        middle=o.command('MGET','left','right');assert middle==['0','0']
        assert w.command('MSET','left','1','right','1')=='OK'
    final=o.command('MGET','left','right');assert final==['1','1']
except Exception as exc:failure=repr(exc);raise
finally:
    for c in connections:c.close()
    (args.out/'events.json').write_text(json.dumps(events,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.out/'status.json').write_text(json.dumps({'case':args.case,'failure':failure})+'\n',encoding='utf-8',newline='\n')
print(json.dumps(verify(args.case,args.out)))
