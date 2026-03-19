# Phase 16: Notizen & Wissensdatenbank

> **Status:** Geplant
> **Erstellt:** 2026-03-19 (Claude App)
> **Umsetzung:** Claude Code
> **Abhängigkeit:** Keine (eigenständig)
> **Branch:** `feature/phase-16-notizen-wissensdatenbank`

---

## Übersicht

Expliziter Fakten- und Notizspeicher für Saleria. Unterschied zu ChromaDB-RAG:
- **ChromaDB** = unscharfe semantische Suche über Konversationen ("worüber haben wir geredet?")
- **NoteStore** = präzise abrufbare Fakten und Freitext-Notizen ("was ist das WLAN-Passwort?")

Zwei Modi:
1. **Key-Value-Fakten**: "WLAN-Passwort Büro" → "xyz123" (exakter Abruf per Schlüssel)
2. **Freitext-Notizen**: "der Vermieter heißt Müller und die Kaution war 1200€" (Volltextsuche)

---

## VORBEREITUNG

Bevor du mit der Implementierung beginnst:

1. Lies `C:\Dev\Elder-Berry\docs\journal.txt` (letzte 80 Zeilen)
2. Lies dieses Konzept-Dokument komplett durch
3. Erstelle Branch: `git checkout -b feature/phase-16-notizen-wissensdatenbank`
4. Schreibe Draft-Eintrag in journal.txt

---

## 16.1 – NoteStore (SQLite + FTS5)

### Neue Datei: `src/elder_berry/tools/note_store.py`

**Klasse:** `NoteStore`

**Storage:** SQLite mit FTS5-Erweiterung (Volltextsuche, in Python-SQLite standardmäßig verfügbar).

**Dependency Injection:**
```python
def __init__(self, db_path: Path | None = None) -> None:
```

**Default DB-Pfad:** `~/.elder-berry/notes.db`

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    key         TEXT,           -- NULL bei Freitext-Notizen, gesetzt bei KV-Fakten
    content     TEXT NOT NULL,  -- Der eigentliche Inhalt / Wert
    tags        TEXT,           -- Komma-separierte Tags (optional, für spätere Filterung)
    created_at  TEXT NOT NULL,  -- ISO 8601 UTC
    updated_at  TEXT NOT NULL   -- ISO 8601 UTC
);

-- Unique Constraint: ein Key pro User (Upsert-Verhalten)
CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_user_key
    ON notes(user_id, key) WHERE key IS NOT NULL;

-- FTS5-Index für Volltextsuche über content + key + tags
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    content, key, tags,
    content=notes,
    content_rowid=id
);

-- Trigger für FTS-Sync (INSERT, UPDATE, DELETE)
-- Siehe Implementierungsdetails unten
```

**DTO:**
```python
@dataclass(frozen=True)
class Note:
    """Eine einzelne Notiz oder ein Fakten-Eintrag."""
    id: int
    user_id: str
    key: str | None       # None = Freitext, gesetzt = KV-Fakt
    content: str
    tags: list[str]       # Geparst aus komma-separiertem DB-Feld
    created_at: datetime
    updated_at: datetime

    @property
    def is_fact(self) -> bool:
        """True wenn Key-Value-Fakt (hat einen Schlüssel)."""
        return self.key is not None

    def format_short(self) -> str:
        """Einzeilige Darstellung für Listenansicht."""
        if self.key:
            return f"#{self.id} 🔑 {self.key}: {self.content}"
        preview = self.content[:80] + ("..." if len(self.content) > 80 else "")
        return f"#{self.id} 📝 {preview}"
```

**Methoden:**
```python
def set_fact(self, user_id: str, key: str, value: str, tags: list[str] | None = None) -> Note:
    """Key-Value-Fakt speichern (Upsert: existierender Key wird überschrieben).

    Args:
        user_id: Matrix-User-ID.
        key: Schlüssel (z.B. "wlan passwort büro"). Wird normalisiert (lowercase, strip).
        value: Wert (z.B. "xyz123").
        tags: Optionale Tags zur Kategorisierung.

    Returns:
        Die erstellte/aktualisierte Note.
    """
```

```python
def add_note(self, user_id: str, content: str, tags: list[str] | None = None) -> Note:
    """Freitext-Notiz speichern (kein Key, immer neuer Eintrag).

    Args:
        user_id: Matrix-User-ID.
        content: Notiztext.
        tags: Optionale Tags.

    Returns:
        Die erstellte Note.
    """

