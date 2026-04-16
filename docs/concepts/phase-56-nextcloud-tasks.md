# Phase 56 – Nextcloud Tasks als Todo-Backend

## Motivation

Saleria's `TodoStore` (SQLite) und Nextcloud Tasks (CalDAV VTODO) sind
zwei getrennte Systeme. Aufgaben die in Nextcloud Tasks angelegt werden
(Web-UI, DAVx5/Handy) sind für Saleria unsichtbar, und Saleria's Todos
werden nicht aufs Handy synchronisiert. Außerdem hat der TodoStore kein
Fälligkeitsdatum — "aufgaben morgen" ist unbeantwortbar.

**Ziel:** Nextcloud Tasks wird die einzige Aufgaben-Datenquelle. Saleria
liest und schreibt VTODOs direkt per CalDAV. Der SQLite-TodoStore wird
nach Migration deprecated.

## Architektur-Entscheidung

- **Kein Sync-Layer** (TodoStore ↔ Nextcloud): Zu komplex, Conflict-
  Handling, zwei Sources-of-Truth. Stattdessen wird Nextcloud Tasks die
  Single Source of Truth, genau wie CalDAV schon bei Terminen die
  GoogleCalendar-API abgelöst hat (Phase 36.2).
- **Gleiche Credentials**: `nextcloud_url`, `nextcloud_user`,
  `nextcloud_app_password` — identisch mit CalDAVCalendarClient.
- **Gleiche Library**: `caldav` + `icalendar` (bereits in Dependencies).
- **Gleicher Pattern**: Lazy-Init, `_call_with_retry`, graceful degradation.

## VTODO ↔ Saleria Mapping

| VTODO-Property   | Saleria-Feld   | Mapping                                     |
|------------------|----------------|---------------------------------------------|
| `UID`            | `uid: str`     | Direkt übernehmen                           |
| `SUMMARY`        | `text: str`    | Direkt übernehmen                           |
| `PRIORITY`       | `priority: str`| iCal 1-4→"hoch", 5→"mittel", 6-9/0→"niedrig"|
| `CATEGORIES`     | `category: str`| Erste Kategorie, Rest ignorieren            |
| `DUE`            | `due: date ∣ None` | Neues Feld (date, nicht datetime)       |
| `STATUS`         | `done: bool`   | COMPLETED→True, sonst False                 |
| `PERCENT-COMPLETE`| —             | Nicht verwendet (Saleria kennt nur done/offen)|
| `DESCRIPTION`    | `description: str` | Optional, für Briefing nicht relevant   |
| `CREATED`        | `created_at`   | Direkt übernehmen                           |
| `COMPLETED`      | `completed_at` | Direkt übernehmen                           |

### Prioritäts-Mapping (iCal ↔ Saleria)

iCal PRIORITY ist 0-9 (0 = undefiniert, 1 = höchste, 9 = niedrigste).
Nextcloud Tasks/DAVx5 verwenden:
- 1-4 → **hoch** (🔴)
- 5   → **mittel** (🟡)
- 6-9, 0 (undefiniert) → **niedrig** (🟢)

Beim Schreiben: hoch→1, mittel→5, niedrig→0 (undefiniert, Standard).

## Subphasen

### 56.1 – CalDAVTaskClient

Neue Klasse `src/elder_berry/tools/caldav_tasks.py`.

```python
@dataclass(frozen=True)
class TaskItem:
    uid: str
    text: str
    priority: str           # "hoch" | "mittel" | "niedrig"
    category: str           # Erste CATEGORIES oder ""
    done: bool
    due: date | None        # Nur Datum, keine Uhrzeit
    description: str
    created_at: datetime | None
    completed_at: datetime | None

    def format_short(self) -> str:
        """Einzeilige Darstellung (wie Todo.format_short, plus Fälligkeitsdatum)."""
        ...

class CalDAVTaskClient:
    def __init__(self, secret_store: SecretStore) -> None: ...
    def _get_task_list(self): ...  # Lazy-Init, findet Nextcloud Tasks-Liste
    def _call_with_retry(self, operation): ...
    def is_available(self) -> bool: ...

    # --- Lesen ---
    def get_open(self, limit: int = 50) -> list[TaskItem]: ...
    def get_open_by_due(self, target: date) -> list[TaskItem]: ...
    def get_overdue(self) -> list[TaskItem]: ...
    def get_done(self, limit: int = 20) -> list[TaskItem]: ...
    def count_open(self) -> dict[str, int]: ...
    def format_for_briefing(self) -> str: ...

    # --- Schreiben ---
    def add(self, text: str, priority: str = "niedrig",
            category: str = "", due: date | None = None) -> TaskItem: ...
    def complete(self, uid: str) -> TaskItem | None: ...
    def reopen(self, uid: str) -> TaskItem | None: ...
    def update_priority(self, uid: str, priority: str) -> TaskItem | None: ...
    def delete(self, uid: str) -> bool: ...
```

