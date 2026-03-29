# Phase 36.1 – NextcloudFilesClient + Cloud-Commands

## Kontext

Nextcloud 33 läuft auf `cloud.last-strawberry.com` (eigener Rootserver).
Saleria soll über Matrix-Commands Dateien hoch-/runterladen, auflisten,
suchen und Share-Links erstellen können.

Server-Setup ist abgeschlossen. Dieser Chat implementiert den Code-Teil.

## Vorbereitung

1. Lies `docs/journal.txt` (letzte 80 Zeilen) für den aktuellen Stand
2. Lies `docs/concepts/phase-36-nextcloud-integration.md` (Abschnitt 36.1)
3. Lies `CLAUDE.md` für Projektkonventionen
4. Erstelle Branch: `feature/phase-36-1-nextcloud-files`

## Neue Dateien

### 1. `src/elder_berry/tools/nextcloud_files.py`

Klasse `NextcloudFilesClient` — WebDAV-Client für Nextcloud.

**Credentials aus SecretStore:**
- `nextcloud_url` → z.B. `https://cloud.last-strawberry.com`
- `nextcloud_user` → Nextcloud-Benutzername
- `nextcloud_app_password` → App-Passwort (nicht Haupt-Passwort!)

**WebDAV-Basis-URL:**
`{nextcloud_url}/remote.php/dav/files/{nextcloud_user}/`

**Methoden:**
```python
class NextcloudFilesClient:
    def __init__(self, secret_store: SecretStore) -> None: ...
    def is_available(self) -> bool: ...  # Credentials vorhanden + Server erreichbar

    def upload(self, local_path: Path, remote_path: str = "/") -> str: ...
        # PUT auf WebDAV-URL, returns remote_path
        # remote_path relativ zum User-Root (z.B. "Saleria/backup.zip")
        # Erstellt Zwischenordner automatisch (MKCOL)

    def download(self, remote_path: str, local_dir: Path | None = None) -> Path: ...
        # GET von WebDAV-URL, speichert in local_dir (default: ~/Downloads)
        # Returns lokaler Pfad

    def list_dir(self, remote_path: str = "/") -> list[NextcloudFile]: ...
        # PROPFIND Depth:1, parsed XML-Response
        # NextcloudFile: dataclass(name, path, is_dir, size, modified)

    def search(self, query: str) -> list[NextcloudFile]: ...
        # PROPFIND Depth:infinity auf Root + Filtern nach Name (case-insensitive contains)

    def share_link(self, remote_path: str) -> str: ...
        # POST /ocs/v2.php/apps/files_sharing/api/v1/shares
        # shareType=3 (public link), returns URL
        # Header: OCS-APIRequest: true
```

**Technische Details:**
- HTTP-Client: `httpx` (bereits in dependencies)
- Auth: HTTP Basic Auth (user + app_password)
- Timeout: 30s für Upload/Download, 10s für Listing/Share
- WebDAV XML-Parsing: `xml.etree.ElementTree` (stdlib, kein neues Dependency)
- Content-Type für PROPFIND: `application/xml`
- Upload Größenlimit: 100 MB (Konstante MAX_UPLOAD_SIZE_BYTES)
- Fehlerklassen: `NextcloudError`, `NextcloudConnectionError`, `NextcloudAuthError`

**PROPFIND Request-Body (für list_dir):**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:getlastmodified/>
    <d:getcontentlength/>
    <d:resourcetype/>
    <d:displayname/>
  </d:prop>
</d:propfind>
```

**PROPFIND Response-Parsing:**
- Namespace: `DAV:` (Prefix `d:`)
- Jedes `<d:response>` enthält `<d:href>` + `<d:propstat>`
- `<d:resourcetype>` enthält `<d:collection/>` für Ordner
- Erstes Response ist der abgefragte Ordner selbst → überspringen

### 2. `src/elder_berry/comms/commands/cloud_commands.py`

Klasse `CloudCommandHandler(CommandHandler)` — neuer Handler für Cloud-Befehle.

**Patterns:**
```python
# cloud upload C:\Users\lera\Documents\report.pdf [Ziel/ordner]
CLOUD_UPLOAD_PATTERN = re.compile(
    r"^cloud\s+upload\s+([a-zA-Z]:\\[^\s]+|/[^\s]+)(?:\s+(.+))?$",
    re.IGNORECASE,
)

