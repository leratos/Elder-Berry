"""Tests für Assistant – Orchestrierung mit gemockten Dependencies."""
import json
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB, Action
from elder_berry.core.assistant import Assistant, AssistantResult
from elder_berry.llm.base import LLMClient
from elder_berry.tts.base import TTSEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def mock_db(tmp_path):
    return ActionsDB(db_path=tmp_path / "test_actions.db")


@pytest.fixture
def mock_controller():
    return MagicMock(spec=ActionController)


@pytest.fixture
def mock_tts():
    return MagicMock(spec=TTSEngine)


@pytest.fixture
def assistant(mock_llm, mock_db, mock_controller, mock_tts):
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
    )


@pytest.fixture
def assistant_no_tts(mock_llm, mock_db, mock_controller):
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=None,
    )


# ---------------------------------------------------------------------------
# Leere Eingabe
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_input_returns_message(self, assistant):
        result = assistant.process("")
        assert result.response == "Leere Eingabe."
        assert result.action_executed is None
        assert result.action_success is False

    def test_whitespace_input_returns_message(self, assistant):
        result = assistant.process("   ")
        assert result.action_executed is None


# ---------------------------------------------------------------------------
# LLM-Antwort ohne Aktion
# ---------------------------------------------------------------------------

class TestNoAction:
    def test_plain_response(self, assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps({
            "action": None,
            "params": {},
            "response": "Hallo! Wie kann ich helfen?"
        })
        result = assistant.process("Hallo")
        assert result.response == "Hallo! Wie kann ich helfen?"
        assert result.action_executed is None
        assert result.action_success is False

    def test_chat_history_in_system_prompt(self, assistant, mock_llm):
        """chat_history wird an den System-Prompt angehängt."""
        mock_llm.generate.return_value = json.dumps({
            "action": None,
            "params": {},
            "response": "Ja, die Rechnung von RK Bedachung.",
        })
        history = "Bisheriger Gesprächsverlauf:\nUser: mail suche RK\nSaleria: 2 Mails gefunden"
        result = assistant.process(
            "fasse die erste zusammen", chat_history=history,
        )

        # System-Prompt muss den Gesprächsverlauf enthalten
        system_arg = mock_llm.generate.call_args[1].get("system", "")
        if not system_arg:
            # Kann auch als Keyword-Arg übergeben worden sein
            system_arg = mock_llm.generate.call_args.kwargs.get("system", "")
        assert "Gesprächsverlauf" in system_arg
        assert "RK" in system_arg

    def test_chat_history_empty_no_extra_text(self, assistant, mock_llm):
        """Leere chat_history fügt keinen Extra-Text zum Prompt hinzu."""
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {}, "response": "OK",
        })
        assistant.process("Hallo", chat_history="")

        system_arg = mock_llm.generate.call_args.kwargs.get("system", "")
        assert "Gesprächsverlauf" not in system_arg


# ---------------------------------------------------------------------------
# LLM-Antwort mit Aktion
# ---------------------------------------------------------------------------

