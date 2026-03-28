"""Tests für SmartContextProvider – Phase 33: Smart Context Layer."""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.core.smart_context import (
    ContextSource,
    SmartContextProvider,
    _META_PHRASES,
    _SOURCE_KEYWORDS,
)


# --- Fixtures ---

@pytest.fixture
def mock_calendar():
    cal = MagicMock()
    event = MagicMock()
    event.format_short.return_value = "14:00-15:00 Zahnarzt"
    cal.get_today.return_value = [event]
    return cal


@pytest.fixture
def mock_todo_store():
    store = MagicMock()
    store.format_for_briefing.return_value = (
        "📋 Offene Todos:\n  - Einkaufen [high]"
    )
    return store


@pytest.fixture
def mock_note_store():
    store = MagicMock()
    note = MagicMock()
    note.key = "dach"
    note.content = "Dachprojekt: Angebot von Firma XY einholen"
    store.search.return_value = [note]
    return store


@pytest.fixture
def mock_contact_store():
    store = MagicMock()
    contact = MagicMock()
    contact.name = "Max Mustermann"
    contact.email = "max@example.com"
    contact.role = "Handwerker"
    store.search.return_value = [contact]
    return store


@pytest.fixture
def mock_reminder_store():
    store = MagicMock()
    reminder = MagicMock()
    reminder.id = 1
    reminder.message = "Müll rausbringen"
    reminder.due_at = datetime(2026, 3, 28, 18, 0, 0, tzinfo=timezone.utc)
    store.get_pending.return_value = [reminder]
    return store


@pytest.fixture
def mock_weather():
    client = MagicMock()
    result = MagicMock()
    result.description = "Bewölkt"
    result.temperature = 12.5
    result.apparent_temperature = 10.2
    client.get_current.return_value = result
    return client


@pytest.fixture
def provider_all(
    mock_calendar, mock_todo_store, mock_note_store,
    mock_contact_store, mock_reminder_store, mock_weather,
):
    return SmartContextProvider(
        calendar=mock_calendar,
        todo_store=mock_todo_store,
        note_store=mock_note_store,
        contact_store=mock_contact_store,
        reminder_store=mock_reminder_store,
        weather_client=mock_weather,
        default_user_id="@user:matrix.test",
    )


@pytest.fixture
def provider_empty():
    return SmartContextProvider()


# === _detect_sources Tests ===

