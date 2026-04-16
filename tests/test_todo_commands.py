"""Tests für TodoCommandHandler (Phase 56.2 – Nextcloud Tasks Backend)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.todo_commands import (
    TODO_ADD_PATTERN, TODO_COMPLETE_PATTERN, TODO_DELETE_PATTERN,
    TODO_FILTER_PATTERN, TODO_PRIORITY_PATTERN, TODO_REOPEN_PATTERN,
    TodoCommandHandler,
)
from elder_berry.tools.caldav_tasks import TaskItem


# ── Helpers ──────────────────────────────────────────────────────────

def _make_task(
    uid: str = "uid-1",
    text: str = "Test",
    priority: str = "niedrig",
    category: str = "",
    done: bool = False,
    due: date | None = None,
) -> TaskItem:
    return TaskItem(
        uid=uid, text=text, priority=priority, category=category,
        done=done, due=due, description="",
        created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        completed_at=None,
    )


def _make_client() -> MagicMock:
    """Erstellt einen Mock-CalDAVTaskClient."""
    client = MagicMock()
    client.get_open.return_value = []
    client.get_done.return_value = []
    return client


@pytest.fixture()
def client() -> MagicMock:
    return _make_client()


@pytest.fixture()
def handler(client: MagicMock) -> TodoCommandHandler:
    return TodoCommandHandler(task_client=client)


# ── Pattern Tests ──

class TestTodoAddPattern:
    def test_todo_colon_text(self) -> None:
        m = TODO_ADD_PATTERN.match("todo: Milch kaufen")
        assert m and m.group(1) == "Milch kaufen"

    def test_todo_space_text(self) -> None:
        m = TODO_ADD_PATTERN.match("todo Milch kaufen")
        assert m and m.group(1) == "Milch kaufen"

    def test_aufgabe_colon(self) -> None:
        m = TODO_ADD_PATTERN.match("aufgabe: Dachdecker")
        assert m and m.group(1) == "Dachdecker"

    def test_no_match_todos(self) -> None:
        assert TODO_ADD_PATTERN.match("todos") is None


class TestTodoCompletePattern:
    def test_todo_erledigt_id(self) -> None:
        m = TODO_COMPLETE_PATTERN.search("todo erledigt #3")
        assert m and (m.group(1) or m.group(2)) == "3"

    def test_todo_id_erledigt(self) -> None:
        m = TODO_COMPLETE_PATTERN.search("todo #3 erledigt")
        assert m is not None

    def test_no_naked_erledigt(self) -> None:
        assert TODO_COMPLETE_PATTERN.search("erledigt #3") is None


class TestTodoReopenPattern:
    def test_reopen(self) -> None:
        m = TODO_REOPEN_PATTERN.search("todo wieder öffnen #3")
        assert m is not None

    def test_reopen_reverse(self) -> None:
        m = TODO_REOPEN_PATTERN.search("todo #3 wieder öffnen")
        assert m is not None


class TestTodoPriorityPattern:
    def test_prio_change(self) -> None:
        m = TODO_PRIORITY_PATTERN.search("todo priorität #3 hoch")
        assert m is not None

    def test_prio_short(self) -> None:
        m = TODO_PRIORITY_PATTERN.search("todo prio #3 mittel")
        assert m is not None


class TestTodoDeletePattern:
    def test_delete(self) -> None:
        m = TODO_DELETE_PATTERN.match("todo löschen #3")
        assert m and m.group(1) == "3"


class TestTodoFilterPattern:
    def test_filter_priority(self) -> None:
        m = TODO_FILTER_PATTERN.match("todos hoch")
        assert m and m.group(1) == "hoch"

    def test_filter_category(self) -> None:
        m = TODO_FILTER_PATTERN.match("todos Arbeit")
        assert m and m.group(1) == "Arbeit"


# ── Parsing Tests ──

class TestParseTodoFields:
    def test_text_only(self) -> None:
        h = TodoCommandHandler()
        r = h._parse_todo_fields("Milch kaufen")
        assert r["text"] == "Milch kaufen"
        assert r["priority"] == "niedrig"
        assert r["category"] == ""

    def test_with_priority(self) -> None:
        h = TodoCommandHandler()
        r = h._parse_todo_fields("Dachdecker, hoch")
        assert r["priority"] == "hoch"

    def test_with_category(self) -> None:
        h = TodoCommandHandler()
        r = h._parse_todo_fields("Einkaufen, Privat")
        assert r["category"] == "Privat"

    def test_all_fields(self) -> None:
        h = TodoCommandHandler()
        r = h._parse_todo_fields("Dachdecker anrufen, hoch, Arbeit")
        assert r["text"] == "Dachdecker anrufen"
        assert r["priority"] == "hoch"
        assert r["category"] == "Arbeit"

    def test_empty(self) -> None:
        h = TodoCommandHandler()
        assert h._parse_todo_fields("") == {}


# ── Session-Index Tests ──

class TestSessionIndex:
    def test_build_and_resolve(self, handler: TodoCommandHandler) -> None:
        items = [_make_task(uid="aaa"), _make_task(uid="bbb")]
        handler._build_index(items)
        assert handler._resolve_index(1) == "aaa"
        assert handler._resolve_index(2) == "bbb"
        assert handler._resolve_index(3) is None

    def test_index_resets_on_new_list(self, handler: TodoCommandHandler) -> None:
        handler._build_index([_make_task(uid="old")])
        assert handler._resolve_index(1) == "old"

        handler._build_index([_make_task(uid="new")])
        assert handler._resolve_index(1) == "new"

    def test_format_items_includes_numbers(
        self, handler: TodoCommandHandler,
    ) -> None:
        items = [_make_task(uid="a", text="Erste"), _make_task(uid="b", text="Zweite")]
        text = handler._format_items(items, "Header:")
        assert "#1" in text
        assert "#2" in text
        assert "Erste" in text
        assert "Zweite" in text


# ── Command Execution Tests ──

class TestCmdTodoAdd:
    def test_add_success(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.add.return_value = _make_task(text="Milch kaufen")
        r = handler.execute("todo_add", "todo: Milch kaufen")
        assert r.success
        assert "Milch kaufen" in r.text
        client.add.assert_called_once_with(
            text="Milch kaufen", priority="niedrig", category="",
        )

    def test_add_with_priority(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.add.return_value = _make_task(
            text="Dachdecker", priority="hoch", category="Arbeit",
        )
        r = handler.execute("todo_add", "todo: Dachdecker, hoch, Arbeit")
        assert r.success
        client.add.assert_called_once_with(
            text="Dachdecker", priority="hoch", category="Arbeit",
        )

    def test_no_client(self) -> None:
        h = TodoCommandHandler(task_client=None)
        r = h.execute("todo_add", "todo: Test")
        assert not r.success


class TestCmdTodoComplete:
    def test_complete_success(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        # Erst auflisten, damit Index befüllt wird
        task = _make_task(uid="uid-42", text="Erledigt")
        client.get_open.return_value = [task]
        handler.execute("todos", "todos")

        # Dann erledigen
        client.complete.return_value = _make_task(
            uid="uid-42", text="Erledigt", done=True,
        )
        r = handler.execute("todo_complete", "todo erledigt #1")
        assert r.success
        assert "Erledigt" in r.text
        client.complete.assert_called_once_with("uid-42")

    def test_complete_no_index(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_complete", "todo erledigt #1")
        assert not r.success
        assert "nicht im Index" in r.text

    def test_complete_not_found(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_open.return_value = [_make_task(uid="uid-x")]
        handler.execute("todos", "todos")

        client.complete.return_value = None
        r = handler.execute("todo_complete", "todo erledigt #1")
        assert not r.success


class TestCmdTodoList:
    def test_list_open(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_open.return_value = [
            _make_task(uid="a", text="Eins"),
            _make_task(uid="b", text="Zwei"),
        ]
        r = handler.execute("todos", "todos")
        assert r.success
        assert "2 offene Aufgaben" in r.text
        assert "#1" in r.text
        assert "#2" in r.text

    def test_list_empty(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todos", "todos")
        assert r.success
        assert "Keine offenen Aufgaben" in r.text


class TestCmdTodoFilter:
    def test_filter_priority(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_open.return_value = [
            _make_task(uid="a", text="A", priority="hoch"),
            _make_task(uid="b", text="B", priority="niedrig"),
        ]
        r = handler.execute("todo_filter", "todos hoch")
        assert r.success
        assert "A" in r.text
        assert "B" not in r.text

    def test_filter_category(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_open.return_value = [
            _make_task(uid="a", text="A", category="Arbeit"),
            _make_task(uid="b", text="B", category="Privat"),
        ]
        r = handler.execute("todo_filter", "todos arbeit")
        assert r.success
        assert "A" in r.text
        assert "B" not in r.text

    def test_filter_erledigt(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_done.return_value = [
            _make_task(uid="d", text="Fertig", done=True),
        ]
        r = handler.execute("todo_filter", "todos erledigt")
        assert r.success
        assert "Fertig" in r.text

    def test_filter_cleanup_asks_confirmation(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_done.return_value = [
            _make_task(uid="d", text="Alt", done=True),
        ]
        r = handler.execute("todo_filter", "todos aufräumen")
        assert r.success
        assert r.pending_confirmation is True
        assert r.pending_data["action_type"] == "bulk_delete_todos"
        assert r.pending_data["count"] == 1

    def test_filter_cleanup_confirmed(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.delete_all_done.return_value = 1
        r = handler.execute_cleanup()
        assert r.success
        assert "1 erledigte Aufgaben gelöscht" in r.text

    def test_filter_no_match(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_open.return_value = []
        r = handler.execute("todo_filter", "todos hoch")
        assert r.success
        assert "Keine Aufgaben" in r.text


class TestCmdTodoReopen:
    def test_reopen_success(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        task = _make_task(uid="uid-r", text="Test", done=True)
        client.get_done.return_value = [task]
        handler.execute("todo_filter", "todos erledigt")

        client.reopen.return_value = _make_task(uid="uid-r", text="Test")
        r = handler.execute("todo_reopen", "todo wieder öffnen #1")
        assert r.success
        assert "Wieder offen" in r.text

    def test_reopen_no_index(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_reopen", "todo wieder öffnen #1")
        assert not r.success
        assert "nicht im Index" in r.text


class TestCmdTodoPriority:
    def test_priority_change(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        task = _make_task(uid="uid-p", text="Test", priority="niedrig")
        client.get_open.return_value = [task]
        handler.execute("todos", "todos")

        client.update_priority.return_value = _make_task(
            uid="uid-p", text="Test", priority="hoch",
        )
        r = handler.execute("todo_priority", "todo priorität #1 hoch")
        assert r.success
        assert "Priorität" in r.text

    def test_priority_no_index(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_priority", "todo priorität #1 hoch")
        assert not r.success
        assert "nicht im Index" in r.text


class TestCmdTodoDelete:
    def test_delete_success(
        self, handler: TodoCommandHandler, client: MagicMock,
    ) -> None:
        client.get_open.return_value = [
            _make_task(uid="uid-del", text="Weg damit"),
        ]
        handler.execute("todos", "todos")

        client.delete.return_value = True
        r = handler.execute("todo_delete", "todo löschen #1")
        assert r.success
        assert "gelöscht" in r.text

    def test_delete_no_index(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_delete", "todo löschen #1")
        assert not r.success
        assert "nicht im Index" in r.text


class TestTodoKeywords:
    def test_simple_todos(self, handler: TodoCommandHandler) -> None:
        assert "todos" in handler.simple_commands

    def test_keyword_match(self, handler: TodoCommandHandler) -> None:
        kw = handler.keywords
        assert "todos" in kw
        assert "offene aufgaben" in kw["todos"]

    def test_descriptions(self, handler: TodoCommandHandler) -> None:
        desc = handler.command_descriptions
        assert len(desc) >= 4
