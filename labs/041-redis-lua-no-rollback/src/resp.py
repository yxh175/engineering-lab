import io
import json
import socket
import time
def pack(args):
    values=[str(x).encode() for x in args]
    return b'*'+str(len(values)).encode()+b'\r\n'+b''.join(b'$'+str(len(v)).encode()+b'\r\n'+v+b'\r\n' for v in values)
def parse(stream,record=lambda b:None):
    line=stream.readline();assert line and line.endswith(b'\r\n');record(line);body=line[1:-2];tag=line[:1]
    if tag==b'+':return body.decode()
    if tag==b'-':return {'error':body.decode()}
    if tag==b':':return int(body)
    if tag==b'$':
        n=int(body)
        if n==-1:return None
        b=stream.read(n+2);assert len(b)==n+2 and b.endswith(b'\r\n');record(b);return b[:-2].decode()
    if tag==b'*':
        n=int(body)
        return None if n==-1 else [parse(stream,record) for _ in range(n)]
    raise AssertionError('RESP2 tag')
def decode_all(data):
    s=io.BytesIO(data);values=[]
    while s.tell()<len(data):values.append(parse(s))
    return values
class Connection:
    def __init__(self,name,port,dest,events):
        self.name=name;self.dest=dest;self.events=events;self.requests=[];self.responses=[]
        self.socket=socket.create_connection(('127.0.0.1',port),timeout=5);self.socket.settimeout(5);self.stream=self.socket.makefile('rb')
    def send(self,*commands):
        b=b''.join(pack(c) for c in commands);self.requests.append(b)
        self.events.append({'ns':time.perf_counter_ns(),'kind':'send','connection':self.name,'commands':[list(c) for c in commands]})
        self.socket.sendall(b)
    def receive(self):
        value=parse(self.stream,self.responses.append)
        self.events.append({'ns':time.perf_counter_ns(),'kind':'recv','connection':self.name,'value':value});return value
    def command(self,*args):self.send(args);return self.receive()
    def close(self):
        self.stream.close();self.socket.close()
        (self.dest/(self.name+'.requests.bin')).write_bytes(b''.join(self.requests))
        (self.dest/(self.name+'.responses.bin')).write_bytes(b''.join(self.responses))
