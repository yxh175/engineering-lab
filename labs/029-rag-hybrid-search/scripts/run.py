import json,math,struct,sys,traceback
from pathlib import Path
from settings import LAB,ROOT,PSQL
sys.path.insert(0,str(ROOT/'shared/scripts'));sys.path.insert(0,str(LAB/'src'))
from evidence import Evidence,sha
from search import inputs,init_sql,query_sql,terms
setup=[p for p in sorted((LAB/'results').glob('*-postgres-setup/manifest.json')) if json.loads(p.read_text(encoding='utf-8'))['all_passed']][-1]
e=Evidence(LAB,'hybrid-search',[Path(__file__), LAB/'scripts/settings.py', LAB/'src/search.py', LAB/'input-spec.json', LAB/'docker-compose.yml'],{'trials_per_case':10,'setup_manifest':setup.relative_to(ROOT).as_posix(),'setup_manifest_sha256':sha(setup),'rrf_k':60,'candidates_per_path':10,'source_chunk_policy':'char384-overlap0'});failure=None
def validate_db(rows,chunks,cv):
    lookup={c['chunk_id']:(c,v) for c,v in zip(chunks,cv)};assert len(rows)==len(lookup)==16
    for row in rows:
        c,v=lookup[row['chunk_id']];assert all(row[n]==c[n] for n in ['doc_id','start','end']) and row['content']==c['text']
        actual=json.loads(row['embedding']);assert len(actual)==512 and all(struct.pack('<f',a)==struct.pack('<f',b) for a,b in zip(actual,v))
def metrics(qs,rs,key,chunks):
    lookup={c['chunk_id']:c for c in chunks};values=[]
    for q,r in zip(qs,rs):
        ranking=r[key];rel=set(q['relevant_doc_ids']);first=next((i for i,v in enumerate(ranking[:10],1) if lookup[v['chunk_id']]['doc_id'] in rel),None)
        recalls={str(k):len({lookup[v['chunk_id']]['doc_id'] for v in ranking[:k]}&rel)/len(rel) for k in [1,3,5]}
        ev=q['evidence'][0];complete=any(lookup[v['chunk_id']]['doc_id']==ev['doc_id'] and lookup[v['chunk_id']]['start']<=ev['start'] and lookup[v['chunk_id']]['end']>=ev['end'] for v in ranking[:3])
        values.append({'query_id':q['query_id'],'doc_recall':recalls,'mrr10':1/first if first else 0,'first_relevant_rank10':first,'complete_evidence3':complete,'top3_chunk_ids':[v['chunk_id'] for v in ranking[:3]]})
    return values
try:
    spec,chunks,qs,cv,qv=inputs();(e.dest/'borrowed-inputs.json').write_text(json.dumps(spec,indent=2)+'\n',encoding='utf-8',newline='\n');lookup={c['chunk_id']:v for c,v in zip(chunks,cv)}
    native=json.loads((ROOT/spec['files']['chunks']['path']).with_name('per-query.json').read_text(encoding='utf-8'))
    e.require('container-before',['docker','inspect','lab029-postgres'])
    mappings=[{'query_id':q['query_id'],'query':q['query'],'identifier_terms':terms(q['query'])[0],'chinese_bigram_terms':terms(q['query'])[1]} for q in qs]
    (e.dest/'query-term-map.json').write_text(json.dumps(mappings,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    for roundnum in range(1,11):
        label=f'round-{roundnum:02d}';sql=init_sql()+"SELECT json_build_object('backend_pid',pg_backend_pid(),'version',version(),'transaction_time',now());\n"+''.join(query_sql(q,v) for q,v in zip(qs,qv))
        (e.dest/(label+'.sql')).write_text(sql,encoding='utf-8',newline='\n')
        raw=e.require(label,PSQL,stdin=sql.encode('utf-8'),timeout=45);lines=raw.decode('utf-8').splitlines();assert len(lines)==27
        info=json.loads(lines[0]);db=json.loads(lines[1]);connection=json.loads(lines[2]);rs=[json.loads(v) for v in lines[3:]];validate_db(db,chunks,cv)
        assert info['server_version'].startswith('17.') and info['vector_version']=='0.8.2' and info['rows']==16 and len(info['indexes'])==1 and 'btree' in info['indexes'][0]
        for qi,(q,r) in enumerate(zip(qs,rs)):
            assert r['query_id']==q['query_id'] and [v['rank'] for v in r['vector']]==list(range(1,17)) and [v['chunk_id'] for v in r['vector']]==[v['chunk_id'] for v in native[qi]['ranking']]
            for v in r['vector']:
                c=lookup[v['chunk_id']];expected=1-math.fsum(a*b for a,b in zip(qv[qi],c))/(math.sqrt(math.fsum(x*x for x in qv[qi]))*math.sqrt(math.fsum(x*x for x in c)))
                assert abs(v['distance']-expected)<2e-6
            lexical=r['lexical'];assert [v['rank'] for v in lexical]==list(range(1,len(lexical)+1)) and sorted(lexical,key=lambda v:(-v['score'],v['chunk_id']))==lexical
            candidate={}
            for side in ['vector','lexical']:
                for row in r[side][:10]:
                    v=candidate.setdefault(row['chunk_id'],{'vector_rank':None,'lexical_rank':None,'score':0});v[side+'_rank']=row['rank'];v['score']+=1/(60+row['rank'])
            expected=sorted(candidate,key=lambda cid:(-candidate[cid]['score'],cid));assert [v['chunk_id'] for v in r['rrf']]==expected
            for row in r['rrf']:
                v=candidate[row['chunk_id']];assert row['vector_rank']==v['vector_rank'] and row['lexical_rank']==v['lexical_rank'] and abs(row['score']-v['score'])<1e-14
        allmetrics={case:metrics(qs,rs,case,chunks) for case in ['vector','lexical','rrf']}
        (e.dest/(label+'-metrics.json')).write_text(json.dumps(allmetrics,indent=2)+'\n',encoding='utf-8',newline='\n')
        for case,values in allmetrics.items():
            trial={'case':case,'round':roundnum,'backend_pid':connection['backend_pid'],'doc_recall1':sum(v['doc_recall']['1'] for v in values)/24,'doc_recall3':sum(v['doc_recall']['3'] for v in values)/24,'doc_recall5':sum(v['doc_recall']['5'] for v in values)/24,'mrr10':sum(v['mrr10'] for v in values)/24,'complete_evidence3':sum(v['complete_evidence3'] for v in values)/24,'passed':True};e.data['trials'].append(trial)
            print(f'{label} {case}: Recall3 {trial["doc_recall3"]:.4f}, MRR10 {trial["mrr10"]:.4f}',flush=True)
    sql='EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query_sql(qs[0],qv[0]);(e.dest/'explain.sql').write_text(sql,encoding='utf-8',newline='\n');e.require('explain',PSQL,stdin=sql.encode('utf-8'),timeout=30)
    e.require('container-after',['docker','inspect','lab029-postgres']);e.require('logs',['docker','logs','lab029-postgres'])
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}';(e.dest/'runner-exception.txt').write_text(traceback.format_exc(),encoding='utf-8');e.data['trials'].append({'case':'incomplete-round','passed':False})
raise SystemExit(0 if e.seal(failure) else 1)
