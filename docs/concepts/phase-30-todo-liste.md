# Phase 30 – To-Do / Aufgabenliste (TodoStore)

## Übersicht

Saleria verwaltet Aufgaben ohne feste Zeitbindung. Im Gegensatz zu Erinnerungen
(Phase 8.2, zeitbasiert: "erinnere mich um 18:00") sind Todos zeitlose Aufgaben:
"Milch kaufen", "Dachdecker anrufen", "Steuererklärung machen".

### Abgrenzung: Todo vs. Erinnerung vs. Kalendertermin

| Feature | Zeitbindung | Trigger | Beispiel |
|---------|-------------|---------|----------|
| **Kalendertermin** | Fester Zeitpunkt | Watcher-Notification | "Meeting morgen 14:00" |
| **Erinnerung** | Fester Zeitpunkt | Scheduler feuert | "Erinnere mich um 18:00: Wäsche" |
| **Todo** | Keine | Nutzer fragt / Briefing | "Milch kaufen" |

Todos können optional eine **Priorität** (hoch/mittel/niedrig) und eine
**Kategorie** (Einkauf, Arbeit, Privat, ...) haben, aber beides ist optional.

### User-Flow

```
Nutzer: "todo: Milch kaufen"
Saleria: "✅ Todo #1: Milch kaufen"

Nutzer: "todo: Dachdecker anrufen, hoch, Arbeit"
Saleria: "✅ Todo #2: Dachdecker anrufen (🔴 hoch, Arbeit)"

Nutzer: "todos"
Saleria: "3 offene Todos:
  #1 ⬚ Milch kaufen
  #2 ⬚ Dachdecker anrufen (🔴 hoch, Arbeit)
  #3 ⬚ Steuererklärung (🟡 mittel)"

Nutzer: "todo erledigt #1"
Saleria: "✅ Erledigt: Milch kaufen"

Nutzer: "briefing"
Saleria: "... Wetter ... Termine ... Erinnerungen ...
  📋 3 offene Todos (1 hoch, 1 mittel, 1 niedrig)"
```
---

## 1. TodoStore – Persistenter Aufgabenspeicher

**Datei**: `src/elder_berry/tools/todo_store.py`

Folgt dem ReminderStore/NoteStore-Pattern: SQLite, WAL, Thread-safe.
Eigene DB-Datei (`todos.db`).

### Datenmodell

```python
"""TodoStore – Persistente Aufgabenliste (SQLite).

Speichert Aufgaben ohne feste Zeitbindung mit optionaler Priorität und Kategorie.
Neustart-sicher, Multi-User-fähig (Matrix User-IDs).

Verwendung:
    store = TodoStore()
    t = store.add("@user:matrix.org", "Milch kaufen")
    t = store.add("@user:matrix.org", "Dachdecker anrufen",
                   priority="hoch", category="Arbeit")
    todos = store.get_open("@user:matrix.org")
    store.complete(t.id)
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "todos.db"
_CLEANUP_DAYS = 90  # Erledigte Todos nach 90 Tagen aufräumen

# Gültige Prioritäten
PRIORITIES = ("hoch", "mittel", "niedrig")
PRIORITY_ICONS = {"hoch": "🔴", "mittel": "🟡", "niedrig": "🟢"}


@dataclass(frozen=True)
class Todo:
    """Eine einzelne Aufgabe."""

    id: int
    user_id: str
    text: str
    """Aufgabentext."""

    priority: str
    """Priorität: "hoch", "mittel", "niedrig". Default: "niedrig"."""

    category: str
    """Optionale Kategorie (z.B. "Einkauf", "Arbeit"). Leer wenn nicht gesetzt."""

    done: bool
    """True wenn erledigt."""

    created_at: datetime
    completed_at: datetime | None
    """Zeitpunkt der Erledigung (None wenn offen)."""

    def format_short(self) -> str:
        """Einzeilige Darstellung."""
        check = "☑" if self.done else "⬚"
        prio = PRIORITY_ICONS.get(self.priority, "")
        cat = f", {self.category}" if self.category else ""
        extras = f" ({prio} {self.priority}{cat})" if self.priority != "niedrig" or self.category else ""
        if self.category and self.priority == "niedrig":
            extras = f" ({self.category})"
        return f"#{self.id} {check} {self.text}{extras}"
```
### SQL-Schema und Klasse

