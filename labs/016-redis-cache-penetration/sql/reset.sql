TRUNCATE TABLE items;
INSERT INTO items VALUES(1,'existing'),(2,'');
SELECT id,HEX(payload) FROM items ORDER BY id;