def get_fact(self, user_id: str, key: str) -> Note | None:
    """Exakten KV-Fakt per Schlüssel abrufen.

    Args:
        user_id: Matrix-User-ID.
        key: Schlüssel (wird normalisiert).

    Returns:
        Note oder None wenn nicht gefunden.
    """

def search(self, user_id: str, query: str, limit: int = 10) -> list[Note]:
    """Volltextsuche über alle Notizen (FTS5 MATCH).

    Durchsucht content, key und tags. Ergebnisse nach Relevanz sortiert.

    Args:
        user_id: Matrix-User-ID.
        query: Suchbegriff (FTS5-Syntax: Einzelwörter, "phrase", prefix*).
        limit: Maximale Ergebnisse.

    Returns:
        Liste von Notes, nach Relevanz sortiert (FTS5 rank).
    """

def list_all(self, user_id: str, limit: int = 20) -> list[Note]:
    """Alle Notizen eines Users (neueste zuerst).

    Args:
        user_id: Matrix-User-ID.
        limit: Maximale Ergebnisse.

    Returns:
        Liste von Notes, nach updated_at DESC sortiert.
    """

def delete(self, note_id: int) -> bool:
    """Notiz per ID löschen.

    Returns:
        True wenn gelöscht, False wenn nicht gefunden.
    """

def delete_fact(self, user_id: str, key: str) -> bool:
    """KV-Fakt per Schlüssel löschen.

    Returns:
        True wenn gelöscht, False wenn nicht gefunden.
    """
```

**FTS5-Sync-Trigger (in `_create_table()` ausführen):**
```sql
-- Nach INSERT
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, content, key, tags)
    VALUES (new.id, new.content, new.key, new.tags);
END;

-- Nach UPDATE
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, content, key, tags)
    VALUES('delete', old.id, old.content, old.key, old.tags);
    INSERT INTO notes_fts(rowid, content, key, tags)
    VALUES (new.id, new.content, new.key, new.tags);
END;

-- Nach DELETE
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, content, key, tags)
    VALUES('delete', old.id, old.content, old.key, old.tags);
END;
```

**Key-Normalisierung:**
```python
@staticmethod
def _normalize_key(key: str) -> str:
    """Normalisiert Keys: lowercase, strip, mehrfache Leerzeichen → einfach."""
    import re
    return re.sub(r'\s+', ' ', key.strip().lower())
```

**Sonstiges:**
- Thread-safe: `check_same_thread=False` (wie ReminderStore)
- WAL-Modus: `PRAGMA journal_mode=WAL`
- `close()` Methode für sauberes Shutdown

---

## 16.2 – NoteCommandHandler (Remote Commands)

### Neue Datei: `src/elder_berry/comms/commands/note_commands.py`

**Klasse:** `NoteCommandHandler(CommandHandler)`

**Commands und Patterns:**

| Command | Pattern / Trigger | Beispiel |
|---|---|---|
| `note_set_fact` | `merk dir:?\s+(.+?)\s+(?:ist|=|:)\s+(.+)` | "merk dir: WLAN Büro ist xyz123" |
| `note_add` | `^notiz:?\s+(.+)` | "notiz: Vermieter heißt Müller, Kaution 1200€" |
| `note_get_fact` | `was ist (.+)\??` | "was ist das WLAN Passwort Büro?" |
| `note_search` | `notiz(?:en)?\s+suche\s+(.+)` | "notizen suche Vermieter" |
| `note_list` | `notizen` (simple_command) | "notizen" |
| `note_delete` | `notiz löschen\s+#?(\d+)` | "notiz löschen #3" |
| `note_delete_fact` | `vergiss\s+(.+)` | "vergiss WLAN Passwort Büro" |

**Keywords:**
```python
@property
def keywords(self) -> dict[str, list[str]]:
    return {
        "note_set_fact": ["merk dir", "merke dir", "speicher dir"],
        "note_add": ["notiz", "notiere"],
        "note_get_fact": ["was ist", "was war", "wie heißt", "wie lautet"],
        "note_search": ["notizen suche", "notiz suche", "suche in notizen"],
        "note_list": ["notizen", "alle notizen", "meine notizen"],
        "note_delete": ["notiz löschen", "lösche notiz"],
        "note_delete_fact": ["vergiss"],
    }
```

