ALTER TABLE events ADD KEY ix_order(tenant_id,created_at DESC,id DESC);
ANALYZE TABLE events;
SHOW CREATE TABLE events;
SHOW INDEX FROM events;
