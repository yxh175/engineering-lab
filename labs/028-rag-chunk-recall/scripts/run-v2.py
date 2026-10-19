import json,sys,traceback
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1];PY=ROOT/'.work/rag-venv/Scripts/python.exe'
sys.path.insert(0,str(ROOT/'shared/scripts'))
from evidence import Evidence,sha
expected_cache=str(ROOT/'.work/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620')
setups=[p for p in sorted((LAB/'results').glob('*-model-bootstrap/manifest.json')) if json.loads(p.read_text(encoding='utf-8'))['all_passed'] and json.loads(p.read_text(encoding='utf-8'))['parameters']['cache']==expected_cache]
assert setups,'Run setup.py in this checkout first; published absolute cache is not reused across checkouts'
setup=setups[-1]
e=Evidence(LAB,'chunk-retrieval',[Path(__file__), LAB/'src/retrieve.py', LAB/'src/build_fixture.py', LAB/'data/corpus.json', LAB/'data/qrels.json', LAB/'requirements.txt'],{'trials_per_case':10,'setup_manifest':setup.relative_to(ROOT).as_posix(),'setup_manifest_sha256':sha(setup),'model_revision':'7999e1d3359715c523056ef9478215996d62a620','query_count':24,'document_count':16})
failure=None
try:
    for i in range(1,11):
        out=e.dest/f'round-{i:02d}'
        e.require(f'worker-{i:02d}',[str(PY),str(LAB/'src/retrieve.py'),'--out',str(out),'--round',str(i),'--bootstrap',str(setup)],timeout=180)
        data=json.loads((out/'worker.json').read_text(encoding='utf-8'));assert len(data['summary'])==4 and not data['socket_connection_attempts']
        for row in data['summary']:e.data['trials'].append({**row,'worker_pid':data['pid'],'passed':True})
        print(f'round {i:02d}: four real CPU embedding/retrieval cases PASS',flush=True)
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'worker-incomplete','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
