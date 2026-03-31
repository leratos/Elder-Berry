# Phase: Nextcloud Setup Command

**Dokument:** `docs/concepts/nextcloud-setup-command.md`  
**Stand:** 2026-03-31  
**Ziel:** Saleria-Befehl "richte nextcloud ein" — löscht Standard-NC-Dateien, legt Ordnerstruktur an

---

## Kontext

`NextcloudFilesClient` (`tools/nextcloud_files.py`) hat:
- ✅ `list_dir(path)` — PROPFIND Depth:1
- ✅ `search(query)` — PROPFIND Depth:infinity, clientseitig gefiltert
- ✅ `_ensure_directories(path)` — privat, MKCOL mit 405=already exists als OK
- ❌ `mkdir(path)` — fehlt als öffentliche Methode
- ❌ `delete(path)` — fehlt komplett

`CloudCommandHandler` (`comms/commands/cloud_commands.py`) erhält ein neues Pattern.  
Bestätigungsflow läuft über `PendingConfirmationManager` (bereits im System vorhanden).

---

## Schritt 1 — `nextcloud_files.py` erweitern

Lies die Datei vor dem Schreiben vollständig.

### 1a. `mkdir` hinzufügen

```python
def mkdir(self, remote_path: str) -> bool:
    """Erstellt ein Verzeichnis via WebDAV MKCOL.

    Args:
        remote_path: Pfad relativ zum User-Root (z.B. "Manuale/Elektronik").

    Returns:
        True wenn neu erstellt (201), False wenn bereits vorhanden (405).

    Raises:
        NextcloudConnectionError: Server nicht erreichbar.
        NextcloudAuthError: Authentifizierung fehlgeschlagen.
        NextcloudError: Anderer Fehler (z.B. 409 Conflict wenn Parent fehlt).
    """
    if not self._has_credentials:
        raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

    url = self._webdav_url(remote_path.strip("/")) + "/"
    try:
        resp = httpx.request("MKCOL", url, auth=self._auth, timeout=10.0)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise NextcloudConnectionError(f"Server nicht erreichbar: {exc}") from exc

    self._check_auth_error(resp)
    if resp.status_code == 201:
        logger.info("Verzeichnis erstellt: %s", remote_path)
        return True
    if resp.status_code == 405:
        logger.debug("Verzeichnis bereits vorhanden: %s", remote_path)
        return False
    raise NextcloudError(
        f"MKCOL fehlgeschlagen für '{remote_path}': HTTP {resp.status_code}"
    )
```

**Wichtig:** 409 Conflict bedeutet Parent-Verzeichnis fehlt. Der Aufrufer muss
Verzeichnisse von außen nach innen anlegen (erst `Manuale/`, dann `Manuale/Elektronik/`).

### 1b. `delete` hinzufügen

```python
def delete(self, remote_path: str) -> None:
    """Löscht eine Datei oder ein Verzeichnis (inkl. Inhalt) via WebDAV DELETE.

    Args:
        remote_path: Pfad relativ zum User-Root.

    Raises:
        NextcloudConnectionError: Server nicht erreichbar.
        NextcloudAuthError: Authentifizierung fehlgeschlagen.
        NextcloudError: Datei/Verzeichnis nicht gefunden oder anderer Fehler.
    """
    if not self._has_credentials:
        raise NextcloudError("Nextcloud-Credentials nicht konfiguriert")

    url = self._webdav_url(remote_path.strip("/"))
    try:
        resp = httpx.request("DELETE", url, auth=self._auth, timeout=15.0)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise NextcloudConnectionError(f"Server nicht erreichbar: {exc}") from exc

    self._check_auth_error(resp)
    if resp.status_code == 404:
        # Bereits weg — kein Fehler, idempotent
        logger.debug("DELETE: Nicht gefunden (bereits gelöscht?): %s", remote_path)
        return
    if resp.status_code not in (200, 204):
        raise NextcloudError(
            f"DELETE fehlgeschlagen für '{remote_path}': HTTP {resp.status_code}"
        )
    logger.info("Gelöscht: %s", remote_path)
```