```python
class TodoStore:
    """SQLite-basierter Aufgabenspeicher.

    Alle Zeiten werden intern als UTC gespeichert (ISO 8601).
    Thread-safe: check_same_thread=False.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                text         TEXT NOT NULL,
                priority     TEXT NOT NULL DEFAULT 'niedrig',
                category     TEXT NOT NULL DEFAULT '',
                done         INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        self._conn.commit()
```
### Methoden

```python
    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def add(
        self,
        user_id: str,
        text: str,
        priority: str = "niedrig",
        category: str = "",
    ) -> Todo:
        """Aufgabe hinzufügen.

        Args:
            user_id: Matrix-User-ID.
            text: Aufgabentext.
            priority: "hoch", "mittel" oder "niedrig" (default).
            category: Optionale Kategorie.

        Returns:
            Das erstellte Todo.

        Raises:
            ValueError: Bei ungültiger Priorität.
        """
        if priority not in PRIORITIES:
            raise ValueError(
                f"Ungültige Priorität: {priority}. "
                f"Erlaubt: {', '.join(PRIORITIES)}"
            )
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO todos (user_id, text, priority, category, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, text, priority, category, now),
        )
        self._conn.commit()
        return self._get_by_id(cursor.lastrowid)

    def complete(self, todo_id: int) -> Todo | None:
        """Aufgabe als erledigt markieren.

        Returns:
            Aktualisiertes Todo oder None wenn nicht gefunden.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            "UPDATE todos SET done = 1, completed_at = ? WHERE id = ? AND done = 0",
            (now, todo_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            return None
        return self._get_by_id(todo_id)

    def reopen(self, todo_id: int) -> Todo | None:
        """Erledigtes Todo wieder öffnen.

        Returns:
            Aktualisiertes Todo oder None wenn nicht gefunden.
        """
        cursor = self._conn.execute(
            "UPDATE todos SET done = 0, completed_at = NULL WHERE id = ? AND done = 1",
            (todo_id,),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            return None
        return self._get_by_id(todo_id)

    def update_priority(self, todo_id: int, priority: str) -> Todo | None:
        """Priorität ändern.

        Returns:
            Aktualisiertes Todo oder None wenn nicht gefunden.
        """
        if priority not in PRIORITIES:
            raise ValueError(f"Ungültige Priorität: {priority}")
        cursor = self._conn.execute(
            "UPDATE todos SET priority = ? WHERE id = ?",
            (priority, todo_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            return None
        return self._get_by_id(todo_id)
```
```python
    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    def get_open(
        self,
        user_id: str,
        priority: str = "",
        category: str = "",
        limit: int = 50,
    ) -> list[Todo]:
        """Offene Todos eines Users.

        Args:
            user_id: Matrix-User-ID.
            priority: Optional: nur diese Priorität.
            category: Optional: nur diese Kategorie.
            limit: Max. Ergebnisse.

        Returns:
            Liste von Todos, sortiert: hoch → mittel → niedrig, dann nach ID.
        """
        query = "SELECT * FROM todos WHERE user_id = ? AND done = 0"
        params: list = [user_id]

        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if category:
            query += " AND category = ? COLLATE NOCASE"
            params.append(category)

        # Sortierung: hoch=0, mittel=1, niedrig=2, dann älteste zuerst
        query += """
            ORDER BY
                CASE priority
                    WHEN 'hoch' THEN 0
                    WHEN 'mittel' THEN 1
                    WHEN 'niedrig' THEN 2
                END,
                id ASC
            LIMIT ?
        """
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def get_done(
        self, user_id: str, limit: int = 20,
    ) -> list[Todo]:
        """Erledigte Todos (neueste zuerst)."""
        rows = self._conn.execute(
            "SELECT * FROM todos WHERE user_id = ? AND done = 1 "
            "ORDER BY completed_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_todo(r) for r in rows]

    def count_open(self, user_id: str) -> dict[str, int]:
        """Anzahl offener Todos pro Priorität.

        Returns:
            Dict wie {"hoch": 2, "mittel": 1, "niedrig": 5, "total": 8}
        """
        rows = self._conn.execute(
            "SELECT priority, COUNT(*) FROM todos "
            "WHERE user_id = ? AND done = 0 GROUP BY priority",
            (user_id,),
        ).fetchall()
        counts = {p: 0 for p in PRIORITIES}
        for prio, count in rows:
            counts[prio] = count
        counts["total"] = sum(counts.values())
        return counts

    def format_for_briefing(self, user_id: str) -> str:
        """Kompakte Zusammenfassung für das Tages-Briefing.

        Gibt z.B. zurück:
        "📋 5 offene Todos (2 hoch, 1 mittel, 2 niedrig)"
        Oder bei wenigen Todos die Liste direkt.
        """
        counts = self.count_open(user_id)
        total = counts["total"]
        if total == 0:
            return "📋 Keine offenen Todos."

        if total <= 5:
            # Bei wenigen: direkt auflisten
            todos = self.get_open(user_id, limit=5)
            lines = [f"📋 {total} offene Todos:"]
            for t in todos:
                lines.append(f"  {t.format_short()}")
            return "\n".join(lines)

        # Bei vielen: nur Zusammenfassung
        parts = []
        for p in PRIORITIES:
            if counts[p] > 0:
                parts.append(f"{counts[p]} {p}")
        return f"📋 {total} offene Todos ({', '.join(parts)})"
```
```python
    # ------------------------------------------------------------------
    # Löschen + Aufräumen
    # ------------------------------------------------------------------

    def delete(self, todo_id: int) -> bool:
        """Todo per ID löschen (unabhängig vom Status).

        Returns:
            True wenn gelöscht.
        """
        cursor = self._conn.execute(
            "DELETE FROM todos WHERE id = ?", (todo_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_all_done(self, user_id: str) -> int:
        """Alle erledigten Todos eines Users löschen.

        Returns:
            Anzahl gelöschter Todos.
        """
        cursor = self._conn.execute(
            "DELETE FROM todos WHERE user_id = ? AND done = 1",
            (user_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def cleanup(self, days: int = _CLEANUP_DAYS) -> int:
        """Erledigte Todos älter als N Tage aufräumen.

        Wird periodisch aufgerufen (z.B. beim Start oder im Briefing).

        Returns:
            Anzahl aufgeräumter Todos.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cursor = self._conn.execute(
            "DELETE FROM todos WHERE done = 1 AND completed_at < ?",
            (cutoff.isoformat(),),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("TodoStore cleanup: %d erledigte Todos entfernt", deleted)
        return deleted

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _get_by_id(self, todo_id: int) -> Todo:
        """Holt ein Todo per ID (interner Gebrauch nach INSERT/UPDATE)."""
        row = self._conn.execute(
            "SELECT * FROM todos WHERE id = ?", (todo_id,),
        ).fetchone()
        return self._row_to_todo(row)

    @staticmethod
    def _row_to_todo(row: tuple) -> Todo:
        """Konvertiert DB-Row in Todo-DTO."""
        id_, user_id, text, priority, category, done, created_at, completed_at = row
        return Todo(
            id=id_,
            user_id=user_id,
            text=text,
            priority=priority,
            category=category,
            done=bool(done),
            created_at=datetime.fromisoformat(created_at),
            completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
        )

    def close(self) -> None:
        """Verbindung sauber schließen."""
        try:
            self._conn.close()
        except Exception:
            pass
```