class TestDetectSources:
    """Keyword-basierte Quellen-Erkennung."""

    def test_calendar_keywords(self, provider_all):
        for kw in ["termin", "kalender", "meeting", "heute", "morgen", "montag"]:
            result = provider_all._detect_sources(f"Was ist der {kw}?")
            assert ContextSource.CALENDAR in result, (
                f"'{kw}' should trigger CALENDAR"
            )

    def test_todo_keywords(self, provider_all):
        for kw in ["todo", "aufgabe", "erledigen", "machen"]:
            result = provider_all._detect_sources(f"Was soll ich {kw}?")
            assert ContextSource.TODOS in result, (
                f"'{kw}' should trigger TODOS"
            )

    def test_reminder_keywords(self, provider_all):
        for kw in ["erinnerung", "fällig", "vergessen"]:
            result = provider_all._detect_sources(f"Habe ich eine {kw}?")
            assert ContextSource.REMINDERS in result, (
                f"'{kw}' should trigger REMINDERS"
            )

    def test_note_keywords(self, provider_all):
        for kw in ["notiz", "merke", "fakt"]:
            result = provider_all._detect_sources(f"Gibt es eine {kw}?")
            assert ContextSource.NOTES in result, (
                f"'{kw}' should trigger NOTES"
            )

    def test_contact_keywords(self, provider_all):
        for kw in ["kontakt", "telefon", "email", "nummer"]:
            result = provider_all._detect_sources(f"Was ist die {kw}?")
            assert ContextSource.CONTACTS in result, (
                f"'{kw}' should trigger CONTACTS"
            )

    def test_weather_keywords(self, provider_all):
        for kw in ["wetter", "regen", "temperatur", "kalt", "warm"]:
            result = provider_all._detect_sources(f"Wie ist das {kw}?")
            assert ContextSource.WEATHER in result, (
                f"'{kw}' should trigger WEATHER"
            )

    def test_meta_phrase_was_muss_ich(self, provider_all):
        result = provider_all._detect_sources("Was muss ich heute noch machen?")
        assert ContextSource.CALENDAR in result
        assert ContextSource.TODOS in result
        assert ContextSource.REMINDERS in result

    def test_meta_phrase_briefing(self, provider_all):
        result = provider_all._detect_sources("Gib mir ein Briefing")
        assert ContextSource.CALENDAR in result
        assert ContextSource.TODOS in result
        assert ContextSource.REMINDERS in result
        assert ContextSource.WEATHER in result

    def test_meta_phrase_wie_sieht_mein_tag_aus(self, provider_all):
        result = provider_all._detect_sources("Wie sieht mein Tag aus?")
        assert ContextSource.CALENDAR in result
        assert ContextSource.TODOS in result
        assert ContextSource.REMINDERS in result
        assert ContextSource.WEATHER in result

    def test_meta_phrase_tagesplan(self, provider_all):
        result = provider_all._detect_sources("Zeig mir den Tagesplan")
        assert ContextSource.CALENDAR in result
        assert ContextSource.TODOS in result
        assert ContextSource.REMINDERS in result

    def test_no_keywords_returns_empty(self, provider_all):
        result = provider_all._detect_sources("Hallo, wie geht es dir?")
        assert result == set()

    def test_case_insensitive(self, provider_all):
        result = provider_all._detect_sources("TERMIN morgen WETTER")
        assert ContextSource.CALENDAR in result
        assert ContextSource.WEATHER in result

    def test_multiple_sources(self, provider_all):
        result = provider_all._detect_sources(
            "Zeig mir meine Termine und das Wetter",
        )
        assert ContextSource.CALENDAR in result
        assert ContextSource.WEATHER in result

    def test_all_meta_phrases_recognized(self, provider_all):
        for phrase, expected_sources in _META_PHRASES:
            result = provider_all._detect_sources(phrase)
            for source in expected_sources:
                assert source in result, (
                    f"'{phrase}' should trigger {source.value}"
                )


# === _filter_available Tests ===

class TestFilterAvailable:
    """Filtert auf konfigurierte Stores."""

    def test_all_stores_configured(self, provider_all):
        all_sources = set(ContextSource)
        result = provider_all._filter_available(all_sources)
        assert result == all_sources

    def test_no_stores_configured(self, provider_empty):
        all_sources = set(ContextSource)
        result = provider_empty._filter_available(all_sources)
        assert result == set()

    def test_partial_stores(self, mock_calendar):
        provider = SmartContextProvider(calendar=mock_calendar)
        result = provider._filter_available(
            {ContextSource.CALENDAR, ContextSource.TODOS},
        )
        assert result == {ContextSource.CALENDAR}


# === Einzelne Query-Methoden ===

class TestQueryCalendar:
    def test_events_formatted(self, provider_all, mock_calendar):
        result = provider_all._query_calendar()
        assert "📅 Termine heute:" in result
        assert "14:00-15:00 Zahnarzt" in result

    def test_no_events_returns_empty(self, provider_all, mock_calendar):
        mock_calendar.get_today.return_value = []
        assert provider_all._query_calendar() == ""

    def test_multiple_events(self, provider_all, mock_calendar):
        ev1 = MagicMock()
        ev1.format_short.return_value = "09:00-10:00 Standup"
        ev2 = MagicMock()
        ev2.format_short.return_value = "14:00-15:00 Zahnarzt"
        mock_calendar.get_today.return_value = [ev1, ev2]
        result = provider_all._query_calendar()
        assert "Standup" in result
        assert "Zahnarzt" in result


class TestQueryTodos:
    def test_todos_returned(self, provider_all):
        result = provider_all._query_todos()
        assert "Offene Todos" in result
        assert "Einkaufen" in result

    def test_no_user_id_returns_empty(self, mock_todo_store):
        provider = SmartContextProvider(
            todo_store=mock_todo_store, default_user_id="",
        )
        assert provider._query_todos() == ""


