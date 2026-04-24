"""Tests: Phase 22 – Intent-Routing Verbesserung.

Tests für:
1. Keyword-Audit: Neue Keywords matchen korrekt
2. get_command_summary(): Dynamischer Command-Prompt
3. Retry-Logik: LLM-Korrektur bei Parse-Fehler
"""
import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from elder_berry.comms.remote_commands import RemoteCommandHandler


# ---------------------------------------------------------------------------
# Helper: Minimaler RemoteCommandHandler (nur mit den nötigen Dependencies)
# ---------------------------------------------------------------------------

def _make_handler(**kwargs) -> RemoteCommandHandler:
    """Erstellt einen RemoteCommandHandler mit Minimal-Dependencies."""
    return RemoteCommandHandler(**kwargs)


# ===========================================================================
# Teil 1: Keyword-Audit – Neue Keywords matchen korrekt
# ===========================================================================

class TestKeywordAudit:
    """Prüft dass die neuen Keywords aus dem Audit korrekt geroutet werden."""

    @pytest.fixture
    def handler(self):
        return _make_handler()

    # --- System Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("mach ein foto vom bildschirm", "screenshot"),
        ("zeig mir den bildschirm", "screenshot"),
        ("wie geht es dem pc", "status"),
        ("cpu auslastung", "status"),
        ("ram auslastung", "status"),
        ("musik pausieren", "pause"),
        ("halt die musik an", "pause"),
        ("musik weiter", "play"),
        ("spiel weiter", "play"),
        ("vorheriger song", "prev"),
        ("lied zurück", "prev"),
        ("lautstärke", "volume"),
        ("leiser", "harmony_volume_down"),
        ("lauter", "harmony_volume_up"),
        ("starte dich neu", "restart"),
        ("zeig mir die befehle", "hilfe"),
    ])
    def test_system_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- Calendar Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("zeitplan", "termine"),
        ("terminplan", "termine"),
        ("agenda", "termine"),
        ("was hab ich vor", "termine"),
        ("hab ich heute was", "termine"),
        ("bin ich heute frei", "termine"),
        ("wochenplan", "termine_woche"),
        ("wochenübersicht", "termine_woche"),
        ("bin ich morgen frei", "termine_morgen"),
        ("was hab ich morgen vor", "termine_morgen"),
    ])
    def test_calendar_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- Mail Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("post", "mails"),
        ("nachrichten", "mails"),
        ("eingang", "mails"),
        ("hab ich mails", "mails"),
        ("gibt es neue mails", "mails"),
        ("sind mails da", "mails"),
        ("mails checken", "mails"),
        ("mails zusammenfassen", "mail_summary"),
    ])
    def test_mail_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- File Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("was hab ich kopiert", "clipboard"),
        ("zeig zwischenablage", "clipboard"),
        ("was ist kopiert", "clipboard"),
    ])
    def test_file_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- Process Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("pc aufwecken", "wol"),
        ("rechner wecken", "wol"),
        ("tower wecken", "wol"),
        ("läuft alles", "selfcheck"),
        ("geht alles", "selfcheck"),
    ])
    def test_process_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- Weather Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("regen", "wetter"),
        ("sonnig", "wetter"),
        ("gewitter", "wetter"),
        ("schnee", "wetter"),
        ("regenschirm", "wetter"),
        ("friert es", "wetter"),
        ("wird es kalt", "wetter"),
        ("soll ich eine jacke mitnehmen", "wetter"),
        ("workout", "training"),
        ("laufende timer", "erinnerungen"),
        ("tagesbriefing", "briefing"),
        ("was gibt es neues", "briefing"),
    ])
    def test_weather_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- Advanced Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("kannst du das anklicken", "computer_use"),
        ("nachschauen im internet", "web_search"),
        ("schau mal im netz", "web_search"),
        ("im netz suchen", "web_search"),
        ("datei zusammenfassen", "document_summary"),
    ])
    def test_advanced_keywords(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    # --- Note Commands ---

    @pytest.mark.parametrize("text,expected", [
        ("denk dran: Milch kaufen", "note_set_fact"),
        ("weißt du noch was das WLAN Passwort ist", "note_get_fact"),
        ("wann ist der Termin", "note_get_fact"),
        ("wer ist mein Vermieter", "note_get_fact"),
        ("durchsuche notizen", "note_search"),
        ("schreib auf: morgen Arzt", "note_add"),
    ])
    def test_note_keywords(self, handler, text, expected):
        note_store = MagicMock()
        h = _make_handler(note_store=note_store)
        assert h.parse_command(text) == expected


# ===========================================================================
# Teil 1b: Bestehende Keywords funktionieren weiterhin
# ===========================================================================

class TestExistingKeywordsStillWork:
    """Regression: Bestehende Keywords dürfen nicht kaputt gehen."""

    @pytest.fixture
    def handler(self):
        return _make_handler()

    @pytest.mark.parametrize("text,expected", [
        ("screenshot", "screenshot"),
        ("status", "status"),
        ("hilfe", "hilfe"),
        ("mails", "mails"),
        ("termine", "termine"),
        ("wetter", "wetter"),
        ("briefing", "briefing"),
        ("erinnerungen", "erinnerungen"),
        ("clipboard", "clipboard"),
        ("training", "training"),
        ("prs", "prs"),
        ("wol", "wol"),
        ("selfcheck", "selfcheck"),
        ("audio", "audio"),
    ])
    def test_simple_commands_still_work(self, handler, text, expected):
        assert handler.parse_command(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("wie ist das wetter", "wetter"),
        ("regnet es", "wetter"),
        ("brauche ich einen schirm", "wetter"),
        ("neue mails", "mails"),
        ("posteingang", "mails"),
        ("was steht an", "termine"),
        ("guten morgen", "briefing"),
        ("zeig dich", "avatar"),
    ])
    def test_existing_keywords_still_work(self, handler, text, expected):
        assert handler.parse_command(text) == expected


