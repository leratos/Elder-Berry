"""Tests für TodoCommandHandler (Phase 30)."""
from __future__ import annotations

from pathlib import Path

import pytest

from elder_berry.comms.commands.todo_commands import (
    TODO_ADD_PATTERN, TODO_COMPLETE_PATTERN, TODO_DELETE_PATTERN,
    TODO_FILTER_PATTERN, TODO_PRIORITY_PATTERN, TODO_REOPEN_PATTERN,
    TodoCommandHandler,
)
from elder_berry.tools.todo_store import TodoStore

USER = "@test:matrix.org"


@pytest.fixture()
def store(tmp_path: Path) -> TodoStore:
    return TodoStore(db_path=tmp_path / "t.db")


@pytest.fixture()
def handler(store: TodoStore) -> TodoCommandHandler:
    return TodoCommandHandler(todo_store=store, default_user_id=USER)


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


# ── Command Execution Tests ──

class TestCmdTodoAdd:
    def test_add_success(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_add", "todo: Milch kaufen")
        assert r.success
        assert "Milch kaufen" in r.text

    def test_add_with_priority(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_add", "todo: Dachdecker, hoch, Arbeit")
        assert r.success
        assert "hoch" in r.text

    def test_no_store(self) -> None:
        h = TodoCommandHandler(todo_store=None)
        r = h.execute("todo_add", "todo: Test")
        assert not r.success


class TestCmdTodoComplete:
    def test_complete_success(self, handler: TodoCommandHandler,
                              store: TodoStore) -> None:
        t = store.add(USER, "Test")
        r = handler.execute("todo_complete", f"todo erledigt #{t.id}")
        assert r.success
        assert "Erledigt" in r.text

    def test_complete_not_found(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_complete", "todo erledigt #999")
        assert not r.success


class TestCmdTodoList:
    def test_list_open(self, handler: TodoCommandHandler,
                       store: TodoStore) -> None:
        store.add(USER, "Eins")
        store.add(USER, "Zwei")
        r = handler.execute("todos", "todos")
        assert r.success
        assert "2 offene Todos" in r.text

    def test_list_empty(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todos", "todos")
        assert r.success
        assert "Keine offenen Todos" in r.text


class TestCmdTodoFilter:
    def test_filter_priority(self, handler: TodoCommandHandler,
                             store: TodoStore) -> None:
        store.add(USER, "A", priority="hoch")
        store.add(USER, "B", priority="niedrig")
        r = handler.execute("todo_filter", "todos hoch")
        assert r.success
        assert "A" in r.text
        assert "B" not in r.text

    def test_filter_category(self, handler: TodoCommandHandler,
                             store: TodoStore) -> None:
        store.add(USER, "A", category="Arbeit")
        store.add(USER, "B", category="Privat")
        r = handler.execute("todo_filter", "todos Arbeit")
        assert r.success
        assert "A" in r.text
        assert "B" not in r.text

    def test_filter_erledigt(self, handler: TodoCommandHandler,
                             store: TodoStore) -> None:
        t = store.add(USER, "Fertig")
        store.complete(t.id)
        r = handler.execute("todo_filter", "todos erledigt")
        assert r.success
        assert "Fertig" in r.text

    def test_filter_cleanup(self, handler: TodoCommandHandler,
                            store: TodoStore) -> None:
        t = store.add(USER, "Alt")
        store.complete(t.id)
        r = handler.execute("todo_filter", "todos aufräumen")
        assert r.success
        assert "1 erledigte Todos gelöscht" in r.text

    def test_filter_no_match(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_filter", "todos hoch")
        assert r.success
        assert "Keine Todos" in r.text


class TestCmdTodoReopen:
    def test_reopen_success(self, handler: TodoCommandHandler,
                            store: TodoStore) -> None:
        t = store.add(USER, "Test")
        store.complete(t.id)
        r = handler.execute("todo_reopen", f"todo wieder öffnen #{t.id}")
        assert r.success
        assert "Wieder offen" in r.text

    def test_reopen_not_found(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_reopen", "todo wieder öffnen #999")
        assert not r.success


class TestCmdTodoPriority:
    def test_priority_change(self, handler: TodoCommandHandler,
                             store: TodoStore) -> None:
        t = store.add(USER, "Test", priority="niedrig")
        r = handler.execute("todo_priority", f"todo priorität #{t.id} hoch")
        assert r.success
        assert "Priorität" in r.text

    def test_priority_not_found(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_priority", "todo priorität #999 hoch")
        assert not r.success


class TestCmdTodoDelete:
    def test_delete_success(self, handler: TodoCommandHandler,
                            store: TodoStore) -> None:
        t = store.add(USER, "Weg damit")
        r = handler.execute("todo_delete", f"todo löschen #{t.id}")
        assert r.success
        assert "gelöscht" in r.text

    def test_delete_not_found(self, handler: TodoCommandHandler) -> None:
        r = handler.execute("todo_delete", "todo löschen #999")
        assert not r.success


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
