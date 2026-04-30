"""Tests: CalendarCommandHandler – Termin CRUD, Pattern-Matching."""

from datetime import datetime, date, timedelta
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.calendar_commands import (
    TERMIN_CREATE_PATTERN,
    TERMIN_DELETE_PATTERN,
    TERMIN_SEARCH_PATTERN,
    TERMINE_PATTERN,
    CalendarCommandHandler,
    _parse_natural_date,
    _parse_recurrence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(summary="Zahnarzt", event_id="evt123"):
    evt = MagicMock()
    evt.summary = summary
    evt.event_id = event_id
    evt.format_short.return_value = f"{summary} (id={event_id})"
    return evt


@pytest.fixture
def calendar():
    cal = MagicMock()
    cal.get_today.return_value = [_make_event()]
    cal.get_tomorrow.return_value = [_make_event("Meeting", "evt456")]
    cal.get_events.return_value = [_make_event()]
    cal.format_events.return_value = "- Zahnarzt 14:00"
    cal.search_events.return_value = [_make_event()]
    return cal


@pytest.fixture
def handler(calendar):
    return CalendarCommandHandler(calendar=calendar)


@pytest.fixture
def handler_no_calendar():
    return CalendarCommandHandler(calendar=None)


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------


class TestTerminePattern:
    @pytest.mark.parametrize(
        "text,param",
        [
            ("termine morgen", "morgen"),
            ("termine woche", "woche"),
            ("termine 5", "5"),
            ("Termine Morgen", "Morgen"),
        ],
    )
    def test_valid(self, text, param):
        m = TERMINE_PATTERN.match(text.lower())
        assert m is not None

    def test_bare_termine_no_match(self):
        assert TERMINE_PATTERN.match("termine") is None


class TestTerminCreatePattern:
    @pytest.mark.parametrize(
        "text",
        [
            "termin: Zahnarzt morgen 14:00",
            "termin: Meeting 2026-03-30 10:00",
            "termin: Call 30.03 15:30",
            "termin: Test 30.03.2026 09:00",
            "erstelle termin Meeting morgen 14:00",
            "termin Zahnarzt übermorgen 10:00",
            "termin: Lunch morgen um 12:30 Uhr",
        ],
    )
    def test_valid(self, text):
        assert TERMIN_CREATE_PATTERN.match(text) is not None

    def test_no_time_is_all_day(self):
        """Ohne Uhrzeit = Ganztags-Event (kein Fehler mehr)."""
        m = TERMIN_CREATE_PATTERN.match("termin: Urlaub morgen")
        assert m is not None
        assert m.group(3) is None  # Keine Uhrzeit

    def test_all_day_with_date(self):
        m = TERMIN_CREATE_PATTERN.match("termin: Urlaub 15.07")
        assert m is not None
        assert m.group(1).strip() == "Urlaub"
        assert m.group(3) is None

    def test_recurrence_yearly(self):
        m = TERMIN_CREATE_PATTERN.match("termin: Geburtstag Lisa 28.09 jährlich")
        assert m is not None
        assert m.group(3) is None  # Keine Uhrzeit
        assert m.group(4).lower() == "jährlich"

    def test_recurrence_daily_with_time(self):
        m = TERMIN_CREATE_PATTERN.match(
            "termin: Standup morgen 09:00 täglich wiederholen"
        )
        assert m is not None
        assert m.group(3) == "09:00"
        assert m.group(4).lower() == "täglich"

    def test_recurrence_weekly(self):
        m = TERMIN_CREATE_PATTERN.match("termin: Jour fixe 01.04 10:00 wöchentlich")
        assert m is not None
        assert m.group(4).lower() == "wöchentlich"

    def test_recurrence_english(self):
        m = TERMIN_CREATE_PATTERN.match("termin: Backup 01.04 yearly")
        assert m is not None
        assert m.group(4).lower() == "yearly"


class TestTerminDeletePattern:
    @pytest.mark.parametrize(
        "text",
        [
            "termin löschen abc123",
            "lösche termin abc123",
            "lösche den termin abc123",
            "lösche alle termine",
            "entferne termin test",
        ],
    )
    def test_valid(self, text):
        assert TERMIN_DELETE_PATTERN.match(text) is not None


class TestTerminSearchPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "termin suche Zahnarzt",
            "suche den termin Meeting",
            "termine suche Arzt",
        ],
    )
    def test_valid(self, text):
        assert TERMIN_SEARCH_PATTERN.search(text) is not None