# ===========================================================================
# Teil 2: get_command_summary() – Dynamischer Command-Prompt
# ===========================================================================

class TestGetCommandSummary:
    """Prüft dass get_command_summary() korrekt generiert wird."""

    def test_returns_non_empty_string(self):
        handler = _make_handler()
        summary = handler.get_command_summary()
        assert isinstance(summary, str)
        assert len(summary) > 100  # Muss substanziell sein

    def test_contains_key_commands(self):
        handler = _make_handler()
        summary = handler.get_command_summary()
        # Prüfe ob wichtige Commands enthalten sind
        assert "status" in summary.lower()
        assert "screenshot" in summary.lower()
        assert "wetter" in summary.lower()
        assert "hilfe" in summary.lower()

    def test_contains_mail_commands(self):
        handler = _make_handler()
        summary = handler.get_command_summary()
        assert "mail" in summary.lower()

    def test_contains_calendar_commands(self):
        handler = _make_handler()
        summary = handler.get_command_summary()
        assert "termin" in summary.lower()

    def test_note_commands_included_when_note_store_present(self):
        note_store = MagicMock()
        handler = _make_handler(note_store=note_store)
        summary = handler.get_command_summary()
        assert "notiz" in summary.lower()

    def test_note_commands_absent_when_no_note_store(self):
        handler = _make_handler()
        summary = handler.get_command_summary()
        # NoteCommandHandler wird nicht registriert wenn note_store=None
        assert "merk dir" not in summary.lower()

    def test_each_line_starts_with_dash(self):
        handler = _make_handler()
        summary = handler.get_command_summary()
        for line in summary.strip().split("\n"):
            line = line.strip()
            if line:
                assert line.startswith("- "), f"Zeile beginnt nicht mit '- ': {line}"

    def test_summary_is_deterministic(self):
        """Zwei Aufrufe liefern identische Ergebnisse."""
        handler = _make_handler()
        s1 = handler.get_command_summary()
        s2 = handler.get_command_summary()
        assert s1 == s2


# ===========================================================================
# Teil 2b: command_descriptions auf allen Handlern vorhanden
# ===========================================================================

