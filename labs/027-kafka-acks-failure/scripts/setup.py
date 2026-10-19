import json
import os
import socket
import sys
import traceback
from pathlib import Path
from settings import LAB,ROOT,PYTHON,BROKER,COMPOSE,CONTAINERS
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'docker-setup',[Path(__file__), LAB/'scripts/settings.py', LAB/'docker-compose.yml', LAB/'requirements.txt'],{'project':'engineering-lab-027','brokers':3,'controllers':1,'host_ports':[19027,19028,19029]})
failure=None
try:
    assert os.name=='nt' and sys.version_info[:2]==(3,12)
    for port in [19027,19028,19029]:
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    assert not e.require('existing-containers',['docker','ps','-a','-q','--filter','label=com.docker.compose.project=engineering-lab-027']).strip()
    if not PYTHON.exists():
        e.require('create-venv',[sys.executable,'-m','venv',str(ROOT/'.work/kafka-venv')],timeout=120)
        e.require('install-client',[str(PYTHON),'-m','pip','install','--require-hashes','-r',str(LAB/'requirements.txt')],timeout=180)
    v=json.loads(e.require('client-version',[str(PYTHON),'-c','import confluent_kafka as k,sys,json;print(json.dumps({"python":sys.version,"client":k.version(),"librdkafka":k.libversion()}))']))
    assert v['client'][0]==v['librdkafka'][0]=='2.11.1'
    e.require('compose-config',COMPOSE+['config']);e.require('up',COMPOSE+['up','-d','--wait','--wait-timeout','180'],timeout=210)
    info=json.loads(e.require('containers',['docker','inspect',*CONTAINERS]));assert len(info)==4 and all(c['State']['Health']['Status']=='healthy' for c in info)
    code='from confluent_kafka.admin import AdminClient;import json;m=AdminClient({"bootstrap.servers":'+repr(BROKER)+'}).list_topics(timeout=15);print(json.dumps({"cluster_id":m.cluster_id,"brokers":{str(i):{"host":b.host,"port":b.port} for i,b in m.brokers.items()}}))'
    meta=json.loads(e.require('broker-metadata',[str(PYTHON),'-c',code]));assert set(meta['brokers'])=={'1','2','3'}
    assert meta['brokers']=={str(i):{'host':'127.0.0.1','port':19026+i} for i in range(1,4)}
    e.require('controller-quorum',['docker','exec','lab027-controller','/opt/kafka/bin/kafka-metadata-quorum.sh','--bootstrap-server','broker1:9092','describe','--status'])
    e.require('kafka-version',['docker','exec','lab027-broker1','/opt/kafka/bin/kafka-topics.sh','--version'])
    for name in CONTAINERS:e.require(name+'-logs',['docker','logs',name])
    e.data['trials'].append({'case':'isolated-three-broker-environment','passed':True})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'isolated-three-broker-environment','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
