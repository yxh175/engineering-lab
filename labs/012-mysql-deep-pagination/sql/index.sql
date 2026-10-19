ALTER TABLE events DROP INDEX idx_tenant_kind_seq, ADD INDEX idx_page (seq_no,id);
ANALYZE TABLE events;
SHOW CREATE TABLE events;
SELECT index_name,stat_name,stat_value,@@innodb_page_size FROM mysql.innodb_index_stats WHERE database_name='engine_lab_012' AND table_name='events' AND stat_name IN ('size','n_leaf_pages') ORDER BY index_name,stat_name;