**Hinweis**: `from datetime import timedelta` muss im Import ergänzt werden.
---

## 2. TodoCommandHandler – Matrix Commands

**Datei**: `src/elder_berry/comms/commands/todo_commands.py`

### Patterns

```python
"""TodoCommandHandler – Aufgabenlisten-Commands.

Commands:
- todo: <text>                          → Aufgabe anlegen
- todo: <text>, hoch, Arbeit           → Mit Priorität + Kategorie
- todos / aufgaben                      → Offene Todos anzeigen
- todos hoch / todos Arbeit             → Gefiltert nach Priorität/Kategorie
- todo erledigt #<ID>                   → Als erledigt markieren
- todo wieder öffnen #<ID>              → Erledigt → offen
- todo priorität #<ID> hoch             → Priorität ändern
- todo löschen #<ID>                    → Todo löschen
- todos erledigt                        → Erledigte Todos anzeigen
- todos aufräumen                       → Erledigte löschen
"""

# "todo: Milch kaufen" / "todo Milch kaufen" / "aufgabe: Dachdecker anrufen"
TODO_ADD_PATTERN = re.compile(
    r"^(?:todo|aufgabe)[:\s]+(.+)$",
    re.IGNORECASE,
)

# "todo erledigt #3" / "todo #3 erledigt" / "erledigt #3"
TODO_COMPLETE_PATTERN = re.compile(
    r"(?:todo\s+erledigt\s+#?(\d+)"
    r"|todo\s+#?(\d+)\s+erledigt"
    r"|erledigt\s+#?(\d+))",
    re.IGNORECASE,
)

# "todo wieder öffnen #3" / "todo #3 wieder öffnen"
TODO_REOPEN_PATTERN = re.compile(
    r"todo\s+(?:wieder\s+öffnen|reopenen?)\s+#?(\d+)"
    r"|todo\s+#?(\d+)\s+(?:wieder\s+öffnen|reopenen?)",
    re.IGNORECASE,
)

# "todo priorität #3 hoch" / "todo #3 priorität hoch"
TODO_PRIORITY_PATTERN = re.compile(
    r"todo\s+(?:priorität|prio)\s+#?(\d+)\s+(hoch|mittel|niedrig)"
    r"|todo\s+#?(\d+)\s+(?:priorität|prio)\s+(hoch|mittel|niedrig)",
    re.IGNORECASE,
)

# "todo löschen #3"
TODO_DELETE_PATTERN = re.compile(
    r"^todo\s+(?:löschen|lösche|entferne?)\s+#?(\d+)$",
    re.IGNORECASE,
)

# "todos hoch" / "todos Arbeit" / "aufgaben mittel"
TODO_FILTER_PATTERN = re.compile(
    r"^(?:todos?|aufgaben)\s+(.+)$",
    re.IGNORECASE,
)
```
### Klassen-Signatur

