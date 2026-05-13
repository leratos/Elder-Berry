# Notizen-Backend: NoteStore → Nextcloud Notes (Replace, Konzept)

**Status:** Konzept (2026-05-13)
**Branch:** feature/concept-note-nextcloud-replace
**Aufwand:** ~2–3 Sessions (geschätzt)
**Voraussetzung:** Nextcloud-Instanz mit Notes-App, App-Password im SecretStore.

## 1. Trigger

Beobachtung aus Phase-82-Smoketest (Lera, 2026-05-11): „Notizen ist nicht
mit nextcloud verbunden". Korrekt — der Notizen-Teil von `NoteStore`
([note_store.py](../../src/elder_berry/tools/note_store.py)) ist eine
rein lokale SQLite + FTS5-Lösung. Im Vergleich:

- **Kontakte:** CardDAV via `CardDAVSyncClient` (`tools/carddav_sync.py`).
- **Termine:** Google Calendar via `GoogleCalendarClient`
  (`tools/google_calendar.py`) — **kein** lokaler Cache, direkter API-Client.
- **Todos:** CalDAV via `CalDAVTaskClient` — ebenfalls kein lokaler Cache.

Notizen sind die letzte Domäne mit lokaler Persistenz statt API-Wrapper.
Folge: Notizen sind tower-/server-lokal, weder per Web (Nextcloud) noch
mobile App (Nextcloud Android/iOS) zugreifbar.

**Zweite Erkenntnis (2026-05-13):** Saleria läuft auf demselben Server wie
die Nextcloud-Instanz. Damit ist die ursprünglich angedachte Sync-Lösung
(bidirektionaler Pull/Push mit etag-Konflikten) überdimensioniert —
HTTP-Calls gegen Loopback haben Millisekunden-Latenz, ein lokaler Cache
bringt keine spürbare Performance, kostet aber Konflikt-Komplexität.

## 2. Ziel

Notizen wandern komplett zu **Nextcloud Notes API v1**. Single Source of
Truth ist Nextcloud, kein lokaler Cache, keine Sync-Logik. Pattern analog
`google_calendar.py` / `caldav_calendar.py`: reiner API-Wrapper.

`NoteStore` wird in zwei Teile gespalten:

- **`FactStore`** (neu, ersetzt den Key-Value-Teil von NoteStore): bleibt
  lokal SQLite für `set_fact`/`get_fact`. Fakten sind ein anderer
  Use-Case (kurze Lookups per Schlüssel, kein Notes-Format) und gehören
  nicht in eine Notes-App.
- **`NextcloudNotesClient`** (neu, ersetzt den Notizen-Teil): reiner
  API-Wrapper ohne State.

**Kern-Eigenschaften:**

1. Notizen-CRUD läuft synchron gegen Nextcloud Notes API.
2. Volltextsuche per `GET /notes` + Python-Substring-Filter. Akzeptiert
   für <1000 Notizen (Linear-Scan in Python <50ms bei realistischen
   Inhaltsgrößen). Cache-Layer kommt erst, wenn der Use-Case auftaucht.
3. **Categories** (single-valued) als strukturelle Hauptschublade
   pro Notiz — „in welche Kategorie gehört das?" (`Einkauf`, `Arbeit`,
   `Projekt`, …). Nextcloud-Web zeigt Categories als Sidebar-Ordner,
   API filtert server-seitig via `?category=`.
4. **Hashtags** im Content (`#dringend #vermieter`) als freie
   Multi-Tags zusätzlich zu Categories. Hashtags lösen ein anderes
   Problem als Categories (Quer-Tag vs. strukturelle Einordnung) und
   ergänzen sich.
5. Matrix-Command-API bekommt eine Erweiterung für Categories
   (`notiz <Kategorie>: ...`, `notizen liste <Kategorie>`,
   `notizen kategorien`). Bestehende Commands bleiben kompatibel
   (`notiz: ...` ohne Kategorie → Default-Category).

**Nicht-Ziele:**