**Pattern-Priorität (WICHTIG):**
- `note_get_fact` Pattern (`was ist ...?`) darf NICHT mit allgemeinen LLM-Fragen kollidieren
- Strategie: Zuerst exakten Key-Lookup versuchen. Wenn kein Treffer → Anfrage an LLM durchlassen (kein Intercept)
- Das heißt: `execute("note_get_fact", "was ist das WLAN Passwort Büro?")` versucht Key-Lookup,
  bei Miss gibt es `CommandResult(success=False)` → Bridge leitet an LLM weiter
- "merk dir" und "notiz:" sind eindeutig genug → immer intercepten

**Execute-Methode (Kernlogik):**
```python
def execute(self, command: str, raw_text: str) -> CommandResult:
    match command:
        case "note_set_fact":
            # Pattern: "merk dir: <key> ist/=: <value>"
            # Regex extrahiert key + value
            # → note_store.set_fact(user_id, key, value)
            # Response: "Gemerkt: {key} = {value}"
            # Bei Update: "Aktualisiert: {key} = {value} (vorher: {old})"

        case "note_add":
            # Pattern: "notiz: <freitext>"
            # → note_store.add_note(user_id, content)
            # Response: "Notiz #{id} gespeichert."

        case "note_get_fact":
            # "was ist <key>?"
            # → note_store.get_fact(user_id, key)
            # Treffer: "{key}: {value}"
            # Kein Treffer: CommandResult(success=False) → LLM-Fallthrough

        case "note_search":
            # "notizen suche <query>"
            # → note_store.search(user_id, query)
            # Formatierte Liste oder "Keine Treffer"

        case "note_list":
            # → note_store.list_all(user_id)
            # Formatierte Liste (max 20)

        case "note_delete":
            # "notiz löschen #3"
            # → note_store.delete(note_id)

        case "note_delete_fact":
            # "vergiss WLAN Passwort Büro"
            # → note_store.delete_fact(user_id, key)
```

**User-ID-Handling:**
- `NoteCommandHandler` bekommt `user_id` als Konstruktor-Parameter
- Wird in `MatrixBridge` aus dem Matrix-Event extrahiert (sender)
- Problem: CommandHandler hat aktuell kein User-Kontext pro Aufruf
- Lösung: `execute(command, raw_text)` → Signatur erweitern um optionalen `user_id: str = ""`?
- ODER: NoteCommandHandler speichert Default-User-ID (Single-User-System, nur 1 Matrix-User)
- **Empfehlung:** Default-User aus SecretStore (`matrix_owner_id` oder einfach den Bot-Owner)
  → Single-User-Projekt, kein Multi-Tenant nötig. Überkomplizieren vermeiden.

---

## 16.3 – Integration

### Geänderte Dateien

**`src/elder_berry/comms/remote_commands.py`:**
- NoteCommandHandler importieren
- In `_handlers` Liste eintragen
- Priorität: nach weather_commands, vor advanced_commands
  (Notiz-Patterns sind spezifisch genug, keine Kollisionen erwartet)
- HELP_TEXT ergänzen: Notizen-Sektion

**HELP_TEXT Ergänzung:**
```
📝 Notizen & Wissen:
  merk dir: <key> ist <wert>  – Fakt speichern
  notiz: <text>               – Freitext-Notiz
  was ist <key>?              – Fakt abrufen
  notizen suche <begriff>     – Notizen durchsuchen
  notizen                     – Alle Notizen anzeigen
  notiz löschen #<id>         – Notiz löschen
  vergiss <key>               – Fakt vergessen
```

**`scripts/start_saleria.py`:**
- NoteStore importieren und initialisieren (nach reminder_store, gleiche Stelle)
- An RemoteCommandHandler übergeben: `note_store=note_store`

**`src/elder_berry/character/saleria.yaml`:**
- Remote-Tool-Liste ergänzen: "merk dir: ...", "notiz: ...", "was ist ...?"

**`src/elder_berry/core/assistant.py`:**
- Fallback-Prompt Remote-Tool-Liste ergänzen (gleiche Commands wie saleria.yaml)

---

## 16.4 – Tests

### Neue Datei: `tests/test_note_store.py`

