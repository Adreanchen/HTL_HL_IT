# PostgreSQL Rollen & Berechtigungen (Gemini hat geholfen :)

## Berechtigungsmatrix

| **Gruppe / Rolle** | **tests (Schema)** | **t1_rw, t2_rw**                       | **t3_ro**                    | **Sequenzen**               |
| ------------------ | ------------------ | -------------------------------------- | ---------------------------- | --------------------------- |
| **admin_grp**      | `ALL`              | `ALL`                                  | `ALL`                        | `ALL`                       |
| **production_grp** | `USAGE`            | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | `SELECT`, `INSERT`, `UPDATE` | `SELECT`, `USAGE`, `UPDATE` |
| **read_only_grp**  | `USAGE`            | `SELECT`                               | `SELECT`                     | `SELECT`                    |
| **developer_grp**  | Keine              | Keine                                  | Keine                        | Keine                       |

## Test 1: `admin1` (Vollzugriff)

Admin darf alle Tabellen verändern, Daten löschen und neue Tabellen anlegen/löschen.   

```postgresql
Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »admin1«.
 current_user | session_user
--------------+--------------
 admin1       | admin1
(1 Zeile)

INSERT 0 1
UPDATE 1
DELETE 1
DELETE 1
INSERT 0 1
CREATE TABLE
DROP TABLE
```

## Test 2: `prod1` (Eingeschränkter Schreibzugriff)

Darf lesen, einfügen, Sequenzen nutzen und `t1_rw` löschen.   

`DELETE` auf `t3_ro` und `CREATE TABLE` im Schema `tests` werden verweigert.   

```postgresql
Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »prod1«.
 current_user | session_user
--------------+--------------
 prod1        | prod1
(1 Zeile)

 id | name  | val
----+-------+-----
  1 | Alpha | 100
  2 | Beta  | 200
(2 Zeilen)

 id |  category   |         description
----+-------------+----------------------------
  2 | STATIC_DATA | Read-Only Static Reference
  1 | SYS_CONF    | System Configuration
(2 Zeilen)

INSERT 0 1
UPDATE 1
DELETE 1
 nextval
---------
       9
(1 Zeile)

psql:verification_and_tests.sql:28: FEHLER:  keine Berechtigung für Tabelle t3_ro
psql:verification_and_tests.sql:30: FEHLER:  keine Berechtigung für Schema tests
ZEILE 1: CREATE TABLE tests.prod_illegal (id int);
                      ^
```

## Test 3: `ro1` (Nur Lesezugriff)

Darf Tabellen und Sequenzen lesen. Schreibzugriffe (`INSERT`, `UPDATE`, `DELETE`) werden abgewiesen.   

```postgresql
Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »ro1«.
 current_user | session_user
--------------+--------------
 ro1          | ro1
(1 Zeile)

 id |  category   |         description
----+-------------+----------------------------
  2 | STATIC_DATA | Read-Only Static Reference
  1 | SYS_CONF    | System Configuration
(2 Zeilen)

 last_value
------------
          9
(1 Zeile)

psql:verification_and_tests.sql:39: FEHLER:  keine Berechtigung für Tabelle t1_rw
psql:verification_and_tests.sql:40: FEHLER:  keine Berechtigung für Tabelle t1_rw
psql:verification_and_tests.sql:41: FEHLER:  keine Berechtigung für Tabelle t1_rw
```

## Test 4: `dev1` (Nur Basisrechte / Temp Tables)

Darf eigene temporäre Tabellen verwalten. Zugriff auf das Schema `tests` wird verweigert.   

```postgresql
Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »dev1«.
 current_user | session_user
--------------+--------------
 dev1         | dev1
(1 Zeile)

CREATE TABLE
INSERT 0 1
 id |         note
----+---------------------
  1 | Temporary Workspace
(1 Zeile)

psql:verification_and_tests.sql:51: FEHLER:  keine Berechtigung für Schema tests
ZEILE 1: SELECT * FROM tests.t1_rw;
                       ^
```

## Test 5: Default Privileges (`t4_future`)

Zukünftige Tabellen erben automatisch die Rechte: `prod1` darf einfügen, `ro1` nur lesen (Schreibzugriff scheitert).   

