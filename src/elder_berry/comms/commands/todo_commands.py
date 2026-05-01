"""TodoCommandHandler – Aufgabenlisten-Commands (Nextcloud Tasks).

Commands:
- todo: <text>                          → Aufgabe anlegen
- todo: <text>, hoch, Arbeit           → Mit Priorität + Kategorie
- todos / aufgaben                      → Offene Aufgaben anzeigen
- todos hoch / todos Arbeit             → Gefiltert
- todo erledigt #<Nr>                   → Als erledigt markieren
- todo wieder öffnen #<Nr>              → Erledigt → offen
- todo priorität #<Nr> hoch             → Priorität ändern
- todo löschen #<Nr>                    → Aufgabe löschen
- todos erledigt                        → Erledigte Aufgaben anzeigen
- todos aufräumen                       → Erledigte löschen

Nummern (#1, #2, ...) sind Session-Indizes, die bei jeder Auflistung
neu vergeben werden. Intern werden sie auf CalDAV-UIDs aufgelöst.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.tools.caldav_tasks import PRIORITIES

if TYPE_CHECKING:
    from elder_berry.tools.caldav_tasks import CalDAVTaskClient

logger = logging.getLogger(__name__)

TODO_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?(?:todo|aufgabe)[:\s]+(.+)$",
    re.IGNORECASE,
)

TODO_COMPLETE_PATTERN = re.compile(
    r"(?:todo|aufgabe)\s+erledigt\s+#?(\d+)"
    r"|(?:todo|aufgabe)\s+#?(\d+)\s+erledigt",
    re.IGNORECASE,
)

TODO_REOPEN_PATTERN = re.compile(
    r"todo\s+(?:wieder\s+öffnen|reopenen?)\s+#?(\d+)"
    r"|todo\s+#?(\d+)\s+(?:wieder\s+öffnen|reopenen?)",
    re.IGNORECASE,
)

TODO_PRIORITY_PATTERN = re.compile(
    r"todo\s+(?:priorität|prio)\s+#?(\d+)\s+(hoch|mittel|niedrig)"
    r"|todo\s+#?(\d+)\s+(?:priorität|prio)\s+(hoch|mittel|niedrig)",
    re.IGNORECASE,
)

TODO_DELETE_PATTERN = re.compile(
    r"^(?:bitte\s+)?todo\s+(?:löschen|lösche|entferne?)\s+#?(\d+)$",
    re.IGNORECASE,
)

TODO_FILTER_PATTERN = re.compile(
    r"^(?:todos?|aufgaben)\s+(.+)$",
    re.IGNORECASE,
)


class TodoCommandHandler(CommandHandler):
    """Aufgabenlisten-Commands für Matrix (Nextcloud Tasks Backend)."""

    def __init__(
        self,
        task_client: CalDAVTaskClient | None = None,
    ) -> None:
        self._client = task_client
        # Session-Index: Nummer → UUID (wird bei jeder Auflistung neu befüllt)
        self._index_map: dict[int, str] = {}

    @property
    def simple_commands(self) -> set[str]:
        return {"todos", "aufgaben", "todo"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (TODO_COMPLETE_PATTERN, "todo_complete", False, True),
            (TODO_REOPEN_PATTERN, "todo_reopen", False, True),
            (TODO_PRIORITY_PATTERN, "todo_priority", False, True),
            (TODO_DELETE_PATTERN, "todo_delete", False, False),
            (TODO_ADD_PATTERN, "todo_add", False, False),
            (TODO_FILTER_PATTERN, "todo_filter", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "todos": [
                "todos",
                "aufgaben",
                "to-do",
                "to do",
                "meine aufgaben",
                "offene aufgaben",
                "was muss ich noch",
                "aufgabenliste",
                "todo liste",
            ],
            "todo_add": [
                "neues todo",
                "neue aufgabe",
                "todo hinzufügen",
                "aufgabe hinzufügen",
                "aufgabe anlegen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "todo: <text> – Aufgabe anlegen (optional: , hoch/mittel, Kategorie)",
            "todos – Offene Aufgaben anzeigen",
            "todo erledigt #<Nr> – Aufgabe abhaken",
            "todo löschen #<Nr> – Aufgabe löschen",
            "todos erledigt – Erledigte anzeigen",
            "todos aufräumen – Alle erledigten löschen",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if not self._client:
            return self.not_configured(command, "Aufgabenliste")
        dispatch = {
            "todos": self._cmd_list,
            "aufgaben": self._cmd_list,
            "todo": self._cmd_list,
            "todo_add": self._cmd_add,
            "todo_complete": self._cmd_complete,
            "todo_reopen": self._cmd_reopen,
            "todo_priority": self._cmd_priority,
            "todo_delete": self._cmd_delete,
            "todo_filter": self._cmd_filter,
        }
        handler = dispatch.get(command)
        if handler:
            return handler(raw_text)
        return CommandResult(
            command=command, success=False, text=f"Unbekannter Command: {command}"
        )

    # ------------------------------------------------------------------
    # Session-Index
    # ------------------------------------------------------------------

    def _build_index(self, items) -> None:
        """Baut den Session-Index auf: #1 → uid, #2 → uid, ..."""
        self._index_map = {i + 1: item.uid for i, item in enumerate(items)}

    def _resolve_index(self, index: int) -> str | None:
        """Löst einen Session-Index (#N) auf die CalDAV-UID auf."""
        return self._index_map.get(index)

    def _format_items(self, items, header: str) -> str:
        """Formatiert Items mit Session-Index-Nummern."""
        self._build_index(items)
        lines = [header]
        for i, item in enumerate(items, 1):
            lines.append(f"  #{i} {item.format_short()}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_add(self, raw_text: str) -> CommandResult:
        match = TODO_ADD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="todo_add",
                success=False,
                text="Text fehlt. Beispiel: todo: Einkaufen gehen",
            )
        fields = self._parse_todo_fields(match.group(1))
        if not fields or not fields.get("text"):
            return CommandResult(
                command="todo_add",
                success=False,
                text="Text fehlt. Beispiel: todo: Einkaufen gehen, hoch, Haushalt",
            )
        item = self._client.add(
            text=fields["text"],
            priority=fields.get("priority", "niedrig"),
            category=fields.get("category", ""),
            due=fields.get("due"),
        )
        return CommandResult(
            command="todo_add", success=True, text=f"✅ Aufgabe: {item.format_short()}"
        )

    def _cmd_complete(self, raw_text: str) -> CommandResult:
        match = TODO_COMPLETE_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="todo_complete",
                success=False,
                text="Welche Aufgabe? Beispiel: todo erledigt #1",
            )
        idx = int(match.group(1) or match.group(2))
        uid = self._resolve_index(idx)
        if not uid:
            return CommandResult(
                command="todo_complete",
                success=False,
                text=f"Aufgabe #{idx} nicht im Index. "
                "Zeige zuerst die Liste mit 'todos'.",
            )
        item = self._client.complete(uid)
        if item:
            return CommandResult(
                command="todo_complete", success=True, text=f"✅ Erledigt: {item.text}"
            )
        return CommandResult(
            command="todo_complete",
            success=False,
            text=f"Aufgabe #{idx} nicht gefunden oder bereits erledigt.",
        )

    def _cmd_reopen(self, raw_text: str) -> CommandResult:
        match = TODO_REOPEN_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="todo_reopen",
                success=False,
                text="Welche Aufgabe? Beispiel: todo wieder öffnen #1",
            )
        idx = int(match.group(1) or match.group(2))
        uid = self._resolve_index(idx)
        if not uid:
            return CommandResult(
                command="todo_reopen",
                success=False,
                text=f"Aufgabe #{idx} nicht im Index. "
                "Zeige zuerst die Liste mit 'todos erledigt'.",
            )
        item = self._client.reopen(uid)
        if item:
            return CommandResult(
                command="todo_reopen",
                success=True,
                text=f"🔄 Wieder offen: {item.text}",
            )
        return CommandResult(
            command="todo_reopen",
            success=False,
            text=f"Aufgabe #{idx} nicht gefunden oder nicht erledigt.",
        )

    def _cmd_priority(self, raw_text: str) -> CommandResult:
        match = TODO_PRIORITY_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="todo_priority",
                success=False,
                text="Nicht erkannt. Beispiel: todo priorität #1 hoch",
            )
        idx = int(match.group(1) or match.group(3))
        prio = (match.group(2) or match.group(4)).lower()
        uid = self._resolve_index(idx)
        if not uid:
            return CommandResult(
                command="todo_priority",
                success=False,
                text=f"Aufgabe #{idx} nicht im Index. "
                "Zeige zuerst die Liste mit 'todos'.",
            )
        try:
            item = self._client.update_priority(uid, prio)
        except ValueError as e:
            return CommandResult(command="todo_priority", success=False, text=str(e))
        if item:
            return CommandResult(
                command="todo_priority",
                success=True,
                text=f"✅ Priorität: {item.format_short()}",
            )
        return CommandResult(
            command="todo_priority",
            success=False,
            text=f"Aufgabe #{idx} nicht gefunden.",
        )

    def _cmd_delete(self, raw_text: str) -> CommandResult:
        match = TODO_DELETE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="todo_delete",
                success=False,
                text="Welche Aufgabe? Beispiel: todo löschen #1",
            )
        idx = int(match.group(1))
        uid = self._resolve_index(idx)
        if not uid:
            return CommandResult(
                command="todo_delete",
                success=False,
                text=f"Aufgabe #{idx} nicht im Index. "
                "Zeige zuerst die Liste mit 'todos'.",
            )
        if self._client.delete(uid):
            return CommandResult(
                command="todo_delete", success=True, text=f"🗑️ Aufgabe #{idx} gelöscht."
            )
        return CommandResult(
            command="todo_delete", success=False, text=f"Aufgabe #{idx} nicht gefunden."
        )

    def _cmd_list(self, _raw_text: str) -> CommandResult:
        items = self._client.get_open()
        if not items:
            return CommandResult(
                command="todos", success=True, text="📋 Keine offenen Aufgaben."
            )
        text = self._format_items(
            items,
            f"📋 {len(items)} offene Aufgaben:",
        )
        return CommandResult(command="todos", success=True, text=text)

    def _cmd_filter(self, raw_text: str) -> CommandResult:
        match = TODO_FILTER_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="todo_filter", success=False, text="Format: todos <filter>"
            )
        filter_text = match.group(1).strip().lower()

        # Sonder-Cases
        if filter_text in ("erledigt", "done", "abgehakt"):
            return self._cmd_done()
        if filter_text in ("aufräumen", "bereinigen", "cleanup"):
            return self._cmd_cleanup()

        # Datums-Filter
        if filter_text in ("heute", "today"):
            return self._cmd_due_date(date.today(), "heute")
        if filter_text in ("morgen", "tomorrow"):
            return self._cmd_due_date(
                date.today() + timedelta(days=1),
                "morgen",
            )
        if filter_text in ("überfällig", "overdue", "ueberfaellig"):
            return self._cmd_overdue()
        if filter_text in (
            "woche",
            "diese woche",
            "this week",
        ):
            return self._cmd_due_week()

        # Prioritäts-Filter
        if filter_text in PRIORITIES:
            all_open = self._client.get_open()
            items = [t for t in all_open if t.priority == filter_text]
        else:
            # Kategorie-Filter (case-insensitive)
            all_open = self._client.get_open()
            items = [t for t in all_open if t.category.lower() == filter_text]

        if not items:
            return CommandResult(
                command="todo_filter",
                success=True,
                text=f"📋 Keine Aufgaben für '{filter_text}'.",
            )
        text = self._format_items(
            items,
            f"📋 {len(items)} Aufgaben ({filter_text}):",
        )
        return CommandResult(command="todo_filter", success=True, text=text)

    def _cmd_due_date(
        self,
        target: date,
        label: str,
    ) -> CommandResult:
        """Aufgaben mit Fälligkeit an einem bestimmten Datum."""
        items = self._client.get_open_by_due(target)
        if not items:
            return CommandResult(
                command="todo_filter",
                success=True,
                text=f"📋 Keine Aufgaben fällig {label} ({target.strftime('%d.%m.')}).",
            )
        text = self._format_items(
            items,
            f"📋 {len(items)} Aufgaben fällig {label} ({target.strftime('%d.%m.')}):",
        )
        return CommandResult(command="todo_filter", success=True, text=text)

    def _cmd_overdue(self) -> CommandResult:
        """Überfällige Aufgaben."""
        items = self._client.get_overdue()
        if not items:
            return CommandResult(
                command="todo_filter",
                success=True,
                text="📋 Keine überfälligen Aufgaben. 👍",
            )
        text = self._format_items(
            items,
            f"⚠ {len(items)} überfällige Aufgaben:",
        )
        return CommandResult(command="todo_filter", success=True, text=text)

    def _cmd_due_week(self) -> CommandResult:
        """Aufgaben fällig diese Woche (Mo–So)."""
        today = date.today()
        # Montag dieser Woche
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        items = self._client.get_open_by_due_range(monday, sunday)
        if not items:
            return CommandResult(
                command="todo_filter",
                success=True,
                text=f"📋 Keine Aufgaben fällig diese Woche "
                f"({monday.strftime('%d.%m.')}–{sunday.strftime('%d.%m.')}).",
            )
        text = self._format_items(
            items,
            f"📋 {len(items)} Aufgaben diese Woche "
            f"({monday.strftime('%d.%m.')}–{sunday.strftime('%d.%m.')}):",
        )
        return CommandResult(command="todo_filter", success=True, text=text)

    def _cmd_done(self) -> CommandResult:
        items = self._client.get_done()
        if not items:
            return CommandResult(
                command="todos_done", success=True, text="📋 Keine erledigten Aufgaben."
            )
        text = self._format_items(
            items,
            f"📋 {len(items)} erledigte Aufgaben:",
        )
        return CommandResult(command="todos_done", success=True, text=text)

    def _cmd_cleanup(self) -> CommandResult:
        done_items = self._client.get_done(limit=100)
        if not done_items:
            return CommandResult(
                command="todos_cleanup",
                success=True,
                text="📋 Keine erledigten Aufgaben zum Aufräumen.",
            )
        count = len(done_items)
        return CommandResult(
            command="todos_cleanup",
            success=True,
            text=f"🗑️ {count} erledigte Aufgaben löschen? Bestätige mit 'ja'.",
            pending_confirmation=True,
            pending_data={
                "action_type": "bulk_delete_todos",
                "count": count,
            },
        )

    def execute_cleanup(self) -> CommandResult:
        """Führt das Aufräumen nach Bestätigung aus."""
        deleted = self._client.delete_all_done()
        return CommandResult(
            command="todos_cleanup",
            success=True,
            text=f"✅ {deleted} erledigte Aufgaben gelöscht.",
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_todo_fields(raw: str) -> dict:
        """Parst komma-separierte Todo-Felder inkl. Fälligkeitsdatum.

        Format: text[, priorität][, kategorie][, datum]
        Datum: heute, morgen, übermorgen, Wochentag, DD.MM., DD.MM.YYYY
        """
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            return {}
        result: dict = {
            "text": parts[0],
            "priority": "niedrig",
            "category": "",
            "due": None,
        }
        for part in parts[1:]:
            lower = part.lower()
            if lower in PRIORITIES:
                result["priority"] = lower
                continue
            parsed_date = _parse_date_token(lower)
            if parsed_date is not None:
                result["due"] = parsed_date
                continue
            if not result["category"]:
                result["category"] = part
        return result


# ── Date-Parsing ─────────────────────────────────────────────────────

_WEEKDAYS_DE = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonntag": 6,
}

_DATE_PATTERN = re.compile(
    r"^(\d{1,2})\.(\d{1,2})\.(?:(\d{4}))?$",
)


def _parse_date_token(token: str) -> date | None:
    """Parst ein einzelnes Datums-Token.

    Unterstützt:
    - heute, morgen, übermorgen
    - Wochentage (nächster Montag, etc.)
    - DD.MM. / DD.MM.YYYY
    """
    today = date.today()

    if token in ("heute", "today"):
        return today
    if token in ("morgen", "tomorrow"):
        return today + timedelta(days=1)
    if token in ("übermorgen", "uebermorgen"):
        return today + timedelta(days=2)

    # Wochentag
    if token in _WEEKDAYS_DE:
        target_weekday = _WEEKDAYS_DE[token]
        days_ahead = target_weekday - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    # DD.MM. oder DD.MM.YYYY
    match = _DATE_PATTERN.match(token)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_str = match.group(3)
        year = int(year_str) if year_str else today.year
        try:
            result = date(year, month, day)
            # Wenn kein Jahr angegeben und Datum in Vergangenheit → nächstes Jahr
            if not year_str and result < today:
                result = date(year + 1, month, day)
            return result
        except ValueError:
            return None

    return None
