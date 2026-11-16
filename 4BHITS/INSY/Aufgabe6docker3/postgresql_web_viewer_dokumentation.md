# PostgreSQL Web-Viewer mit eigenem Docker-Image

## 1. SSH-Verbindung und Arbeitsbereich vorbereiten (Windows -> Debian-Server)
```cmd
ssh frit@192.168.1.165
```
``````bash
PS C:\Users\Adrian-LOQ>
PS C:\Users\Adrian-LOQ> ssh frit@<IP>
frit@<IP>'s password:
Linux ServerDesHomes 6.12.111+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.111-1 (2026-09-28) x86_64

The programs included with the Debian GNU/Linux system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/copyright.

Debian GNU/Linux comes with ABSOLUTELY NO WARRANTY, to the extent
permitted by applicable law.
Last login: Wed Nov 11 14:57:41 2026 from <IP>
frit@ServerDesHomes:~$ su -
Password:
root@ServerDesHomes:~# cd INSYpostgres/
root@ServerDesHomes:~/INSYpostgres# mkdir task3
root@ServerDesHomes:~/INSYpostgres# cd task3/
root@ServerDesHomes:~/INSYpostgres/task3# docker network create web-db-netz
a412bbbbb5d2bdbffd105ba03a752b3f0e5921fa414d8001c43e4a9d4e8f97da
root@ServerDesHomes:~/INSYpostgres/task3#
``````

## 2. Erstellung der Webseite (`index.php`) und des `Dockerfile`
```php
<?php
$host = getenv('DB_HOST') ?: 'postgres-db';
$db   = getenv('DB_NAME') ?: 'meine_datenbank';
$user = getenv('DB_USER') ?: 'postgres';
$pass = getenv('DB_PASS') ?: 'geheim123';

$erlaubte_tabellen = ['kunden', 'produkte']; 
$gewaehlte_tabelle = $_GET['tabelle'] ?? $erlaubte_tabellen[0];

if (!in_array($gewaehlte_tabelle, $erlaubte_tabellen)) {
    die("Ungültige Tabellenauswahl!");
}

try {
    $pdo = new PDO("pgsql:host=$host;port=5432;dbname=$db", $user, $pass);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    
    $stmt = $pdo->query('SELECT * FROM "' . $gewaehlte_tabelle . '"');
    $daten = $stmt->fetchAll(PDO::FETCH_ASSOC);
} catch (PDOException $e) {
    die("Datenbankfehler: " . $e->getMessage());
}
?>

<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>PostgreSQL Viewer</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { background-color: #f4f4f4; }
    </style>
</head>
<body>
    <h2>Tabellen-Ansicht (PostgreSQL)</h2>
    <form method="GET">
        <label for="tabelle">Tabelle auswählen:</label>
        <select name="tabelle" id="tabelle" onchange="this.form.submit()">
            <?php foreach ($erlaubte_tabellen as $tab): ?>
                <option value="<?= htmlspecialchars($tab) ?>" <?= ($tab === $gewaehlte_tabelle) ? 'selected' : '' ?>>
                    <?= htmlspecialchars(ucfirst($tab)) ?>
                </option>
            <?php endforeach; ?>
        </select>
    </form>

    <?php if (count($daten) > 0): ?>
        <table>
            <thead>
                <tr>
                    <?php foreach (array_keys($daten[0]) as $spalte): ?>
                        <th><?= htmlspecialchars($spalte) ?></th>
                    <?php endforeach; ?>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($daten as $zeile): ?>
                    <tr>
                        <?php foreach ($zeile as $wert): ?>
                            <td><?= htmlspecialchars((string)$wert) ?></td>
                        <?php endforeach; ?>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    <?php else: ?>
        <p>Die Tabelle ist leer.</p>
    <?php endif; ?>
</body>
</html>
```

```dockerfile
FROM php:8.3-apache

RUN apt-get update && apt-get install -y libpq-dev \
    && docker-php-ext-install pdo pdo_pgsql \
    && rm -rf /var/lib/apt/lists/*

COPY index.php /var/www/html/index.php
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task3#
root@ServerDesHomes:~/INSYpostgres/task3# vim index.php
root@ServerDesHomes:~/INSYpostgres/task3# vim Dockerfile
root@ServerDesHomes:~/INSYpostgres/task3#
``````

## 3. Eigenes Webserver-Image bauen
```bash
docker build -t mein-pg-viewer .
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task3#
root@ServerDesHomes:~/INSYpostgres/task3# docker build -t mein-pg-viewer .
[+] Building 21.4s (8/8) FINISHED                                                                        docker:default
 => [internal] load build definition from Dockerfile                                                               0.0s
 => => transferring dockerfile: 234B                                                                               0.0s
 => [internal] load metadata for docker.io/library/php:8.3-apache                                                  0.7s
 => [internal] load .dockerignore                                                                                  0.0s
 => => transferring context: 2B                                                                                    0.0s
 => CACHED [1/3] FROM docker.io/library/php:8.3-apache@sha256:a800bbd2c0aa322702259ed475556b2cbc311076a8d3c4bba9b  0.1s
 => => resolve docker.io/library/php:8.3-apache@sha256:a800bbd2c0aa322702259ed475556b2cbc311076a8d3c4bba9bfe96838  0.1s
 => [internal] load build context                                                                                  0.0s
 => => transferring context: 2.80kB                                                                                0.0s
 => [2/3] RUN apt-get update && apt-get install -y libpq-dev     && docker-php-ext-install pdo pdo_pgsql     &&   16.8s
 => [3/3] COPY index.php /var/www/html/index.php                                                                   0.1s
 => exporting to image                                                                                             3.5s
 => => exporting layers                                                                                            0.7s
 => => exporting manifest sha256:19a8a8c94c1bc598a2e4890fee18953a8b769d1ef58e7235ed4001ec0e232114                  0.0s
 => => exporting config sha256:eea39c9b13268203bee2ab55a3266b6e174547e14d04f4e3494008ed88ba4187                    0.0s
 => => exporting attestation manifest sha256:2ec5690c698cf951e1c96a65a36cb7c3f1e72dad1a91c9683ce0759605c291f9      0.0s
 => => exporting manifest list sha256:39e6e1c1687d41f3bee120f3caf0b7f815999049312788b82f7c2b16a1d3b97d             0.0s
 => => naming to docker.io/library/mein-pg-viewer:latest                                                           0.0s
 => => unpacking to docker.io/library/mein-pg-viewer:latest                                                        2.6s