class TestWithAction:
    def test_press_key(self, assistant, mock_llm, mock_controller):
        mock_llm.generate.return_value = json.dumps({
            "action": "press_key",
            "params": {"key": "enter"},
            "response": "Enter gedrückt."
        })
        result = assistant.process("Drücke Enter")
        assert result.action_executed == "press_key"
        assert result.action_success is True
        mock_controller.press_key.assert_called_once_with("enter")

    def test_type_text(self, assistant, mock_llm, mock_controller):
        mock_llm.generate.return_value = json.dumps({
            "action": "type_text",
            "params": {"text": "hello world"},
            "response": "Text getippt."
        })
        result = assistant.process("Tippe hello world")
        mock_controller.type_text.assert_called_once_with("hello world")
        assert result.action_success is True

    def test_hotkey(self, assistant, mock_llm, mock_controller):
        mock_llm.generate.return_value = json.dumps({
            "action": "hotkey",
            "params": {"keys": ["ctrl", "c"]},
            "response": "Kopiert."
        })
        result = assistant.process("Kopiere das")
        mock_controller.hotkey.assert_called_once_with("ctrl", "c")
        assert result.action_success is True

    def test_set_volume(self, assistant, mock_llm, mock_controller):
        mock_llm.generate.return_value = json.dumps({
            "action": "set_volume",
            "params": {"level": 0.5},
            "response": "Lautstärke auf 50%."
        })
        result = assistant.process("Lautstärke auf 50%")
        mock_controller.set_volume.assert_called_once_with(0.5)
        assert result.action_success is True

    def test_mute(self, assistant, mock_llm, mock_controller):
        mock_llm.generate.return_value = json.dumps({
            "action": "mute",
            "params": {"state": True},
            "response": "Stummgeschaltet."
        })
        result = assistant.process("Stummschalten")
        mock_controller.mute.assert_called_once_with(True)
        assert result.action_success is True

    def test_focus_window(self, assistant, mock_llm, mock_controller):
        mock_controller.focus_window.return_value = True
        mock_llm.generate.return_value = json.dumps({
            "action": "focus_window",
            "params": {"title": "Notepad"},
            "response": "Notepad fokussiert."
        })
        result = assistant.process("Öffne Notepad")
        mock_controller.focus_window.assert_called_once_with("Notepad")
        assert result.action_success is True

    def test_focus_window_not_found(self, assistant, mock_llm, mock_controller):
        mock_controller.focus_window.return_value = False
        mock_llm.generate.return_value = json.dumps({
            "action": "focus_window",
            "params": {"title": "Nonexistent"},
            "response": "Fenster nicht gefunden."
        })
        result = assistant.process("Öffne Nonexistent")
        assert result.action_success is False

    def test_minimize_window(self, assistant, mock_llm, mock_controller):
        mock_controller.minimize_window.return_value = True
        mock_llm.generate.return_value = json.dumps({
            "action": "minimize_window",
            "params": {"title": "Firefox"},
            "response": "Firefox minimiert."
        })
        result = assistant.process("Minimiere Firefox")
        assert result.action_success is True

    def test_maximize_window(self, assistant, mock_llm, mock_controller):
        mock_controller.maximize_window.return_value = True
        mock_llm.generate.return_value = json.dumps({
            "action": "maximize_window",
            "params": {"title": "Firefox"},
            "response": "Firefox maximiert."
        })
        result = assistant.process("Maximiere Firefox")
        assert result.action_success is True


# ---------------------------------------------------------------------------
# Unbekannte / fehlerhafte Aktionen
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_unknown_action(self, assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps({
            "action": "fly_to_moon",
            "params": {},
            "response": "Das kann ich leider nicht."
        })
        result = assistant.process("Flieg zum Mond")
        assert result.action_executed == "fly_to_moon"
        assert result.action_success is False

    def test_missing_params(self, assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps({
            "action": "press_key",
            "params": {},
            "response": "Taste gedrückt."
        })
        result = assistant.process("Drücke eine Taste")
        assert result.action_success is False

    def test_controller_exception(self, assistant, mock_llm, mock_controller):
        mock_controller.press_key.side_effect = RuntimeError("Hardware-Fehler")
        mock_llm.generate.return_value = json.dumps({
            "action": "press_key",
            "params": {"key": "a"},
            "response": "Taste gedrückt."
        })
        result = assistant.process("Drücke A")
        assert result.action_success is False


# ---------------------------------------------------------------------------
# JSON-Parsing
# ---------------------------------------------------------------------------

class TestJSONParsing:
    def test_json_with_surrounding_text(self, assistant, mock_llm):
        mock_llm.generate.return_value = (
            'Hier ist meine Antwort:\n'
            '{"action": null, "params": {}, "response": "Alles klar!"}\n'
            'Ende.'
        )
        result = assistant.process("Test")
        assert result.response == "Alles klar!"

    def test_non_json_fallback(self, assistant, mock_llm):
        mock_llm.generate.return_value = "Ich bin ein einfacher Text ohne JSON."
        result = assistant.process("Test")
        assert result.response == "Ich bin ein einfacher Text ohne JSON."
        assert result.action_executed is None


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

class TestTTS:
    def test_tts_called_with_response(self, assistant, mock_llm, mock_tts):
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {}, "response": "Hallo!"
        })
        assistant.process("Hi")
        mock_tts.speak.assert_called_once_with("Hallo!")

    def test_tts_none_skips_speech(self, assistant_no_tts, mock_llm):
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {}, "response": "Hallo!"
        })
        result = assistant_no_tts.process("Hi")
        assert result.response == "Hallo!"

    def test_tts_error_does_not_crash(self, assistant, mock_llm, mock_tts):
        mock_tts.speak.side_effect = RuntimeError("TTS kaputt")
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {}, "response": "Hallo!"
        })
        result = assistant.process("Hi")
        assert result.response == "Hallo!"