```python
class TodoCommandHandler(CommandHandler):
    def __init__(
        self,
        todo_store: TodoStore | None = None,
        default_user_id: str = "",
    ) -> None:
        self._store = todo_store
        self._default_user_id = default_user_id

    @property
    def simple_commands(self) -> set[str]:
        return {"todos", "aufgaben"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (TODO_COMPLETE_PATTERN, "todo_complete", False, True),
            (TODO_REOPEN_PATTERN, "todo_reopen", False, True),
            (TODO_PRIORITY_PATTERN, "todo_priority", False, True),
            (TODO_DELETE_PATTERN, "todo_delete", False, False),
            (TODO_ADD_PATTERN, "todo_add", False, False),
            # TODO_FILTER_PATTERN am Ende (am wenigsten spezifisch):
            (TODO_FILTER_PATTERN, "todo_filter", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "todos": [
                "todos", "aufgaben", "to-do", "to do",
                "meine aufgaben", "offene aufgaben",
                "was muss ich noch", "was steht an",
                "aufgabenliste", "todo liste",
            ],
            "todos_done": [
                "erledigte todos", "erledigte aufgaben",
                "was hab ich erledigt", "abgehakt",
            ],
            "todos_cleanup": [
                "todos aufräumen", "aufgaben aufräumen",
                "erledigte löschen", "todos bereinigen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "todo: <text> – Aufgabe anlegen (optional: , hoch/mittel, Kategorie)",
            "todos – Offene Aufgaben anzeigen",
            "todos <filter> – Gefiltert (hoch/mittel/niedrig oder Kategorie)",
            "todo erledigt #<ID> – Aufgabe abhaken",
            "todo wieder öffnen #<ID> – Aufgabe wieder öffnen",
            "todo priorität #<ID> hoch/mittel/niedrig – Priorität ändern",
            "todo löschen #<ID> – Aufgabe löschen",
            "todos erledigt – Erledigte anzeigen",
            "todos aufräumen – Alle erledigten löschen",
        ]
```
### Parsing-Logik für todo: Komma-separierte Felder

Analog zum Kontaktbuch (Phase 29): flexibles Komma-Format.

```python
def _parse_todo_fields(self, raw: str) -> dict[str, str]:
    """Parst komma-separierte Todo-Felder.

    Erkennt automatisch:
    - Priorität: "hoch", "mittel", "niedrig"
    - Erster non-priority/non-category String: Text
    - Rest: Kategorie

    Beispiele:
    - "Milch kaufen" → {text: "Milch kaufen", priority: "niedrig", category: ""}
    - "Dachdecker anrufen, hoch, Arbeit" → {text: "Dachdecker...", priority: "hoch", category: "Arbeit"}
    - "Geschenk kaufen, Privat" → {text: "Geschenk kaufen", priority: "niedrig", category: "Privat"}
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return {}

    result = {"text": parts[0], "priority": "niedrig", "category": ""}

    for part in parts[1:]:
        lower = part.lower()
        if lower in PRIORITIES:
            result["priority"] = lower
        else:
            # Alles andere ist Kategorie (erste nicht erkannte Angabe)
            if not result["category"]:
                result["category"] = part

    return result
```

