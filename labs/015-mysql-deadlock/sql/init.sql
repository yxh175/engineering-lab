DROP DATABASE IF EXISTS engine_lab_015;
CREATE DATABASE engine_lab_015;
USE engine_lab_015;
CREATE TABLE accounts(id INT PRIMARY KEY, value INT NOT NULL) ENGINE=InnoDB;
INSERT INTO accounts VALUES(1,0),(2,0);
SELECT id,value FROM accounts ORDER BY id;
