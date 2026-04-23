# Matrix Synapse Server – Setup-Anleitung

> **Server:** Plesk (Ubuntu 24.04, Xeon E-2276G, 32GB RAM)
> **Domain:** `matrix.last-strawberry.com`
> **Zweck:** Privater Matrix-Server für Elder-Berry / Saleria Bot
> **Federation:** Deaktiviert (privater Server)
> **E2EE:** Deaktiviert (Phase 1)

---

## Übersicht

| Komponente | Rolle |
|-----------|-------|
| Synapse | Matrix Homeserver (Docker) |
| PostgreSQL 16 | Datenbank für Synapse (Docker) |
| Plesk Nginx | Reverse Proxy + SSL (Let's Encrypt) |
| Element | Client auf Handy/Desktop |

## Voraussetzungen

- SSH-Zugang zum Plesk-Server (root oder sudo)
- Docker + Docker Compose installiert (prüfen: `docker --version` und `docker compose version`)
- Plesk Docker Extension installiert (Plesk Panel → Extensions → Docker)
- Domain `matrix.last-strawberry.com` als Subdomain in Plesk angelegt

---

## Schritt 1 – Subdomain in Plesk anlegen

1. Plesk Panel öffnen → **Websites & Domains**
2. **Add Subdomain** → `matrix` (ergibt `matrix.last-strawberry.com`)
3. **Document Root:** `/var/www/vhosts/last-strawberry.com/matrix.last-strawberry.com`
4. **SSL/TLS:** Let's Encrypt aktivieren
   - Unter der Subdomain → **SSL/TLS Certificates** → **Install** (Let's Encrypt)
   - Haken bei "Redirect from http to https"
5. **Testen:** `https://matrix.last-strawberry.com` sollte eine leere Plesk-Seite zeigen

## Schritt 2 – Docker Compose Verzeichnis vorbereiten

```bash
# SSH auf den Server
ssh root@dein-server

# Verzeichnis erstellen
mkdir -p /opt/matrix
cd /opt/matrix

# Unterverzeichnisse
mkdir -p synapse-data
```

## Schritt 3 – Docker Compose Datei erstellen

```bash
nano /opt/matrix/docker-compose.yml
```

Inhalt:

```yaml
services:
  synapse:
    image: matrixdotorg/synapse:latest
    container_name: synapse
    volumes:
      - ./synapse-data:/data
    environment:
      SYNAPSE_CONFIG_DIR: /data
      SYNAPSE_CONFIG_PATH: /data/homeserver.yaml
      TZ: "Europe/Berlin"
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8008:8008"
    networks:
      - matrix-net
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fSs", "http://localhost:8008/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 5s

  postgres:
    image: postgres:16-alpine
    container_name: synapse-postgres
    environment:
      POSTGRES_DB: synapse
      POSTGRES_USER: synapse
      POSTGRES_PASSWORD: "HIER_SICHERES_PASSWORT_SETZEN"
      POSTGRES_INITDB_ARGS: "--encoding=UTF-8 --lc-collate=C --lc-ctype=C"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U synapse"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks:
      - matrix-net
    restart: unless-stopped

networks:
  matrix-net:
    driver: bridge

volumes:
  postgres-data:
```

> **WICHTIG:** `HIER_SICHERES_PASSWORT_SETZEN` durch ein echtes Passwort ersetzen!
> Merke dir das Passwort – du brauchst es in Schritt 5 nochmal.

## Schritt 4 – Synapse Config generieren

```bash
cd /opt/matrix

docker run -it --rm \
  -v "$(pwd)/synapse-data:/data" \
  -e SYNAPSE_SERVER_NAME=matrix.last-strawberry.com \
  -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest generate
```

Das erzeugt `synapse-data/homeserver.yaml` + Signing Keys.

## Schritt 5 – homeserver.yaml anpassen

```bash
nano /opt/matrix/synapse-data/homeserver.yaml
```

### 5a) Datenbank auf PostgreSQL umstellen

Die generierte Config nutzt SQLite. Das **ersetzen** durch:

```yaml
# ALTE SQLite-Config LÖSCHEN:
# database:
#   name: sqlite3
#   args:
#     database: /data/homeserver.db

# NEU – PostgreSQL:
database:
  name: psycopg2
  txn_limit: 10000
  args:
    user: synapse
    password: "HIER_SICHERES_PASSWORT_SETZEN"
    database: synapse
    host: synapse-postgres
    port: 5432
    cp_min: 5
    cp_max: 10
```

> **Achtung:** `host: synapse-postgres` ist der Container-Name aus docker-compose!
> Passwort muss identisch sein mit dem aus Schritt 3.

### 5b) Federation deaktivieren

In `homeserver.yaml` folgende Einstellungen setzen/ändern:

```yaml
# Federation AUS (privater Server)
federation_domain_whitelist: []

# Listener – nur Client-API, kein Federation-Port
listeners:
  - port: 8008
    tls: false
    type: http
    x_forwarded: true
    resources:
      - names: [client, consent]
        compress: false
```

### 5c) Registration deaktivieren

```yaml
# Niemand kann sich selbst registrieren
enable_registration: false

# Brauchen wir um Accounts über CLI zu erstellen
registration_shared_secret: "HIER_LANGEN_ZUFALLSSTRING_SETZEN"
```

> Tipp: Zufallsstring generieren: `openssl rand -hex 32`

### 5d) Medien-Upload begrenzen (optional aber empfohlen)

```yaml
max_upload_size: 50M
```

## Schritt 6 – Container starten

```bash
cd /opt/matrix
docker compose up -d
```

Prüfen ob alles läuft:

```bash
docker compose ps
# Beide Container sollten "running" sein

docker compose logs synapse --tail 50
# Keine Errors? Gut.

# Health-Check:
curl -s http://localhost:8008/health
# Erwartete Antwort: "OK"

# Version prüfen:
curl -s http://localhost:8008/_matrix/client/versions | python3 -m json.tool
# Sollte eine Liste von unterstützten Versionen zeigen
```

## Schritt 7 – Plesk Proxy Rules einrichten

Jetzt verbinden wir die Subdomain mit dem Synapse Container.

**Option A – Über Plesk Docker Proxy Rules (bevorzugt):**

1. Plesk Panel → **Websites & Domains** → `matrix.last-strawberry.com`
2. → **Docker Proxy Rules** → **Add Rule**
3. Einstellungen:
   - **URL:** (leer lassen = Root der Subdomain)
   - **Container:** `synapse`
   - **Port:** `8008 → 8008`
4. Speichern

**Option B – Manuelle Nginx-Direktiven (falls Docker Proxy Rules nicht funktioniert):**

1. Plesk Panel → **Websites & Domains** → `matrix.last-strawberry.com`
2. → **Apache & nginx Settings**
3. Unter **Additional nginx directives** einfügen:

```nginx
location /_matrix {
    proxy_pass http://127.0.0.1:8008;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
    client_max_body_size 50M;
    proxy_http_version 1.1;
}

location /_synapse/client {
    proxy_pass http://127.0.0.1:8008;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;
}
```

4. Speichern → Plesk startet Nginx automatisch neu

**Testen (egal welche Option):**

```bash
# Extern (vom eigenen PC):
curl -s https://matrix.last-strawberry.com/_matrix/client/versions
# Sollte JSON mit Versionen zurückgeben

# Wenn Fehler: Plesk Nginx Logs prüfen
tail -50 /var/log/nginx/error.log
```

## Schritt 8 – Accounts erstellen

```bash
# Bot-Account (Saleria):
docker exec -it synapse register_new_matrix_user \
  -c /data/homeserver.yaml \
  http://localhost:8008 \
  -u saleria \
  -p "SICHERES_BOT_PASSWORT" \
  --no-admin

# User-Account (du):
docker exec -it synapse register_new_matrix_user \
  -c /data/homeserver.yaml \
  http://localhost:8008 \
  -u dein_username \
  -p "DEIN_PASSWORT" \
  --admin
```

> **Merke dir die Passwörter!** Das Bot-Passwort brauchst du später in der
> Elder-Berry Config (`.env`).

Ergebnis:
- `@saleria:matrix.last-strawberry.com` (Bot, kein Admin)
- `@dein_username:matrix.last-strawberry.com` (Du, Admin)

## Schritt 9 – Element Client einrichten

### Handy (Android / iOS):
1. Element aus App Store / Play Store installieren
2. **Sign In** → **Edit Homeserver**
3. Homeserver URL: `https://matrix.last-strawberry.com`
4. Login mit deinem User-Account (`dein_username` + Passwort)
5. Raum erstellen: **+** → **New Room**
   - Name: z.B. "Saleria" oder "Elder-Berry"
   - Privat (Invite Only)
   - E2EE: **AUS** (wichtig! Sonst kann der Bot nicht lesen)
6. In den Raum gehen → **Invite** → `@saleria:matrix.last-strawberry.com`

### Desktop (optional):
- Element Desktop: https://element.io/download
- Oder Element Web: https://app.element.io → Custom Homeserver

### Raum-ID notieren:
Die Raum-ID brauchst du für die Bot-Config. Du findest sie in Element unter:
**Room Settings → Advanced → Internal Room ID**
Format: `!xxxxxxxxxxxx:matrix.last-strawberry.com`

## Schritt 10 – Verifizierung

Checkliste – alles muss grün sein:

```
[ ] curl https://matrix.last-strawberry.com/_matrix/client/versions → JSON
[ ] curl https://matrix.last-strawberry.com/health → "OK" (oder 404, je nach Proxy)
[ ] Element Login funktioniert (Handy)
[ ] Raum erstellt + Saleria eingeladen
[ ] Raum-ID notiert
[ ] Bot-Passwort sicher gespeichert (für SecretStore auf Tower)
```

## Schritt 11 – Bot verbinden

Nach dem Server-Setup verbindet sich Elder-Berry automatisch mit dem Matrix-Server.
Im SecretStore die Zugangsdaten des Bot-Accounts hinterlegen:

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()
store.set("matrix_homeserver", "https://matrix.last-strawberry.com")
store.set("matrix_user_id", "@saleria:matrix.last-strawberry.com")
store.set("matrix_access_token", "syt_...")  # via /_matrix/client/v3/login
store.set("matrix_room_id", "!roomid:matrix.last-strawberry.com")
store.set("matrix_allowed_senders", "@dein_username:matrix.last-strawberry.com")
```

Den Access-Token erhältst du via:
```bash
curl -X POST https://matrix.last-strawberry.com/_matrix/client/v3/login \
  -H "Content-Type: application/json" \
  -d '{"type":"m.login.password","user":"saleria","password":"SICHERES_BOT_PASSWORT"}'
```

Dann Elder-Berry starten – der Bot verbindet sich automatisch und akzeptiert den Raum-Invite:

---

## Troubleshooting

### "Connection refused" bei curl localhost:8008
```bash
docker compose ps          # Läuft der Container?
docker compose logs synapse --tail 100  # Fehler in Logs?
```

### Element zeigt "Can't reach homeserver"
- SSL-Zertifikat gültig? `curl -v https://matrix.last-strawberry.com` prüfen
- Proxy Rule aktiv? Plesk → Subdomain → Docker Proxy Rules prüfen
- Nginx läuft? `systemctl status nginx`

### "Database connection error" in Synapse Logs
- PostgreSQL Container läuft? `docker compose ps`
- Passwort in homeserver.yaml identisch mit docker-compose.yml?
- Host `synapse-postgres` korrekt? (= Container-Name)

### Synapse startet nicht nach Config-Änderung
```bash
# Config validieren (zeigt Syntax-Fehler):
docker compose exec synapse python -m synapse.config \
  -c /data/homeserver.yaml --generate-missing-and-exit
```

### Logs anzeigen
```bash
docker compose logs -f synapse     # Live-Logs Synapse
docker compose logs -f postgres    # Live-Logs PostgreSQL
```

## Wartung

### Synapse updaten
```bash
cd /opt/matrix
docker compose pull synapse
docker compose up -d synapse
```

### Datenbank-Backup
```bash
docker compose exec postgres pg_dump -U synapse synapse > backup_$(date +%Y%m%d).sql
```

### Container stoppen/starten
```bash
cd /opt/matrix
docker compose stop     # Stoppen (Daten bleiben)
docker compose start    # Wieder starten
docker compose down     # Stoppen + Container entfernen (Volumes bleiben)
docker compose down -v  # ALLES löschen (⚠️ auch Daten!)
```

### Speicherverbrauch prüfen
```bash
docker stats synapse synapse-postgres --no-stream
du -sh /opt/matrix/synapse-data/    # Synapse Daten
docker volume ls | grep postgres    # PostgreSQL Volume
```

---

## Nächste Schritte

Wenn der Server läuft:

1. **Elder-Berry Secrets setzen** (Schritt 11)
2. **Bot starten**: `python scripts/start_saleria.py`
3. **Test in Element**: `status` → Saleria antwortet mit System-Info
4. **Weitere Konfiguration**: `http://localhost:8090` (Settings Dashboard)

Vollständige Installations-Dokumentation: **[INSTALLATION.md](INSTALLATION.md)**