# ---------------------------------------------------------------------------
# _parse_natural_date
# ---------------------------------------------------------------------------


class TestParseNaturalDate:
    def test_morgen(self):
        result = _parse_natural_date("morgen")
        expected = date.today() + timedelta(days=1)
        assert result.date() == expected

    def test_uebermorgen(self):
        result = _parse_natural_date("übermorgen")
        expected = date.today() + timedelta(days=2)
        assert result.date() == expected

    def test_iso_format(self):
        result = _parse_natural_date("2026-03-30")
        assert result == datetime(2026, 3, 30)

    def test_de_format(self):
        result = _parse_natural_date("30.03.2026")
        assert result == datetime(2026, 3, 30)

    def test_de_short(self):
        result = _parse_natural_date("30.03")
        assert result.month == 3
        assert result.day == 30

    def test_invalid(self):
        assert _parse_natural_date("gestern") is None

    def test_de_format_yy(self):
        result = _parse_natural_date("30.03.26")
        assert result.year == 2026


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class TestCalendarInterface:
    def test_simple_commands(self, handler):
        cmds = handler.simple_commands
        assert "termine" in cmds
        assert "kalender" in cmds

    def test_patterns(self, handler):
        names = [p[1] for p in handler.patterns]
        assert "termin_create" in names
        assert "termin_delete" in names
        assert "termin_search" in names
        assert "termine" in names

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "termine" in kw


# ---------------------------------------------------------------------------
# Termine (Query)
# ---------------------------------------------------------------------------


class TestTermineQuery:
    def test_termine_today(self, handler, calendar):
        result = handler.execute("termine", "termine")
        assert result.success is True
        assert "Termine heute" in result.text
        calendar.get_today.assert_called_once()

    def test_termine_morgen_via_pattern(self, handler, calendar):
        result = handler.execute("termine", "termine morgen")
        assert result.success is True
        calendar.get_tomorrow.assert_called_once()

    def test_termine_woche(self, handler, calendar):
        result = handler.execute("termine", "termine woche")
        assert result.success is True
        calendar.get_events.assert_called_once_with(days=7)

    def test_termine_n_days(self, handler, calendar):
        result = handler.execute("termine", "termine 3")
        assert result.success is True
        calendar.get_events.assert_called_once_with(days=3)

    def test_termine_keyword_woche(self, handler, calendar):
        result = handler.execute("termine_woche", "nächste woche")
        assert result.success is True
        calendar.get_events.assert_called_once_with(days=7)

    def test_termine_keyword_morgen(self, handler, calendar):
        result = handler.execute("termine_morgen", "morgen termine")
        assert result.success is True
        calendar.get_tomorrow.assert_called_once()

    def test_no_calendar(self, handler_no_calendar):
        result = handler_no_calendar.execute("termine", "termine")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_calendar_exception(self, handler, calendar):
        calendar.get_today.side_effect = RuntimeError("API error")
        result = handler.execute("termine", "termine")
        assert result.success is False

    def test_stores_last_events(self, handler, calendar):
        events = [_make_event()]
        calendar.get_today.return_value = events
        handler.execute("termine", "termine")
        assert handler._last_events == events


# ---------------------------------------------------------------------------
# Termin Create
# ---------------------------------------------------------------------------