### Pattern-Priorität: "todos erledigt" vs TODO_FILTER

"todos erledigt" könnte als TODO_FILTER_PATTERN matchen (filter="erledigt").
Das ist gewollt: `_cmd_todo_filter()` prüft ob der Filter "erledigt" ist
und zeigt dann die erledigten Todos. Kein Keyword-Konflikt nötig.

```python
def _cmd_todo_filter(self, raw_text: str) -> CommandResult:
    match = TODO_FILTER_PATTERN.match(raw_text.strip().lower())
    filter_text = match.group(1).strip()

    # Sonder-Cases
    if filter_text in ("erledigt", "done", "abgehakt"):
        return self._cmd_todos_done()
    if filter_text in ("aufräumen", "bereinigen", "cleanup"):
        return self._cmd_todos_cleanup()

    # Prioritäts-Filter
    if filter_text in PRIORITIES:
        todos = self._store.get_open(self._user_id, priority=filter_text)
        ...

    # Kategorie-Filter (alles andere)
    todos = self._store.get_open(self._user_id, category=filter_text)
    ...
```
---

## 3. Briefing-Integration

**Datei**: `src/elder_berry/comms/briefing_scheduler.py`

Das Tages-Briefing (Phase 8.3) zeigt aktuell: Wetter + Termine + Erinnerungen.
Todos werden als vierter Block ergänzt.

### Änderung in BriefingScheduler

```python
class BriefingScheduler:
    def __init__(
        self,
        # ... bestehende Parameter ...
        todo_store: TodoStore | None = None,  # NEU
    ) -> None:
        # ...
        self._todo_store = todo_store
```

In der Briefing-Generierung (die Methode die den Briefing-Text zusammenbaut):

```python
# Nach Erinnerungen, vor dem Abschluss:
if self._todo_store:
    todo_summary = self._todo_store.format_for_briefing(user_id)
    if todo_summary:
        briefing_parts.append(todo_summary)
```

Das ergibt im Briefing z.B.:

```
☀️ Wetter: 18°C, sonnig, leichter Wind
📅 2 Termine heute: 10:00 Daily, 14:00 Zahnarzt
⏰ 1 offene Erinnerung: 18:00 Wäsche abholen
📋 3 offene Todos (1 hoch, 1 mittel, 1 niedrig)
```
---

## 4. RemoteCommandHandler + Start-Script

### remote_commands.py

```python
from elder_berry.comms.commands.todo_commands import TodoCommandHandler

class RemoteCommandHandler:
    def __init__(
        self,
        # ... bestehende Parameter ...
        todo_store: TodoStore | None = None,  # NEU
    ) -> None:
        # ...
        self._todo: TodoCommandHandler | None = None
        if todo_store is not None:
            self._todo = TodoCommandHandler(
                todo_store=todo_store,
                default_user_id=default_user_id,
            )

        # Handler-Liste: _todo nach _weather (wegen "erledigt" Keyword-Nähe
        # zu Erinnerungen), vor _calendar
        # ACHTUNG: Potenzielle Kollision mit Erinnerungs-Keywords prüfen!
        self._handlers: list[CommandHandler] = [
            self._system,
            self._weather,   # Timer + Erinnerungen
            self._todo,      # NEU – Todos (nach Erinnerungen)
            self._calendar,
            self._mail,
            # ...
        ]
```

### HELP_TEXT Erweiterung

```
📋 Aufgaben / Todos:
  todo: <text> – Aufgabe anlegen
    Beispiel: todo: Milch kaufen
    Mit Priorität: todo: Dachdecker anrufen, hoch, Arbeit
  todos – Offene Aufgaben anzeigen
  todos hoch – Nur hohe Priorität
  todos Arbeit – Nur Kategorie "Arbeit"
  todo erledigt #<ID> – Aufgabe abhaken
  todo wieder öffnen #<ID> – Wieder öffnen
  todo priorität #<ID> hoch/mittel/niedrig – Priorität ändern
  todo löschen #<ID> – Aufgabe löschen
  todos erledigt – Erledigte anzeigen
  todos aufräumen – Alle erledigten löschen
```

