import argparse
import json
import time
from pathlib import Path
from resp import Connection
from verify import verify,clients
a=argparse.ArgumentParser();a.add_argument('--port',type=int,required=True);a.add_argument('--case',required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
assert args.case in ['shared','separate','nonblocking-control'];args.out.mkdir(parents=True,exist_ok=False)
events=[];connections=[];failure=None
try:
    w=Connection('writer',args.port,args.out,events);connections.append(w);o=Connection('observer',args.port,args.out,events);connections.append(o)
    cid=w.command('CLIENT','ID');assert isinstance(cid,int)
    assert o.command('FLUSHDB')=='OK' and o.command('SET','answer','42')=='OK'
    if args.case=='nonblocking-control':
        w.send(('LPOP','queue'),('GET','answer'));assert w.receive() is None and w.receive()=='42'
    else:
        if args.case=='shared':w.send(('BLPOP','queue','0.4'),('GET','answer'))
        else:w.send(('BLPOP','queue','0.4'))
        deadline=time.monotonic()+1
        while True:
            state=clients(o.command('CLIENT','LIST'))[cid]
            if 'b' in state['flags'] and state['cmd']=='blpop':break
            assert time.monotonic()<deadline
        if args.case=='separate':
            assert o.command('GET','answer')=='42'
            after=clients(o.command('CLIENT','LIST'))[cid];assert 'b' in after['flags'] and after['cmd']=='blpop'
        assert w.receive() is None
        if args.case=='shared':assert w.receive()=='42'
except Exception as exc:failure=repr(exc);raise
finally:
    for c in connections:c.close()
    (args.out/'events.json').write_text(json.dumps(events,indent=2)+'\n',encoding='utf-8',newline='\n')
    (args.out/'status.json').write_text(json.dumps({'case':args.case,'failure':failure})+'\n',encoding='utf-8',newline='\n')
print(json.dumps(verify(args.case,args.out)))