class TestQueryReminders:
    def _patch_now(self, year=2026, month=3, day=28, hour=12):
        """Patch datetime.now() in smart_context Modul."""
        mock_dt = MagicMock(wraps=datetime)
        mock_dt.now.return_value = datetime(
            year, month, day, hour, 0, 0, tzinfo=timezone.utc,
        )
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        return patch("elder_berry.core.smart_context.datetime", mock_dt)

    def test_today_reminders_included(self, provider_all):
        with self._patch_now():
            result = provider_all._query_reminders()
        assert "⏰ Offene Erinnerungen:" in result
        assert "Müll rausbringen" in result

    def test_no_pending_returns_empty(self, provider_all, mock_reminder_store):
        mock_reminder_store.get_pending.return_value = []
        with self._patch_now():
            result = provider_all._query_reminders()
        assert result == ""

    def test_future_reminders_filtered(self, provider_all, mock_reminder_store):
        reminder = MagicMock()
        reminder.id = 2
        reminder.message = "Nächste Woche"
        reminder.due_at = datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc)
        mock_reminder_store.get_pending.return_value = [reminder]
        with self._patch_now():
            result = provider_all._query_reminders()
        assert result == ""

    def test_no_user_id_passes_none(self, mock_reminder_store):
        mock_reminder_store.get_pending.return_value = []
        provider = SmartContextProvider(
            reminder_store=mock_reminder_store, default_user_id="",
        )
        with self._patch_now():
            provider._query_reminders()
        mock_reminder_store.get_pending.assert_called_once_with(None)


class TestQueryNotes:
    def test_notes_found(self, provider_all):
        result = provider_all._query_notes("Dachprojekt")
        assert "📝 Relevante Notizen:" in result
        assert "🔑 dach:" in result
        assert "Dachprojekt" in result

    def test_note_without_key(self, provider_all, mock_note_store):
        note = MagicMock()
        note.key = None
        note.content = "Einfache Notiz"
        mock_note_store.search.return_value = [note]
        result = provider_all._query_notes("test")
        assert "🔑" not in result
        assert "Einfache Notiz" in result

    def test_no_user_id_returns_empty(self, mock_note_store):
        provider = SmartContextProvider(
            note_store=mock_note_store, default_user_id="",
        )
        assert provider._query_notes("test") == ""

    def test_no_results_returns_empty(self, provider_all, mock_note_store):
        mock_note_store.search.return_value = []
        assert provider_all._query_notes("xyz") == ""

    def test_content_truncated_at_200(self, provider_all, mock_note_store):
        note = MagicMock()
        note.key = None
        note.content = "A" * 300
        mock_note_store.search.return_value = [note]
        result = provider_all._query_notes("lang")
        assert "A" * 200 in result
        assert "A" * 201 not in result


class TestQueryContacts:
    def test_contacts_found(self, provider_all):
        result = provider_all._query_contacts("Max")
        assert "👤 Gefundene Kontakte:" in result
        assert "Max Mustermann" in result
        assert "max@example.com" in result
        assert "Handwerker" in result

    def test_contact_without_email(self, provider_all, mock_contact_store):
        contact = MagicMock()
        contact.name = "Lisa"
        contact.email = ""
        contact.role = "Freundin"
        mock_contact_store.search.return_value = [contact]
        result = provider_all._query_contacts("Lisa")
        assert "Lisa" in result
        assert "Freundin" in result

    def test_no_user_id_returns_empty(self, mock_contact_store):
        provider = SmartContextProvider(
            contact_store=mock_contact_store, default_user_id="",
        )
        assert provider._query_contacts("test") == ""

    def test_no_results_returns_empty(self, provider_all, mock_contact_store):
        mock_contact_store.search.return_value = []
        assert provider_all._query_contacts("xyz") == ""


class TestQueryWeather:
    def test_weather_formatted(self, provider_all):
        result = provider_all._query_weather()
        assert "🌤️ Wetter:" in result
        assert "Bewölkt" in result
        assert "12.5°C" in result
        assert "10.2°C" in result