**Wichtige Details:**

- **Task-Liste finden**: Nextcloud Tasks speichert VTODOs in einer
  eigenen CalDAV-Collection. `principal.calendars()` liefert alle
  Collections. Die Task-Liste hat `supported-calendar-component-set`
  mit `VTODO`. Alternativ: `caldav` hat `cal.todos()` Methode.
  Zuerst nach Name "Aufgaben"/"Tasks" suchen, sonst erste mit
  VTODO-Support nehmen.
- **Kein `user_id`-Parameter**: CalDAV kennt nur einen User pro
  Verbindung (Nextcloud-Credentials). Die `user_id`-Parameter aus
  TodoStore fallen weg.
- **ID-Typ ändert sich**: TodoStore nutzt `int` (AUTO_INCREMENT),
  CalDAV nutzt `str` (UUID). Alle Command-Handler müssen auf `str`
  umgestellt werden.
- **`caldav` Todos-API**: `cal.todos()` holt alle offenen VTODOs.
  `cal.todo_by_uid(uid)` holt ein spezifisches. `todo.complete()` und
  `todo.save()` zum Schreiben. Für neue Todos: `cal.save_todo(ical_str)`.

### 56.2 – TodoCommandHandler umverdrahten

`src/elder_berry/comms/commands/todo_commands.py`

**Änderungen:**
- Constructor: `todo_store: TodoStore` → `task_client: CalDAVTaskClient`
- `default_user_id` fällt weg (CalDAV braucht keine User-ID)
- `_cmd_list` ruft `task_client.get_open()` statt `store.get_open(user_id)`
- `_cmd_add` ruft `task_client.add()` statt `store.add(user_id, ...)`
- `_cmd_complete/reopen/delete`: ID-Typ von `int` auf `str` (UUID).
  Regex-Patterns `#?(\d+)` müssen auf `#?(\S+)` oder UUID-Pattern
  angepasst werden. **Achtung:** UUIDs sind unhandlich für Chat-
  Interaktion. Lösung: `format_short()` zeigt eine kurze Nummer
  (z.B. letzte 4 Zeichen der UUID oder ein laufender Index pro
  Abfrage). Details in Implementierung klären.
- `_cmd_filter` erweitern: "morgen", "heute", "überfällig" als neue
  Schlüsselwörter die `get_open_by_due()` bzw. `get_overdue()` aufrufen.
- `execute_cleanup` → `task_client.delete_all_done()` (iteriert über
  `get_done()` und löscht einzeln, CalDAV hat kein Bulk-Delete).

### 56.3 – Due-Date-Support in Commands

Neue Command-Patterns für Fälligkeitsdatum:

```
todo: Arzt anrufen, morgen           → due = morgen
todo: Steuererklärung, hoch, 15.05   → priority=hoch, due=15.05.2026
aufgaben morgen                       → get_open_by_due(morgen)
aufgaben heute                        → get_open_by_due(heute)
aufgaben überfällig                   → get_overdue()
aufgaben diese woche                  → get_open_by_due(Mo-So)
```

**Date-Parsing** (in `_parse_todo_fields` erweitern):
- "heute" → `date.today()`
- "morgen" → `date.today() + 1`
- "übermorgen" → `date.today() + 2`
- Wochentage: "montag" → nächster Montag
- Datum: "15.05" / "15.05.2026" → `date(2026, 5, 15)`