# cloud download Dokumente/report.pdf
CLOUD_DOWNLOAD_PATTERN = re.compile(
    r"^cloud\s+download\s+(.+)$",
    re.IGNORECASE,
)

# cloud dateien [ordner] / cloud ls [ordner]
CLOUD_LIST_PATTERN = re.compile(
    r"^cloud\s+(?:dateien|ls|list)(?:\s+(.+))?$",
    re.IGNORECASE,
)

# cloud suche <query>
CLOUD_SEARCH_PATTERN = re.compile(
    r"^cloud\s+(?:suche|search|find)\s+(.+)$",
    re.IGNORECASE,
)

```python
# cloud link <pfad>
CLOUD_LINK_PATTERN = re.compile(
    r"^cloud\s+(?:link|share|teile)\s+(.+)$",
    re.IGNORECASE,
)
```

**Kollisionsprüfung:** Alle Patterns beginnen mit `cloud ` — keine Kollision
mit bestehenden Commands (clipboard, clone, etc. beginnen nicht mit "cloud").
Trotzdem: prüfe gegen alle Pattern in allen existierenden Handlern.

**DI:** `nextcloud_files: NextcloudFilesClient | None = None`

**Verhalten bei fehlender Nextcloud:**
Alle Commands geben `CommandResult(success=False, text="Nextcloud nicht konfiguriert.")` zurück.

**Upload-Logik:**
- Lokale Datei validieren (existiert, ist Datei, < 100 MB)
- remote_path: wenn angegeben → verwenden, sonst → `/Saleria/{filename}`
- Upload → Erfolgsmeldung mit Remote-Pfad

**Download-Logik:**
- Download nach `~/Downloads/` (Standard)
- `file_path` im CommandResult setzen → Bridge sendet die Datei via Matrix

**List-Logik:**
- Formatierung: Ordner mit 📁, Dateien mit 📄, Größe in KB/MB
- Max 20 Einträge anzeigen, bei mehr: "(und X weitere)"

**Search-Logik:**
- Wie List, aber mit Filter
- "Keine Ergebnisse" wenn leer

**Share-Link-Logik:**
- Link erstellen → URL als Text zurückgeben

### 3. `tests/test_nextcloud_files.py`

Tests für `NextcloudFilesClient`. Alles gemockt (kein echter Server nötig).

**Test-Kategorien (~20 Tests):**

Credentials & Verfügbarkeit:
- `test_init_from_secret_store` — Credentials korrekt gelesen
- `test_is_available_success` — Server erreichbar
- `test_is_available_no_credentials` — Fehlende Credentials → False
- `test_is_available_server_unreachable` — Timeout → False

Upload:
- `test_upload_success` — PUT + Statuscode 201/204
- `test_upload_creates_directories` — MKCOL für Zwischenordner
- `test_upload_file_not_found` — Lokale Datei fehlt → Fehler
- `test_upload_file_too_large` — Über 100 MB → Fehler
- `test_upload_server_error` — 500 → NextcloudError

Download:
- `test_download_success` — GET + Datei gespeichert
- `test_download_file_not_found` — 404 → Fehler
- `test_download_custom_dir` — Eigenes Zielverzeichnis

List:
- `test_list_dir_root` — PROPFIND + XML-Parsing
- `test_list_dir_subfolder` — Relativer Pfad
- `test_list_dir_empty` — Leerer Ordner → leere Liste

Search:
- `test_search_found` — Treffer zurückgeben
- `test_search_no_results` — Kein Treffer → leere Liste

Share:
- `test_share_link_success` — OCS API + URL zurück
- `test_share_link_not_found` — Datei existiert nicht → Fehler

### 4. `tests/test_cloud_commands.py`

Tests für `CloudCommandHandler`. Client gemockt.

**Test-Kategorien (~15 Tests):**

