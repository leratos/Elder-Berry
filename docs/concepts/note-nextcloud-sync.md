# Notiz ↔ Nextcloud-Sync (Konzept)

**Status:** Konzept (2026-05-11)
**Branch:** TBD (eigener Branch wenn die Phase startet)
**Aufwand:** ~2–3 Sessions (geschätzt)
**Voraussetzung:** Nextcloud-Instanz mit Notes-App, App-Password im SecretStore.

## 1. Trigger

Beobachtung aus Phase-82-Smoketest (Lera, 2026-05-11): „Notizen ist
nicht mit nextcloud verbunden". Korrekt — `NoteStore` ist eine reine
SQLite + FTS5-Lösung lokal auf dem Tower
([note_store.py](../../src/elder_berry/tools/note_store.py)). Andere
Domänen sind längst angebunden:

- **Kontakte:** CardDAV via `CardDAVSyncClient` (`tools/carddav_sync.py`).
- **Termine:** Google Calendar via `GoogleCalendarClient`.
- **Todos:** CalDAV via `CalDAVTaskClient`.

Notizen sind die letzte Domäne ohne Cloud-Anbindung. Konsequenz:
Notizen sind tower-lokal, weder per Web (Nextcloud) noch mobile App
(Nextcloud Android/iOS) zugreifbar. Lera müsste neue Notizen immer
über Saleria/Matrix erfassen, kann sie unterwegs nicht ergänzen.

## 2. Ziel

Bidirektionaler Sync zwischen lokalem `NoteStore` und der
**Nextcloud Notes App** (REST API v1). Lera kann Notizen wahlweise
über Saleria, das Nextcloud-Web oder die Notes-Mobile-App erfassen
und bearbeiten — der Tower-Speicher bleibt die Single-Source-of-Truth
für FTS-Suche, Nextcloud ist die Outbound-/Edit-Schicht.

**Kern-Eigenschaften:**

1. Sync läuft als Background-Job (Scheduler, ~alle 5 min).
2. Konfliktauflösung über Nextcloud-`etag` + lokales `updated_at`.
3. Manueller Trigger via Matrix-Command (`notizen sync` / `notizen
   sync push|pull`), analog zum Kontakte-Sync.
4. **Nur Freitext-Notizen sind in Scope.** Key-Value-Fakten
   (`set_fact` / `get_fact`) bleiben lokal — sie sind ein anderer
   Use-Case (schnelle Lookups, kein Notes-App-Format).

**Nicht-Ziele:**

- Echtzeit-Push (z.B. WebSocket). Polling alle 5 min reicht für den
  Anwendungsfall.
- Multi-User-Sync mit Berechtigungen. Single-User-Projekt.
- Tag-Sync. Tags sind lokal SQLite-Feld; Nextcloud Notes hat zwar
  Categories, aber Mapping ist semantisch nicht 1:1 (Tags sind
  multi-valued, Category ist single-valued). Out-of-Scope für Etappe 1.
- Verschlüsselung end-to-end auf Notes-Inhalts-Ebene. Notes liegen in
  Nextcloud, das ist die Vertrauensgrenze (analog Kontakte, Termine).

## 3. Architektur

### 3.1 Nextcloud Notes API v1

Endpoints (relativ zu `<base>/index.php/apps/notes/api/v1/`):

| Verb | Pfad | Zweck |
|---|---|---|
| GET | `notes` | Alle Notizen (mit `If-None-Match: <etag>` für 304-Optimierung) |
| GET | `notes/<id>` | Einzelne Notiz |
| POST | `notes` | Neue Notiz erstellen |
| PUT | `notes/<id>` | Update (mit `If-Match: <etag>` zur Konflikt-Erkennung) |
| DELETE | `notes/<id>` | Löschen |

Auth: HTTP Basic Auth mit App-Password (im SecretStore unter
z.B. `nextcloud_notes_app_password`).

Wichtige Response-Felder:

```json
{
  "id": 76,
  "etag": "10fb...",
  "modified": 1734567890,
  "title": "Erste Zeile als Titel",
  "content": "Erste Zeile als Titel\n\nWeiterer Markdown-Text...",
  "category": "",
  "favorite": false
}
```

`title` wird vom Server aus der ersten Zeile von `content` abgeleitet —
muss beim PUT/POST nicht mitgeschickt werden.

### 3.2 Datenmodell-Mapping

Lokales `Note`-DTO erweitert um zwei optionale Felder zur
Sync-Verfolgung:

```python
@dataclass(frozen=True)
class Note:
    id: int
    user_id: str
    key: str | None              # None = Freitext-Notiz (sync-relevant)
    content: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    # NEU (Phase-Note-Sync):
    nc_id: int | None = None      # Nextcloud-Notes-ID, None wenn nie hochgeladen
    nc_etag: str | None = None    # Etag aus letzter erfolgreicher Sync
```

Schema-Migration: SQLite `ALTER TABLE notes ADD COLUMN nc_id INTEGER`,
analog `nc_etag TEXT`. Bei NoteStore-Init wird Migration idempotent
ausgeführt (falls Spalte fehlt — siehe Pattern in existierenden
`_create_tables`-Methoden).

### 3.3 Neue Klasse `NextcloudNotesSyncClient`

`src/elder_berry/tools/nextcloud_notes_sync.py` — eigene Datei, eine
Klasse pro Datei (analog `carddav_sync.py`).

```python
class NextcloudNotesSyncClient:
    def __init__(
        self,
        note_store: NoteStore,
        base_url: str,
        username: str,
        app_password: str,
        user_id: str,         # Matrix-User-ID, für NoteStore-Filterung
    ) -> None: ...

    def sync(self) -> SyncResult: ...
    """Vollständiger bidirektionaler Sync (push + pull)."""

    def push_only(self) -> SyncResult: ...
    """Nur lokale Notizen ohne nc_id zu Nextcloud hochladen."""

    def pull_only(self) -> SyncResult: ...
    """Nur Nextcloud-Notizen herunterladen, keine Uploads."""
```

`SyncResult` ist DTO: `pushed: int`, `pulled: int`, `conflicts: int`,
`deleted_local: int`, `deleted_remote: int`, `errors: list[str]`.

### 3.4 Sync-Algorithmus (bidirektional)

```
1. Pull-Phase:
   a. GET /notes mit If-None-Match (cached etag global). 304 -> skip pull.
   b. Für jede Remote-Notiz:
      - Lokal vorhanden (nc_id-Match)?
        - Ja, nc_etag == remote.etag -> skip (unverändert).
        - Ja, nc_etag != remote.etag -> Konflikt-Check:
          - lokales updated_at > remote.modified -> push lokal (überschreibt)
          - sonst -> pull (überschreibt lokal)
        - Nein -> neue lokale Notiz mit nc_id/nc_etag setzen.

2. Push-Phase:
   a. Lokale Notizen ohne nc_id (= nie hochgeladen) -> POST + nc_id/etag merken.
   b. Lokale Notizen mit nc_id aber updated_at > nc_etag-Stand -> PUT mit
      If-Match: <nc_etag>. Bei 412 (Precondition Failed) -> Konflikt-Pfad.

3. Delete-Reconciliation:
   a. Lokale Notiz hat nc_id, aber Remote-Notiz nicht mehr in pull-Response
      -> lokal löschen (Remote war Wahrheit).
   b. (Out-of-Scope Etappe 1) Lokale Notizen, die nie nc_id hatten und
      lokal gelöscht wurden, sind weg -- kein Tombstone-Tracking.
```

### 3.5 Konfliktauflösung

Bei Edit-Konflikt (beide Seiten haben das gleiche Original verändert):
**Last-Writer-Wins** anhand `updated_at` vs. `remote.modified` —
konsistent mit Kontakte-Sync. Kein Merge-UI.

Trade-off: kann zu Datenverlust führen wenn auf beiden Seiten
unterschiedlich editiert wurde zwischen zwei Sync-Läufen. Mitigation:
Sync-Interval kurz halten (5 min). Bei explizitem Multi-Edit-Workflow
(z.B. Lera arbeitet ne Stunde offline mobil) wäre eine Verlängerung
auf 1 min oder eine On-Demand-Sync-Triggerung sinnvoll — kommt wenn
der Use-Case auftaucht.

### 3.6 Matrix-Commands

Neuer Handler oder Erweiterung von `NoteCommandHandler`:

```text
notizen sync         -> bidirektionaler Sync
notizen sync push    -> nur lokale Änderungen hoch
notizen sync pull    -> nur Nextcloud-Änderungen runter
notizen sync status  -> letzter Sync, Anzahl Konflikte
```

Analog zu den existierenden `kontakte sync`-Commands.

### 3.7 Scheduler-Integration

Background-Job in `BriefingScheduler` oder eigener Scheduler-Slot:
alle 5 Minuten `sync()` aufrufen, Fehler loggen aber nicht
re-throwen (Sync-Fehler darf den Bot nicht crashen).