### scripts/start.py

```python
from elder_berry.tools.todo_store import TodoStore

todo_store = TodoStore()
todo_store.cleanup()  # Beim Start: alte erledigte Todos aufräumen
logger.info("TodoStore initialisiert: %s", todo_store._db_path)

# An RemoteCommandHandler + BriefingScheduler durchreichen
remote_commands = RemoteCommandHandler(
    # ... bestehende Parameter ...
    todo_store=todo_store,  # NEU
)

briefing_scheduler = BriefingScheduler(
    # ... bestehende Parameter ...
    todo_store=todo_store,  # NEU
)
```
---

## 5. Design-Entscheidungen

1. **Eigene DB-Datei**: `todos.db` — gleiche Begründung wie ContactStore.
   Todos haben ein anderes Lifecycle als Notizen oder Kontakte.

2. **Keine Deadline/Due-Date**: Bewusst weggelassen. Wenn eine Aufgabe ein
   Datum hat, ist es eine Erinnerung oder ein Kalendertermin. Todos sind
   per Definition zeitlos. Das hält das Modell einfach und die Abgrenzung klar.

3. **Prioritäten statt Tags**: Drei feste Stufen (hoch/mittel/niedrig) statt
   freie Tags. Begründung: Tags sind mächtig aber schwer über Sprach-Commands
   zu managen. Prioritäten sind intuitiv ("todo hoch"), sortierbar, und
   reichen für eine persönliche Aufgabenliste.

4. **Kategorien sind freiform**: "Arbeit", "Einkauf", "Privat" — der Nutzer
   entscheidet. Keine Vordefinition, keine Validierung. Wird nur für Filterung
   genutzt.

5. **Cleanup beim Start**: `todo_store.cleanup(90)` beim Anwendungsstart.
   Erledigte Todos älter als 90 Tage werden automatisch gelöscht.
   Kein Cron, kein Scheduler — einfach beim Start.

6. **Sortierung**: Offene Todos immer nach Priorität (hoch → niedrig),
   dann nach ID (älteste zuerst). Das ergibt eine natürliche "dringendste
   zuerst"-Reihenfolge.

---

## 6. Potenzielle Kollisionen

### "erledigt" — Todo vs. Erinnerung

"erledigt #3" könnte sowohl ein Todo als auch eine Erinnerung meinen.
Aktuell hat die Erinnerungs-Commands kein "erledigt"-Pattern (Erinnerungen
werden "gefeuert" oder "gelöscht", nicht "erledigt"). Prüfen ob es
trotzdem Überschneidungen gibt.

→ **TODO_COMPLETE_PATTERN** matcht: "todo erledigt #3", "erledigt #3"
→ Das nackte "erledigt #3" (ohne "todo") ist ambig.

**Lösung**: Das nackte "erledigt #3" im Pattern behalten, aber in der
Handler-Reihenfolge steht _todo NACH _weather (Erinnerungen). Wenn
_weather "erledigt #3" nicht erkennt, fällt es an _todo durch.
Falls _weather es erkennt: Priorität für Erinnerungen.

Alternativ: "erledigt #3" aus TODO_COMPLETE_PATTERN entfernen und nur
"todo erledigt #3" erlauben. Das ist sicherer.

**Empfehlung**: Nur "todo erledigt #3" und "todo #3 erledigt" — das nackte
"erledigt #3" weglassen. Klarheit über Kürze.

```python
# SICHERER: nur mit "todo" Prefix
TODO_COMPLETE_PATTERN = re.compile(
    r"todo\s+erledigt\s+#?(\d+)"
    r"|todo\s+#?(\d+)\s+erledigt",
    re.IGNORECASE,
)
```
### "todo" — Simple Command vs Pattern

"todos" ist ein simple_command (zeigt offene Liste).
"todo: Milch kaufen" wird von TODO_ADD_PATTERN gematcht.
"todo erledigt #3" wird von TODO_COMPLETE_PATTERN gematcht.

Aber: Was passiert bei "todo"? (ohne Doppelpunkt, ohne Parameter)
→ Ist kein simple_command (das ist "todos"), kein Pattern-Match
→ Geht ans LLM

**Lösung**: "todo" (singular, ohne Parameter) auch als simple_command
registrieren → zeigt offene Liste.

```python
@property
def simple_commands(self) -> set[str]:
    return {"todos", "aufgaben", "todo"}
```