---

## Schritt 2 — `cloud_commands.py` erweitern

Lies die Datei vor dem Schreiben vollständig.

### 2a. Neues Command-Pattern registrieren

Pattern (case-insensitiv):
```python
NEXTCLOUD_SETUP_PATTERN = re.compile(
    r"(?:richte?\s+nextcloud\s+ein|nextcloud[\s-]*setup|cloud\s+einrichten)",
    re.IGNORECASE,
)
```

In `parse_command()` eintragen — **vor** generischen Cloud-Patterns, da spezifischer.

### 2b. Setup-Methode implementieren

```python
def _handle_nextcloud_setup(self, text: str) -> CommandResult:
    """Zweistufiger Setup-Befehl:
    1. Scannt Root, listet was gelöscht/erstellt wird → PendingConfirmation
    2. Nach Bestätigung: löscht Standard-Dateien, legt Ordnerstruktur an
    """
```

#### Konstanten (im Handler definieren):

```python
# Standard-Nextcloud-Dateien und -Ordner die gelöscht werden
_NC_DEFAULT_ITEMS = [
    "Nextcloud intro.mp4",
    "Nextcloud.png",
    "Documents",
    "Photos",
    "Talk",
]

# Ziel-Ordnerstruktur (Reihenfolge: Parent vor Child)
_NC_TARGET_DIRS = [
    "Manuale",
    "Manuale/Elektronik",
    "Manuale/3D-Druck",
    "Manuale/Netzwerk",
    "Manuale/Smart-Home",
    "Manuale/Sonstiges",
    "Projekte",
    "Projekte/Elder-Berry",
    "Dokumente",
    "Dokumente/Rechnungen",
    "Dokumente/Vertraege",
    "Dokumente/Behoerden",
    "Saleria",
    "Saleria/Notizen",
    "Saleria/Berichte",
    "Archiv",
]
```

#### Ablauf Phase 1 (Vorschau + Bestätigung):

```python
# Root scannen
root_entries = self._nc_client.list_dir("/")
existing_names = {e.name for e in root_entries}

# Schnittmenge: was tatsächlich vorhanden ist
to_delete = [name for name in _NC_DEFAULT_ITEMS if name in existing_names]

# Welche Ziel-Ordner fehlen noch?
# Nur Top-Level für die Vorschau (nicht alle Sub-Ordner aufzählen)
to_create = _NC_TARGET_DIRS  # Vollständige Liste für Ausführung

# Vorschau-Nachricht aufbauen
lines = ["Ich werde folgende Änderungen an deiner Nextcloud vornehmen:\n"]
if to_delete:
    lines.append("**Löschen:**")
    for name in to_delete:
        lines.append(f"  • {name}")
else:
    lines.append("*(Keine Standard-Dateien gefunden — nichts zu löschen)*")

lines.append("\n**Ordnerstruktur anlegen:**")
for d in _NC_TARGET_DIRS:
    lines.append(f"  • {d}/")

lines.append("\nBestätigen? (ja/nein)")

# PendingConfirmation registrieren
self._pending.set(
    action="nextcloud_setup",
    payload={"to_delete": to_delete, "to_create": _NC_TARGET_DIRS},
)
return CommandResult(text="\n".join(lines), needs_confirmation=True)
```

#### Ablauf Phase 2 (Ausführung nach Bestätigung):