Bei wiederholten Fehlern (z.B. 3× hintereinander): Cooldown auf
30 min, Warning ans Notifications-System.

## 4. Etappen

### 4.1 Etappe 1 — Schema + Client (1 Session)

- Schema-Migration NoteStore (`nc_id`, `nc_etag`).
- `NextcloudNotesSyncClient`-Skelett mit Auth + GET /notes.
- Unit-Tests: Mock-HTTP-Server (responses-Library oder ähnlich),
  Pull-Phase isoliert.

### 4.2 Etappe 2 — Push + Konfliktauflösung (1 Session)

- POST/PUT/DELETE-Methoden.
- Konflikt-Algorithmus aus §3.4 + Tests:
  - Pull-only-Update.
  - Push-only-Update.
  - Beide-Seiten-Update mit Last-Writer-Wins.
  - Delete-Reconciliation.

### 4.3 Etappe 3 — Matrix-Commands + Scheduler (½–1 Session)

- `notizen sync` + `sync push|pull|status`-Commands.
- Scheduler-Integration mit Cooldown bei Fehlern.
- Setup-Wizard-Eintrag für Nextcloud-Notes-App-Password.

## 5. Tests / Akzeptanzkriterien

- Unit-Tests für `NextcloudNotesSyncClient` mit Mock-HTTP:
  - Pull-only (neue Remote-Notiz wird lokal angelegt).
  - Push-only (neue lokale Notiz bekommt nc_id).
  - Bidirektional unverändert (kein Sync nötig, nur etag-Check).
  - Konflikt mit lokal-gewinnt.
  - Konflikt mit remote-gewinnt.
  - Remote-gelöschte Notiz wird lokal entfernt.
  - 412-Precondition-Failed handling.
- Integrations-Test gegen Live-Nextcloud (manuell, einmalig pro
  Etappe-Abschluss):
  - Notiz in Saleria erstellen → erscheint im Nextcloud-Web nach
    nächstem Sync.
  - Notiz im Nextcloud-Web bearbeiten → erscheint korrigiert in
    `notizen suche` nach nächstem Sync.
  - Notiz im Web löschen → `notizen` zeigt sie nicht mehr.

## 6. Risiken

- **R1 — Konflikt-Datenverlust:** Last-Writer-Wins kann legitime
  Edits verlieren. Mitigation: kurzes Sync-Interval. Akzeptiert für
  Single-User-Use-Case.

- **R2 — App-Password im Klartext:** Storage im SecretStore (analog
  CardDAV). Mitigation: SecretStore ist bereits OS-Keyring-basiert
  oder verschlüsselte Datei (siehe `core/secret_store.py`).

- **R3 — Schema-Migration auf produktivem DB:** Falls Lera den NoteStore
  schon mit Inhalten gefüllt hat, muss die Migration idempotent +
  rückwärts-kompatibel sein (`ADD COLUMN IF NOT EXISTS` gibt's in
  SQLite nicht — Workaround: `PRAGMA table_info` prüfen, dann
  konditional ALTER). Tests dafür auf einer mit Notizen vorbefüllten
  DB.

- **R4 — Nextcloud-App-Update bricht API:** Notes API ist seit Jahren
  stabil bei v1. Mitigation: Version-Header parsen, bei unbekannter
  Antwort-Form Sync abbrechen + loggen, nicht crashen.

- **R5 — Multi-Device-Race:** Wenn Lera in 5-min-Fenster auf Web UND
  Mobile UND in Saleria editiert, gewinnt nur eine Version. Realistisch
  selten, akzeptiert.

- **R6 — FTS5-Index nach Pull:** Massive Pull-Änderungen (initialer
  Sync mit vielen Remote-Notizen) müssen den FTS-Index korrekt
  populieren. Bestehende `notes_ai`/`notes_au`/`notes_ad`-Trigger
  greifen automatisch — sollte funktionieren, Test schreiben.

## 7. Out of Scope

- Tag-Sync (siehe §2).
- Categories-Mapping.
- Markdown-Rendering im Matrix-Output (Notizen werden weiter als
  Plaintext angezeigt, Markdown-Sourcen aus Nextcloud bleiben aber
  als Markdown im content).
- Mobile-App-spezifische Features (Pinning, Reminders innerhalb
  einer Notiz etc.) — Nextcloud Notes API hat das nicht.

## 8. Folge-Phasen

- **Note-Sync v2 (offen):** Tag-Sync (mit Category-Mapping-Konvention).
- **Note-Sync v3 (offen):** Echtzeit-Push via Nextcloud-Webhooks
  (falls die App das je bekommt — aktuell nicht).