---

## 7. Neue und geänderte Dateien

### Neue Dateien

| Datei | Beschreibung |
|-------|-------------|
| `src/elder_berry/tools/todo_store.py` | TodoStore – SQLite Aufgabenspeicher |
| `src/elder_berry/comms/commands/todo_commands.py` | TodoCommandHandler – Matrix Commands |
| `tests/test_todo_store.py` | Tests für TodoStore |
| `tests/test_todo_commands.py` | Tests für TodoCommandHandler |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `src/elder_berry/comms/remote_commands.py` | +todo_store DI, TodoCommandHandler registrieren, HELP_TEXT |
| `src/elder_berry/comms/briefing_scheduler.py` | +todo_store DI, Todo-Block im Briefing |
| `scripts/start.py` | TodoStore erstellen + an RemoteCommandHandler + BriefingScheduler durchreichen |
---

## 8. Tests

### test_todo_store.py

```
TestTodoStore:
  test_add_default_priority              – Default "niedrig"
  test_add_with_priority                 – "hoch" gesetzt
  test_add_with_category                 – Kategorie gesetzt
  test_add_invalid_priority              – ValueError bei "dringend"
  test_complete                          – done=True, completed_at gesetzt
  test_complete_already_done             – Schon erledigt → None
  test_complete_not_found                – Unbekannte ID → None
  test_reopen                            – done=False, completed_at=None
  test_reopen_not_done                   – Offenes Todo → None
  test_update_priority                   – Priorität ändern
  test_update_priority_invalid           – ValueError
  test_get_open                          – Nur offene Todos
  test_get_open_sorted_by_priority       – hoch vor mittel vor niedrig
  test_get_open_filter_priority          – Nur "hoch" Todos
  test_get_open_filter_category          – Nur Kategorie "Arbeit"
  test_get_done                          – Nur erledigte Todos
  test_count_open                        – Dict mit Counts pro Priorität
  test_count_open_empty                  – Alles 0 + total=0
  test_format_for_briefing_none          – "Keine offenen Todos"
  test_format_for_briefing_few           – ≤5 → direkte Liste
  test_format_for_briefing_many          – >5 → Zusammenfassung
  test_delete                            – Per ID löschen → True
  test_delete_not_found                  – Unbekannte ID → False
  test_delete_all_done                   – Alle erledigten weg, offene bleiben
  test_cleanup                           – Alte erledigte gelöscht
  test_cleanup_keeps_recent              – Frisch erledigte bleiben
  test_multi_user_isolation              – User A sieht User B's Todos nicht
  test_close                             – Verbindung sauber schließen
  test_format_short                      – Einzeilige Darstellung
  test_format_short_with_priority        – Emoji für Priorität
  test_format_short_with_category        – Kategorie angezeigt
```
### test_todo_commands.py

```
TestTodoAddPattern:
  test_todo_colon_text                   – "todo: Milch kaufen" → match
  test_todo_space_text                   – "todo Milch kaufen" → match
  test_aufgabe_colon                     – "aufgabe: Dachdecker" → match
  test_no_match_todos                    – "todos" → kein Match (simple_command)
  test_no_match_todo_erledigt            – "todo erledigt #3" → kein Match (is COMPLETE)

TestTodoCompletePattern:
  test_todo_erledigt_id                  – "todo erledigt #3" → match
  test_todo_id_erledigt                  – "todo #3 erledigt" → match
  test_no_naked_erledigt                 – "erledigt #3" → kein Match (sicher)

TestTodoReopenPattern:
  test_reopen                            – "todo wieder öffnen #3" → match
  test_reopen_reverse                    – "todo #3 wieder öffnen" → match

TestTodoPriorityPattern:
  test_prio_change                       – "todo priorität #3 hoch" → match
  test_prio_short                        – "todo prio #3 mittel" → match

TestTodoDeletePattern:
  test_delete                            – "todo löschen #3" → match

TestTodoFilterPattern:
  test_filter_priority                   – "todos hoch" → match
  test_filter_category                   – "todos Arbeit" → match
  test_filter_erledigt                   – "todos erledigt" → match

TestParseTodoFields:
  test_text_only                         – {text: "Milch", priority: "niedrig", category: ""}
  test_with_priority                     – {text: "X", priority: "hoch", category: ""}
  test_with_category                     – {text: "X", priority: "niedrig", category: "Arbeit"}
  test_all_fields                        – {text: "X", priority: "hoch", category: "Arbeit"}
  test_empty                             – Leerer Input → {}

TestCmdTodoAdd:
  test_add_success                       – Todo wird angelegt, Bestätigung
  test_add_with_priority_and_category    – Felder korrekt geparst
  test_no_store                          – Fehlermeldung

TestCmdTodoComplete:
  test_complete_success                  – Erledigt + Bestätigung
  test_complete_not_found                – Fehler

TestCmdTodoList:
  test_list_open                         – Offene Todos anzeigen
  test_list_empty                        – "Keine offenen Todos"
  test_list_filter_priority              – Gefiltert nach Priorität
  test_list_filter_category              – Gefiltert nach Kategorie
  test_list_done                         – Erledigte anzeigen

TestCmdTodoDelete:
  test_delete_success                    – Gelöscht + Bestätigung
  test_delete_not_found                  – Fehler

TestTodoKeywords:
  test_keyword_registration              – Keywords sind registriert
  test_command_descriptions              – Beschreibungen vorhanden
  test_simple_commands                   – "todos", "aufgaben", "todo" registriert

TestTodoCollisions:
  test_no_collision_with_erinnerung      – "erinnere mich" → NICHT als todo erkannt
  test_no_collision_with_timer           – "timer 20 min" → NICHT als todo erkannt
```
---

