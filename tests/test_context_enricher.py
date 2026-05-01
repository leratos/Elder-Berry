"""Tests: ContextEnricher – Proaktive Kontext-Verknüpfung (Phase 21)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.core.context_enricher import (
    ContextEnricher,
    EnrichmentResult,
    ENRICHMENT_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_note_store():
    store = MagicMock()
    store.search.return_value = []
    return store


@pytest.fixture
def mock_email_client():
    client = MagicMock()
    client.search.return_value = []
    return client


@pytest.fixture
def mock_weather_client():
    client = MagicMock()
    return client


@pytest.fixture
def mock_memory_store():
    store = MagicMock()
    store.search.return_value = []
    return store


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate.return_value = "Zusammenfassung vom LLM"
    return llm


@pytest.fixture
def enricher(
    mock_note_store, mock_email_client, mock_weather_client, mock_memory_store, mock_llm
):
    return ContextEnricher(
        note_store=mock_note_store,
        email_client=mock_email_client,
        weather_client=mock_weather_client,
        memory_store=mock_memory_store,
        llm=mock_llm,
        default_user_id="@user:matrix.example.com",
    )


def _make_note(key=None, content="Testnotiz"):
    note = MagicMock()
    note.key = key
    note.content = content
    return note


def _make_mail(sender="Max <max@example.com>", subject="Betreff", date=None):
    mail = MagicMock()
    mail.sender = sender
    mail.subject = subject
    mail.date = date or datetime(2026, 3, 19, 14, 22, tzinfo=timezone.utc)
    return mail


def _make_weather(description="Klar", temperature=18.5, apparent_temperature=17.0):
    w = MagicMock()
    w.description = description
    w.temperature = temperature
    w.apparent_temperature = apparent_temperature
    return w


def _make_memory(content="Erinnerung an letzte Besprechung"):
    m = MagicMock()
    m.content = content
    return m


# ---------------------------------------------------------------------------
# EnrichmentResult Dataclass
# ---------------------------------------------------------------------------


class TestEnrichmentResult:
    def test_empty_result_has_no_context(self):
        r = EnrichmentResult()
        assert not r.has_context
        assert r.formatted == ""

    def test_with_notes_has_context(self):
        r = EnrichmentResult(raw_notes=["Notiz 1"])
        assert r.has_context

    def test_with_mails_has_context(self):
        r = EnrichmentResult(raw_mails=["Mail 1"])
        assert r.has_context

    def test_with_weather_has_context(self):
        r = EnrichmentResult(raw_weather="Klar, 18°C")
        assert r.has_context

    def test_with_memories_has_context(self):
        r = EnrichmentResult(raw_memories=["Memory 1"])
        assert r.has_context

    def test_frozen(self):
        r = EnrichmentResult()
        with pytest.raises(AttributeError):
            r.formatted = "nope"


# ---------------------------------------------------------------------------
# ContextEnricher – Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_all_sources_optional(self):
        e = ContextEnricher()
        result = e.enrich_event("Test", datetime.now(timezone.utc))
        assert not result.has_context

    def test_stores_dependencies(self, enricher, mock_note_store, mock_llm):
        assert enricher._note_store is mock_note_store
        assert enricher._llm is mock_llm


# ---------------------------------------------------------------------------
# ContextEnricher – Einzelne Quellen
# ---------------------------------------------------------------------------


class TestSearchNotes:
    def test_returns_formatted_notes(self, enricher, mock_note_store):
        mock_note_store.search.return_value = [
            _make_note(key="Projekt", content="Dachsanierung besprechen"),
        ]
        result = enricher._search_notes("Meeting Max")
        assert len(result) == 1
        assert "Projekt" in result[0]
        assert "Dachsanierung" in result[0]
        mock_note_store.search.assert_called_once_with(
            "@user:matrix.example.com",
            "Meeting Max",
            3,
        )

    def test_empty_when_no_store(self):
        e = ContextEnricher(note_store=None)
        assert e._search_notes("test") == []

    def test_empty_when_no_user_id(self, mock_note_store):
        e = ContextEnricher(note_store=mock_note_store, default_user_id="")
        assert e._search_notes("test") == []

    def test_freetext_note_format(self, enricher, mock_note_store):
        mock_note_store.search.return_value = [
            _make_note(key=None, content="Freier Text")
        ]
        result = enricher._search_notes("query")
        assert result[0].startswith("\U0001f4dd")  # 📝

    def test_timeout_returns_empty(self, enricher, mock_note_store):
        import time

        mock_note_store.search.side_effect = lambda *a: time.sleep(10)
        with patch("elder_berry.core.context_enricher.SOURCE_TIMEOUT_SECONDS", 0.1):
            result = enricher._search_notes("test")
        assert result == []

    def test_exception_returns_empty(self, enricher, mock_note_store):
        mock_note_store.search.side_effect = RuntimeError("DB kaputt")
        result = enricher._search_notes("test")
        assert result == []


class TestSearchMails:
    def test_returns_formatted_mails(self, enricher, mock_email_client):
        mock_email_client.search.return_value = [
            _make_mail(sender="Max", subject="Angebot Dach"),
        ]
        result = enricher._search_mails("Meeting Max")
        assert len(result) == 1
        assert "Max" in result[0]
        assert "Angebot Dach" in result[0]
        mock_email_client.search.assert_called_once_with("Meeting Max", 3, 7)

    def test_empty_when_no_client(self):
        e = ContextEnricher(email_client=None)
        assert e._search_mails("test") == []

    def test_exception_returns_empty(self, enricher, mock_email_client):
        mock_email_client.search.side_effect = ConnectionError("IMAP down")
        result = enricher._search_mails("test")
        assert result == []


class TestGetWeather:
    def test_returns_formatted_weather(self, enricher, mock_weather_client):
        mock_weather_client.get_current.return_value = _make_weather()
        result = enricher._get_weather("Büro")
        assert "Klar" in result
        assert "18.5" in result

    def test_none_when_no_location(self, enricher):
        assert enricher._get_weather(None) is None

    def test_none_when_no_client(self):
        e = ContextEnricher(weather_client=None)
        assert e._get_weather("Büro") is None

    def test_exception_returns_none(self, enricher, mock_weather_client):
        mock_weather_client.get_current.side_effect = RuntimeError("API down")
        result = enricher._get_weather("Büro")
        assert result is None


class TestSearchMemories:
    def test_returns_memory_content(self, enricher, mock_memory_store):
        mock_memory_store.search.return_value = [
            _make_memory("Max will Dachprojekt besprechen"),
        ]
        result = enricher._search_memories("Meeting Max")
        assert len(result) == 1
        assert "Dachprojekt" in result[0]
        mock_memory_store.search.assert_called_once_with("Meeting Max", 3)

    def test_empty_when_no_store(self):
        e = ContextEnricher(memory_store=None)
        assert e._search_memories("test") == []

    def test_exception_returns_empty(self, enricher, mock_memory_store):
        mock_memory_store.search.side_effect = RuntimeError("ChromaDB down")
        result = enricher._search_memories("test")
        assert result == []


# ---------------------------------------------------------------------------
# ContextEnricher – LLM-Formatierung
# ---------------------------------------------------------------------------


class TestFormatWithLLM:
    def test_calls_llm_with_context(self, enricher, mock_llm):
        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher._format_with_llm(
            "Meeting Max",
            now,
            "Büro",
            notes=["📝 Dachprojekt besprechen"],
            mails=["Max: Angebot (19.03. 14:22)"],
            weather="Klar, 18°C",
            memories=[],
        )
        assert result == "Zusammenfassung vom LLM"
        mock_llm.generate.assert_called_once()
        call_args = mock_llm.generate.call_args
        assert "Meeting Max" in call_args[0][0]
        assert call_args[1]["system"] == ENRICHMENT_SYSTEM_PROMPT

    def test_fallback_when_no_llm(self):
        e = ContextEnricher(llm=None)
        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = e._format_with_llm(
            "Test",
            now,
            None,
            notes=["Note"],
            mails=[],
            weather=None,
            memories=[],
        )
        assert "Note" in result

    def test_fallback_on_llm_error(self, enricher, mock_llm):
        mock_llm.generate.side_effect = RuntimeError("LLM down")
        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher._format_with_llm(
            "Test",
            now,
            None,
            notes=["Note"],
            mails=["Mail"],
            weather=None,
            memories=[],
        )
        assert "Note" in result
        assert "Mail" in result


class TestFormatFallback:
    def test_notes_only(self):
        result = ContextEnricher._format_fallback(
            notes=["Notiz 1"],
            mails=[],
            weather=None,
            memories=[],
        )
        assert "\U0001f4dd" in result  # 📝
        assert "Notiz 1" in result

    def test_all_sources(self):
        result = ContextEnricher._format_fallback(
            notes=["N"],
            mails=["M"],
            weather="W",
            memories=["Mem"],
        )
        assert "\U0001f4dd" in result
        assert "\U0001f4e7" in result  # 📧
        assert "\U0001f324" in result  # 🌤️
        assert "\U0001f4ad" in result  # 💭

    def test_empty_returns_empty(self):
        result = ContextEnricher._format_fallback([], [], None, [])
        assert result == ""


# ---------------------------------------------------------------------------
# ContextEnricher – enrich_event Integration
# ---------------------------------------------------------------------------


class TestEnrichEvent:
    def test_all_sources_deliver_context(
        self,
        enricher,
        mock_note_store,
        mock_email_client,
        mock_weather_client,
        mock_memory_store,
        mock_llm,
    ):
        mock_note_store.search.return_value = [
            _make_note(key="Info", content="Wichtig")
        ]
        mock_email_client.search.return_value = [_make_mail()]
        mock_weather_client.get_current.return_value = _make_weather()
        mock_memory_store.search.return_value = [_make_memory()]

        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher.enrich_event("Meeting Max", now, "Büro")

        assert result.has_context
        assert len(result.raw_notes) == 1
        assert len(result.raw_mails) == 1
        assert result.raw_weather is not None
        assert len(result.raw_memories) == 1
        assert result.formatted == "Zusammenfassung vom LLM"

    def test_no_context_found(self, enricher):
        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher.enrich_event("Leerer Termin", now)
        assert not result.has_context
        assert result.formatted == ""

    def test_partial_sources(self, enricher, mock_note_store, mock_llm):
        """Nur Notizen vorhanden, Rest leer → trotzdem Kontext."""
        mock_note_store.search.return_value = [_make_note(content="Nur Notiz")]
        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher.enrich_event("Test", now)
        assert result.has_context
        assert len(result.raw_notes) == 1
        assert result.raw_mails == []
        assert result.raw_weather is None
        mock_llm.generate.assert_called_once()

    def test_no_weather_without_location(
        self, enricher, mock_note_store, mock_weather_client
    ):
        mock_note_store.search.return_value = [_make_note(content="X")]
        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher.enrich_event("Test", now, location=None)
        mock_weather_client.get_current.assert_not_called()
        assert result.raw_weather is None

    def test_graceful_degradation_all_sources_fail(
        self,
        enricher,
        mock_note_store,
        mock_email_client,
        mock_weather_client,
        mock_memory_store,
    ):
        mock_note_store.search.side_effect = RuntimeError("fail")
        mock_email_client.search.side_effect = RuntimeError("fail")
        mock_weather_client.get_current.side_effect = RuntimeError("fail")
        mock_memory_store.search.side_effect = RuntimeError("fail")

        now = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
        result = enricher.enrich_event("Test", now, "Büro")
        assert not result.has_context


# ---------------------------------------------------------------------------
# CalendarWatcher – Enricher-Integration
# ---------------------------------------------------------------------------


class TestCalendarWatcherEnrichment:
    """Testet dass CalendarWatcher den ContextEnricher korrekt aufruft."""

    def test_enricher_called_on_first_reminder(self):
        from elder_berry.comms.calendar_watcher import CalendarWatcher
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import timedelta

        send_alert = MagicMock()
        calendar = MagicMock()
        enricher = MagicMock()
        enricher.enrich_event.return_value = EnrichmentResult(
            raw_notes=["Notiz"],
            formatted="Kontext vom Enricher",
        )

        watcher = CalendarWatcher(
            send_alert=send_alert,
            calendar=calendar,
            reminder_minutes=[15, 5],
            context_enricher=enricher,
        )

        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            summary="Meeting Max",
            start=now + timedelta(minutes=10),
            end=now + timedelta(hours=1),
            all_day=False,
            location="Büro",
            event_id="e1",
        )

        watcher._send_reminder(event, 15)  # Erster Reminder → enrichen
        enricher.enrich_event.assert_called_once_with(
            title="Meeting Max",
            event_time=event.start,
            location="Büro",
        )
        alert_text = send_alert.call_args[0][0]
        assert "Kontext vom Enricher" in alert_text

    def test_enricher_not_called_on_second_reminder(self):
        from elder_berry.comms.calendar_watcher import CalendarWatcher
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import timedelta

        send_alert = MagicMock()
        calendar = MagicMock()
        enricher = MagicMock()

        watcher = CalendarWatcher(
            send_alert=send_alert,
            calendar=calendar,
            reminder_minutes=[15, 5],
            context_enricher=enricher,
        )

        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            summary="Test",
            start=now + timedelta(minutes=3),
            end=now + timedelta(hours=1),
            all_day=False,
            location=None,
            event_id="e2",
        )

        watcher._send_reminder(event, 5)  # Zweiter Reminder → NICHT enrichen
        enricher.enrich_event.assert_not_called()

    def test_enricher_failure_still_sends_alert(self):
        from elder_berry.comms.calendar_watcher import CalendarWatcher
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import timedelta

        send_alert = MagicMock()
        calendar = MagicMock()
        enricher = MagicMock()
        enricher.enrich_event.side_effect = RuntimeError("Enricher kaputt")

        watcher = CalendarWatcher(
            send_alert=send_alert,
            calendar=calendar,
            reminder_minutes=[15, 5],
            context_enricher=enricher,
        )

        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            summary="Test",
            start=now + timedelta(minutes=10),
            end=now + timedelta(hours=1),
            all_day=False,
            location=None,
            event_id="e3",
        )

        watcher._send_reminder(event, 15)
        send_alert.assert_called_once()
        alert_text = send_alert.call_args[0][0]
        assert "Test" in alert_text  # Basis-Alert wurde trotzdem gesendet

    def test_no_enricher_still_works(self):
        """CalendarWatcher ohne Enricher funktioniert wie bisher."""
        from elder_berry.comms.calendar_watcher import CalendarWatcher
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import timedelta

        send_alert = MagicMock()
        calendar = MagicMock()

        watcher = CalendarWatcher(
            send_alert=send_alert,
            calendar=calendar,
            reminder_minutes=[15, 5],
        )

        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            summary="Test",
            start=now + timedelta(minutes=10),
            end=now + timedelta(hours=1),
            all_day=False,
            location=None,
            event_id="e4",
        )

        watcher._send_reminder(event, 15)
        send_alert.assert_called_once()

    def test_empty_enrichment_not_appended(self):
        from elder_berry.comms.calendar_watcher import CalendarWatcher
        from elder_berry.tools.google_calendar import CalendarEvent
        from datetime import timedelta

        send_alert = MagicMock()
        calendar = MagicMock()
        enricher = MagicMock()
        enricher.enrich_event.return_value = EnrichmentResult()  # Kein Kontext

        watcher = CalendarWatcher(
            send_alert=send_alert,
            calendar=calendar,
            reminder_minutes=[15, 5],
            context_enricher=enricher,
        )

        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            summary="Test",
            start=now + timedelta(minutes=10),
            end=now + timedelta(hours=1),
            all_day=False,
            location=None,
            event_id="e5",
        )

        watcher._send_reminder(event, 15)
        alert_text = send_alert.call_args[0][0]
        assert "\n\n" not in alert_text  # Kein Kontext angehängt
