import os
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
PYTHON=ROOT/'.work/kafka-venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
BROKER='127.0.0.1:19025'
MYSQL=['docker','exec','-i','lab025-mysql','mysql','-uroot','-plab025-password','--batch','--raw','--skip-column-names','lab025']
COMPOSE=['docker','compose','-p','engineering-lab-025','-f',str(LAB/'docker-compose.yml')]
def consumer_config(group):
    return {'bootstrap.servers':BROKER,'group.id':group,'enable.auto.commit':False,'enable.auto.offset.store':False,'auto.offset.reset':'earliest','session.timeout.ms':6000,'max.poll.interval.ms':60000,'client.id':group+'-'+str(os.getpid())}
