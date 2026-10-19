"""Synchronous RESP2 client with exact request/response streams and byte offsets.

One caller, one outstanding request. Intended for isolated experiments, not a
production connection pool. SQL/origin work is owned by the calling experiment.
"""
import json
import socket
import time
from evidence import utc

class RedisSession:
    def __init__(self,evidence,name,host,port):
        self.directory=evidence.dest/'redis-sessions'/name
        self.directory.mkdir(parents=True,exist_ok=False)
        self.sock=socket.create_connection((host,port),timeout=5)
        self.reader=self.sock.makefile('rb',buffering=0)
        self.requests=(self.directory/'requests.bin').open('wb')
        self.responses=(self.directory/'responses.bin').open('wb')
        self.commands=(self.directory/'commands.jsonl').open('w',encoding='utf-8',newline='\n')
        self.record={'name':name,'host':host,'port':port,'started_utc':utc(),'commands':0,'errors':0}
        self.closed=False

    def _read(self,size):
        parts=[];left=size
        while left:
            b=self.reader.read(left)
            if not b:raise EOFError('Redis EOF in response')
            self.responses.write(b);parts.append(b);left-=len(b)
        return b''.join(parts)

    def _line(self):
        b=self.reader.readline();self.responses.write(b)
        if not b.endswith(b'\r\n'):raise EOFError('Redis EOF in response line')
        return b[:-2]

    def _response(self):
        prefix=self._read(1);line=self._line()
        if prefix==b'+':return line
        if prefix==b'-':raise RuntimeError('Redis error: '+line.decode(errors='replace'))
        if prefix==b':':return int(line)
        if prefix==b'$':
            size=int(line)
            if size==-1:return None
            assert size>=0
            data=self._read(size);assert self._read(2)==b'\r\n';return data
        if prefix==b'*':
            count=int(line)
            if count==-1:return None
            assert count>=0;return [self._response() for _ in range(count)]
        raise RuntimeError('Unsupported RESP2 prefix '+repr(prefix))

    def call(self,label,*args):
        assert not self.closed
        encoded=[a if isinstance(a,bytes) else str(a).encode() for a in args]
        wire=b'*'+str(len(encoded)).encode()+b'\r\n'+b''.join(b'$'+str(len(a)).encode()+b'\r\n'+a+b'\r\n' for a in encoded)
        rec={'label':label,'args':[a.decode('utf-8') for a in encoded],'started_utc':utc(),
             'request_start':self.requests.tell(),'response_start':self.responses.tell(),'completed':False}
        tick=time.monotonic()
        try:
            self.requests.write(wire);self.requests.flush();self.sock.sendall(wire)
            value=self._response();rec['completed']=True;return value
        except Exception as exc:
            self.record['errors']+=1;rec['error']=str(exc);raise
        finally:
            self.responses.flush()
            rec.update(ended_utc=utc(),elapsed_seconds=time.monotonic()-tick,
                       request_end=self.requests.tell(),response_end=self.responses.tell())
            self.commands.write(json.dumps(rec,ensure_ascii=False)+'\n');self.commands.flush()
            self.record['commands']+=1

    def close(self):
        if self.closed:return
        self.closed=True
        self.reader.close();self.sock.close()
        for f in [self.requests,self.responses,self.commands]:f.close()
        self.record.update(ended_utc=utc(),closed=True)
        (self.directory/'session.json').write_text(json.dumps(self.record,indent=2)+'\n',encoding='utf-8',newline='\n')
