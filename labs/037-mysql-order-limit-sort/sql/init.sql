CREATE DATABASE engine_lab_037 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE engine_lab_037;
CREATE TABLE events (
 id INT NOT NULL PRIMARY KEY,
 tenant_id INT NOT NULL,
 created_at BIGINT NOT NULL,
 payload VARCHAR(64) NOT NULL,
 KEY ix_tenant(tenant_id)
) ENGINE=InnoDB;
CREATE TABLE digits(n TINYINT NOT NULL PRIMARY KEY);
INSERT INTO digits VALUES(0),(1),(2),(3),(4),(5),(6),(7),(8),(9);
INSERT INTO events(id,tenant_id,created_at,payload)
SELECT n+1,n%10,1700000000+((n*37)%1000),CONCAT('event-',LPAD(n+1,6,'0'))
FROM (SELECT d0.n+10*d1.n+100*d2.n+1000*d3.n+10000*d4.n AS n
 FROM digits d0 CROSS JOIN digits d1 CROSS JOIN digits d2 CROSS JOIN digits d3 CROSS JOIN digits d4) seq
WHERE n<50000;
DROP TABLE digits;
ANALYZE TABLE events;