- Lokaler Cache mit Sync (verworfen, siehe §1).
- Hierarchische Categories / verschachtelte Ordner (Nextcloud
  unterstützt es per Subcategories, aber Single-User-Use-Case braucht
  das nicht in Etappe 1).
- Echtzeit-Push / Webhooks.
- Multi-User mit Berechtigungen.
- E2E-Verschlüsselung der Notes-Inhalte (Vertrauensgrenze ist
  Nextcloud, analog Kontakte/Termine).

## 3. Architektur

### 3.1 Nextcloud Notes API v1

Endpoints (relativ zu `<base>/index.php/apps/notes/api/v1/`):

| Verb | Pfad | Zweck |
|---|---|---|
| GET | `notes` | Alle Notizen (optional `category=<name>` für serverseitigen Filter, `exclude=` für Felder) |
| GET | `notes/<id>` | Einzelne Notiz |
| POST | `notes` | Neue Notiz erstellen (Body: `{"content": "...", "category": "Einkauf"}`) |
| PUT | `notes/<id>` | Update (Body: `{"content": "...", "category": "..."}`) |
| DELETE | `notes/<id>` | Löschen |

Auth: HTTP Basic Auth mit App-Password (im SecretStore unter z.B.
`nextcloud_notes_app_password`, analog `nextcloud_caldav_password`).

Response-Felder einer Notiz:

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

