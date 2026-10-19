CREATE DATABASE engine_lab_039;
USE engine_lab_039;
CREATE TABLE accounts(id INT PRIMARY KEY,balance INT NOT NULL,CHECK(balance>=0)) ENGINE=InnoDB;
INSERT INTO accounts VALUES(1,100),(2,0);
