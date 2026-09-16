# Anleitung: PostgreSQL auf Debian VM & Windows einrichten und bidirektional verbinden

Diese Anleitung führt dich Schritt für Schritt durch die vollständige Einrichtung von PostgreSQL auf einer **Debian-VM (unter VMware mit NAT)** sowie auf deinem **Windows-PC** und zeigt, wie du dich von beiden Seiten gegenseitig via `psql` verbindest.

---

## Inhaltsverzeichnis
1. [Voraussetzungen & Netzwerk-Topologie](#1-voraussetzungen--netzwerk-topologie)
2. [PostgreSQL auf Debian VM installieren & einrichten](#2-postgresql-auf-debian-vm-installieren--einrichten)
3. [PostgreSQL auf Windows installieren & einrichten](#3-postgresql-auf-windows-installieren--einrichten)
4. [Windows Firewall konfigurieren](#4-windows-firewall-konfigurieren)
5. [IP-Adressen ermitteln](#5-ip-adressen-ermitteln)
6. [Verbindungstest: Windows ➔ Debian VM](#6-verbindungstest-windows--debian-vm)
7. [Verbindungstest: Debian VM ➔ Windows](#7-verbindungstest-debian-vm--windows)

## 1. Voraussetzungen & Netzwerk-Topologie

* **Virtualisierung:** VMware mit **NAT-Netzwerk (VMnet8)**
* **Gast-System (VM):** Debian Linux
* **Host-System:** Windows 10 / 11
* **Netzwerk-Beispiel (NAT):**
  * Debian VM IP: `192.168.25.129`
  * Windows VMnet8 Gateway/Adapter IP: `192.168.25.1`

---

## 2. PostgreSQL auf Debian VM installieren & einrichten

### 2.1 Installation
Öffne das Terminal auf deiner Debian-VM und führe folgende Befehle aus:

```bash
# Systempaketliste aktualisieren und PostgreSQL installieren
sudo apt update && sudo apt upgrade -y
sudo apt install postgresql postgresql-contrib -y
```

Prüfe, ob der Dienst läuft:
```bash
sudo systemctl status postgresql
```

---

### 2.2 Externe Verbindungen erlauben (`postgresql.conf`)
Standardmäßig lauscht PostgreSQL nur auf `localhost`. Öffne die Konfigurationsdatei:

```bash
sudo nano /etc/postgresql/*/main/postgresql.conf
```

Suche nach der Zeile `#listen_addresses = 'localhost'` und ändere sie zu:
```text
listen_addresses = '*'
```
*(Speichern mit `Strg + O`, `Enter`, Beenden mit `Strg + X`)*

---

### 2.3 Netzwerkzugriff konfigurieren (`pg_hba.conf`)
Erlaube Passwort-Authentifizierung aus dem gesamten Subnetz:

```bash
sudo nano /etc/postgresql/*/main/pg_hba.conf
```

Füge am Ende der Datei folgende Zeile hinzu:
```text
host    all             all             0.0.0.0/0               scram-sha-256
```

---

### 2.4 Passwort für den `postgres`-Benutzer vergeben
Wechsle in die PostgreSQL-Konsole und vergebe ein definiertes Passwort:

```bash
sudo -u postgres psql
```

Führe in der `psql`-Eingabeaufforderung (`postgres=#`) folgenden SQL-Befehl aus:
```sql
ALTER USER postgres WITH PASSWORD 'dein_sicheres_passwort';
\q
```

Starte danach den PostgreSQL-Dienst neu:
```bash
sudo systemctl restart postgresql
```

---

## 3. PostgreSQL auf Windows installieren & einrichten

### 3.1 Installation
1. Lade den Installer für Windows von der offiziellen Website herunter (z. B. EnterpriseDB PostgreSQL Downloads).
2. Wähle bei der Installation die Komponenten:
   * **PostgreSQL Server**
   * **Command Line Tools** (beinhaltet den `psql` Client)
3. Vergib während des Setups ein Passwort für den lokalen `postgres`-Benutzer.

---

### 3.2 PATH-Umgebungsvariable hinzufügen (für `psql` im Terminal)
Damit du `psql` direkt in der Windows PowerShell/CMD nutzen kannst:
1. `Win + R` drücken, `sysdm.cpl` eingeben und **Enter** drücken.
2. Reiter **Erweitert** ➔ **Umgebungsvariablen**.
3. Unter *Systemvariablen* die Variable **Path** auswählen und auf **Bearbeiten** klicken.
4. **Neu** anklicken und den Pfad zum `bin`-Ordner hinzufügen (z. B. `C:\Program Files\PostgreSQL\16\bin`).
5. Alle Fenster mit **OK** bestätigen und Terminal neu öffnen.

---

### 3.3 Remote-Zugriff auf Windows-PostgreSQL aktivieren
1. Öffne `C:\Program Files\PostgreSQL\<Version>\data\postgresql.conf` als Administrator und setze:
   ```text
   listen_addresses = '*'
   ```
2. Öffne `C:\Program Files\PostgreSQL\<Version>\data\pg_hba.conf` als Administrator und füge am Ende hinzu:
   ```text
   host    all             all             0.0.0.0/0               scram-sha-256
   ```
3. Drücke `Win + R`, gib `services.msc` ein, suche den Dienst **postgresql-x64-<Version>** und wähle **Neu starten**.

---

## 4. Windows Firewall konfigurieren

Damit die Debian-VM auf den PostgreSQL-Server unter Windows zugreifen kann, muss Port `5432` in der Windows Defender Firewall freigegeben werden.

Öffne die **PowerShell als Administrator** auf Windows und führe aus:

```powershell
New-NetFirewallRule -DisplayName "PostgreSQL Port 5432" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5432
```

---

## 5. IP-Adressen ermitteln

### 5.1 IP der Debian-VM ermitteln
Führe auf der Debian-VM folgenden Befehl aus:
```bash
ip a
```
Suche nach dem Netzwerkadapter (z. B. `ens33`). 
* *Beispiel:* `inet 192.168.25.129/24` ➔ IP-Adresse ist **`192.168.25.129`**.

---

### 5.2 IP des Windows-PCs (VMnet8) ermitteln
Führe in der Windows PowerShell aus:
```powershell
ipconfig
```
Suche nach dem Adapter **Ethernet-Adapter Ethernet adapter VMnet8** (nicht den WLAN-Adapter verwenden!).
* *Beispiel:* `IPv4-Adresse . . . . . . . . . . . : 192.168.25.1` ➔ IP-Adresse ist **`192.168.25.1`**.

---

## 6. Verbindungstest: Windows ➔ Debian VM

Öffne auf deinem **Windows-PC** die PowerShell/CMD und verbinde dich auf die Debian-VM:

```powershell
psql -h 192.168.25.129 -U postgres # -d postgres
```

* **Passwort:** Gib das auf der Debian-VM gesetzte Passwort ein.
* **Erfolgreich, wenn:** Die Prompt `postgres=#` erscheint.

---

## 7. Verbindungstest: Debian VM ➔ Windows

Öffne auf deiner **Debian-VM** das Terminal und verbinde dich auf den Windows-PostgreSQL-Server:

```bash
psql -h 192.168.25.1 -U postgres # -d postgres
```

* **Passwort:** Gib das bei der Windows-PostgreSQL-Installation vergebene Passwort ein.
* **Erfolgreich, wenn:** Die Prompt `postgres=#` erscheint.
