"""Actual stdlib HTTP exchanges: bytes, status, timing and failure metadata; no fake CLI exit."""
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from evidence import utc

class HTTPCapture:
    def __init__(self,evidence):
        self.evidence=evidence;self.lock=threading.Lock()
        evidence.data['http_requests']=[]

    def call(self,label,url,method='GET',body=None,timeout=15,max_bytes=1048576):
        assert label and all(c.isalnum() or c in '-_' for c in label)
        assert method in ['GET','POST'] and (body is None or isinstance(body,bytes))
        dest=self.evidence.dest/'http-captures'/label;dest.mkdir(parents=True,exist_ok=False)
        headers={'Content-Type':'application/json'} if body is not None else {}
        (dest/'request.json').write_text(json.dumps({'url':url,'method':method,'headers':headers,'body_bytes':len(body or b'')},indent=2)+'\n',encoding='utf-8',newline='\n')
        if body is not None:(dest/'request-body.bin').write_bytes(body)
        rec={'label':label,'url':url,'method':method,'started_utc':utc(),'completed':False,'status':None,'error':None}
        tick=time.monotonic();parts=[];size=0
        try:
            request=urllib.request.Request(url,data=body,method=method,headers=headers)
            try:response=urllib.request.urlopen(request,timeout=timeout)
            except urllib.error.HTTPError as exc:response=exc
            with response:
                rec.update(status=response.status,final_url=response.geturl(),response_headers=list(response.headers.items()))
                while True:
                    chunk=response.read(min(65536,max_bytes+1-size))
                    if not chunk:break
                    parts.append(chunk);size+=len(chunk)
                    if size>max_bytes:raise RuntimeError('HTTP body exceeded capture limit')
            if rec['status']!=200:raise RuntimeError('HTTP status '+str(rec['status']))
            rec['completed']=True
            return b''.join(parts)
        except Exception as exc:
            rec['error']=str(exc);raise
        finally:
            (dest/'response-body.bin').write_bytes(b''.join(parts))
            rec.update(ended_utc=utc(),elapsed_seconds=time.monotonic()-tick,response_bytes=size)
            (dest/'metadata.json').write_text(json.dumps(rec,indent=2)+'\n',encoding='utf-8',newline='\n')
            with self.lock:self.evidence.data['http_requests'].append(rec)