root@ServerDesHomes:~/INSYpostgres/task3#
``````

## 4. Persistentes Volume anlegen und PostgreSQL-Container starten
```bash
docker volume create postgres-daten

docker run -d \
  --name postgres-db \
  --network web-db-netz \
  --restart unless-stopped \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=geheim123 \
  -e POSTGRES_DB=meine_datenbank \
  -v postgres-daten:/var/lib/postgresql/data \
  postgres:16
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task3#
root@ServerDesHomes:~/INSYpostgres/task3# docker volume create postgres-daten

docker run -d \
  --name postgres-db \
  --network web-db-netz \
  --restart unless-stopped \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=geheim123 \
  -e POSTGRES_DB=meine_datenbank \
  -v postgres-daten:/var/lib/postgresql/data \
  postgres:16
postgres-daten
Unable to find image 'postgres:16' locally
16: Pulling from library/postgres
c21dabdd3f40: Pull complete
6a7048238f16: Pull complete
e9b9c168b556: Pull complete
8fe89564ad07: Pull complete
ea97cbaeb613: Pull complete
0c67d4a9f067: Pull complete
d38145328f88: Pull complete
373818e56554: Pull complete
3dcaae3150c1: Pull complete
5dd91dbc2342: Pull complete
37fb86c2a767: Already exists
6f1f66ad722a: Pull complete
0b80e0833f2d: Pull complete
d8948f3622f7: Pull complete
6ae229981968: Download complete
c6e7de97efe2: Download complete
Digest: sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f
Status: Downloaded newer image for postgres:16
1aec8878a1ca02b66abf38aaf585d210cd23dca9a8df7aa5e880bfe543eb3f84
root@ServerDesHomes:~/INSYpostgres/task3#
``````

## 5. Testtabellen und Beispieldaten in PostgreSQL anlegen
```bash
docker exec -i postgres-db psql -U postgres -d meine_datenbank << 'EOF'
CREATE TABLE kunden (id SERIAL PRIMARY KEY, name VARCHAR(50), stadt VARCHAR(50));
INSERT INTO kunden (name, stadt) VALUES ('Max Mustermann', 'Wien'), ('Erika Musterfrau', 'Linz');

CREATE TABLE produkte (id SERIAL PRIMARY KEY, artikel VARCHAR(50), preis NUMERIC(10,2));
INSERT INTO produkte (artikel, preis) VALUES ('Tastatur', 49.90), ('Monitor', 199.00);
EOF
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task3#
root@ServerDesHomes:~/INSYpostgres/task3# docker exec -i postgres-db psql -U postgres -d meine_datenbank << 'EOF'
CREATE TABLE kunden (id SERIAL PRIMARY KEY, name VARCHAR(50), stadt VARCHAR(50));
INSERT INTO kunden (name, stadt) VALUES ('Max Mustermann', 'Wien'), ('Erika Musterfrau', 'Linz');

CREATE TABLE produkte (id SERIAL PRIMARY KEY, artikel VARCHAR(50), preis NUMERIC(10,2));
INSERT INTO produkte (artikel, preis) VALUES ('Tastatur', 49.90), ('Monitor', 199.00);
EOF
CREATE TABLE
INSERT 0 2
CREATE TABLE
INSERT 0 2
root@ServerDesHomes:~/INSYpostgres/task3#
``````

## 6. Webserver-Container starten
```bash
docker run -d \
  --name mein-webserver \
  --network web-db-netz \
  --restart unless-stopped \
  -p 8080:80 \
  -e DB_HOST=postgres-db \
  -e DB_NAME=meine_datenbank \
  -e DB_USER=postgres \
  -e DB_PASS=geheim123 \
  mein-pg-viewer
```
``````bash
root@ServerDesHomes:~/INSYpostgres/task3#
root@ServerDesHomes:~/INSYpostgres/task3# docker run -d \
  --name mein-webserver \
  --network web-db-netz \
  --restart unless-stopped \
  -p 8080:80 \
  -e DB_HOST=postgres-db \
  -e DB_NAME=meine_datenbank \
  -e DB_USER=postgres \
  -e DB_PASS=geheim123 \
  mein-pg-viewer
c8c900ee2b3787b6d2e8b9fa89530bd2ae8a28b69f73d851f88ca3050a7dbd3a
root@ServerDesHomes:~/INSYpostgres/task3#
``````