Pattern-Matching:
- `test_cloud_upload_pattern` — Diverse Pfade
- `test_cloud_download_pattern`
- `test_cloud_list_pattern` — Mit und ohne Ordner
- `test_cloud_search_pattern`
- `test_cloud_link_pattern`
- `test_no_collision_with_existing_patterns` — Kein Overlap

Execution:
- `test_upload_success` — Datei hochgeladen
- `test_upload_no_nextcloud` — Client fehlt → Fehlermeldung
- `test_download_success` — Datei heruntergeladen + file_path gesetzt
- `test_list_success` — Formatierte Liste
- `test_list_empty` — Leerer Ordner
- `test_search_success` — Treffer formatiert
- `test_search_no_results` — Kein Treffer
- `test_share_link_success` — URL zurückgegeben
- `test_cloud_commands_in_help` — command_descriptions vorhanden

## Zu ändernde Dateien

### 5. `src/elder_berry/comms/remote_commands.py`

- Import: `from elder_berry.comms.commands.cloud_commands import CloudCommandHandler`
- TYPE_CHECKING: `from elder_berry.tools.nextcloud_files import NextcloudFilesClient`
- `__init__`: Neuer Parameter `nextcloud_files: NextcloudFilesClient | None = None`
- Handler instanziieren: `CloudCommandHandler(nextcloud_files=nextcloud_files)`
- In `self._handlers` Liste einfügen
- HELP_TEXT: Cloud-Sektion ergänzen:
  ```
  Cloud (Nextcloud):
    cloud upload <pfad> [ziel] – Datei zu Nextcloud hochladen
    cloud download <pfad> – Datei aus Nextcloud herunterladen
    cloud dateien [ordner] – Verzeichnis auflisten
    cloud suche <query> – Dateien suchen
    cloud link <pfad> – Öffentlichen Share-Link erstellen
  ```

### 6. `scripts/start_saleria.py`

In `_init_productivity_services()`:
```python
# Nextcloud Files
if secrets.get_or_none("nextcloud_url"):
    try:
        from elder_berry.tools.nextcloud_files import NextcloudFilesClient
        nc = NextcloudFilesClient(secret_store=secrets)
        if nc.is_available():
            svc["nextcloud_files"] = nc
            logger.info("Nextcloud Files: aktiv (%s)", secrets.get("nextcloud_url"))
        else:
            logger.warning("Nextcloud Files: nicht erreichbar")
    except Exception as e:
        logger.warning("Nextcloud Files nicht verfügbar: %s", e)
```

Im `RemoteCommandHandler(...)` Aufruf:
```python
nextcloud_files=svc.get("nextcloud_files"),
```

### 7. `pyproject.toml`

Keine Änderung nötig — `httpx` ist bereits in dependencies, `xml.etree.ElementTree`
ist stdlib. Nur eintragen wenn doch ein neues Paket gebraucht wird.

## Architektur-Hinweise

- `NextcloudFilesClient` ist eigenständig in `tools/` — wie alle anderen Clients
- `CloudCommandHandler` ist eigenständig in `comms/commands/` — wie alle anderen Handler
- DI über Konstruktor, kein Singleton, kein globaler State
- `httpx` für HTTP (bereits in dependencies, kein neues Paket)
- XML-Parsing mit `xml.etree.ElementTree` (stdlib)
- Fehler loggen mit `logger.error(...)`, nicht `print()`
- Alle Strings: Deutsch (Nutzer-facing), Englisch (Logs, Code-Kommentare)

## SecretStore Setup-Anleitung

Für den manuellen Test nach Implementierung:
```python
from elder_berry.core.secret_store import SecretStore
s = SecretStore()
s.set("nextcloud_url", "https://cloud.last-strawberry.com")
s.set("nextcloud_user", "<username>")
s.set("nextcloud_app_password", "<app-passwort>")
```

## Reihenfolge

1. `NextcloudFilesClient` implementieren + Tests
2. `CloudCommandHandler` implementieren + Tests
3. `remote_commands.py` anpassen (Import + DI + HELP_TEXT)
4. `start_saleria.py` anpassen (Init + DI)
5. Alle Tests ausführen, 0 Fehler
6. Journal-Eintrag abschließen
7. Commit auf Branch