```python
def _execute_nextcloud_setup(self, payload: dict) -> CommandResult:
    to_delete: list[str] = payload["to_delete"]
    to_create: list[str] = payload["to_create"]

    deleted, created, errors = [], [], []

    # 1. Löschen
    for name in to_delete:
        try:
            self._nc_client.delete(name)
            deleted.append(name)
        except NextcloudError as e:
            errors.append(f"Löschen '{name}': {e}")

    # 2. Ordner anlegen (Reihenfolge ist Parent-first — wichtig für 409)
    for path in to_create:
        try:
            is_new = self._nc_client.mkdir(path)
            if is_new:
                created.append(path)
        except NextcloudError as e:
            errors.append(f"mkdir '{path}': {e}")

    # Ergebnis
    lines = ["✅ Nextcloud-Setup abgeschlossen.\n"]
    if deleted:
        lines.append(f"Gelöscht: {', '.join(deleted)}")
    if created:
        lines.append(f"Erstellt: {len(created)} Ordner")
    if errors:
        lines.append(f"\n⚠️ Fehler ({len(errors)}):")
        for err in errors:
            lines.append(f"  • {err}")

    return CommandResult(text="\n".join(lines))
```

---

## Schritt 3 — Tests

Datei: `tests/comms/commands/test_cloud_commands.py` (oder bestehende Test-Datei erweitern)

### Tests für `nextcloud_files.py`:

```
test_mkdir_creates_new_directory          # 201 → True
test_mkdir_existing_directory             # 405 → False (kein Fehler)
test_mkdir_conflict_raises                # 409 → NextcloudError
test_mkdir_no_credentials_raises          # NextcloudError
test_delete_file                          # 204 → OK
test_delete_directory                     # 204 → OK
test_delete_not_found_is_idempotent       # 404 → kein Fehler
test_delete_no_credentials_raises         # NextcloudError
test_delete_auth_error_raises             # 401 → NextcloudAuthError
```

### Tests für `cloud_commands.py`:

```
test_setup_pattern_matches_variants       # "richte nextcloud ein", "nextcloud setup", "cloud einrichten"
test_setup_returns_confirmation_request   # Phase 1: needs_confirmation=True
test_setup_lists_only_existing_defaults   # Nur vorhandene NC-Defaults in Vorschau
test_setup_after_confirm_deletes_defaults # Phase 2: delete aufgerufen
test_setup_after_confirm_creates_dirs     # Phase 2: mkdir für alle Ziel-Ordner
test_setup_parent_before_child_order      # Manuale/ vor Manuale/Elektronik/
test_setup_partial_errors_reported        # Fehler landen in Ergebnis, kein crash
test_setup_empty_root_skips_delete        # Keine Defaults vorhanden → nur anlegen
```

---

## Schritt 4 — Journal-Eintrag

Nach Abschluss in `docs/journal.txt` eintragen:
```
## Abgeschlossen: Nextcloud Setup Command
- nextcloud_files.py: mkdir() + delete() hinzugefügt
- cloud_commands.py: NEXTCLOUD_SETUP_PATTERN + _handle_nextcloud_setup() + _execute_nextcloud_setup()
- Tests: NN passing
```

---

## Offene Punkte / Hinweise für Implementierung

1. **PendingConfirmation-API:** Wie genau `set()` und die Payload-Übergabe bei Bestätigung
   funktioniert, aus `pending_confirmation.py` lesen — nicht annehmen.

2. **`_nc_client` im CloudCommandHandler:** Prüfen ob der Client bereits als Instanzvariable
   existiert oder über Dependency Injection reinkommt. Nicht doppelt instanziieren.

3. **Umlaute in Ordnernamen:** `Verträge` und `Behörden` wurden im Konzept zu
   `Vertraege` / `Behoerden` vereinfacht — WebDAV-Encoding von Umlauts ist fehleranfällig.
   Bewusste Entscheidung, kann geändert werden wenn Tests zeigen dass Encoding korrekt ist.

4. **`Talk`-Ordner:** Nextcloud erstellt `Talk` nur wenn die Talk-App installiert ist.
   Das Scan-und-nur-löschen-wenn-vorhanden-Pattern (Phase 1) deckt das ab.
