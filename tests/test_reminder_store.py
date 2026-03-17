"""Tests: ReminderStore – SQLite-basierte Erinnerungen."""
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from elder_berry.tools.reminder_store import Reminder, ReminderStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Erstellt einen ReminderStore mit temporärer DB."""
    db = tmp_path / "test_reminders.db"
    s = ReminderStore(db_path=db)
    yield s
    s.close()


USER_A = "@alice:matrix.org"
USER_B = "@bob:matrix.org"


def _now_plus(minutes: int = 0) -> datetime:
    """UTC-aware datetime mit Offset in Minuten."""
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# DTO-Tests
# ---------------------------------------------------------------------------

class TestReminderDTO:
    def test_frozen(self):
        r = Reminder(
            id=1, user_id=USER_A, message="Test",
            due_at=_now_plus(10), created_at=_now_plus(),
            fired=False, cancelled=False,
        )
        with pytest.raises(AttributeError):
            r.message = "Changed"

    def test_fields(self):
        now = _now_plus()
        due = _now_plus(30)
        r = Reminder(
            id=42, user_id=USER_A, message="Wäsche",
            due_at=due, created_at=now,
            fired=False, cancelled=False,
        )
        assert r.id == 42
        assert r.user_id == USER_A
        assert r.message == "Wäsche"
        assert r.due_at == due
        assert r.fired is False


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_returns_reminder(self, store):
        r = store.add(USER_A, "Wäsche", _now_plus(30))
        assert isinstance(r, Reminder)
        assert r.id > 0
        assert r.user_id == USER_A
        assert r.message == "Wäsche"
        assert r.fired is False
        assert r.cancelled is False

    def test_add_naive_datetime_raises(self, store):
        naive = datetime(2026, 3, 17, 18, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            store.add(USER_A, "Test", naive)

    def test_add_multiple_ids_increment(self, store):
        r1 = store.add(USER_A, "Eins", _now_plus(10))
        r2 = store.add(USER_A, "Zwei", _now_plus(20))
        assert r2.id > r1.id


# ---------------------------------------------------------------------------
# get_pending()
# ---------------------------------------------------------------------------

class TestGetPending:
    def test_only_unfired_uncancelled(self, store):
        r1 = store.add(USER_A, "Aktiv", _now_plus(30))
        r2 = store.add(USER_A, "Fired", _now_plus(30))
        r3 = store.add(USER_A, "Cancelled", _now_plus(30))

        store.mark_fired(r2.id)
        store.cancel(r3.id)

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].id == r1.id

    def test_filtered_by_user(self, store):
        store.add(USER_A, "Alice", _now_plus(30))
        store.add(USER_B, "Bob", _now_plus(30))

        alice_pending = store.get_pending(user_id=USER_A)
        assert len(alice_pending) == 1
        assert alice_pending[0].message == "Alice"

    def test_empty(self, store):
        assert store.get_pending() == []


# ---------------------------------------------------------------------------
# get_due()
# ---------------------------------------------------------------------------

class TestGetDue:
    def test_past_due_returned(self, store):
        store.add(USER_A, "Fällig", _now_plus(-5))  # 5 Min in der Vergangenheit
        due = store.get_due()
        assert len(due) == 1
        assert due[0].message == "Fällig"

    def test_future_not_returned(self, store):
        store.add(USER_A, "Zukunft", _now_plus(60))
        due = store.get_due()
        assert len(due) == 0

    def test_fired_not_returned(self, store):
        r = store.add(USER_A, "Schon gesendet", _now_plus(-5))
        store.mark_fired(r.id)
        due = store.get_due()
        assert len(due) == 0


# ---------------------------------------------------------------------------
# mark_fired() / cancel() / cancel_all()
# ---------------------------------------------------------------------------

class TestMarkFired:
    def test_mark_fired(self, store):
        r = store.add(USER_A, "Test", _now_plus(-1))
        store.mark_fired(r.id)

        pending = store.get_pending()
        assert len(pending) == 0

        due = store.get_due()
        assert len(due) == 0


class TestCancel:
    def test_cancel(self, store):
        r = store.add(USER_A, "Test", _now_plus(30))
        store.cancel(r.id)
        assert store.get_pending() == []

    def test_cancel_all(self, store):
        store.add(USER_A, "Eins", _now_plus(10))
        store.add(USER_A, "Zwei", _now_plus(20))
        store.add(USER_B, "Bob", _now_plus(30))

        count = store.cancel_all(USER_A)
        assert count == 2
        assert len(store.get_pending(USER_A)) == 0
        assert len(store.get_pending(USER_B)) == 1


# ---------------------------------------------------------------------------
# format_pending()
# ---------------------------------------------------------------------------

class TestFormatPending:
    def test_empty(self, store):
        text = store.format_pending([])
        assert "Keine offenen" in text

    def test_with_reminders(self, store):
        r = store.add(USER_A, "Wäsche abholen", _now_plus(60))
        text = store.format_pending([r])
        assert "Wäsche abholen" in text
        assert f"#{r.id}" in text
        assert "⏰" in text


# ---------------------------------------------------------------------------
# DB-Persistenz
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_survives_reopen(self, tmp_path):
        db = tmp_path / "persist_test.db"
        s1 = ReminderStore(db_path=db)
        s1.add(USER_A, "Persist-Test", _now_plus(30))
        s1.close()

        s2 = ReminderStore(db_path=db)
        pending = s2.get_pending()
        assert len(pending) == 1
        assert pending[0].message == "Persist-Test"
        s2.close()