## 9. Implementierungsreihenfolge für Claude Code

### Schritt 1: TodoStore

1. **`todo_store.py`**: Neue Datei – SQLite, alle CRUD-Methoden + cleanup + format_for_briefing
   + `test_todo_store.py`

### Schritt 2: TodoCommandHandler

2. **`todo_commands.py`**: Neue Datei – alle Patterns + Commands
   + `test_todo_commands.py`
   Beachte: TODO_COMPLETE_PATTERN NUR mit "todo" Prefix (kein nacktes "erledigt #3")

### Schritt 3: Integration

3. **`remote_commands.py`**: todo_store DI, TodoCommandHandler registrieren
   + HELP_TEXT ergänzen
   + Handler-Reihenfolge: nach _weather, vor _calendar
4. **`briefing_scheduler.py`**: todo_store DI, Todo-Block im Briefing
   Lies zuerst die aktuelle briefing_scheduler.py um den genauen Einfügepunkt
   zu finden (nach Erinnerungen, vor Abschluss).
5. **`scripts/start.py`**: TodoStore erstellen + cleanup() + durchreichen

### Schritt 4: Tests

6. Alle bestehenden Tests + neue Tests ausführen
   Besonders prüfen: keine Kollision mit Erinnerungs-Commands

---

## 10. Hinweise für Claude Code

1. **ReminderStore als Vorlage**: TodoStore folgt dem ReminderStore-Pattern
   (SQLite, WAL, Thread-safe, _row_to_dto, close()). Kein FTS5 nötig —
   Todos werden nicht volltextdurchsucht, nur per Priorität/Kategorie gefiltert.

2. **BriefingScheduler lesen**: Vor dem Ändern die aktuelle Datei komplett lesen.
   Die Briefing-Generierung könnte in einer eigenen Methode oder inline sein.
   Den Todo-Block nach dem Erinnerungs-Block einfügen.

3. **TODO_COMPLETE_PATTERN sicher halten**: Kein nacktes "erledigt #3"!
   Nur "todo erledigt #3" und "todo #3 erledigt". Das vermeidet Kollisionen
   mit potentiellen Erinnerungs-Commands.

4. **"todo" als simple_command**: Sowohl "todo" als auch "todos" und "aufgaben"
   als simple_commands registrieren. Alle drei zeigen die offene Liste.

5. **Pattern-Reihenfolge in patterns()**: TODO_COMPLETE und TODO_REOPEN vor
   TODO_ADD, weil "todo erledigt #3" sonst als "todo: erledigt #3" (Add)
   gematcht werden könnte. TODO_FILTER am Ende (least specific).

6. **Briefing format_for_briefing()**: Lebt im TodoStore selbst (nicht im
   Command-Handler). Der BriefingScheduler ruft es direkt auf — analog zu
   wie Wetter, Kalender, Erinnerungen ihre Briefing-Blöcke liefern.

7. **Plattformhinweis**: Alles plattformunabhängig.

8. **Branch**: `feature/phase-30-todo-liste`