class TestCommandDescriptions:
    """Prüft dass jeder Handler command_descriptions definiert."""

    def test_all_handlers_have_descriptions(self):
        handler = _make_handler(note_store=MagicMock())
        for h in handler._handlers:
            descs = h.command_descriptions
            assert isinstance(descs, list), f"{h.__class__.__name__} hat keine Liste"
            assert len(descs) > 0, f"{h.__class__.__name__} hat leere Descriptions"

    def test_descriptions_are_strings(self):
        handler = _make_handler(note_store=MagicMock())
        for h in handler._handlers:
            for desc in h.command_descriptions:
                assert isinstance(desc, str), f"Keine String-Description in {h.__class__.__name__}"
                assert ":" in desc, f"Fehlender Doppelpunkt in Description: {desc}"


# ===========================================================================
# Teil 2c: Dynamischer Prompt im Assistant (SYSTEM_PROMPT_TEMPLATE)
# ===========================================================================

class TestDynamicPromptInAssistant:
    """Prüft dass der dynamische Command-Block in den System-Prompt einfließt."""

    def test_fallback_template_has_remote_commands_placeholder(self):
        from elder_berry.core.assistant import SYSTEM_PROMPT_TEMPLATE
        assert "{remote_commands}" in SYSTEM_PROMPT_TEMPLATE

    def test_build_system_prompt_includes_commands(self):
        """Assistant._build_system_prompt() enthält die Command-Descriptions."""
        from elder_berry.core.assistant import Assistant
        from elder_berry.actions.db import ActionsDB

        llm = MagicMock()
        db = MagicMock(spec=ActionsDB)
        db.list_all.return_value = []
        controller = MagicMock()

        remote = _make_handler()
        assistant = Assistant(
            llm=llm, actions_db=db, controller=controller,
            remote_commands=remote,
        )

        prompt = assistant._build_system_prompt()
        # Der Prompt muss Commands aus den Handlern enthalten
        assert "screenshot" in prompt.lower()
        assert "wetter" in prompt.lower()
        assert "mail" in prompt.lower()

    def test_build_system_prompt_without_remote_commands(self):
        """Ohne RemoteCommandHandler: kein Crash, leerer remote_commands Block."""
        from elder_berry.core.assistant import Assistant
        from elder_berry.actions.db import ActionsDB

        llm = MagicMock()
        db = MagicMock(spec=ActionsDB)
        db.list_all.return_value = []
        controller = MagicMock()

        assistant = Assistant(
            llm=llm, actions_db=db, controller=controller,
        )

        prompt = assistant._build_system_prompt()
        # Darf nicht crashen, remote_commands ist leer
        assert "remote_command" in prompt.lower() or "remote-befehl" in prompt.lower()


# ===========================================================================
# Teil 3: Retry-Logik bei LLM Parse-Fehler
# ===========================================================================

