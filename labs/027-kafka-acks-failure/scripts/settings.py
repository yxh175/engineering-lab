from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
PYTHON=ROOT/'.work/kafka-venv/Scripts/python.exe'
BROKER='127.0.0.1:19027,127.0.0.1:19028,127.0.0.1:19029'
COMPOSE=['docker','compose','-p','engineering-lab-027','-f',str(LAB/'docker-compose.yml')]
CONTAINERS=['lab027-controller','lab027-broker1','lab027-broker2','lab027-broker3']
