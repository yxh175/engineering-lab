CREATE EXTENSION vector;
CREATE TABLE items (id integer PRIMARY KEY, category integer NOT NULL, embedding vector(2) NOT NULL);
INSERT INTO items
SELECT i, CASE WHEN i%100=0 THEN 1 ELSE 0 END, format('[%s,0]',i)::vector
FROM generate_series(1,10000) AS s(i);
SET maintenance_work_mem='32MB';
CREATE INDEX ix_embedding ON items USING hnsw (embedding vector_l2_ops) WITH (m=16,ef_construction=64);
ANALYZE items;