```postgresql
Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »admin1«.
INSERT 0 1

Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »prod1«.
INSERT 0 1
 id |       info
----+-------------------
  1 | Created by admin1
  2 | Inserted by prod1
  3 | Created by admin1
  4 | Inserted by prod1
(4 Zeilen)

Sie sind jetzt verbunden mit der Datenbank »testdb« als Benutzer »ro1«.
 id |       info
----+-------------------
  1 | Created by admin1
  2 | Inserted by prod1
  3 | Created by admin1
  4 | Inserted by prod1
(4 Zeilen)

psql:verification_and_tests.sql:63: FEHLER:  keine Berechtigung für Tabelle t4_future
```

## Test 6: Rechteprüfung im PostgreSQL-Katalog

Bestätigung der Rechte über `\dp` und vorgegebene Zugriffsrechte über `\ddp`:

```postgresql
                                       Zugriffsprivilegien
 Schema |       Name       |   Typ   |     Zugriffsprivilegien      | Spaltenprivilegien | Policys
--------+------------------+---------+----------------------------+--------------------+---------
 tests  | t1_rw            | Tabelle | admin1=arwdDxtm/admin1    +|                    |
        |                  |         | admin_grp=arwdDxtm/admin1 +|                    |
        |                  |         | production_grp=arwd/admin1+|                    |
        |                  |         | read_only_grp=r/admin1     |                    |
 tests  | t1_rw_id_seq     | Sequenz | admin1=rwU/admin1         +|                    |
        |                  |         | admin_grp=rwU/admin1      +|                    |
        |                  |         | production_grp=rwU/admin1 +|                    |
        |                  |         | read_only_grp=r/admin1     |                    |
 tests  | t2_rw            | Tabelle | admin1=arwdDxtm/admin1    +|                    |
        |                  |         | admin_grp=arwdDxtm/admin1 +|                    |
        |                  |         | production_grp=arwd/admin1+|                    |
        |                  |         | read_only_grp=r/admin1     |                    |
 tests  | t2_rw_id_seq     | Sequenz | admin1=rwU/admin1         +|                    |
        |                  |         | admin_grp=rwU/admin1      +|                    |
        |                  |         | production_grp=rwU/admin1 +|                    |
        |                  |         | read_only_grp=r/admin1     |                    |
 tests  | t3_ro            | Tabelle | admin1=arwdDxtm/admin1    +|                    |
        |                  |         | admin_grp=arwdDxtm/admin1 +|                    |
        |                  |         | production_grp=arw/admin1 +|                    |
        |                  |         | read_only_grp=r/admin1     |                    |
 tests  | t3_ro_id_seq     | Sequenz | admin1=rwU/admin1         +|                    |
        |                  |         | admin_grp=rwU/admin1      +|                    |
        |                  |         | production_grp=rwU/admin1 +|                    |
        |                  |         | read_only_grp=r/admin1     |                    |
 tests  | t4_future        | Tabelle | admin_grp=arwdDxtm/admin1 +|                    |
        |                  |         | production_grp=arw/admin1 +|                    |
        |                  |         | read_only_grp=r/admin1    +|                    |
        |                  |         | admin1=arwdDxtm/admin1     |                    |
 tests  | t4_future_id_seq | Sequenz | admin_grp=rwU/admin1      +|                    |
        |                  |         | production_grp=rwU/admin1 +|                    |
        |                  |         | read_only_grp=r/admin1    +|                    |
        |                  |         | admin1=rwU/admin1          |                    |
(8 Zeilen)

               Vorgegebene Zugriffsprivilegien
 Eigent³mer | Schema |   Typ   |     Zugriffsprivilegien
------------+--------+---------+------------------------------
 admin1     | tests  | Sequenz | admin_grp=rwU/admin1        +
            |        |         | production_grp=rwU/admin1   +
            |        |         | read_only_grp=r/admin1
 admin1     | tests  | Tabelle | admin_grp=arwdDxtm/admin1   +
            |        |         | production_grp=arw/admin1   +
            |        |         | read_only_grp=r/admin1
 admin_grp  | tests  | Sequenz | admin_grp=rwU/admin_grp     +
            |        |         | production_grp=rwU/admin_grp+
            |        |         | read_only_grp=r/admin_grp
 admin_grp  | tests  | Tabelle | admin_grp=arwdDxtm/admin_grp+
            |        |         | production_grp=arw/admin_grp+
            |        |         | read_only_grp=r/admin_grp
(4 Zeilen)
```