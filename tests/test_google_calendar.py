"""Tests: GoogleCalendarClient – Google Calendar API Integration."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.google_calendar import CalendarEvent, GoogleCalendarClient


# ---------------------------------------------------------------------------
# CalendarEvent DTO
# ---------------------------------------------------------------------------

class TestCalendarEvent:
    def test_format_short_timed(self):
        event = CalendarEvent(
            summary="Zahnarzt",
            start=datetime(2026, 3, 20, 14, 0),
            end=datetime(2026, 3, 20, 15, 0),
            location="Praxis Dr. Müller",
        )
        result = event.format_short()
        assert "14:00-15:00" in result
        assert "Zahnarzt" in result
        assert "Dr. Müller" in result

    def test_format_short_all_day(self):
        event = CalendarEvent(
            summary="Urlaub",
            start=datetime(2026, 3, 20),
            end=datetime(2026, 3, 21),
            all_day=True,
        )
        assert "ganztags" in event.format_short()
        assert "Urlaub" in event.format_short()

    def test_format_short_no_location(self):
        event = CalendarEvent(
            summary="Meeting",
            start=datetime(2026, 3, 20, 10, 0),
            end=datetime(2026, 3, 20, 11, 0),
        )
        result = event.format_short()
        assert "Meeting" in result
        assert "(" not in result  # Kein Klammer-Ort

    def test_event_id_default_empty(self):
        event = CalendarEvent(
            summary="Test",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 1),
        )
        assert event.event_id == ""

    def test_event_id_set(self):
        event = CalendarEvent(
            summary="Test",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 1),
            event_id="abc123",
        )
        assert event.event_id == "abc123"

    def test_format_short_with_event_id(self):
        event = CalendarEvent(
            summary="Meeting",
            start=datetime(2026, 3, 20, 10, 0),
            end=datetime(2026, 3, 20, 11, 0),
            event_id="xyz789",
        )
        result = event.format_short()
        assert "[#xyz789]" in result

    def test_format_short_without_event_id(self):
        event = CalendarEvent(
            summary="Meeting",
            start=datetime(2026, 3, 20, 10, 0),
            end=datetime(2026, 3, 20, 11, 0),
        )
        result = event.format_short()
        assert "[#" not in result

    def test_frozen(self):
        event = CalendarEvent(
            summary="Test",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 1),
        )
        with pytest.raises(AttributeError):
            event.summary = "Changed"


# ---------------------------------------------------------------------------
# GoogleCalendarClient
# ---------------------------------------------------------------------------

def _make_store_mock(with_tokens: bool = True):
    """Erstellt Mock-SecretStore mit oder ohne Google-Tokens."""
    store = MagicMock()
    if with_tokens:
        token_data = {
            "token": "ya29.fake",
            "refresh_token": "1//fake_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "fake_client_id",
            "client_secret": "fake_secret",
            "scopes": ["https://www.googleapis.com/auth/calendar"],
        }
        store.get.return_value = json.dumps(token_data)
        store.get_or_none.return_value = json.dumps(token_data)
    else:
        store.get_or_none.return_value = None
    return store


class TestGoogleCalendarInit:
    def test_is_available_with_tokens(self):
        store = _make_store_mock(with_tokens=True)
        client = GoogleCalendarClient(secret_store=store)
        assert client.is_available() is True

    def test_is_available_without_tokens(self):
        store = _make_store_mock(with_tokens=False)
        client = GoogleCalendarClient(secret_store=store)
        assert client.is_available() is False

    def test_is_available_invalid_json(self):
        store = MagicMock()
        store.get_or_none.return_value = "not json"
        client = GoogleCalendarClient(secret_store=store)
        assert client.is_available() is False


class TestParseEvent:
    def test_parse_timed_event(self):
        item = {
            "summary": "Standup",
            "start": {"dateTime": "2026-03-20T09:00:00+01:00"},
            "end": {"dateTime": "2026-03-20T09:15:00+01:00"},
            "location": "Zoom",
        }
        event = GoogleCalendarClient._parse_event(item)
        assert event.summary == "Standup"
        assert event.location == "Zoom"
        assert event.all_day is False
        assert event.start.hour == 9

    def test_parse_all_day_event(self):
        item = {
            "summary": "Urlaub",
            "start": {"date": "2026-03-20"},
            "end": {"date": "2026-03-21"},
        }
        event = GoogleCalendarClient._parse_event(item)
        assert event.all_day is True
        assert event.summary == "Urlaub"

    def test_parse_no_summary(self):
        item = {
            "start": {"dateTime": "2026-03-20T10:00:00+01:00"},
            "end": {"dateTime": "2026-03-20T11:00:00+01:00"},
        }
        event = GoogleCalendarClient._parse_event(item)
        assert event.summary == "(Kein Titel)"

    def test_parse_with_description(self):
        item = {
            "summary": "Meeting",
            "start": {"dateTime": "2026-03-20T14:00:00Z"},
            "end": {"dateTime": "2026-03-20T15:00:00Z"},
            "description": "Agenda besprechen",
        }
        event = GoogleCalendarClient._parse_event(item)
        assert event.description == "Agenda besprechen"


class TestFormatEvents:
    def test_format_empty(self):
        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)
        assert client.format_events([]) == "Keine Termine."

    def test_format_multiple_events(self):
        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2026, 3, 20, 9, 0),
                end=datetime(2026, 3, 20, 9, 15),
            ),
            CalendarEvent(
                summary="Zahnarzt",
                start=datetime(2026, 3, 20, 14, 0),
                end=datetime(2026, 3, 20, 15, 0),
            ),
        ]
        result = client.format_events(events)
        assert "Standup" in result
        assert "Zahnarzt" in result
        assert "20.03.2026" in result


class TestSearchEvents:
    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_search_events_passes_query(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [{
                "summary": "Zahnarzt",
                "start": {"dateTime": "2026-04-10T14:00:00+01:00"},
                "end": {"dateTime": "2026-04-10T15:00:00+01:00"},
            }],
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)
        events = client.search_events("Zahnarzt", days=30)

        assert len(events) == 1
        assert events[0].summary == "Zahnarzt"

        # q-Parameter muss gesetzt sein
        call_kwargs = mock_service.events.return_value.list.call_args
        assert call_kwargs.kwargs["q"] == "Zahnarzt"

    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_search_events_empty(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [],
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)
        events = client.search_events("Gibtsnet")

        assert events == []


class TestCreateEvent:
    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_create_event_calls_api(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "abc123",
            "summary": "Test-Termin",
            "start": {"dateTime": "2026-03-20T14:00:00+01:00"},
            "end": {"dateTime": "2026-03-20T15:00:00+01:00"},
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        event = client.create_event(
            summary="Test-Termin",
            start=datetime(2026, 3, 20, 14, 0),
            duration_minutes=60,
        )

        assert event.summary == "Test-Termin"
        mock_service.events.return_value.insert.assert_called_once()

    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_create_event_with_location(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "abc123",
            "summary": "Meeting",
            "start": {"dateTime": "2026-03-20T14:00:00+01:00"},
            "end": {"dateTime": "2026-03-20T15:00:00+01:00"},
            "location": "Büro",
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        event = client.create_event(
            summary="Meeting",
            start=datetime(2026, 3, 20, 14, 0),
            location="Büro",
        )

        call_body = mock_service.events.return_value.insert.call_args
        assert call_body.kwargs["body"]["location"] == "Büro"

    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_create_event_all_day(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "ad123",
            "summary": "Urlaub",
            "start": {"date": "2026-07-15"},
            "end": {"date": "2026-07-16"},
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        event = client.create_event(
            summary="Urlaub",
            start=datetime(2026, 7, 15),
            all_day=True,
        )

        assert event.all_day is True
        call_body = mock_service.events.return_value.insert.call_args.kwargs["body"]
        assert "date" in call_body["start"]
        assert "dateTime" not in call_body["start"]
        assert call_body["start"]["date"] == "2026-07-15"
        assert call_body["end"]["date"] == "2026-07-16"

    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_create_event_with_recurrence(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "rec123",
            "summary": "Geburtstag",
            "start": {"date": "2026-09-28"},
            "end": {"date": "2026-09-29"},
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        client.create_event(
            summary="Geburtstag",
            start=datetime(2026, 9, 28),
            all_day=True,
            recurrence=["RRULE:FREQ=YEARLY"],
        )

        call_body = mock_service.events.return_value.insert.call_args.kwargs["body"]
        assert call_body["recurrence"] == ["RRULE:FREQ=YEARLY"]

    @patch("elder_berry.tools.google_calendar.GoogleCalendarClient._get_service")
    def test_create_event_timed_no_recurrence_no_date_key(self, mock_get_service):
        """Normaler Termin mit Uhrzeit hat dateTime, nicht date."""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "std123",
            "summary": "Meeting",
            "start": {"dateTime": "2026-03-20T14:00:00"},
            "end": {"dateTime": "2026-03-20T15:00:00"},
        }

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        client.create_event(
            summary="Meeting",
            start=datetime(2026, 3, 20, 14, 0),
        )

        call_body = mock_service.events.return_value.insert.call_args.kwargs["body"]
        assert "dateTime" in call_body["start"]
        assert "date" not in call_body["start"]
        assert "recurrence" not in call_body


# ---------------------------------------------------------------------------
# Retry-Logik (_call_with_retry)
# ---------------------------------------------------------------------------

class TestCallWithRetry:
    """Tests für _call_with_retry: stale Connection Recovery."""

    def test_ssl_error_triggers_retry_and_succeeds(self):
        """SSL-EOF beim ersten Versuch → Service neu aufbauen → Retry OK."""
        import ssl

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        mock_service_bad = MagicMock()
        mock_service_good = MagicMock()

        # Erster Call: SSL-Fehler, zweiter Call: Erfolg
        mock_service_bad.events.return_value.list.return_value.execute.side_effect = (
            ssl.SSLError("EOF occurred in violation of protocol")
        )
        mock_service_good.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "e1",
                    "summary": "Test",
                    "start": {"dateTime": "2026-03-20T14:00:00+01:00"},
                    "end": {"dateTime": "2026-03-20T15:00:00+01:00"},
                },
            ],
        }

        with patch.object(client, "_get_service") as mock_gs:
            mock_gs.side_effect = [mock_service_bad, mock_service_good]
            events = client.get_events(days=1)

        assert len(events) == 1
        assert events[0].summary == "Test"
        # Service muss 2x geholt worden sein (original + retry)
        assert mock_gs.call_count == 2

    def test_connection_error_triggers_retry(self):
        """ConnectionError wird ebenfalls retried."""
        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        mock_service_bad = MagicMock()
        mock_service_good = MagicMock()

        mock_service_bad.events.return_value.list.return_value.execute.side_effect = (
            ConnectionError("Connection reset by peer")
        )
        mock_service_good.events.return_value.list.return_value.execute.return_value = {
            "items": [],
        }

        with patch.object(client, "_get_service") as mock_gs:
            mock_gs.side_effect = [mock_service_bad, mock_service_good]
            events = client.get_events(days=1)

        assert events == []
        assert mock_gs.call_count == 2

    def test_non_retriable_error_propagates(self):
        """Nicht-Connection-Fehler werden sofort hochgeworfen."""
        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.side_effect = (
            ValueError("Totally different error")
        )

        with patch.object(client, "_get_service", return_value=mock_service):
            with pytest.raises(ValueError, match="Totally different"):
                client.get_events(days=1)

    def test_service_invalidated_after_ssl_error(self):
        """Nach SSL-Fehler muss _service auf None stehen."""
        import ssl

        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)
        client._service = MagicMock()  # Simuliere gecachten Service

        call_count = 0

        def fake_operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ssl.SSLError("EOF")
            return "ok"

        result = client._call_with_retry(fake_operation)
        assert result == "ok"
        assert client._service is None  # Wurde invalidiert

    def test_delete_event_410_gone_returns_true(self):
        """delete_event: 410 Gone auf Retry = Erfolg (Idempotenz)."""
        store = _make_store_mock()
        client = GoogleCalendarClient(secret_store=store)

        mock_service = MagicMock()
        # Simuliere 410 Gone - Produktionscode prueft String, kein HttpError noetig
        mock_service.events.return_value.delete.return_value.execute.side_effect = (
            Exception("<HttpError 410 when requesting ... returned 'Gone'>")
        )

        with patch.object(client, "_get_service", return_value=mock_service):
            result = client.delete_event("already-gone-id")

        assert result is True
