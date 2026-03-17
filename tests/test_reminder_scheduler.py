"""Tests: ReminderScheduler – Periodischer Check fälliger Erinnerungen."""
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.reminder_scheduler import ReminderScheduler
from elder_berry.tools.reminder_store import ReminderStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_A = "@alice:matrix.org"


def _now_plus(minutes: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "scheduler_test.db"
    s = ReminderStore(db_path=db)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_start_stop(self, store):
        callback = MagicMock()
        scheduler = ReminderScheduler(
            store=store, send_reminder=callback, poll_interval=1,
        )

        assert scheduler.is_running is False
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.stop()
        assert scheduler.is_running is False

    def test_double_start(self, store):
        callback = MagicMock()
        scheduler = ReminderScheduler(
            store=store, send_reminder=callback, poll_interval=1,
        )
        scheduler.start()
        scheduler.start()  # Sollte Warnung loggen, nicht crashen
        scheduler.stop()


# ---------------------------------------------------------------------------
# Fälligkeits-Checks
# ---------------------------------------------------------------------------

class TestDueChecks:
    def test_due_reminder_fires_callback(self, store):
        """Fällige Erinnerung → Callback wird aufgerufen."""
        store.add(USER_A, "Sofort!", _now_plus(-1))
        callback = MagicMock()

        scheduler = ReminderScheduler(
            store=store, send_reminder=callback, poll_interval=1,
        )
        scheduler.start()
        time.sleep(2.5)  # Mindestens 1 Poll-Zyklus
        scheduler.stop()

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == USER_A
        assert "Sofort!" in call_args[1]
        assert "⏰" in call_args[1]

    def test_future_reminder_not_fired(self, store):
        """Nicht fällige Erinnerung → Callback wird NICHT aufgerufen."""
        store.add(USER_A, "Später", _now_plus(60))
        callback = MagicMock()

        scheduler = ReminderScheduler(
            store=store, send_reminder=callback, poll_interval=1,
        )
        scheduler.start()
        time.sleep(2.5)
        scheduler.stop()

        callback.assert_not_called()

    def test_fired_only_once(self, store):
        """Erinnerung wird nach Senden als fired markiert → nur einmal gesendet."""
        store.add(USER_A, "Einmal", _now_plus(-1))
        callback = MagicMock()

        scheduler = ReminderScheduler(
            store=store, send_reminder=callback, poll_interval=1,
        )
        scheduler.start()
        time.sleep(3.5)  # Mindestens 2 Poll-Zyklen
        scheduler.stop()

        # Sollte genau einmal aufgerufen worden sein
        assert callback.call_count == 1

    def test_callback_error_no_crash(self, store):
        """Callback-Fehler → Scheduler läuft weiter (kein Crash)."""
        store.add(USER_A, "Fehler", _now_plus(-1))
        callback = MagicMock(side_effect=RuntimeError("Netzwerk"))

        scheduler = ReminderScheduler(
            store=store, send_reminder=callback, poll_interval=1,
        )
        scheduler.start()
        time.sleep(2.5)

        # Scheduler läuft noch trotz Fehler
        assert scheduler.is_running is True
        # Callback wurde mindestens einmal aufgerufen (Retry bei jedem Zyklus)
        assert callback.call_count >= 1
        scheduler.stop()