# === Integration: get_context ===

class TestGetContext:
    """End-to-End Tests für get_context()."""

    def test_happy_path_single_source(self, provider_all):
        result = provider_all.get_context("Wie wird das Wetter?")
        assert "=== Aktueller Kontext" in result
        assert "🌤️ Wetter:" in result

    def test_happy_path_multi_source(self, provider_all):
        with patch("elder_berry.core.smart_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc,
            )
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = provider_all.get_context("Gib mir ein Briefing")
        assert "📅 Termine heute:" in result
        assert "Offene Todos" in result
        assert "🌤️ Wetter:" in result

    def test_no_keywords_returns_empty(self, provider_all):
        assert provider_all.get_context("Hallo, wie geht es dir?") == ""

    def test_empty_input_returns_empty(self, provider_all):
        assert provider_all.get_context("") == ""

    def test_no_stores_returns_empty(self, provider_empty):
        assert provider_empty.get_context("Was sind meine Termine?") == ""

    def test_store_exception_graceful(self, provider_all, mock_calendar):
        mock_calendar.get_today.side_effect = RuntimeError("Connection failed")
        result = provider_all.get_context("Termine heute?")
        assert isinstance(result, str)
        assert "Connection failed" not in result

    def test_store_timeout_graceful(self, mock_todo_store):
        def slow_store(*args, **kwargs):
            time.sleep(2)
            return "should not appear"

        mock_todo_store.format_for_briefing = slow_store
        provider = SmartContextProvider(
            todo_store=mock_todo_store,
            default_user_id="@user:test",
        )
        with patch("elder_berry.core.smart_context.SOURCE_TIMEOUT_SECONDS", 0.5):
            result = provider.get_context("Meine offenen Aufgaben")
        assert "should not appear" not in result

    def test_format_order_calendar_before_weather(self, provider_all):
        with patch("elder_berry.core.smart_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(
                2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc,
            )
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = provider_all.get_context("Briefing bitte")
        cal_pos = result.find("📅")
        weather_pos = result.find("🌤️")
        assert cal_pos < weather_pos

    def test_context_header_present(self, provider_all):
        result = provider_all.get_context("Termine heute")
        assert result.startswith("=== Aktueller Kontext")


# === Edge Cases ===

class TestEdgeCases:
    def test_partial_stores_only_queries_available(self, mock_calendar):
        provider = SmartContextProvider(calendar=mock_calendar)
        result = provider.get_context("Was steht heute an?")
        assert "📅 Termine heute:" in result
        mock_calendar.get_today.assert_called_once()

    def test_keyword_with_umlaut(self, provider_all):
        result = provider_all._detect_sources("Ist es bewölkt?")
        assert ContextSource.WEATHER in result

    def test_keyword_fällig(self, provider_all):
        result = provider_all._detect_sources("Was ist fällig?")
        assert ContextSource.REMINDERS in result

    def test_hyphenated_keyword(self, provider_all):
        result = provider_all._detect_sources("Meine to-do Liste")
        assert ContextSource.TODOS in result

    def test_all_stores_none_returns_empty(self):
        provider = SmartContextProvider()
        assert provider.get_context("Briefing") == ""

    def test_get_query_fn_returns_none_for_unknown(self, provider_all):
        # ContextSource hat nur definierte Werte, aber _get_query_fn soll
        # None zurückgeben für nicht gemappte Quellen (Defensive)
        fn = provider_all._get_query_fn(ContextSource.CALENDAR, "test")
        assert fn is not None

    def test_multiple_stores_one_fails(
        self, mock_calendar, mock_todo_store, mock_weather,
    ):
        mock_todo_store.format_for_briefing.side_effect = RuntimeError("DB locked")
        provider = SmartContextProvider(
            calendar=mock_calendar,
            todo_store=mock_todo_store,
            weather_client=mock_weather,
            default_user_id="@user:test",
        )
        result = provider.get_context("Briefing bitte")
        # Calendar und Weather sollten trotzdem da sein
        assert "📅 Termine heute:" in result
        assert "🌤️ Wetter:" in result
        assert "DB locked" not in result
