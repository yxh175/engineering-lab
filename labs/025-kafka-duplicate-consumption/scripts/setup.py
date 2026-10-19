import json
import socket
import sys
import traceback
from pathlib import Path
from settings import LAB,ROOT,PYTHON,COMPOSE,MYSQL
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'docker-setup',[Path(__file__), LAB/'scripts/settings.py', LAB/'docker-compose.yml', LAB/'sql/schema.sql', LAB/'requirements.txt'],{'project':'engineering-lab-025','bind':'127.0.0.1:19025'})
failure=None
try:
    with socket.socket() as s:s.bind(('127.0.0.1',19025))
    assert not e.require('existing-containers',['docker','ps','-a','-q','--filter','label=com.docker.compose.project=engineering-lab-025']).strip()
    e.require('compose-config',COMPOSE+['config']);e.require('up',COMPOSE+['up','-d','--wait','--wait-timeout','120'],timeout=150)
    e.require('containers',['docker','inspect','lab025-kafka','lab025-mysql']);e.require('kafka-version',['docker','exec','lab025-kafka','/opt/kafka/bin/kafka-topics.sh','--version'])
    schema=(LAB/'sql/schema.sql').read_bytes();e.require('schema',MYSQL,stdin=schema)
    e.require('client-version',[str(PYTHON),'-c','import confluent_kafka as k,json; print(json.dumps({"client":k.version(),"librdkafka":k.libversion()}))'])
    e.require('broker-metadata',[str(PYTHON),'-c','from confluent_kafka.admin import AdminClient; import json; m=AdminClient({"bootstrap.servers":"127.0.0.1:19025"}).list_topics(timeout=10); print(json.dumps({"cluster_id":m.cluster_id,"brokers":{str(i):{"host":b.host,"port":b.port} for i,b in m.brokers.items()}}))'])
    e.require('kafka-logs',['docker','logs','lab025-kafka']);e.require('mysql-logs',['docker','logs','lab025-mysql'])
    e.data['trials'].append({'case':'isolated-kafka-mysql-environment','passed':True})
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
    e.data['trials'].append({'case':'isolated-kafka-mysql-environment','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
