from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
COMPOSE=['docker','compose','--project-name','engineering-lab-029','-f',str(LAB/'docker-compose.yml')]
PSQL=['docker','exec','-i','-e','PGCLIENTENCODING=UTF8','lab029-postgres','psql','-X','-q','-t','-A','-v','ON_ERROR_STOP=1','-U','lab029','-d','lab029']
