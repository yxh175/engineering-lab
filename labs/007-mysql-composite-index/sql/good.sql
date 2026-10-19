USE engine_lab_007;
CREATE INDEX idx_seq_tenant_kind ON events (seq_no,tenant_id,kind);
ANALYZE TABLE events;
SHOW CREATE TABLE events;
