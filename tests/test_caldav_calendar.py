"""Tests für CalDAVCalendarClient – CalDAV komplett gemockt."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from elder_berry.tools.caldav_calendar import CalDAVCalendarClient
from elder_berry.tools.google_calendar import CalendarEvent


# ── Helpers ──────────────────────────────────────────────────────────

def _make_secret_store(**overrides):
    """Erstellt einen Mock-SecretStore mit Nextcloud-Credentials."""
    defaults = {
        "nextcloud_url": "https://cloud.example.com",
        "nextcloud_user": "testuser",
        "nextcloud_app_password": "secret123",
    }
    defaults.update(overrides)

    store = MagicMock()
    store.get.side_effect = lambda key: defaults[key]
    store.get_or_none.side_effect = lambda key: defaults.get(key)
    return store


def _make_ical(
    summary="Test Event",
    dtstart="20260330T140000",
    dtend="20260330T150000",
    uid="uid-123",
    location=None,
    description=None,
    all_day=False,
    rrule=None,
):
    """Erzeugt einen iCal-String für ein VEVENT."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
    ]
    if all_day:
        lines.append(f"DTSTART;VALUE=DATE:{dtstart}")
        if dtend:
            lines.append(f"DTEND;VALUE=DATE:{dtend}")
    else:
        lines.append(f"DTSTART:{dtstart}")
        if dtend:
            lines.append(f"DTEND:{dtend}")
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    if rrule:
        lines.append(rrule)
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def _make_caldav_event(ical_str):
    """Erzeugt ein Mock-caldav-Event mit .data Attribut."""
    ev = MagicMock()
    ev.data = ical_str
    return ev


def _client_with_calendar(mock_calendar=None):
    """Erstellt einen CalDAVCalendarClient mit vorgefertigtem Kalender-Mock."""
    store = _make_secret_store()
    client = CalDAVCalendarClient(secret_store=store)
    if mock_calendar is None:
        mock_calendar = MagicMock()
    client._calendar = mock_calendar
    return client, mock_calendar


# ── Credentials & Verfügbarkeit ──────────────────────────────────────

class TestCredentialsAndAvailability:
    def test_init_from_secret_store(self):
        store = _make_secret_store()
        client = CalDAVCalendarClient(secret_store=store)
        assert client._store is store
        assert client._calendar is None
        assert client._client is None

    def test_is_available_success(self):
        store = _make_secret_store()
        client = CalDAVCalendarClient(secret_store=store)

        mock_cal = MagicMock()
        mock_cal.name = "Personal"
        # Setze Kalender direkt → _get_calendar() gibt ihn zurück
        client._calendar = mock_cal
        assert client.is_available() is True

    def test_is_available_no_credentials(self):
        store = MagicMock()
        store.get_or_none.return_value = None
        client = CalDAVCalendarClient(secret_store=store)
        assert client.is_available() is False

    def test_is_available_server_unreachable(self):
        store = _make_secret_store()
        client = CalDAVCalendarClient(secret_store=store)

        with patch.object(client, "_get_calendar", side_effect=ConnectionError("timeout")):
            assert client.is_available() is False

    def test_lazy_calendar_init(self):
        store = _make_secret_store()
        client = CalDAVCalendarClient(secret_store=store)
        # Kein Zugriff → kein Kalender
        assert client._calendar is None
        assert client._client is None


# ── Events abrufen ───────────────────────────────────────────────────

