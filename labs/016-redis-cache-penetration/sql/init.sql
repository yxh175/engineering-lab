DROP DATABASE IF EXISTS engine_lab_016;
CREATE DATABASE engine_lab_016;
USE engine_lab_016;
CREATE TABLE items(id INT PRIMARY KEY,payload VARCHAR(64) NOT NULL) ENGINE=InnoDB;
INSERT INTO items VALUES(1,'existing'),(2,'');
SELECT id,HEX(payload) FROM items ORDER BY id;
