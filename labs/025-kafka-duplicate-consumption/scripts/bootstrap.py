import hashlib
import json
import os
import sys
import traceback
import urllib.request
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'dependencies',[Path(__file__)],{'kafka_tag':'apache/kafka:3.9.1','python_client':'confluent-kafka==2.11.1','venv':'.work/kafka-venv','platform_wheel':'cp312-win_amd64'})
failure=None
try:
    e.require('docker-version',['docker','version']);e.require('pull-kafka',['docker','pull','apache/kafka:3.9.1'],timeout=600)
    inspect=json.loads(e.require('inspect-kafka',['docker','image','inspect','apache/kafka:3.9.1']))[0]
    assert inspect['RepoDigests'];(e.dest/'kafka-digest.json').write_text(json.dumps({'repo_digests':inspect['RepoDigests'],'image_id':inspect['Id']},indent=2)+'\n')
    venv=ROOT/'.work/kafka-venv';e.require('create-venv',[sys.executable,'-m','venv',str(venv)],timeout=120)
    python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    url='https://pypi.org/pypi/confluent-kafka/2.11.1/json';data=urllib.request.urlopen(url,timeout=60).read();(e.dest/'pypi-release.json').write_bytes(data)
    release=json.loads(data);items=[v for v in release['urls'] if v['filename']=='confluent_kafka-2.11.1-cp312-cp312-win_amd64.whl'];assert len(items)==1
    wheel=items[0];folder=LAB/'.work/wheels';folder.mkdir(parents=True,exist_ok=True);target=folder/wheel['filename']
    target.write_bytes(urllib.request.urlopen(wheel['url'],timeout=60).read());assert hashlib.sha256(target.read_bytes()).hexdigest()==wheel['digests']['sha256']
    (e.dest/'wheel-provenance.json').write_text(json.dumps({'metadata_url':url,'filename':wheel['filename'],'download_url':wheel['url'],'sha256':wheel['digests']['sha256'],'bytes':target.stat().st_size},indent=2)+'\n')
    e.require('install-wheel',[str(python),'-m','pip','install','--no-index',str(target)],timeout=120)
    e.require('pip-freeze',[str(python),'-m','pip','freeze'])
    e.require('client-version',[str(python),'-c','import sys,json,confluent_kafka as k; print(json.dumps({"python":sys.version,"client_version":k.version(),"librdkafka":k.libversion()}))'])
    e.data['trials'].append({'case':'isolated-dependency-acquisition','passed':True})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
    e.data['trials'].append({'case':'isolated-dependency-acquisition','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
