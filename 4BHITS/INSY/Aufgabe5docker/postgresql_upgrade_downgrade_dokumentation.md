# PostgreSQL Upgrade & Downgrade mit Docker

## 1. SSH-Verbindung und Arbeitsbereich vorbereiten (Windows -> Debian-Server)
```cmd
ssh frit@192.168.1.165
```
``````bash
PS C:\Users\Adrian-LOQ>
PS C:\Users\Adrian-LOQ> ssh frit@192.168.1.165
frit@192.168.1.165's password:
Linux ServerDesHomes 6.12.111+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.111-1 (2026-09-28) x86_64

The programs included with the Debian GNU/Linux system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/copyright.

Debian GNU/Linux comes with ABSOLUTELY NO WARRANTY, to the extent
permitted by applicable law.
Last login: Wed Nov  4 16:08:55 2026 from 172.18.0.2
frit@ServerDesHomes:~$ su -
Password:
root@ServerDesHomes:~#
root@ServerDesHomes:~# cd INSYpostgres/
root@ServerDesHomes:~/INSYpostgres# mkdir task2 && cd task2
root@ServerDesHomes:~/INSYpostgres/task2# docker network create db-net
d13c5c1b8bce612b56dfa0a29de2519a7276988d457cb938732bf953c9c71135
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 2. Start der alten Datenbank (Version 15)
```bash
docker run --name db-alt \
  --network db-net \
  -e POSTGRES_PASSWORD=geheim \
  -d postgres:15-bookworm
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker run --name db-alt \
  --network db-net \
  -e POSTGRES_PASSWORD=geheim \
  -d postgres:15-bookworm
Unable to find image 'postgres:15-bookworm' locally
15-bookworm: Pulling from library/postgres
dd051e1b8c92: Pull complete
c546e3505d96: Pull complete
801c4a1b859b: Pull complete
ee1a43e100e3: Pull complete
cb0c38192fd3: Pull complete
674113f3e6b8: Pull complete
2e3ed4989c11: Pull complete
9919e1411b1e: Pull complete
90c8a2deccd9: Pull complete
0a3ea8dfa12b: Pull complete
8d83524dd6d8: Pull complete
384e5a56d82a: Pull complete
be1d33f3d4ed: Pull complete
244eab90cbaa: Pull complete
e8f050a00fa3: Download complete
12acf86b68fc: Download complete
Digest: sha256:19b8449e2187e8a174b40c8832a7ed9da45813b74c2779b1c614e7e7d0ee47f0
Status: Downloaded newer image for postgres:15-bookworm
123461eaf5904e3b9419d839500fb348d7ddf1d9f74080eb0b173dfa3baa21c6
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 3. Testdaten in der alten Datenbank anlegen
```bash
docker exec -it db-alt psql -U postgres -c "
CREATE TABLE test_tabelle (id SERIAL PRIMARY KEY, inhalt VARCHAR(50));
INSERT INTO test_tabelle (inhalt) VALUES ('Daten vor dem Upgrade');
SELECT * FROM test_tabelle;
"
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker exec -it db-alt psql -U postgres -c "
CREATE TABLE test_tabelle (id SERIAL PRIMARY KEY, inhalt VARCHAR(50));
INSERT INTO test_tabelle (inhalt) VALUES ('Daten vor dem Upgrade');
SELECT * FROM test_tabelle;
"
CREATE TABLE
INSERT 0 1
 id |        inhalt
----+-----------------------
  1 | Daten vor dem Upgrade
(1 row)

