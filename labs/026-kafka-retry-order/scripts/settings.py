import os
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
PYTHON=ROOT/'.work/kafka-venv/Scripts/python.exe';BROKER='127.0.0.1:19026'
MYSQL=['docker','exec','-i','lab026-mysql','mysql','-uroot','-plab026-password','--batch','--raw','--skip-column-names','lab026']
COMPOSE=['docker','compose','-p','engineering-lab-026','-f',str(LAB/'docker-compose.yml')]
def config(group):return {'bootstrap.servers':BROKER,'group.id':group,'client.id':group+'-'+str(os.getpid()),'enable.auto.commit':False,'enable.auto.offset.store':False,'auto.offset.reset':'earliest','session.timeout.ms':6000,'max.poll.interval.ms':60000}
