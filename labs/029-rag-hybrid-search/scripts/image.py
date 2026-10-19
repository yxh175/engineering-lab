import json,sys,traceback
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence
e=Evidence(LAB,'image-identity',[Path(__file__)],{'tag':'pgvector/pgvector:0.8.2-pg17','cached_image_only':True});failure=None
try:
    d=json.loads(e.require('image',['docker','image','inspect','pgvector/pgvector:0.8.2-pg17']))[0];assert d['Architecture']=='amd64' and d['Os']=='linux'
    names=[v for v in d['RepoDigests'] if v.startswith('pgvector/pgvector@sha256:')];assert len(names)==1
    e.data['trials'].append({'case':'cached-official-image-identified','passed':True,'image_id':d['Id'],'digest':names[0]});print(names[0])
except BaseException as exc:
    failure=str(exc);(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'cached-official-image-identified','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
