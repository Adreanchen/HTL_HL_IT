\c testdb admin1

SELECT current_user, session_user;

INSERT INTO tests.t1_rw (name, val) VALUES ('AdminRecord', 999);
UPDATE tests.t1_rw SET val = 1000 WHERE name = 'AdminRecord';
DELETE FROM tests.t1_rw WHERE name = 'AdminRecord';

DELETE FROM tests.t3_ro WHERE id = 1;
INSERT INTO tests.t3_ro (id, category, description) VALUES (1, 'SYS_CONF', 'System Configuration');

CREATE TABLE tests.admin_check (id int);
DROP TABLE tests.admin_check;

\c testdb prod1

SELECT current_user, session_user;

SELECT * FROM tests.t1_rw LIMIT 2;
SELECT * FROM tests.t3_ro;

INSERT INTO tests.t1_rw (name, val) VALUES ('ProdRecord', 555);
UPDATE tests.t1_rw SET val = 556 WHERE name = 'ProdRecord';
DELETE FROM tests.t1_rw WHERE name = 'ProdRecord';

SELECT nextval('tests.t1_rw_id_seq');

DELETE FROM tests.t3_ro WHERE id = 2;

CREATE TABLE tests.prod_illegal (id int);

\c testdb ro1

SELECT current_user, session_user;

SELECT * FROM tests.t3_ro;
SELECT last_value FROM tests.t1_rw_id_seq;

INSERT INTO tests.t1_rw (name, val) VALUES ('RO_Hack', 1);
UPDATE tests.t1_rw SET val = 0;
DELETE FROM tests.t1_rw WHERE id = 1;

\c testdb dev1

SELECT current_user, session_user;

CREATE TEMP TABLE dev_temp_tbl (id int, note text);
INSERT INTO dev_temp_tbl VALUES (1, 'Temporary Workspace');
SELECT * FROM dev_temp_tbl;

SELECT * FROM tests.t1_rw;

\c testdb admin1
CREATE TABLE tests.t4_future (id serial primary key, info text);
INSERT INTO tests.t4_future (info) VALUES ('Created by admin1');

\c testdb prod1
INSERT INTO tests.t4_future (info) VALUES ('Inserted by prod1');
SELECT * FROM tests.t4_future;

\c testdb ro1
SELECT * FROM tests.t4_future;
INSERT INTO tests.t4_future (info) VALUES ('Illegal ro1 insert');

\c testdb admin1
\dp tests.*
\ddp