**Tests NoteStore (~25-30 Tests):**
1. Init: DB erstellt, Tabellen + FTS existieren
2. set_fact: neuer Fakt, Rückgabe korrekt
3. set_fact: Update existierender Key (Upsert)
4. set_fact: Key-Normalisierung ("WLAN Büro" == "wlan büro")
5. add_note: Freitext-Notiz, key=None
6. add_note: Mehrere Notizen gleicher User
7. get_fact: existierender Key → Note
8. get_fact: nicht existierender Key → None
9. get_fact: Key eines anderen Users → None (Isolation)
10. search: Treffer in content
11. search: Treffer in key
12. search: Treffer in tags
13. search: Kein Treffer → leere Liste
14. search: Limit wird respektiert
15. search: Prefix-Suche ("Vermi*" findet "Vermieter")
16. list_all: mehrere Notizen, neueste zuerst
17. list_all: Limit wird respektiert
18. list_all: User-Isolation
19. delete: existierende Note → True
20. delete: nicht existierende Note → False
21. delete: FTS-Index wird aktualisiert (Suche findet gelöschte Notiz nicht mehr)
22. delete_fact: per Key löschen
23. delete_fact: nicht existierender Key → False
24. format_short: KV-Fakt Format
25. format_short: Freitext Format (Truncation bei >80 Zeichen)
26. Tags: Komma-separiert speichern und lesen
27. close: Verbindung sauber schließen

### Neue Datei: `tests/test_note_commands.py`

**Tests NoteCommandHandler (~15-20 Tests):**
1. Pattern: "merk dir: WLAN ist xyz" → note_set_fact
2. Pattern: "merk dir WLAN ist xyz" (ohne Doppelpunkt)
3. Pattern: "notiz: Vermieter heißt Müller" → note_add
4. Pattern: "was ist das WLAN?" → note_get_fact
5. Pattern: "notizen suche Vermieter" → note_search
6. Pattern: "notizen" → note_list
7. Pattern: "notiz löschen #3" → note_delete
8. Pattern: "vergiss WLAN Passwort" → note_delete_fact
9. Execute: set_fact + get_fact Roundtrip
10. Execute: note_get_fact Miss → success=False (LLM-Fallthrough)
11. Execute: note_add + note_search Roundtrip
12. Execute: note_list formatierte Ausgabe
13. Execute: note_delete → success=True
14. Execute: note_delete nicht existierend → Fehlermeldung
15. Keywords: alle Keywords korrekt gemappt
16. Keyword-Trigger: "speicher dir" → note_set_fact

---

## 16.5 – Edge Cases & Bekannte Risiken

1. **"was ist"-Kollision mit LLM:** "was ist Photosynthese?" soll NICHT in den NoteStore.
   Lösung: get_fact versucht Lookup → Miss → success=False → Bridge leitet an LLM weiter.
   Das funktioniert nur wenn die Bridge bei `success=False` nicht abbricht.
   → **Prüfe Bridge-Verhalten bei success=False für Remote-Commands.**

2. **FTS5 vs. deutsche Sprache:** FTS5 tokenisiert nach Whitespace/Satzzeichen.
   Deutsche Komposita ("Hausverwaltung") werden nicht in "Haus" + "Verwaltung" zerlegt.
   Akzeptabel für v1. Workaround: User nutzt Prefix-Suche ("Haus*").

3. **Key-Ambiguität:** "merk dir: meine Schwester heißt Anna" – ist "meine Schwester"
   der Key und "Anna" der Wert? Oder ist alles Freitext?
   Regex `(.+?)\s+(?:ist|=|:)\s+(.+)` matcht lazy auf den Key (minimal) → "meine Schwester"
   als Key, "Anna" als Wert. Das passt für die meisten Fälle.
   Fallback: Wenn kein "ist/=/:" gefunden → als Freitext-Notiz speichern, nicht als Fakt.

4. **Upsert-Feedback:** Bei Update eines existierenden Fakts den alten Wert anzeigen:
   "Aktualisiert: WLAN Büro = neues_passwort (vorher: altes_passwort)"

---

## 16.6 – Abhängigkeiten

- **Neue Packages:** Keine (SQLite + FTS5 sind in Python-Stdlib enthalten)
- **Bestehende Imports:** SecretStore (für Default-User-ID), CommandHandler ABC, CommandResult DTO
- **Dateien die gelesen werden müssen BEVOR implementiert wird:**
  - `src/elder_berry/comms/commands/base.py` (CommandHandler ABC) ✅ bereits gelesen
  - `src/elder_berry/comms/commands/weather_commands.py` (als Referenz für Handler-Struktur)
  - `src/elder_berry/tools/reminder_store.py` (als Referenz für SQLite-Pattern) ✅ bereits gelesen
  - `src/elder_berry/comms/remote_commands.py` (Orchestrator, Handler-Registrierung)
  - `scripts/start_saleria.py` (Init-Kette) ✅ bereits gelesen
