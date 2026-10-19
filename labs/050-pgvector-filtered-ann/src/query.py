def sql(case):
    exact=case=='exact-filtered';filtered=case!='unfiltered-control'
    iterative='strict_order' if case=='iterative-filtered' else 'off'
    settings=f"""BEGIN;
SET LOCAL enable_seqscan={'on' if exact else 'off'};
SET LOCAL enable_indexscan={'off' if exact else 'on'};
SET LOCAL enable_bitmapscan=off;
SET LOCAL work_mem='16MB';
SET LOCAL hnsw.ef_search=40;
SET LOCAL hnsw.iterative_scan='{iterative}';
SET LOCAL hnsw.max_scan_tuples=20000;
SET LOCAL hnsw.scan_mem_multiplier=1;
"""
    query="SELECT id,category,embedding <-> '[0,0]'::vector AS distance FROM items "+("WHERE category=1 " if filtered else "")+"ORDER BY embedding <-> '[0,0]'::vector LIMIT 10"
    result=f"""WITH nearest AS ({query})
SELECT json_build_object('case','{case}','backend_pid',pg_backend_pid(),
'ef_search',current_setting('hnsw.ef_search'),'iterative_scan',current_setting('hnsw.iterative_scan'),
'max_scan_tuples',current_setting('hnsw.max_scan_tuples'),'scan_mem_multiplier',current_setting('hnsw.scan_mem_multiplier'),
'rows',COALESCE((SELECT json_agg(row_to_json(nearest) ORDER BY distance) FROM nearest),'[]'::json));
EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) {query};
COMMIT;
"""
    return settings+result