class TestRetryLogic:
    """Prüft die Retry-Logik in _handle_llm_remote_command."""

    def _make_bridge(self):
        """Erstellt eine MatrixBridge mit Mocks für Tests."""
        from elder_berry.comms.bridge import MatrixBridge

        channel = MagicMock()
        channel.send_text = AsyncMock()
        channel.send_image = AsyncMock()
        channel.send_file = AsyncMock()
        channel.send_audio = AsyncMock()

        assistant = MagicMock()
        remote = _make_handler()

        bridge = MatrixBridge(
            channel=channel,
            assistant=assistant,
            remote_commands=remote,
        )
        return bridge, channel, assistant, remote

    def test_retry_called_on_parse_failure(self):
        """Wenn parse_command fehlschlägt, wird ein Retry-LLM-Call gemacht."""
        bridge, channel, assistant, remote = self._make_bridge()

        # LLM gibt einen ungültigen Command zurück
        llm_result = MagicMock()
        llm_result.response = "Ich schaue nach..."
        llm_result.action_executed = "remote_command"
        llm_result.action_params = {"command": "zeig mails von gestern"}
        llm_result.audio_path = None

        # Retry: generate_raw gibt korrigierten Command zurück
        assistant.generate_raw.return_value = "mails"

        msg = MagicMock()
        msg.sender = "@user:test"
        msg.room_id = "!room:test"
        msg.body = "zeig mails von gestern"
        msg.timestamp = 0

        asyncio.run(bridge._handler._handle_llm_remote_command(msg, llm_result))

        # generate_raw wurde für Retry aufgerufen (nicht process)
        assert assistant.generate_raw.called
        assert not assistant.process.called

    def test_no_retry_when_parse_succeeds(self):
        """Wenn parse_command sofort matcht, kein Retry."""
        bridge, channel, assistant, remote = self._make_bridge()

        llm_result = MagicMock()
        llm_result.response = "Hier sind deine Mails"
        llm_result.action_executed = "remote_command"
        llm_result.action_params = {"command": "mails"}
        llm_result.audio_path = None

        msg = MagicMock()
        msg.sender = "@user:test"
        msg.room_id = "!room:test"
        msg.body = "zeig mails"
        msg.timestamp = 0

        asyncio.run(bridge._handler._handle_llm_remote_command(msg, llm_result))

        # Kein Retry nötig – parse_command matcht direkt
        assert not assistant.process.called

    def test_retry_with_corrected_command_from_response(self):
        """Retry: LLM antwortet mit Command als Klartext."""
        bridge, channel, assistant, remote = self._make_bridge()

        llm_result = MagicMock()
        llm_result.response = "Moment..."
        llm_result.action_executed = "remote_command"
        # Komplett unbekannter Command der kein Keyword matcht
        llm_result.action_params = {"command": "zeig die elektronische korrespondenz"}
        llm_result.audio_path = None

        # Retry: generate_raw gibt "mails" zurück
        assistant.generate_raw.return_value = "mails"

        msg = MagicMock()
        msg.sender = "@user:test"
        msg.room_id = "!room:test"
        msg.body = "zeig die elektronische korrespondenz"
        msg.timestamp = 0

        asyncio.run(bridge._handler._handle_llm_remote_command(msg, llm_result))

        # generate_raw wurde für Retry aufgerufen (nicht process)
        assert assistant.generate_raw.called
        assert not assistant.process.called

    def test_no_command_text_does_nothing(self):
        """Leerer command-Parameter → kein Crash, kein Retry."""
        bridge, channel, assistant, remote = self._make_bridge()

        llm_result = MagicMock()
        llm_result.response = "Ok"
        llm_result.action_executed = "remote_command"
        llm_result.action_params = {"command": ""}
        llm_result.audio_path = None

        msg = MagicMock()
        msg.sender = "@user:test"
        msg.room_id = "!room:test"
        msg.body = "test"
        msg.timestamp = 0

        # Darf nicht crashen
        asyncio.run(bridge._handler._handle_llm_remote_command(msg, llm_result))
        assert not assistant.process.called


# ===========================================================================
# Edge-Cases: Keyword-Konflikte und Prioritäten
# ===========================================================================

class TestKeywordPriorities:
    """Prüft dass Keyword-Konflikte korrekt durch Handler-Reihenfolge aufgelöst werden."""

    @pytest.fixture
    def handler(self):
        return _make_handler(
            reminder_store=MagicMock(),
            note_store=MagicMock(),
        )

    def test_loeschen_not_ambiguous(self):
        """'lösche erinnerung 3' matcht Weather (Reminder), nicht Calendar."""
        handler = _make_handler(reminder_store=MagicMock())
        cmd = handler.parse_command("lösche erinnerung 3")
        assert cmd == "reminder_delete"

    def test_kein_command_gibt_none(self):
        """Normaler Konversationstext gibt None zurück."""
        handler = _make_handler()
        assert handler.parse_command("Wie geht es dir heute?") is None

    def test_case_insensitive(self):
        """Keywords matchen case-insensitive."""
        handler = _make_handler()
        assert handler.parse_command("SCREENSHOT") == "screenshot"
        assert handler.parse_command("Mails") == "mails"
        assert handler.parse_command("WETTER") == "wetter"
