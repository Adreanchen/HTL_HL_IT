SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE datname = 'testdb' AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS testdb;

DROP ROLE IF EXISTS admin1, admin2;
DROP ROLE IF EXISTS prod1, prod2;
DROP ROLE IF EXISTS dev1, dev2;
DROP ROLE IF EXISTS ro1, ro2;

DROP ROLE IF EXISTS admin_grp;
DROP ROLE IF EXISTS production_grp;
DROP ROLE IF EXISTS developer_grp;
DROP ROLE IF EXISTS read_only_grp;

DROP ROLE IF EXISTS dbadmin;