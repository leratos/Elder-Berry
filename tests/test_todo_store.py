"""Tests für TodoStore (Phase 30)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from elder_berry.tools.todo_store import TodoStore

USER = "@test:matrix.org"
USER_B = "@other:matrix.org"


@pytest.fixture()
def store(tmp_path: Path) -> TodoStore:
    s = TodoStore(db_path=tmp_path / "todos.db")
    yield s
    s.close()


class TestAdd:
    def test_add_default_priority(self, store: TodoStore) -> None:
        t = store.add(USER, "Milch kaufen")
        assert t.text == "Milch kaufen"
        assert t.priority == "niedrig"
        assert t.done is False

    def test_add_with_priority(self, store: TodoStore) -> None:
        t = store.add(USER, "Dachdecker", priority="hoch")
        assert t.priority == "hoch"

    def test_add_with_category(self, store: TodoStore) -> None:
        t = store.add(USER, "Meeting", category="Arbeit")
        assert t.category == "Arbeit"

    def test_add_invalid_priority(self, store: TodoStore) -> None:
        with pytest.raises(ValueError, match="Ungültige Priorität"):
            store.add(USER, "X", priority="dringend")


class TestComplete:
    def test_complete(self, store: TodoStore) -> None:
        t = store.add(USER, "Test")
        done = store.complete(t.id)
        assert done is not None
        assert done.done is True
        assert done.completed_at is not None

    def test_complete_already_done(self, store: TodoStore) -> None:
        t = store.add(USER, "Test")
        store.complete(t.id)
        assert store.complete(t.id) is None

    def test_complete_not_found(self, store: TodoStore) -> None:
        assert store.complete(9999) is None


class TestReopen:
    def test_reopen(self, store: TodoStore) -> None:
        t = store.add(USER, "Test")
        store.complete(t.id)
        reopened = store.reopen(t.id)
        assert reopened is not None
        assert reopened.done is False
        assert reopened.completed_at is None

    def test_reopen_not_done(self, store: TodoStore) -> None:
        t = store.add(USER, "Test")
        assert store.reopen(t.id) is None


class TestUpdatePriority:
    def test_update_priority(self, store: TodoStore) -> None:
        t = store.add(USER, "Test")
        updated = store.update_priority(t.id, "hoch")
        assert updated is not None
        assert updated.priority == "hoch"

    def test_update_priority_invalid(self, store: TodoStore) -> None:
        t = store.add(USER, "Test")
        with pytest.raises(ValueError):
            store.update_priority(t.id, "ultra")


class TestGetOpen:
    def test_get_open(self, store: TodoStore) -> None:
        store.add(USER, "A")
        store.add(USER, "B")
        t3 = store.add(USER, "C")
        store.complete(t3.id)
        assert len(store.get_open(USER)) == 2

    def test_get_open_sorted_by_priority(self, store: TodoStore) -> None:
        store.add(USER, "low", priority="niedrig")
        store.add(USER, "high", priority="hoch")
        store.add(USER, "mid", priority="mittel")
        todos = store.get_open(USER)
        assert todos[0].priority == "hoch"
        assert todos[1].priority == "mittel"
        assert todos[2].priority == "niedrig"

    def test_get_open_filter_priority(self, store: TodoStore) -> None:
        store.add(USER, "A", priority="hoch")
        store.add(USER, "B", priority="niedrig")
        result = store.get_open(USER, priority="hoch")
        assert len(result) == 1
        assert result[0].text == "A"

    def test_get_open_filter_category(self, store: TodoStore) -> None:
        store.add(USER, "A", category="Arbeit")
        store.add(USER, "B", category="Privat")
        result = store.get_open(USER, category="Arbeit")
        assert len(result) == 1


class TestGetDone:
    def test_get_done(self, store: TodoStore) -> None:
        t = store.add(USER, "A")
        store.complete(t.id)
        done = store.get_done(USER)
        assert len(done) == 1
        assert done[0].done is True


class TestCountOpen:
    def test_count_open(self, store: TodoStore) -> None:
        store.add(USER, "A", priority="hoch")
        store.add(USER, "B", priority="hoch")
        store.add(USER, "C", priority="niedrig")
        counts = store.count_open(USER)
        assert counts["hoch"] == 2
        assert counts["niedrig"] == 1
        assert counts["total"] == 3

    def test_count_open_empty(self, store: TodoStore) -> None:
        counts = store.count_open(USER)
        assert counts["total"] == 0


class TestBriefing:
    def test_format_for_briefing_none(self, store: TodoStore) -> None:
        assert "Keine offenen" in store.format_for_briefing(USER)

    def test_format_for_briefing_few(self, store: TodoStore) -> None:
        store.add(USER, "A")
        store.add(USER, "B")
        text = store.format_for_briefing(USER)
        assert "2 offene Todos:" in text
        assert "⬚" in text

    def test_format_for_briefing_many(self, store: TodoStore) -> None:
        for i in range(8):
            store.add(USER, f"Todo {i}", priority="niedrig")
        text = store.format_for_briefing(USER)
        assert "8 offene Todos" in text
        assert "⬚" not in text  # Zusammenfassung, keine Liste


class TestDelete:
    def test_delete(self, store: TodoStore) -> None:
        t = store.add(USER, "A")
        assert store.delete(t.id) is True
        assert store.get_open(USER) == []

    def test_delete_not_found(self, store: TodoStore) -> None:
        assert store.delete(9999) is False

    def test_delete_all_done(self, store: TodoStore) -> None:
        t1 = store.add(USER, "A")
        store.add(USER, "B")
        store.complete(t1.id)
        deleted = store.delete_all_done(USER)
        assert deleted == 1
        assert len(store.get_open(USER)) == 1


class TestCleanup:
    def test_cleanup(self, store: TodoStore) -> None:
        t = store.add(USER, "Old")
        store.complete(t.id)
        # Manuell completed_at auf vor 100 Tagen setzen
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        store._conn.execute("UPDATE todos SET completed_at=? WHERE id=?", (old, t.id))
        store._conn.commit()
        assert store.cleanup(days=90) == 1

    def test_cleanup_keeps_recent(self, store: TodoStore) -> None:
        t = store.add(USER, "Recent")
        store.complete(t.id)
        assert store.cleanup(days=90) == 0


class TestMultiUser:
    def test_multi_user_isolation(self, store: TodoStore) -> None:
        store.add(USER, "A")
        store.add(USER_B, "B")
        assert len(store.get_open(USER)) == 1
        assert len(store.get_open(USER_B)) == 1


class TestFormat:
    def test_format_short(self, store: TodoStore) -> None:
        t = store.add(USER, "Milch kaufen")
        assert "⬚" in t.format_short()
        assert "Milch kaufen" in t.format_short()

    def test_format_short_with_priority(self, store: TodoStore) -> None:
        t = store.add(USER, "Dringend", priority="hoch")
        assert "🔴" in t.format_short()

    def test_format_short_with_category(self, store: TodoStore) -> None:
        t = store.add(USER, "Test", category="Arbeit", priority="niedrig")
        assert "Arbeit" in t.format_short()


class TestClose:
    def test_close(self, tmp_path: Path) -> None:
        s = TodoStore(db_path=tmp_path / "t.db")
        s.add(USER, "Test")
        s.close()
        s.close()  # Doppeltes close → kein Crash
