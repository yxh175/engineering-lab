DROP DATABASE IF EXISTS engine_lab_007;
CREATE DATABASE engine_lab_007 CHARACTER SET latin1 COLLATE latin1_bin;
USE engine_lab_007;
CREATE TABLE events (
  id INT UNSIGNED NOT NULL PRIMARY KEY,
  tenant_id TINYINT UNSIGNED NOT NULL,
  kind TINYINT UNSIGNED NOT NULL,
  seq_no INT UNSIGNED NOT NULL,
  payload VARCHAR(128) NOT NULL,
  KEY idx_tenant_kind_seq (tenant_id, kind, seq_no)
) ENGINE=InnoDB;
CREATE TABLE digits (n INT NOT NULL PRIMARY KEY);
INSERT INTO digits VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9);
INSERT INTO events (id, tenant_id, kind, seq_no, payload)
SELECT n+1, MOD(n,4)+1, MOD(FLOOR(n/4),10), FLOOR(n/40),
       RPAD(CONCAT('event-',n+1),128,'x')
FROM (
  SELECT a.n+10*b.n+100*c.n+1000*d.n+10000*e.n+100000*f.n AS n
  FROM digits a CROSS JOIN digits b CROSS JOIN digits c
  CROSS JOIN digits d CROSS JOIN digits e CROSS JOIN digits f
) AS numbers
WHERE n < 200000
ORDER BY n;
DROP TABLE digits;
ANALYZE TABLE events;
SELECT COUNT(*),MIN(id),MAX(id),COUNT(DISTINCT tenant_id),COUNT(DISTINCT kind),COUNT(DISTINCT seq_no) FROM events;
SELECT tenant_id,kind,COUNT(*),MIN(seq_no),MAX(seq_no) FROM events GROUP BY tenant_id,kind ORDER BY tenant_id,kind;