class TestTerminCreate:
    def test_create_morgen(self, handler, calendar):
        evt = _make_event("Zahnarzt", "new123")
        calendar.create_event.return_value = evt
        result = handler.execute("termin_create", "termin: Zahnarzt morgen 14:00")
        assert result.success is True
        assert "erstellt" in result.text.lower()
        calendar.create_event.assert_called_once()

    def test_create_no_calendar(self, handler_no_calendar):
        result = handler_no_calendar.execute(
            "termin_create", "termin: Test morgen 14:00"
        )
        assert result.success is False

    def test_create_invalid_format(self, handler):
        result = handler.execute("termin_create", "termin: Test")
        assert result.success is False

    def test_create_invalid_date(self, handler):
        # "gestern" wird vom Create-Pattern nicht erkannt → Format-Fehler
        result = handler.execute("termin_create", "termin: Test gestern 14:00")
        assert result.success is False

    def test_create_api_error(self, handler, calendar):
        calendar.create_event.side_effect = RuntimeError("API fail")
        result = handler.execute("termin_create", "termin: Test morgen 14:00")
        assert result.success is False


# ---------------------------------------------------------------------------
# Termin Search
# ---------------------------------------------------------------------------


class TestTerminSearch:
    def test_search_success(self, handler, calendar):
        result = handler.execute("termin_search", "termin suche Zahnarzt")
        assert result.success is True
        assert "Zahnarzt" in result.text
        calendar.search_events.assert_called_once()

    def test_search_no_results(self, handler, calendar):
        calendar.search_events.return_value = []
        result = handler.execute("termin_search", "termin suche XYZ")
        assert result.success is True
        assert "Keine" in result.text

    def test_search_no_calendar(self, handler_no_calendar):
        result = handler_no_calendar.execute("termin_search", "termin suche test")
        assert result.success is False

    def test_search_invalid_format(self, handler):
        result = handler.execute("termin_search", "suche")
        assert result.success is False


# ---------------------------------------------------------------------------
# Termin Delete
# ---------------------------------------------------------------------------


class TestTerminDelete:
    def test_delete_by_index(self, handler, calendar):
        events = [_make_event("A", "id1"), _make_event("B", "id2")]
        handler._last_events = events
        result = handler.execute("termin_delete", "lösche den 1. termin")
        assert result.success is True
        calendar.delete_event.assert_called_once_with("id1")

    def test_delete_alle_asks_confirmation(self, handler, calendar):
        events = [_make_event("A", "id1"), _make_event("B", "id2")]
        handler._last_events = events
        result = handler.execute("termin_delete", "lösche alle termine")
        assert result.success is True
        assert result.pending_confirmation is True
        assert result.pending_data["action_type"] == "bulk_delete_events"
        assert result.pending_data["event_ids"] == ["id1", "id2"]
        calendar.delete_event.assert_not_called()

    def test_delete_alle_confirmed(self, handler, calendar):
        """execute_delete_all_events löscht nach Bestätigung."""
        result = handler.execute_delete_all_events(["id1", "id2"])
        assert result.success is True
        assert calendar.delete_event.call_count == 2

    def test_delete_no_events(self, handler):
        handler._last_events = []
        result = handler.execute("termin_delete", "lösche alle termine")
        assert result.success is False

    def test_delete_by_title(self, handler, calendar):
        events = [_make_event("Zahnarzt", "id1")]
        handler._last_events = events
        result = handler.execute("termin_delete", "lösche termin Zahnarzt")
        assert result.success is True
        calendar.delete_event.assert_called_once_with("id1")

    def test_delete_invalid_index(self, handler):
        handler._last_events = [_make_event()]
        result = handler.execute("termin_delete", "lösche den 5. termin")
        assert result.success is False
        assert "ungültig" in result.text.lower()

    def test_delete_no_calendar(self, handler_no_calendar):
        result = handler_no_calendar.execute("termin_delete", "lösche termin x")
        assert result.success is False

    def test_delete_api_error(self, handler, calendar):
        events = [_make_event("A", "id1")]
        handler._last_events = events
        calendar.delete_event.side_effect = RuntimeError("fail")
        result = handler.execute("termin_delete", "lösche den 1. termin")
        assert result.success is False


