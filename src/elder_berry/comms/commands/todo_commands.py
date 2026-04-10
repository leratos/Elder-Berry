"""TodoCommandHandler – Aufgabenlisten-Commands.

Commands:
- todo: <text>                          → Aufgabe anlegen
- todo: <text>, hoch, Arbeit           → Mit Priorität + Kategorie
- todos / aufgaben                      → Offene Todos anzeigen
- todos hoch / todos Arbeit             → Gefiltert
- todo erledigt #<ID>                   → Als erledigt markieren
- todo wieder öffnen #<ID>              → Erledigt → offen
- todo priorität #<ID> hoch             → Priorität ändern
- todo löschen #<ID>                    → Todo löschen
- todos erledigt                        → Erledigte Todos anzeigen
- todos aufräumen                       → Erledigte löschen
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.tools.todo_store import PRIORITIES

if TYPE_CHECKING:
    from elder_berry.tools.todo_store import TodoStore

logger = logging.getLogger(__name__)

TODO_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?(?:todo|aufgabe)[:\s]+(.+)$", re.IGNORECASE,
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
    r"^(?:todos?|aufgaben)\s+(.+)$", re.IGNORECASE,
)


class TodoCommandHandler(CommandHandler):
    """Aufgabenlisten-Commands für Matrix."""

    def __init__(self, todo_store: TodoStore | None = None,
                 default_user_id: str = "") -> None:
        self._store = todo_store
        self._default_user_id = default_user_id

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
                "todos", "aufgaben", "to-do", "to do",
                "meine aufgaben", "offene aufgaben",
                "was muss ich noch", "aufgabenliste", "todo liste",
            ],
            "todo_add": [
                "neues todo", "neue aufgabe", "todo hinzufügen",
                "aufgabe hinzufügen", "aufgabe anlegen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "todo: <text> – Aufgabe anlegen (optional: , hoch/mittel, Kategorie)",
            "todos – Offene Aufgaben anzeigen",
            "todo erledigt #<ID> – Aufgabe abhaken",
            "todo löschen #<ID> – Aufgabe löschen",
            "todos erledigt – Erledigte anzeigen",
            "todos aufräumen – Alle erledigten löschen",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if not self._store:
            return self.not_configured(command, "Aufgabenliste")
        dispatch = {
            "todos": self._cmd_list, "aufgaben": self._cmd_list,
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
        return CommandResult(command=command, success=False,
                             text=f"Unbekannter Command: {command}")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_add(self, raw_text: str) -> CommandResult:
        match = TODO_ADD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="todo_add", success=False,
                                 text="Text fehlt. Beispiel: todo: Einkaufen gehen")
        fields = self._parse_todo_fields(match.group(1))
        if not fields or not fields.get("text"):
            return CommandResult(command="todo_add", success=False,
                                 text="Text fehlt. Beispiel: todo: Einkaufen gehen, hoch, Haushalt")
        todo = self._store.add(
            self._default_user_id, text=fields["text"],
            priority=fields.get("priority", "niedrig"),
            category=fields.get("category", ""),
        )
        return CommandResult(command="todo_add", success=True,
                             text=f"✅ Todo {todo.format_short()}")

    def _cmd_complete(self, raw_text: str) -> CommandResult:
        match = TODO_COMPLETE_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(command="todo_complete", success=False,
                                 text="Welche Aufgabe? Beispiel: todo erledigt #5")
        tid = int(match.group(1) or match.group(2))
        todo = self._store.complete(tid)
        if todo:
            return CommandResult(command="todo_complete", success=True,
                                 text=f"✅ Erledigt: {todo.text}")
        return CommandResult(command="todo_complete", success=False,
                             text=f"Todo #{tid} nicht gefunden oder bereits erledigt.")

    def _cmd_reopen(self, raw_text: str) -> CommandResult:
        match = TODO_REOPEN_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(command="todo_reopen", success=False,
                                 text="Welche Aufgabe? Beispiel: todo wieder öffnen #5")
        tid = int(match.group(1) or match.group(2))
        todo = self._store.reopen(tid)
        if todo:
            return CommandResult(command="todo_reopen", success=True,
                                 text=f"🔄 Wieder offen: {todo.text}")
        return CommandResult(command="todo_reopen", success=False,
                             text=f"Todo #{tid} nicht gefunden oder nicht erledigt.")

    def _cmd_priority(self, raw_text: str) -> CommandResult:
        match = TODO_PRIORITY_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(command="todo_priority", success=False,
                                 text="Nicht erkannt. Beispiel: todo priorität #5 hoch")
        tid = int(match.group(1) or match.group(3))
        prio = (match.group(2) or match.group(4)).lower()
        try:
            todo = self._store.update_priority(tid, prio)
        except ValueError as e:
            return CommandResult(command="todo_priority", success=False,
                                 text=str(e))
        if todo:
            return CommandResult(command="todo_priority", success=True,
                                 text=f"✅ Priorität: {todo.format_short()}")
        return CommandResult(command="todo_priority", success=False,
                             text=f"Todo #{tid} nicht gefunden.")

    def _cmd_delete(self, raw_text: str) -> CommandResult:
        match = TODO_DELETE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="todo_delete", success=False,
                                 text="Welche Aufgabe? Beispiel: todo löschen #5")
        tid = int(match.group(1))
        if self._store.delete(tid):
            return CommandResult(command="todo_delete", success=True,
                                 text=f"🗑️ Todo #{tid} gelöscht.")
        return CommandResult(command="todo_delete", success=False,
                             text=f"Todo #{tid} nicht gefunden.")

    def _cmd_list(self, _raw_text: str) -> CommandResult:
        todos = self._store.get_open(self._default_user_id)
        if not todos:
            return CommandResult(command="todos", success=True,
                                 text="📋 Keine offenen Todos.")
        lines = [f"📋 {len(todos)} offene Todos:"]
        for t in todos:
            lines.append(f"  {t.format_short()}")
        return CommandResult(command="todos", success=True,
                             text="\n".join(lines))

    def _cmd_filter(self, raw_text: str) -> CommandResult:
        match = TODO_FILTER_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(command="todo_filter", success=False,
                                 text="Format: todos <filter>")
        filter_text = match.group(1).strip().lower()
        uid = self._default_user_id

        # Sonder-Cases
        if filter_text in ("erledigt", "done", "abgehakt"):
            return self._cmd_done()
        if filter_text in ("aufräumen", "bereinigen", "cleanup"):
            return self._cmd_cleanup()

        # Prioritäts-Filter
        if filter_text in PRIORITIES:
            todos = self._store.get_open(uid, priority=filter_text)
        else:
            # Kategorie-Filter
            todos = self._store.get_open(uid, category=filter_text)

        if not todos:
            return CommandResult(command="todo_filter", success=True,
                                 text=f"📋 Keine Todos für '{filter_text}'.")
        lines = [f"📋 {len(todos)} Todos ({filter_text}):"]
        for t in todos:
            lines.append(f"  {t.format_short()}")
        return CommandResult(command="todo_filter", success=True,
                             text="\n".join(lines))

    def _cmd_done(self) -> CommandResult:
        todos = self._store.get_done(self._default_user_id)
        if not todos:
            return CommandResult(command="todos_done", success=True,
                                 text="📋 Keine erledigten Todos.")
        lines = [f"📋 {len(todos)} erledigte Todos:"]
        for t in todos:
            lines.append(f"  {t.format_short()}")
        return CommandResult(command="todos_done", success=True,
                             text="\n".join(lines))

    def _cmd_cleanup(self) -> CommandResult:
        done_todos = self._store.get_done(
            self._default_user_id, limit=100,
        )
        if not done_todos:
            return CommandResult(command="todos_cleanup", success=True,
                                 text="📋 Keine erledigten Todos zum Aufräumen.")
        count = len(done_todos)
        return CommandResult(
            command="todos_cleanup",
            success=True,
            text=f"🗑️ {count} erledigte Todos löschen? Bestätige mit 'ja'.",
            pending_confirmation=True,
            pending_data={
                "action_type": "bulk_delete_todos",
                "count": count,
            },
        )

    def execute_cleanup(self) -> CommandResult:
        """Führt das Aufräumen nach Bestätigung aus."""
        deleted = self._store.delete_all_done(self._default_user_id)
        return CommandResult(command="todos_cleanup", success=True,
                             text=f"✅ {deleted} erledigte Todos gelöscht.")

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_todo_fields(raw: str) -> dict[str, str]:
        """Parst komma-separierte Todo-Felder."""
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            return {}
        result = {"text": parts[0], "priority": "niedrig", "category": ""}
        for part in parts[1:]:
            lower = part.lower()
            if lower in PRIORITIES:
                result["priority"] = lower
            elif not result["category"]:
                result["category"] = part
        return result
