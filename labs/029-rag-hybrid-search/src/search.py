"""Read real frozen float32 arrays; actual SQL full-text and pgvector query plans."""
import ast,hashlib,json,math,re,struct
from pathlib import Path
LAB=Path(__file__).resolve().parents[1];ROOT=LAB.parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def array(path):
    b=path.read_bytes();assert b[:8]==b'\x93NUMPY\x01\x00';n=struct.unpack('<H',b[8:10])[0];head=ast.literal_eval(b[10:10+n].decode('latin1'));assert head['descr']=='<f4' and head['fortran_order'] is False
    rows,columns=head['shape'];assert columns==512;raw=b[10+n:];assert len(raw)==rows*columns*4
    values=struct.unpack('<'+'f'*(rows*columns),raw);result=[values[i*columns:(i+1)*columns] for i in range(rows)]
    assert all(all(math.isfinite(v) for v in r) and abs(math.sqrt(math.fsum(v*v for v in r))-1)<2e-6 for r in result)
    return result
def inputs():
    spec=json.loads((LAB/'input-spec.json').read_text(encoding='utf-8'))
    for item in spec['files'].values():assert sha(ROOT/item['path'])==item['sha256']
    get=lambda name:ROOT/spec['files'][name]['path']
    chunks=json.loads(get('chunks').read_text(encoding='utf-8'));queries=json.loads(get('qrels').read_text(encoding='utf-8'));cv=array(get('chunk_vectors'));qv=array(get('query_vectors'))
    assert len(chunks)==len(cv)==16 and len(queries)==len(qv)==24
    return spec,chunks,queries,cv,qv
def literal(value):return "'"+str(value).replace("'","''")+"'"
def vector(values):return literal('['+','.join(format(v,'.17g') for v in values)+']')+'::vector'
def terms(text):
    identifiers=['i'+m.group().lower().encode().hex() for m in re.finditer(r'[A-Za-z][A-Za-z0-9_-]*|\d+',text)]
    zh=[]
    for run in re.findall(r'[\u4e00-\u9fff]+',text):
        zh.extend('z'+run[i:i+2].encode().hex() for i in range(len(run)-1))
    return identifiers,zh
def lexvector(text):
    ids,zh=terms(text)
    return "setweight(to_tsvector('simple',"+literal(' '.join(ids))+"),'A') || setweight(to_tsvector('simple',"+literal(' '.join(zh))+"),'D')"
def lexquery(text):
    ids,zh=terms(text);unique=sorted(set(ids+zh));assert unique
    return "to_tsquery('simple',"+literal(' | '.join(unique))+')'
def init_sql():
    _,chunks,_,cv,_=inputs();commands=['CREATE EXTENSION IF NOT EXISTS vector;','CREATE TABLE IF NOT EXISTS corpus(chunk_id text PRIMARY KEY,doc_id text NOT NULL,start_pos int NOT NULL,end_pos int NOT NULL,content text NOT NULL,embedding vector(512) NOT NULL,lexical tsvector NOT NULL);','TRUNCATE corpus;']
    for c,v in zip(chunks,cv):commands.append('INSERT INTO corpus VALUES('+','.join([literal(c['chunk_id']),literal(c['doc_id']),str(c['start']),str(c['end']),literal(c['text']),vector(v),lexvector(c['text'])])+');')
    commands.append("SELECT json_build_object('server_version',current_setting('server_version'),'vector_version',(SELECT extversion FROM pg_extension WHERE extname='vector'),'rows',(SELECT count(*) FROM corpus),'indexes',(SELECT json_agg(indexdef ORDER BY indexname) FROM pg_indexes WHERE tablename='corpus'));")
    commands.append("SELECT json_agg(json_build_object('chunk_id',chunk_id,'doc_id',doc_id,'start',start_pos,'end',end_pos,'content',content,'embedding',embedding::text,'lexical',lexical::text) ORDER BY chunk_id COLLATE \"C\") FROM corpus;")
    return '\n'.join(commands)+'\n'
def query_sql(q,v):
    return '''WITH scored AS MATERIALIZED (
 SELECT chunk_id,embedding <=> '''+vector(v)+''' AS distance,ts_rank(lexical,'''+lexquery(q['query'])+''',2) AS lex_score,lexical @@ '''+lexquery(q['query'])+''' AS lex_match FROM corpus
), vr AS (SELECT chunk_id,distance,row_number() OVER(ORDER BY distance,chunk_id COLLATE "C") AS rank FROM scored),
lr AS (SELECT chunk_id,lex_score,row_number() OVER(ORDER BY lex_score DESC,chunk_id COLLATE "C") AS rank FROM scored WHERE lex_match),
fusion AS (SELECT coalesce(vr.chunk_id,lr.chunk_id) AS chunk_id,vr.rank AS vector_rank,lr.rank AS lexical_rank,
 coalesce(1.0/(60+vr.rank),0)+coalesce(1.0/(60+lr.rank),0) AS rrf_score
 FROM (SELECT * FROM vr WHERE rank<=10) vr FULL JOIN (SELECT * FROM lr WHERE rank<=10) lr USING(chunk_id)),
rr AS (SELECT *,row_number() OVER(ORDER BY rrf_score DESC,chunk_id COLLATE "C") AS rank FROM fusion)
SELECT json_build_object('query_id','''+literal(q['query_id'])+''','tsquery',('''+lexquery(q['query'])+''')::text,
 'vector',(SELECT json_agg(json_build_object('chunk_id',chunk_id,'distance',distance,'rank',rank) ORDER BY rank) FROM vr),
 'lexical',coalesce((SELECT json_agg(json_build_object('chunk_id',chunk_id,'score',lex_score,'rank',rank) ORDER BY rank) FROM lr),'[]'::json),
 'rrf',(SELECT json_agg(json_build_object('chunk_id',chunk_id,'vector_rank',vector_rank,'lexical_rank',lexical_rank,'score',rrf_score,'rank',rank) ORDER BY rank) FROM rr));
'''
