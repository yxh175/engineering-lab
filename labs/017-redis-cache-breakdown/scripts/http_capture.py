"""Capture actual HTTP response body for the controlled local origin."""
import argparse
import sys
import urllib.error
import urllib.request
p=argparse.ArgumentParser();p.add_argument('url');p.add_argument('--method',default='GET');args=p.parse_args()
data=sys.stdin.buffer.read() if args.method=='POST' else None
request=urllib.request.Request(args.url,data=data,method=args.method,headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(request,timeout=15) as response:
        body=response.read(65537);assert len(body)<=65536
        sys.stdout.buffer.write(body)
        assert response.status==200
except urllib.error.HTTPError as exc:
    sys.stdout.buffer.write(exc.read());print(str(exc),file=sys.stderr);raise SystemExit(1)
