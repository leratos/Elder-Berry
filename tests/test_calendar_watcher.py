"""Tests: CalendarWatcher – Proaktive Kalender-Erinnerungen (Phase 17)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.calendar_watcher import CalendarWatcher
from elder_berry.tools.google_calendar import CalendarEvent


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_event(
    summary: str = "Testtermin",
    minutes_from_now: float = 10,
    all_day: bool = False,
    location: str | None = None,
    event_id: str = "event_001",
) -> CalendarEvent:
    start = _now() + timedelta(minutes=minutes_from_now)
    end = start + timedelta(hours=1)
    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        all_day=all_day,
        location=location,
        event_id=event_id,
    )


@pytest.fixture
def mock_calendar():
    cal = MagicMock()
    cal.get_events_range.return_value = []
    return cal


@pytest.fixture
def send_alert():
    return MagicMock()


@pytest.fixture
def watcher(mock_calendar, send_alert):
    return CalendarWatcher(
        send_alert=send_alert,
        calendar=mock_calendar,
        reminder_minutes=[15, 5],
        poll_interval=300,
    )


# ---------------------------------------------------------------------------
# Init-Tests
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_reminder_minutes(self, mock_calendar, send_alert):
        w = CalendarWatcher(send_alert=send_alert, calendar=mock_calendar)
        assert 15 in w._reminder_minutes
        assert 5 in w._reminder_minutes

    def test_custom_reminder_minutes(self, mock_calendar, send_alert):
        w = CalendarWatcher(
            send_alert=send_alert,
            calendar=mock_calendar,
            reminder_minutes=[30, 10],
        )
        assert 30 in w._reminder_minutes
        assert 10 in w._reminder_minutes

    def test_default_poll_interval(self, mock_calendar, send_alert):
        w = CalendarWatcher(send_alert=send_alert, calendar=mock_calendar)
        assert w._poll_interval == 300

    def test_custom_poll_interval(self, mock_calendar, send_alert):
        w = CalendarWatcher(
            send_alert=send_alert,
            calendar=mock_calendar,
            poll_interval=60,
        )
        assert w._poll_interval == 60

    def test_not_running_initially(self, watcher):
        assert not watcher.is_running


# ---------------------------------------------------------------------------
# _check_upcoming – Erinnerungs-Logik
# ---------------------------------------------------------------------------


class TestCheckUpcoming:
    def test_event_in_10_min_triggers_15min_reminder(
        self, watcher, mock_calendar, send_alert
    ):
        event = _make_event(minutes_from_now=10)
        mock_calendar.get_events_range.return_value = [event]

        watcher._check_upcoming()

        send_alert.assert_called_once()
        assert "15 Minuten" in send_alert.call_args[0][0]

    def test_event_in_3_min_triggers_5min_reminder(
        self, watcher, mock_calendar, send_alert
    ):
        """Event in 3 Min → sowohl 5-Min als auch 15-Min Reminder feuern (beide <= 3)."""
        event = _make_event(minutes_from_now=3)
        mock_calendar.get_events_range.return_value = [event]

        watcher._check_upcoming()

        # Beide Reminder feuern (15 > 3 → True, 5 > 3 → True)
        assert send_alert.call_count >= 1
        call_texts = " ".join(c[0][0] for c in send_alert.call_args_list)
        assert "5 Minuten" in call_texts

    def test_event_in_3_min_triggers_both_reminders(
        self, watcher, mock_calendar, send_alert
    ):
        """Event in 3 Min → 15-Min UND 5-Min Reminder feuern (beide <= minutes_until)."""
        event = _make_event(minutes_from_now=3)
        mock_calendar.get_events_range.return_value = [event]

        watcher._check_upcoming()

        assert send_alert.call_count == 2

    def test_all_day_event_skipped(self, watcher, mock_calendar, send_alert):
        event = _make_event(all_day=True, minutes_from_now=5)
        mock_calendar.get_events_range.return_value = [event]

        watcher._check_upcoming()

        send_alert.assert_not_called()

    def test_no_events_no_alerts(self, watcher, mock_calendar, send_alert):
        mock_calendar.get_events_range.return_value = []

        watcher._check_upcoming()

        send_alert.assert_not_called()

    def test_event_far_away_no_reminder(self, watcher, mock_calendar, send_alert):
        """Event in 60 Min → kein Reminder feuert."""
        event = _make_event(minutes_from_now=60)
        mock_calendar.get_events_range.return_value = [event]

        watcher._check_upcoming()

        send_alert.assert_not_called()


# ---------------------------------------------------------------------------
# Deduplizierung
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_reminder_not_sent_twice(self, watcher, mock_calendar, send_alert):
        event = _make_event(minutes_from_now=10)
        mock_calendar.get_events_range.return_value = [event]

        watcher._check_upcoming()
        watcher._check_upcoming()  # Zweiter Poll

        # Nur einmal gesendet
        assert send_alert.call_count == 1

    def test_different_reminders_sent_separately(
        self, watcher, mock_calendar, send_alert
    ):
        event = _make_event(minutes_from_now=10)
        mock_calendar.get_events_range.return_value = [event]
        watcher._check_upcoming()  # → 15-Min

        # Event jetzt 3 Min entfernt
        event2 = _make_event(minutes_from_now=3, event_id="event_001")
        mock_calendar.get_events_range.return_value = [event2]
        watcher._check_upcoming()  # → 5-Min (15-Min schon gesendet)

        # 15-Min + 5-Min = 2 Aufrufe
        assert send_alert.call_count == 2


# ---------------------------------------------------------------------------
# _send_reminder – Formatierung
# ---------------------------------------------------------------------------


class TestSendReminder:
    def test_format_without_location(self, watcher, send_alert):
        event = _make_event(summary="Zahnarzt", minutes_from_now=10, location=None)
        watcher._send_reminder(event, 15)

        text = send_alert.call_args[0][0]
        assert "Zahnarzt" in text
        assert "15 Minuten" in text
        assert "📍" not in text

    def test_format_with_location(self, watcher, send_alert):
        event = _make_event(
            summary="Meeting", location="Büro Hauptstr. 1", minutes_from_now=10
        )
        watcher._send_reminder(event, 5)

        text = send_alert.call_args[0][0]
        assert "Meeting" in text
        assert "5 Minuten" in text
        assert "📍" in text
        assert "Büro Hauptstr. 1" in text

    def test_format_hours(self, watcher, send_alert):
        event = _make_event(minutes_from_now=60)
        watcher._send_reminder(event, 60)

        text = send_alert.call_args[0][0]
        assert "1h" in text

    def test_format_hours_and_minutes(self, watcher, send_alert):
        event = _make_event(minutes_from_now=90)
        watcher._send_reminder(event, 90)

        text = send_alert.call_args[0][0]
        assert "1h" in text and "30min" in text

    def test_send_alert_error_no_crash(self, watcher, send_alert):
        send_alert.side_effect = Exception("Netzwerk-Fehler")
        event = _make_event(minutes_from_now=5)
        # Kein Crash erwartet
        watcher._send_reminder(event, 5)


# ---------------------------------------------------------------------------
# _cleanup_past_events
# ---------------------------------------------------------------------------


class TestCleanupPastEvents:
    def test_current_events_stay(self, watcher):
        watcher._reminded_events = {"event_001": {15}, "event_002": {5}}
        current = [_make_event(event_id="event_001")]
        watcher._cleanup_past_events(current)
        assert "event_001" in watcher._reminded_events

    def test_past_events_removed(self, watcher):
        watcher._reminded_events = {"old_event": {15, 5}}
        current = []  # leer = alle weg
        watcher._cleanup_past_events(current)
        assert "old_event" not in watcher._reminded_events


# ---------------------------------------------------------------------------
# start/stop – Thread-Management
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_sets_running(self, watcher):
        watcher.start()
        assert watcher.is_running
        watcher.stop()

    def test_stop_resets_running(self, watcher):
        watcher.start()
        watcher.stop()
        assert not watcher.is_running

    def test_double_start_no_error(self, watcher):
        watcher.start()
        watcher.start()  # Zweites Start ignoriert
        assert watcher.is_running
        watcher.stop()

    def test_stop_without_start_no_error(self, watcher):
        watcher.stop()  # Kein Fehler


# ---------------------------------------------------------------------------
# API-Fehler – Graceful Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_calendar_api_error_no_crash(self, watcher, mock_calendar, send_alert):
        mock_calendar.get_events_range.side_effect = Exception("API Error 500")

        # _check_upcoming fangt Exception
        watcher._check_upcoming()

        send_alert.assert_not_called()

    def test_run_loop_continues_after_error(self, watcher, mock_calendar, send_alert):
        """Fehler beim ersten Poll → nächster Poll funktioniert."""
        event = _make_event(minutes_from_now=5)
        mock_calendar.get_events_range.side_effect = [
            Exception("Erster Fehler"),
            [event],
        ]

        watcher._check_upcoming()  # Fehler
        watcher._check_upcoming()  # Erfolg → 15-Min UND 5-Min feuern (event in 5 min)

        # Mindestens 1 Reminder gesendet (nach dem Fehler)
        assert send_alert.call_count >= 1
