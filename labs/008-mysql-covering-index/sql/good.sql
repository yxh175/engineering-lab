CREATE INDEX idx_tenant_kind_seq_payload ON events(tenant_id,kind,seq_no,payload);
ANALYZE TABLE events;
SHOW CREATE TABLE events;
