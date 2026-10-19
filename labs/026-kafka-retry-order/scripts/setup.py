import json
import os
import socket
import sys
import traceback
from pathlib import Path
from settings import LAB,ROOT,PYTHON,COMPOSE,MYSQL
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'docker-setup',[Path(__file__), LAB/'scripts/settings.py', LAB/'docker-compose.yml', LAB/'requirements.txt', LAB/'sql/schema.sql'],{'project':'engineering-lab-026','bind':'127.0.0.1:19026'})
failure=None
try:
    assert os.name=='nt' and sys.version_info[:2]==(3,12)
    with socket.socket() as s:s.bind(('127.0.0.1',19026))
    assert not e.require('existing-containers',['docker','ps','-a','-q','--filter','label=com.docker.compose.project=engineering-lab-026']).strip()
    if not PYTHON.exists():
        e.require('create-venv',[sys.executable,'-m','venv',str(ROOT/'.work/kafka-venv')],timeout=120)
        e.require('install-client',[str(PYTHON),'-m','pip','install','--require-hashes','-r',str(LAB/'requirements.txt')],timeout=180)
    v=json.loads(e.require('client-version',[str(PYTHON),'-c','import confluent_kafka as k,sys,json;print(json.dumps({"python":sys.version,"client":k.version(),"librdkafka":k.libversion()}))']))
    assert v['client'][0]==v['librdkafka'][0]=='2.11.1'
    e.require('pip-freeze',[str(PYTHON),'-m','pip','freeze'])
    e.require('compose-config',COMPOSE+['config']);e.require('up',COMPOSE+['up','-d','--wait','--wait-timeout','120'],timeout=150)
    e.require('containers',['docker','inspect','lab026-kafka','lab026-mysql']);e.require('kafka-version',['docker','exec','lab026-kafka','/opt/kafka/bin/kafka-topics.sh','--version'])
    e.require('schema',MYSQL,stdin=(LAB/'sql/schema.sql').read_bytes());e.require('kafka-logs',['docker','logs','lab026-kafka']);e.require('mysql-logs',['docker','logs','lab026-mysql'])
    e.data['trials'].append({'case':'isolated-environment','passed':True})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'isolated-environment','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
