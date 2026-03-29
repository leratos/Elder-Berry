# Phase 36 – Nextcloud-Integration

## Ziel

Nextcloud als Self-Hosted-Backend für Salerias Datei-, Kalender- und
Kontaktverwaltung. Ersetzt die Google-Calendar-Abhängigkeit und ergänzt
bestehende lokale Stores um geräteübergreifende Synchronisation.

Passt zur Projektphilosophie: eigene Daten auf eigenem Server (wie Matrix).

## Infrastruktur

| Ressource | Vorhanden |
|---|---|
| Server | Rootserver (Xeon E-2276G, 32 GB RAM, Ubuntu 24.04 LTS) |
| Webserver | Plesk Obsidian v18 |
| SSL | Vorhanden |
| Domain | z.B. `cloud.last-strawberry.com` (Subdomain) |
| Datenbank | MariaDB via Plesk |
| Auslastung | CPU 0.13 (15 Min), RAM 9.6% belegt – massiv Reserven |

Nextcloud läuft auf demselben Server wie Matrix-Synapse.

## Unterphasen

### 36.1 – Nextcloud Setup + WebDAV Files

**Ziel:** Nextcloud installieren, Saleria kann Dateien hoch-/runterladen.

#### Server-Setup
- Nextcloud via Plesk installieren (Docker oder nativ via Plesk Toolkit)
- Subdomain + SSL konfigurieren
- MariaDB-Datenbank + Nextcloud-Admin-User anlegen
- App-Passwort für Saleria generieren (kein Haupt-Passwort im Bot)

#### NextcloudFilesClient (`tools/nextcloud_files.py`)
- WebDAV-Client (httpx oder webdavlib)
- Methoden:
  - `upload(local_path, remote_path)` – Datei hochladen
  - `download(remote_path, local_path)` – Datei herunterladen
  - `list_dir(remote_path)` – Verzeichnis auflisten
  - `search(query)` – Dateien suchen (PROPFIND/SEARCH)
  - `share_link(remote_path)` – öffentlichen Share-Link erstellen
- Credentials: SecretStore (`nextcloud_url`, `nextcloud_user`, `nextcloud_app_password`)
- Dependency: `httpx` (bereits vorhanden) oder `webdavclient3`

#### FileCommandHandler erweitern
- `cloud upload <pfad>` – lokale Datei → Nextcloud
- `cloud download <pfad>` – Nextcloud → lokal + Matrix senden
- `cloud dateien [ordner]` – Verzeichnislisting
- `cloud suche <query>` – Dateisuche
- `cloud link <pfad>` – Share-Link generieren + an Matrix senden

#### Tests
- NextcloudFilesClient: Mock-Tests für WebDAV-Operationen
- FileCommandHandler: Command-Pattern-Tests

### 36.2 – CalDAV Kalender (Google Calendar ersetzen)

**Ziel:** GoogleCalendarClient durch CalDAV-Client ersetzen.

#### CalDAVCalendarClient (`tools/caldav_calendar.py`)
- Basiert auf `caldav` Python-Library (CalDAV-Protokoll)
- Gleiches Interface wie GoogleCalendarClient:
  - `get_events_today()`, `get_events_tomorrow()`
  - `get_events_range(start, end)`
  - `create_event(title, start, end, description)`
  - `delete_event(event_id)`
  - `search_events(query)`
- CalDAV-URL: `https://cloud.last-strawberry.com/remote.php/dav/calendars/<user>/`
- Credentials: SecretStore (`caldav_url`, `caldav_user`, `caldav_password`)
- Migration: bestehende Google-Termine exportieren (ICS) → Nextcloud importieren

#### Integration
- CalendarCommands: Client-Austausch (DI, kein Code-Umbau nötig)
- CalendarWatcher: funktioniert unverändert (nutzt `get_events_range`)
- BriefingScheduler: funktioniert unverändert
- ContextEnricher: funktioniert unverändert
- GoogleCalendarClient + OAuth2-Setup bleiben als Fallback im Code (optional)

#### Dependency
- `caldav` – Pure-Python CalDAV-Client
- Neue optionale Gruppe: `[nextcloud]` in pyproject.toml

### 36.3 – CardDAV Kontakte (optional, ergänzend)

**Ziel:** ContactStore optional um CardDAV-Sync erweitern.

#### Ansatz: Hybrid (SQLite + CardDAV-Sync)
- ContactStore bleibt primäre Datenquelle (schnell, offline)
- CardDAV-Sync als optionaler Export/Import:
  - `sync_to_nextcloud()` – lokale Kontakte → Nextcloud vCards
  - `sync_from_nextcloud()` – Nextcloud vCards → lokale Kontakte
  - Manuell per Command: `kontakte sync`
- Kein Echtzeit-Sync (zu komplex, Konflikte)
- Vorteil: Kontakte auf dem Handy per DAVx5 verfügbar

#### Dependency
- `vdirsyncer` oder direkte CardDAV-Calls via `httpx`

## Was NICHT migriert wird

| Feature | Grund |
|---|---|
| NoteStore (Notizen) | SQLite + FTS5 ist schneller und offline-fähig. Nextcloud Notes API ist schwach. |
| TodoStore (Todos) | SQLite mit Prioritäten/Kategorien passt besser als CalDAV VTODO. |
| E-Mail | Nextcloud Mail ist nur ein Webmail-UI, kein Vorteil gegenüber direktem IMAP. |
| Matrix-Kommunikation | Matrix ist für Bot-Kommunikation besser geeignet als Nextcloud Talk. |

## Architektur-Entscheidungen

### WebDAV-Library
- **Option A:** `httpx` direkt (WebDAV ist HTTP + XML) – kein neues Dependency
- **Option B:** `webdavclient3` – abstrahiert WebDAV, aber zusätzliches Dependency
- **Empfehlung:** Option A für Files (einfache PUT/GET/PROPFIND), `caldav`-Library
  für Kalender (CalDAV ist komplex genug für eine dedizierte Library)

### Credentials
- App-Passwort (nicht Haupt-Passwort) im SecretStore
- Setup-Script: `scripts/setup_nextcloud.py` (URL + User + App-Passwort konfigurieren)

### Offline-Verhalten
- Files: Fehler loggen, Nutzer informieren ("Nextcloud nicht erreichbar")
- Kalender: Offline-Cache optional (SQLite Mirror der nächsten 7 Tage)
- Kontakte: SQLite bleibt primär → offline immer verfügbar

## Reihenfolge und Abhängigkeiten

```text
36.1 (Files/WebDAV) ──→ 36.2 (CalDAV) ──→ 36.3 (CardDAV, optional)
      │                       │
      └── Nextcloud muss      └── caldav-Library
          laufen                   als Dependency
```

- 36.1 ist Voraussetzung: Nextcloud muss installiert und erreichbar sein
- 36.2 kann unabhängig von 36.1 implementiert werden (nur gleicher Server)
- 36.3 ist optional und kann auch später nachgezogen werden

## Aufwand-Schätzung

| Unterphase | Aufwand | Neue Klassen | Neue Tests |
|---|---|---|---|
| 36.1 Files | Klein–Mittel | NextcloudFilesClient | ~20 |
| 36.2 CalDAV | Mittel | CalDAVCalendarClient | ~25 |
| 36.3 CardDAV | Klein | ContactStore-Erweiterung | ~15 |

## Kosten

- Nextcloud: kostenlos (Open Source)
- Server: bereits bezahlt
- CalDAV-Library: kostenlos
- Kein API-Key nötig (eigener Server)