class TestGetEvents:
    def test_get_events_today(self):
        client, cal = _client_with_calendar()
        ical = _make_ical(summary="Zahnarzt", uid="ev1")
        cal.search.return_value = [_make_caldav_event(ical)]

        events = client.get_events(days=1)
        assert len(events) == 1
        assert events[0].summary == "Zahnarzt"
        assert events[0].event_id == "ev1"
        cal.search.assert_called_once()

    def test_get_events_multiple_days(self):
        client, cal = _client_with_calendar()
        ev1 = _make_caldav_event(_make_ical(summary="A", uid="1", dtstart="20260330T100000", dtend="20260330T110000"))
        ev2 = _make_caldav_event(_make_ical(summary="B", uid="2", dtstart="20260402T090000", dtend="20260402T100000"))
        cal.search.return_value = [ev2, ev1]  # unsortiert

        events = client.get_events(days=7)
        assert len(events) == 2
        assert events[0].summary == "A"
        assert events[1].summary == "B"

    def test_get_events_empty(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = []
        assert client.get_events(days=1) == []

    def test_get_today_delegates(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = []
        client.get_today()
        cal.search.assert_called_once()

    def test_get_tomorrow(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = []
        client.get_tomorrow()
        call_kwargs = cal.search.call_args
        # start sollte morgen 00:00 UTC sein
        start_arg = call_kwargs.kwargs.get("start") or call_kwargs[1].get("start")
        assert start_arg.hour == 0
        assert start_arg.minute == 0

    def test_get_events_range(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = []
        start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        end = datetime(2026, 4, 7, tzinfo=timezone.utc)
        client.get_events_range(start=start, end=end)
        call_kwargs = cal.search.call_args
        assert call_kwargs.kwargs.get("start") == start or call_kwargs[1].get("start") == start

    def test_get_events_max_results(self):
        client, cal = _client_with_calendar()
        # 5 Events zurückgeben, aber max_results=3
        days = ["20260325", "20260326", "20260327", "20260328", "20260329"]
        icals = [
            _make_caldav_event(_make_ical(
                summary=f"Ev{i}", uid=f"uid{i}",
                dtstart=f"{days[i]}T100000", dtend=f"{days[i]}T110000",
            ))
            for i in range(5)
        ]
        cal.search.return_value = icals
        events = client.get_events(days=7, max_results=3)
        assert len(events) == 3

    def test_get_events_sorted(self):
        client, cal = _client_with_calendar()
        late = _make_caldav_event(_make_ical(summary="Spät", uid="l", dtstart="20260330T180000", dtend="20260330T190000"))
        early = _make_caldav_event(_make_ical(summary="Früh", uid="e", dtstart="20260330T080000", dtend="20260330T090000"))
        cal.search.return_value = [late, early]

        events = client.get_events(days=1)
        assert events[0].summary == "Früh"
        assert events[1].summary == "Spät"


# ── Suche ────────────────────────────────────────────────────────────

class TestSearchEvents:
    def test_search_events_found(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = [
            _make_caldav_event(_make_ical(summary="Zahnarzt Dr. Müller", uid="z1")),
            _make_caldav_event(_make_ical(summary="Einkaufen", uid="e1")),
        ]
        results = client.search_events("zahnarzt")
        assert len(results) == 1
        assert results[0].summary == "Zahnarzt Dr. Müller"

    def test_search_events_no_results(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = [
            _make_caldav_event(_make_ical(summary="Meeting", uid="m1")),
        ]
        results = client.search_events("yoga")
        assert results == []

    def test_search_events_case_insensitive(self):
        client, cal = _client_with_calendar()
        cal.search.return_value = [
            _make_caldav_event(_make_ical(summary="YOGA Kurs", uid="y1")),
        ]
        results = client.search_events("yoga")
        assert len(results) == 1


# ── Event erstellen ──────────────────────────────────────────────────

class TestCreateEvent:
    def test_create_event_normal(self):
        client, cal = _client_with_calendar()
        start = datetime(2026, 3, 30, 14, 0)
        event = client.create_event("Zahnarzt", start, duration_minutes=60)

        assert isinstance(event, CalendarEvent)
        assert event.summary == "Zahnarzt"
        assert event.start == start
        assert event.end == start + timedelta(minutes=60)
        assert not event.all_day
        assert event.event_id  # UID gesetzt
        cal.save_event.assert_called_once()

    def test_create_event_all_day(self):
        client, cal = _client_with_calendar()
        start = datetime(2026, 7, 15)
        event = client.create_event("Urlaub", start, all_day=True)

        assert event.all_day is True
        assert event.start == datetime(2026, 7, 15)
        assert event.end == datetime(2026, 7, 16)
        ical_str = cal.save_event.call_args[0][0]
        assert "VALUE=DATE:20260715" in ical_str

    def test_create_event_with_location(self):
        client, cal = _client_with_calendar()
        start = datetime(2026, 3, 30, 14, 0)
        event = client.create_event("Zahnarzt", start, location="Praxis Dr. Müller")

        assert event.location == "Praxis Dr. Müller"
        ical_str = cal.save_event.call_args[0][0]
        assert "LOCATION:Praxis Dr. Müller" in ical_str

    def test_create_event_with_recurrence(self):
        client, cal = _client_with_calendar()
        start = datetime(2026, 9, 28)
        event = client.create_event(
            "Geburtstag", start, all_day=True,
            recurrence=["RRULE:FREQ=YEARLY"],
        )
        ical_str = cal.save_event.call_args[0][0]
        assert "RRULE:FREQ=YEARLY" in ical_str

    def test_create_event_returns_calendar_event(self):
        client, cal = _client_with_calendar()
        start = datetime(2026, 3, 30, 10, 0)
        result = client.create_event(
            "Test", start, duration_minutes=30,
            description="Notiz", location="Büro",
        )
        assert isinstance(result, CalendarEvent)
        assert result.description == "Notiz"
        assert result.location == "Büro"


# ── Event löschen ────────────────────────────────────────────────────

class TestDeleteEvent:
    def test_delete_event_success(self):
        client, cal = _client_with_calendar()
        mock_event = MagicMock()
        cal.event_by_uid.return_value = mock_event

        result = client.delete_event("uid-123")
        assert result is True
        mock_event.delete.assert_called_once()

    def test_delete_event_not_found(self):
        client, cal = _client_with_calendar()
        cal.event_by_uid.side_effect = Exception("404 Not Found")

        result = client.delete_event("uid-gone")
        assert result is True  # Idempotenz

    def test_delete_event_already_gone(self):
        client, cal = _client_with_calendar()
        cal.event_by_uid.side_effect = Exception("410 Gone")

        result = client.delete_event("uid-old")
        assert result is True


# ── Parsing ──────────────────────────────────────────────────────────

class TestParseEvent:
    def test_parse_event_normal(self):
        ical = _make_ical(
            summary="Meeting", uid="m1",
            dtstart="20260330T140000", dtend="20260330T150000",
        )
        event = CalDAVCalendarClient._parse_event(_make_caldav_event(ical))
        assert event.summary == "Meeting"
        assert event.event_id == "m1"
        assert not event.all_day
        assert event.start.hour == 14
        assert event.end.hour == 15

    def test_parse_event_all_day(self):
        ical = _make_ical(
            summary="Urlaub", uid="u1",
            dtstart="20260715", dtend="20260716",
            all_day=True,
        )
        event = CalDAVCalendarClient._parse_event(_make_caldav_event(ical))
        assert event.all_day is True
        assert event.start == datetime(2026, 7, 15)
        assert event.end == datetime(2026, 7, 16)

    def test_parse_event_no_dtend(self):
        ical = _make_ical(
            summary="Quickie", uid="q1",
            dtstart="20260330T100000", dtend=None,
        )
        event = CalDAVCalendarClient._parse_event(_make_caldav_event(ical))
        assert event.end == event.start + timedelta(hours=1)

    def test_parse_event_with_location_and_description(self):
        ical = _make_ical(
            summary="Arzt", uid="a1",
            location="Praxis", description="Blutabnahme",
        )
        event = CalDAVCalendarClient._parse_event(_make_caldav_event(ical))
        assert event.location == "Praxis"
        assert event.description == "Blutabnahme"

    def test_parse_event_no_vevent_raises(self):
        ical = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"
        with pytest.raises(ValueError, match="Kein VEVENT"):
            CalDAVCalendarClient._parse_event(_make_caldav_event(ical))


# ── Connection Recovery ──────────────────────────────────────────────

class TestConnectionRecovery:
    def test_retry_after_connection_error(self):
        store = _make_secret_store()
        client = CalDAVCalendarClient(secret_store=store)

        mock_cal = MagicMock()
        call_count = 0

        def search_with_fail(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("connection reset")
            return []

        mock_cal.search.side_effect = search_with_fail

        # Pre-set calendar so _get_calendar works after reset
        with patch.object(client, "_get_calendar", return_value=mock_cal):
            events = client.get_events(days=1)

        assert events == []
        assert call_count == 2  # 1. Versuch fehlgeschlagen, 2. erfolgreich