# ---------------------------------------------------------------------------
# System-Prompt + ActionsDB Integration
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_system_prompt_includes_db_actions(self, assistant, mock_llm, mock_db):
        mock_db.add("öffne browser", "focus_window", "Firefox")
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {}, "response": "ok"
        })
        assistant.process("test")
        system_prompt = mock_llm.generate.call_args.kwargs.get("system", "")
        if not system_prompt:
            system_prompt = mock_llm.generate.call_args[1].get("system", "")
        assert "öffne browser" in system_prompt

    def test_db_action_use_tracked(self, assistant, mock_llm, mock_db, mock_controller):
        mock_db.add("set_volume", "set_volume", "")
        mock_llm.generate.return_value = json.dumps({
            "action": "set_volume",
            "params": {"level": 0.8},
            "response": "Lautstärke gesetzt."
        })
        assistant.process("Lauter")
        action = mock_db.get("set_volume")
        assert action is not None
        assert action.use_count == 1


# ---------------------------------------------------------------------------
# AssistantResult DTO
# ---------------------------------------------------------------------------

class TestAssistantResult:
    def test_result_fields(self):
        r = AssistantResult(response="ok", action_executed="press_key",
                            action_success=True)
        assert r.response == "ok"
        assert r.action_executed == "press_key"
        assert r.action_success is True


# ---------------------------------------------------------------------------
# generate_raw – Tests
# ---------------------------------------------------------------------------

class TestGenerateRaw:
    def test_returns_raw_llm_text(self, assistant, mock_llm):
        mock_llm.generate.return_value = "mail suche Rechnung"
        result = assistant.generate_raw("Was ist der Command?")
        assert result == "mail suche Rechnung"
        mock_llm.generate.assert_called_once()

    def test_does_not_call_smart_context(self, assistant, mock_llm):
        mock_smart = MagicMock()
        assistant._smart_context = mock_smart
        mock_llm.generate.return_value = "ok"
        assistant.generate_raw("test")
        mock_smart.get_context.assert_not_called()

    def test_does_not_call_memory(self, assistant, mock_llm):
        mock_memory = MagicMock()
        assistant._memory = mock_memory
        mock_llm.generate.return_value = "ok"
        assistant.generate_raw("test")
        mock_memory.get_context.assert_not_called()
        mock_memory.add.assert_not_called()

    def test_does_not_call_tts(self, assistant, mock_llm, mock_tts):
        mock_llm.generate.return_value = "ok"
        assistant.generate_raw("test")
        mock_tts.speak.assert_not_called()

    def test_passes_system_and_history(self, assistant, mock_llm):
        mock_llm.generate.return_value = "ok"
        assistant.generate_raw("input", system="sys", chat_history="hist")
        call_args = mock_llm.generate.call_args
        assert call_args[0][0] == "input"
        assert "sys" in call_args[1]["system"]
        assert "hist" in call_args[1]["system"]