`title` wird vom Server aus der ersten Zeile abgeleitet — beim POST/PUT
nicht mitschicken. Für unseren Use-Case relevant: `id`, `content`,
`modified` (für „letzte 10 Notizen"-Sortierung).

Wir nutzen weder `etag`, `category` noch `favorite` aktiv.

### 3.2 Refactor: `FactStore` aus `NoteStore` extrahieren

Neue Datei `src/elder_berry/tools/fact_store.py` — eine Klasse, eine
Datei (Konvention CLAUDE.md). Der heutige `NoteStore` enthält zwei
unzusammenhängende Konzepte; das wird sauber getrennt.

`FactStore` übernimmt aus `NoteStore`:

SQLite-Tabelle (vereinfacht — nur Fakten):

```sql
CREATE TABLE facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, key)
);
```

Methoden: `set_fact`, `get_fact`, `delete_fact`, `list_facts`.
Keine FTS5, keine Tag-Spalte, kein Notizen-Code.

DB-Pfad bleibt `~/.elder-berry/notes.db` (Bestandsschutz; oder umbenennen
auf `facts.db` — Entscheidung in Etappe 1, beide trivial).

`NoteStore` wird **komplett gelöscht** (auch die `Note`-DTO-Klasse, da
sie das Doppel-Modell repräsentiert).

### 3.3 Neue Klasse `NextcloudNotesClient`

`src/elder_berry/tools/nextcloud_notes_client.py` — reiner API-Wrapper,
analog `caldav_calendar.py` / `google_calendar.py`. Kein State, keine DB.

```python
@dataclass(frozen=True)
class NextcloudNote:
    id: int
    content: str
    category: str
    modified: datetime
    title: str

class NextcloudNotesClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: str,
        timeout: float = 10.0,
    ) -> None: ...

    def list_notes(
        self,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[NextcloudNote]: ...
    """Alle Notizen, optional gefiltert per Nextcloud-Server-Query
    (?category=...). Sortiert nach `modified` desc."""

    def get_note(self, note_id: int) -> NextcloudNote: ...

    def create_note(
        self,
        content: str,
        category: str | None = None,
    ) -> NextcloudNote: ...

    def update_note(
        self,
        note_id: int,
        content: str | None = None,
        category: str | None = None,
    ) -> NextcloudNote: ...

    def delete_note(self, note_id: int) -> None: ...

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[NextcloudNote]: ...
    """GET /notes (optional mit category-Filter) + Python-Substring-
    Filter case-insensitive auf Content. Notes-API hat keinen
    serverseitigen Search-Endpoint."""

    def list_categories(self) -> list[str]: ...
    """Aktuell genutzte Categories aus dem Server-Bestand (deduped,
    sortiert). Über GET /notes aggregiert -- Nextcloud-API hat keinen
    dedizierten Categories-Endpoint."""
```

Fehlerbehandlung: HTTP-Fehler → eigene Exception-Klasse
`NextcloudNotesError` mit Status-Code + Message. Timeout + Retry-Logik
analog CalDAV-Client (CLAUDE.md-Regel).

### 3.4 Categories und Hashtags — zwei Achsen

Zwei unterschiedliche Probleme, zwei unterschiedliche Lösungen.

**Categories (single-valued, strukturell):**

- Whitelist im Code als Default-Set: `Allgemein`, `Einkauf`, `Projekt`,
  `Arbeit`, `Privat`. Konstante in
  `src/elder_berry/tools/note_categories.py` (eigene Datei, eine
  Sache pro Datei).
- **Whitelist mit Override:** Lera kann jede beliebige Category
  angeben — ist sie nicht in der Whitelist, akzeptiert der Handler sie
  trotzdem, loggt aber eine Warning (`logger.warning("Unbekannte
  Category '%s' verwendet", category)`). Schutz gegen Tippfehler
  (`Einakuf` statt `Einkauf`) wird damit zu einer Soft-Hilfe statt
  einem Hard-Block; bewusst gewählt, weil Whitelist-Pflege sonst zur
  Wartungslast wird.
- **Default-Category:** `notiz:` ohne explizite Category → Category
  `Allgemein`. Konstante `DEFAULT_CATEGORY` in `note_categories.py`.
- Category-Filter geht direkt an Nextcloud (`GET /notes?category=...`),
  spart Bandbreite + Python-Filter.

**Hashtags (multi-valued, frei):**

- Hashtags werden direkt in den Content geschrieben (`#dringend
  #vermieter`). Keine separate API-Repräsentation in Etappe 1 —
  Hashtag ist nur eine Konvention im Plain-Text.
- Konsistent mit Notes-Mobile-Konvention (App zeigt Hashtags
  hervorgehoben an).
- Suche per Hashtag: `notizen suche #vermieter` → User schreibt `#`
  explizit, Substring-Match findet die Hashtag-Vorkommen. Kein
  spezielles Hashtag-Parsing in Etappe 1.

**Trade-offs:**

- Strukturierte Multi-Tag-Queries („alle Notizen mit `#X` UND `#Y`")
  gehen nicht — out of scope, würde Komplexität bringen die der
  Single-User-Use-Case nicht braucht.
- Whitelist-Override mit Warning ist eine Soft-Convention; Lera muss
  selbst aufpassen Tippfehler zu vermeiden. Real-Risk niedrig, weil
  `notizen kategorien` die existierenden Categories sichtbar macht.

### 3.5 Matrix-Commands: Pattern-Erweiterung für Categories

**Heute** (`NoteCommandHandler` in `comms/commands/note_commands.py`):

```text
notiz: <content>           → NoteStore.add_note
notizen liste              → NoteStore.list_all
notizen suche <query>      → NoteStore.search (FTS5)
notiz löschen #<id>        → NoteStore.delete
merk dir <key>: <value>    → NoteStore.set_fact
was ist <key>              → NoteStore.get_fact
```

**Neu** — gleiches Backend-Swap-Prinzip, plus Category-Syntax:

```text
notiz: <content>                → create_note(content, "Allgemein")
notiz <Kategorie>: <content>    → create_note(content, "<Kategorie>")
notizen liste                   → list_notes(limit=20)
notizen liste <Kategorie>       → list_notes(category="<Kategorie>", limit=20)
notizen suche <query>           → search(query)
notizen suche <Kategorie> <query> → search(query, category="<Kategorie>")
notizen kategorien              → list_categories() + Whitelist-Markierung
notiz löschen #<id>             → delete_note(id)
merk dir <key>: <value>         → FactStore.set_fact  (unverändert)
was ist <key>                   → FactStore.get_fact  (unverändert)
```

**Pattern-Update für `NOTE_ADD_PATTERN`:**

```python
NOTE_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz(?:\s+(?P<category>[\wÄÖÜäöüß\-]+))?\s*:\s*(?P<content>.+)$",
    re.IGNORECASE | re.DOTALL,  # DOTALL aus Phase 90-A bleibt
)
```

Single-Word-Category (Whitespace nicht erlaubt) — Pattern-Trenner
sonst nicht eindeutig. Whitelist enthält daher nur Single-Word-Begriffe
(`Allgemein`, `Einkauf`, `Projekt`, `Arbeit`, `Privat`). Mehr-Wort-
Categories sind out of scope; falls Lera „Persönliche Notizen" will,
müsste das `Persoenlich` oder `PersoenlichesZeug` heißen.

**Whitelist-Override-Verhalten:**

Bei Match auf `notiz Einakuf: ...` (Tippfehler) → Category wird auf
Nextcloud trotzdem als `Einakuf` angelegt, Handler loggt Warning,
Matrix-Response enthält Hinweis: „Notiz unter neuer Kategorie
'Einakuf' angelegt. Bekannte Kategorien: Allgemein, Einkauf, …".

**`notizen kategorien`-Output:**

```text
Kategorien:
  • Allgemein        (24 Notizen)   ← Whitelist + genutzt
  • Einkauf          (8 Notizen)    ← Whitelist + genutzt
  • Projekt          (0 Notizen)    ← Whitelist, ungenutzt
  • Arbeit           (3 Notizen)    ← Whitelist + genutzt
  • Privat           (0 Notizen)    ← Whitelist, ungenutzt
  • MoscowMule       (1 Notiz)      ← frei (nicht in Whitelist)
```

**Dependencies:** `NoteCommandHandler` bekommt zwei Dependencies via
Konstruktor (`NextcloudNotesClient`, `FactStore`) statt einer
(`NoteStore`).

**ID-Format:** Notizen-IDs kommen jetzt von Nextcloud (auch INTEGER).
Externe Darstellung bleibt `#<id>`. Lera muss keine ID-Konventionen
neu lernen.

### 3.6 Keine Daten-Migration

Bestätigt 2026-05-13 (Lera): aktuell keine produktiven Notizen, alles
Testphase. NoteStore-DB wird beim Wegfall des Notizen-Codes nicht
migriert; nur die Fakten-Tabelle wandert konzeptuell in den `FactStore`
(gleiche DB-Datei oder umbenannt, siehe §3.2).

Falls beim Etappe-1-Start doch noch Notizen vorhanden sind: einmaliger
Ad-hoc-Dump per Hand (`sqlite3 notes.db "SELECT content FROM notes
WHERE key IS NULL"` → manuell ins Nextcloud-Web kopieren). Kein Code
dafür schreiben.

## 4. Etappen

### 4.1 Etappe 1 — FactStore-Refactor (½–1 Session)

- `FactStore`-Klasse extrahieren (`tools/fact_store.py`).
- `NoteStore` komplett entfernen (inkl. `Note`-DTO, FTS5-Trigger,
  Notes-Tabelle).
- Bestehende Tests für Fakten-Teil (`test_note_store.py`) splitten in
  `test_fact_store.py` (Fakten-Tests bleiben grün) und
  Notizen-Tests werden gelöscht (kommen neu in Etappe 2/3 gegen
  Nextcloud-Mock).
- `NoteCommandHandler` temporär: Fakten-Commands gehen an `FactStore`,
  Notizen-Commands geben „Backend wird umgestellt, bitte warten"-Antwort
  zurück (oder werden temporär deaktiviert). Sauberer: dieser Schritt
  und Etappe 2 in einem Branch zusammenführen, damit keine Production-
  Lücke entsteht.

### 4.2 Etappe 2 — NextcloudNotesClient + Tests (1 Session)

- `note_categories.py` mit `DEFAULT_CATEGORY = "Allgemein"` und
  `KNOWN_CATEGORIES = frozenset({"Allgemein", "Einkauf", "Projekt",
  "Arbeit", "Privat"})`.
- `NextcloudNotesClient`-Klasse mit CRUD + Search + `list_categories`.
- Unit-Tests mit Mock-HTTP (`responses`-Library oder `unittest.mock`
  auf `requests.Session`):
  - `list_notes()` → leere Liste, gefüllte Liste, Sortierung nach
    `modified`.
  - `list_notes(category="Einkauf")` → Query-Param landet korrekt am
    Request.
  - `create_note(content, category)` → POST-Body enthält beide Felder.
  - `create_note(content)` ohne Category → POST-Body hat keine
    Category (Server-Default leer; Default `Allgemein` wird im
    Handler gesetzt, nicht im Client).
  - `update_note` → PUT mit partial Update (nur content / nur
    category / beide).
  - `delete_note` → DELETE 204.
  - `search(query)` und `search(query, category)` → Filter-Kombi.
  - `list_categories` → Dedup + Sort über GET /notes-Response.
  - Fehlerfälle: 401 (App-Password falsch), 404 (Note weg), 500
    (Server-Fehler) → jeweils `NextcloudNotesError` mit korrektem
    Status.
- Setup-Wizard-Eintrag für `nextcloud_notes_app_password` im
  SecretStore (Pattern bei CalDAV abschauen).

### 4.3 Etappe 3 — NoteCommandHandler umstellen + Integration (1 Session)

- `NoteCommandHandler` bekommt `NextcloudNotesClient` injiziert.
- `NOTE_ADD_PATTERN` erweitert um optionale Category-Capture-Group
  (siehe §3.5). `_try_parse_multi_line` (Phase 90-A) bleibt
  unverändert.
- Neue Commands: `notizen liste <Kategorie>`, `notizen kategorien`.
- Whitelist-Override-Logik: bei unbekannter Category → Warning loggen,
  Hinweis in Matrix-Response anhängen.
- Default-Category-Logik: `notiz:` ohne Group-1-Match →
  `category=DEFAULT_CATEGORY`.
- Hilfe-Text in `help_sections.py` aktualisieren:
  - `notiz Einkauf: …`-Beispiel neben `notiz: …`.
  - `notizen kategorien` als neuer Eintrag.
  - Hashtag-Hinweis bei `notiz:`-Beispielen (`#dringend` etc.).
- Integrationstest manuell (Live-Nextcloud):
  - `notiz Einkauf: Milch #dringend` → erscheint im Nextcloud-Web
    unter Kategorie „Einkauf".
  - `notiz: Testnotiz` → erscheint unter „Allgemein".
  - `notizen liste einkauf` → nur Einkauf-Notizen.
  - `notizen kategorien` → korrekte Counts.
  - Im Web bearbeiten → `notizen liste` zeigt aktualisierten Stand.
  - `notiz löschen #<id>` → weg auch im Web.
- Smoketest mit Lera über Matrix.

## 5. Tests / Akzeptanzkriterien

**Etappe 1:**
- `test_fact_store.py`: alle bestehenden Fakten-Tests grün, keine
  Regression.
- `test_note_store.py`: gelöscht (Modul existiert nicht mehr).

**Etappe 2:**
- `test_nextcloud_notes_client.py`: CRUD + Search + Fehlerfälle gegen
  Mock-HTTP.
- mypy strict + ruff check grün auf neuer Datei.

**Etappe 3:**
- `test_note_commands.py`: Tests gegen Mock-`NextcloudNotesClient`,
  alle Command-Pfade abgedeckt (add / list / search / delete).
- Live-Integrationstest (manuell, einmalig vor Merge).

## 6. Risiken

- **R1 — Nextcloud-Downtime macht Notizen unzugänglich.** Bei
  Server-Co-Location ohnehin gemeinsamer Failure-Mode (wenn Nextcloud
  down ist, hat Saleria auch andere Probleme). Akzeptiert.

- **R2 — App-Password im SecretStore.** Pattern wie CardDAV/CalDAV.
  SecretStore ist OS-Keyring oder verschlüsselte Datei
  (`core/secret_store.py`). Kein neues Risiko.

- **R3 — Suchlaufzeit bei vielen Notizen.** Bei >>1000 Notizen wird
  `GET /notes` + Python-Filter langsam (sowohl Bandbreite als auch
  Filter). Mitigation: erst implementieren wenn der Use-Case auftaucht
  (z.B. Read-Through-Cache mit kurzer TTL). Akzeptiert für Etappe 1.

- **R4 — Hashtag-Konvention bricht heutige Tag-API.** Lera hat heute
  einen `tags`-Parameter beim `notiz:`-Command (laut Code in
  `note_commands.py` zu prüfen — falls genutzt). Im Single-User-Setup
  unkritisch, aber muss in der `help_sections.py`-Doku aktualisiert
  werden, damit das `notizen` Hilfe-Output stimmt.

- **R5 — Nextcloud-App-Update bricht API.** Notes API v1 ist seit
  Jahren stabil. Mitigation: bei unerwartetem Response-Format Sync-Call
  loggen + Exception statt Crash. Standard Error-Handling.

- **R6 — FactStore-DB-Datei vs. NoteStore-DB-Datei.** Wenn die DB-Datei
  übernommen wird (`notes.db` → `FactStore` benutzt sie weiter), bleibt
  die alte `notes`-Tabelle als toter Code in der DB liegen, bis ein
  `VACUUM` läuft. Kosmetisch, kein Funktionsproblem. Alternativ:
  `FactStore` erzeugt frische `facts.db`, alte Datei wird nach
  manueller Bestätigung gelöscht. Entscheidung in Etappe 1.

- **R7 — Whitelist-Drift / Tippfehler-Categories.** Whitelist-Override
  erlaubt freie Strings, daher kann sich über Zeit eine Mischung aus
  Tippfehlern (`Einakuf`) und Synonymen (`Einkauf` vs. `Einkaufsliste`)
  in Nextcloud ansammeln. Mitigation: `notizen kategorien` zeigt alle
  vorhandenen + Whitelist-Markierung; Lera kann manuell im Nextcloud-
  Web aufräumen. Kein automatisierter Rename in Etappe 1.

- **R8 — Pattern-Ambiguität bei Multi-Word-Category-Wunsch.** Pattern
  matched nur Single-Word vor `:`. Falls Lera doch Mehr-Wort-Categories
  will, müsste der Pattern auf eine andere Trenner-Konvention umgebaut
  werden (z.B. `notiz [Persoenlich]: ...` oder Quoted-String). Out of
  Scope Etappe 1, Folge-Phase wenn der Use-Case kommt.

## 7. Out of Scope

- Lokaler Cache mit Sync (verworfene Alternative aus erster
  Konzept-Iteration, siehe §1).
- Hierarchische Categories (Nextcloud kann Subcategories per
  `Parent/Child`-Naming; in Etappe 1 nur flache Categories).
- Multi-Word-Categories (Pattern-Trenner sonst nicht eindeutig,
  siehe R8).
- Category-Rename per Matrix-Command — Lera räumt im Nextcloud-Web
  auf, falls Whitelist-Drift entsteht.
- Hashtag-Parsing für strukturierte Tag-Queries („alle Notizen mit
  Tag X und Y"). Etappe 1 bleibt bei reiner Substring-Suche.
- Markdown-Rendering im Matrix-Output. Notizen werden weiter als
  Plaintext ausgegeben; Markdown-Source aus Nextcloud bleibt als
  Markdown im Content.
- Mobile-App-spezifische Features (Pinning, Favoriten, Reminders).

## 8. Folge-Phasen

- **Note-Backend v2 (offen):** Read-Through-Cache, falls Suchlaufzeit
  zum Thema wird.
- **Note-Backend v3 (offen):** Strukturiertes Hashtag-Parsing für
  Multi-Tag-Queries.
- **Note-Backend v4 (offen):** Hierarchische Categories +
  Multi-Word-Categories mit alternativer Trenner-Syntax.
