# Prompt: Server-Backup mit BorgBackup → Hetzner Storage Box

## Kontext

Rootserver bei Strato (h2724315.stratoserver.net), Ubuntu 24.04 LTS, Plesk Obsidian.
Aktueller Speicherverbrauch: ~31 GB von 434 GB.
Bisheriges Backup: Plesk Scheduled Backup → Dropbox (abgekündigt).
Neues Ziel: Hetzner Storage Box BX11 (1 TB, SSH/SFTP/Borg nativ).
Server-User für Administration: `lera` (sudo)
PHP-Pfad für occ: `sudo -u lera /opt/plesk/php/8.3/bin/php -d memory_limit=512M`
Nextcloud-Pfad: `/var/www/vhosts/last-strawberry.com/cloud.last-strawberry.com/`
Nextcloud-Daten: `/var/www/vhosts/last-strawberry.com/nextcloud-data/`

## Was gesichert werden muss

### 1. Nextcloud
- Datenverzeichnis: `/var/www/vhosts/last-strawberry.com/nextcloud-data/`
- Config: `/var/www/vhosts/last-strawberry.com/cloud.last-strawberry.com/config/`
- MariaDB Datenbank (Name ermitteln aus config.php → `dbname`)

### 2. Matrix/Synapse
- PostgreSQL Datenbank (Synapse)
- Media-Store (Pfad aus Synapse homeserver.yaml ermitteln)
- Synapse Config: homeserver.yaml + signing keys

### 3. Plesk & System
- Plesk-Konfiguration: `/opt/psa/` (oder Plesk-eigenes Backup nutzen)
- Webroot: `/var/www/vhosts/`
- SSL-Zertifikate (Let's Encrypt via Plesk)
- Fail2Ban Configs: `/etc/fail2ban/filter.d/nextcloud.conf`, `/etc/fail2ban/jail.d/nextcloud.local`
- SSH-Tunnel Config: systemd-Service für RPi5-Tunnel
- Nginx Custom Configs (z.B. /alexa/ Location)

### 4. Datenbanken (Pre-Backup Dumps)
- MariaDB: `mysqldump` vor Borg-Lauf (Nextcloud DB)
- PostgreSQL: `pg_dump` vor Borg-Lauf (Synapse DB)
- Dumps nach `/var/backups/db-dumps/` schreiben, Borg sichert diesen Ordner mit

## Anforderungen

- **Verschlüsselung**: Client-seitig (AES-256 via BorgBackup `repokey-blake2`)
- **Deduplikation**: Borg-nativ (spart Speicher bei inkrementellen Backups)
- **Retention Policy**: 7 daily, 4 weekly, 6 monthly, 1 yearly
- **Automatisierung**: Cronjob (z.B. täglich 03:00 Uhr)
- **Monitoring**: Exit-Code prüfen, optional E-Mail bei Fehler
- **Nextcloud Maintenance Mode**: Vor DB-Dump aktivieren, danach deaktivieren

## Setup-Schritte

### Schritt 1: Hetzner Storage Box vorbereiten
- BX11 bestellen (1 TB, ~3,81€/Monat)
- SSH-Key von Server generieren und auf Storage Box hinterlegen
- Borg-Zugriff auf Storage Box aktivieren (SSH-Port 23)
- Verbindung testen: `ssh -p 23 uXXXXXX@uXXXXXX.your-storagebox.de`

### Schritt 2: BorgBackup auf Server installieren
```bash
sudo apt install borgbackup
```

### Schritt 3: Borg-Repository auf Storage Box initialisieren
```bash
export BORG_REPO='ssh://uXXXXXX@uXXXXXX.your-storagebox.de:23/./backups/server'
export BORG_PASSPHRASE='<sicheres-passwort-generieren>'
borg init --encryption=repokey-blake2 $BORG_REPO
```
- BORG_PASSPHRASE sicher ablegen (z.B. in `/root/.borg-passphrase`, chmod 600)
- Borg Key exportieren und OFFLINE sichern: `borg key export $BORG_REPO`

### Schritt 4: Backup-Script erstellen
- Pfad: `/usr/local/bin/borg-backup.sh`
- Ablauf:
  1. Nextcloud Maintenance Mode AN
  2. MariaDB Dump (Nextcloud DB)
  3. PostgreSQL Dump (Synapse DB)
  4. Nextcloud Maintenance Mode AUS
  5. Borg create (alle Pfade)
  6. Borg prune (Retention Policy)
  7. Borg compact
  8. Exit-Code prüfen, bei Fehler E-Mail / Log

### Schritt 5: Cronjob einrichten
```bash
# /etc/cron.d/borg-backup
0 3 * * * root /usr/local/bin/borg-backup.sh >> /var/log/borg-backup.log 2>&1
```

### Schritt 6: Restore testen
- Einzelne Datei wiederherstellen
- DB-Dump wiederherstellen (auf Testdatenbank)
- Dokumentieren welche Befehle für einen Full-Restore nötig sind

### Schritt 7: Altes Dropbox-Backup in Plesk deaktivieren

## Wichtige Hinweise

- Borg auf Hetzner Storage Box nutzt SSH-Port **23** (nicht 22)
- Hetzner Storage Box unterstützt Borg nativ (kein `borgmatic` nötig, aber optional)
- BORG_PASSPHRASE und exportierter Key müssen OFFLINE gesichert werden (USB-Stick, Passwort-Manager)
  → Ohne Passphrase + Key ist das verschlüsselte Backup wertlos
- Nextcloud Maintenance Mode ist wichtig damit die DB konsistent gedumpt wird
- Plesk-eigene Backups können parallel weiterlaufen (lokal) als zweite Sicherungsebene

## Erwartetes Ergebnis

- Tägliches verschlüsseltes inkrementelles Backup um 03:00 Uhr
- Retention: 7 daily + 4 weekly + 6 monthly + 1 yearly
- Alle kritischen Daten gesichert (Nextcloud, Matrix, Plesk, DBs, Configs)
- Restore-Anleitung dokumentiert
- Altes Dropbox-Backup deaktiviert

## Offene Punkte (vor Start klären)

- [ ] Hetzner Storage Box bestellt? → Username (uXXXXXX) eintragen
- [ ] SSH-Key auf Storage Box hinterlegt?
- [ ] Synapse DB-Name und Media-Store-Pfad ermitteln
- [ ] Nextcloud DB-Name aus config.php auslesen
- [ ] BORG_PASSPHRASE generiert und sicher abgelegt?