# ---------------------------------------------------------------------------
# _parse_index
# ---------------------------------------------------------------------------


class TestParseIndex:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1", 1),
            ("2.", 2),
            ("den 1.", 1),
            ("ersten", 1),
            ("zweiten", 2),
            ("dritten", 3),
            ("die erste", 1),
        ],
    )
    def test_valid(self, text, expected):
        assert CalendarCommandHandler._parse_index(text) == expected

    def test_invalid(self):
        assert CalendarCommandHandler._parse_index("abc") is None


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _parse_recurrence
# ---------------------------------------------------------------------------


class TestParseRecurrence:
    @pytest.mark.parametrize(
        "text,expected_freq",
        [
            ("jährlich", "YEARLY"),
            ("yearly", "YEARLY"),
            ("monatlich", "MONTHLY"),
            ("monthly", "MONTHLY"),
            ("wöchentlich", "WEEKLY"),
            ("weekly", "WEEKLY"),
            ("täglich", "DAILY"),
            ("daily", "DAILY"),
        ],
    )
    def test_valid(self, text, expected_freq):
        result = _parse_recurrence(text)
        assert result == [f"RRULE:FREQ={expected_freq}"]

    def test_none_input(self):
        assert _parse_recurrence(None) is None

    def test_empty_string(self):
        assert _parse_recurrence("") is None

    def test_unknown(self):
        assert _parse_recurrence("stündlich") is None


# ---------------------------------------------------------------------------
# Termin Create – All-Day + Recurrence
# ---------------------------------------------------------------------------


class TestTerminCreateAllDay:
    def test_create_all_day(self, handler, calendar):
        evt = _make_event("Urlaub", "new_ad")
        calendar.create_event.return_value = evt
        result = handler.execute("termin_create", "termin: Urlaub 15.07")
        assert result.success is True
        calendar.create_event.assert_called_once()
        call_kwargs = calendar.create_event.call_args.kwargs
        assert call_kwargs["all_day"] is True
        assert call_kwargs["recurrence"] is None

    def test_create_with_recurrence_yearly(self, handler, calendar):
        evt = _make_event("Geburtstag Lisa", "new_rec")
        calendar.create_event.return_value = evt
        result = handler.execute(
            "termin_create",
            "termin: Geburtstag Lisa 28.09 jährlich",
        )
        assert result.success is True
        call_kwargs = calendar.create_event.call_args.kwargs
        assert call_kwargs["all_day"] is True
        assert call_kwargs["recurrence"] == ["RRULE:FREQ=YEARLY"]
        assert "wiederholt" in result.text

    def test_create_with_time_and_recurrence(self, handler, calendar):
        evt = _make_event("Standup", "new_daily")
        calendar.create_event.return_value = evt
        result = handler.execute(
            "termin_create",
            "termin: Standup morgen 09:00 täglich wiederholen",
        )
        assert result.success is True
        call_kwargs = calendar.create_event.call_args.kwargs
        assert call_kwargs["all_day"] is False
        assert call_kwargs["recurrence"] == ["RRULE:FREQ=DAILY"]

    def test_create_with_time_no_recurrence(self, handler, calendar):
        """Bestehender Fall: Uhrzeit ohne Wiederholung bleibt wie bisher."""
        evt = _make_event("Zahnarzt", "evt_std")
        calendar.create_event.return_value = evt
        result = handler.execute("termin_create", "termin: Zahnarzt morgen 14:00")
        assert result.success is True
        call_kwargs = calendar.create_event.call_args.kwargs
        assert call_kwargs["all_day"] is False
        assert call_kwargs["recurrence"] is None


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    def test_unknown(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False