root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 4. Start der neuen Datenbank (Version 16)
```bash
docker run --name db-neu \
  --network db-net \
  -e POSTGRES_PASSWORD=geheim \
  -d postgres:16-bookworm
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker run --name db-neu \
  --network db-net \
  -e POSTGRES_PASSWORD=geheim \
  -d postgres:16-bookworm
Unable to find image 'postgres:16-bookworm' locally
16-bookworm: Pulling from library/postgres
68d798fb46d0: Pull complete
a8c21670182b: Pull complete
dd051e1b8c92: Already exists
1d919c5645b1: Pull complete
9bcbde3fb062: Pull complete
136766c05e5f: Pull complete
ffef70d379d2: Pull complete
27df7b5bf0b5: Pull complete
b056e8cb2530: Pull complete
5760334e16b5: Pull complete
61b3cc329be3: Pull complete
2a13757dbdad: Pull complete
cda6e21da0f2: Pull complete
fce9821bac7d: Pull complete
f27ec3e8224c: Download complete
534f220000aa: Download complete
Digest: sha256:5264710be20f409750ac6dc4e5706dcef929c87e241605463f0f9aefa932a8d9
Status: Downloaded newer image for postgres:16-bookworm
41d88b3951f0c3a01efb4070f62b6832ed3d6549b935be630f469122db92284e
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 5. Datenbank-Upgrade (Migration v15 -> v16)
```bash
docker exec db-alt pg_dump -U postgres -d postgres | docker exec -i db-neu psql -U postgres -d postgres
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker exec db-alt pg_dump -U postgres -d postgres | docker exec -i db-neu psql -U postgres -d postgres
SET
SET
SET
SET
SET
 set_config
------------

(1 row)

SET
SET
SET
SET
SET
SET
CREATE TABLE
ALTER TABLE
CREATE SEQUENCE
ALTER TABLE
ALTER SEQUENCE
ALTER TABLE
COPY 1
 setval
--------
      1
(1 row)

ALTER TABLE
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 6. Verifizierung des Upgrades & Einfügen neuer Daten
```bash
docker exec -it db-neu psql -U postgres -c "SELECT * FROM test_tabelle;"
docker exec -it db-neu psql -U postgres -c "INSERT INTO test_tabelle (inhalt) VALUES ('Daten NACH dem Upgrade');"
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker exec -it db-neu psql -U postgres -c "SELECT * FROM test_tabelle;"
 id |        inhalt
----+-----------------------
  1 | Daten vor dem Upgrade
(1 row)

root@ServerDesHomes:~/INSYpostgres/task2# docker exec -it db-neu psql -U postgres -c "INSERT INTO test_tabelle (inhalt) VALUES ('Daten NACH dem Upgrade');"
INSERT 0 1
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 7. Vorbereitung für Downgrade (Alte Tabelle löschen)
```bash
docker exec -it db-alt psql -U postgres -c "DROP TABLE test_tabelle;"
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker exec -it db-alt psql -U postgres -c "DROP TABLE test_tabelle;"
DROP TABLE
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 8. Datenbank-Downgrade (Migration v16 -> v15)
```bash
docker exec db-neu pg_dump -U postgres -d postgres | docker exec -i db-alt psql -U postgres -d postgres
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker exec db-neu pg_dump -U postgres -d postgres | docker exec -i db-alt psql -U postgres -d postgres
SET
SET
SET
SET
SET
 set_config
------------

(1 row)

SET
SET
SET
SET
SET
SET
CREATE TABLE
ALTER TABLE
CREATE SEQUENCE
ALTER SEQUENCE
ALTER SEQUENCE
ALTER TABLE
COPY 2
 setval
--------
      2
(1 row)

ALTER TABLE
root@ServerDesHomes:~/INSYpostgres/task2#
``````

## 9. Verifizierung des Downgrades
```bash
docker exec -it db-alt psql -U postgres -c "SELECT * FROM test_tabelle;"
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task2#
root@ServerDesHomes:~/INSYpostgres/task2# docker exec -it db-alt psql -U postgres -c "SELECT * FROM test_tabelle;"
 id |         inhalt
----+------------------------
  1 | Daten vor dem Upgrade
  2 | Daten NACH dem Upgrade
(2 rows)

root@ServerDesHomes:~/INSYpostgres/task2#
``````