**`_cmd_filter` erweitern** (neue Schlüsselwörter):
- `heute` / `today` → `get_open_by_due(date.today())`
- `morgen` / `tomorrow` → `get_open_by_due(date.today() + 1)`
- `überfällig` / `overdue` → `get_overdue()`
- `woche` / `diese woche` → `get_open_by_due(range Mo-So)`

### 56.4 – SmartContext + BriefingScheduler umstellen

**`smart_context.py`:**
- `_query_todos()`: `todo_store.format_for_briefing(user_id)` →
  `task_client.format_for_briefing()` (kein user_id mehr)
- `SmartContextProvider.__init__`: `todo_store: TodoStore` →
  `task_client: CalDAVTaskClient | None`
- TYPE_CHECKING import anpassen

**`briefing_scheduler.py`:**
- `_build_todo_section()`: Gleiche Umstellung.
- Constructor-Parameter anpassen.

**`remote_commands.py`:**
- TodoCommandHandler-Instanziierung: `todo_store=todo_store` →
  `task_client=task_client`
- `start_saleria.py`: CalDAVTaskClient instanziieren,
  TodoStore-Instanziierung entfernen.

### 56.5 – Migration & Deprecation

1. **Migrations-Script** (`scripts/migrate_todos_to_nextcloud.py`):
   - Liest alle offenen Todos aus `~/.elder-berry/todos.db`
   - Erstellt je ein VTODO in Nextcloud Tasks via CalDAVTaskClient
   - Mapping: `text→SUMMARY`, `priority→PRIORITY`, `category→CATEGORIES`,
     `created_at→CREATED`. Kein DUE (alte Todos hatten keins).
   - Loggt jede Migration, stoppt bei Fehler.
   - Idempotent: Prüft per SUMMARY-Match ob bereits migriert.

2. **TodoStore deprecaten**:
   - `todo_store.py`: Deprecation-Warning im Docstring
   - Alle Imports/Referenzen auf TodoStore entfernen aus:
     - `smart_context.py`
     - `briefing_scheduler.py`
     - `remote_commands.py`
     - `start_saleria.py`
   - `todo_store.py` und `todo_commands.py` (alter Import) bleiben im
     Repo für Referenz, werden aber nicht mehr instanziiert.

## Betroffene Dateien

| Datei | Aktion |
|-------|--------|
| `tools/caldav_tasks.py` | NEU – CalDAVTaskClient + TaskItem |
| `comms/commands/todo_commands.py` | ÄNDERN – auf CalDAVTaskClient umstellen |
| `core/smart_context.py` | ÄNDERN – todo_store → task_client |
| `comms/briefing_scheduler.py` | ÄNDERN – todo_store → task_client |
| `comms/remote_commands.py` | ÄNDERN – Instanziierung umstellen |
| `start_saleria.py` (o.ä. Startup) | ÄNDERN – CalDAVTaskClient statt TodoStore |
| `tools/todo_store.py` | DEPRECATE – nicht mehr verwendet |
| `scripts/migrate_todos_to_nextcloud.py` | NEU – Einmal-Migration |
| `tests/test_caldav_tasks.py` | NEU |
| `tests/test_todo_commands.py` | ÄNDERN – Mocks umstellen |

## Offene Fragen (Implementierung klären)

1. **UUID-Handling in Chat**: CalDAV-UIDs sind lange UUIDs. Für
   "todo erledigt #5" brauchen wir entweder:
   - Kurzform (letzte 4 Hex-Zeichen, Kollisionsrisiko gering bei <1000 Todos)
   - Session-basiertes Index-Mapping (bei jeder Auflistung nummerieren,
     Index → UUID intern auflösen). Vorteil: wie bisher #1, #2, #3.
     Nachteil: Index ist nur gültig bis zur nächsten Abfrage.
   → **Empfehlung: Session-Index.** Nutzerfreundlicher, TodoStore hatte
   auch sequenzielle IDs.

2. **Offline-Verhalten**: Wenn Nextcloud nicht erreichbar → graceful
   degradation wie bei CalDAVCalendarClient. `is_available()` prüft
   Erreichbarkeit. Commands geben Fehlermeldung statt Crash.
