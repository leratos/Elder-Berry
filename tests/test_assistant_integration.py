"""Integrationstests: Assistant + CharacterEngine + CoquiTTS + Avatar."""

import json
from unittest.mock import MagicMock

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.avatar.base import AvatarRenderer
from elder_berry.character.base import Emotion
from elder_berry.character.saleria import SaleriaEngine
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
    return ActionsDB(db_path=tmp_path / "test.db")


@pytest.fixture
def mock_controller():
    return MagicMock(spec=ActionController)


@pytest.fixture
def mock_tts():
    return MagicMock(spec=TTSEngine)


@pytest.fixture
def mock_avatar():
    return MagicMock(spec=AvatarRenderer)


@pytest.fixture
def character():
    return SaleriaEngine()


@pytest.fixture
def full_assistant(
    mock_llm, mock_db, mock_controller, mock_tts, character, mock_avatar
):
    """Assistant mit allen Komponenten inkl. CharacterEngine und Avatar."""
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
        character=character,
        avatar=mock_avatar,
    )


@pytest.fixture
def assistant_with_character(mock_llm, mock_db, mock_controller, mock_tts, character):
    """Assistant mit CharacterEngine aber ohne Avatar."""
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
        character=character,
    )


# ---------------------------------------------------------------------------
# CharacterEngine Integration
# ---------------------------------------------------------------------------


class TestCharacterPrompt:
    def test_system_prompt_uses_character(self, full_assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Hallo!"}
        )
        full_assistant.process("Hallo")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system", mock_llm.generate.call_args[1].get("system", "")
        )
        assert "Saleria Berry" in system_prompt

    def test_prompt_contains_emotion_tags(self, full_assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Test"}
        )
        full_assistant.process("Test")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system", mock_llm.generate.call_args[1].get("system", "")
        )
        assert "[cheerful]" in system_prompt
        assert "[angry]" in system_prompt


# ---------------------------------------------------------------------------
# Emotion Extraction
# ---------------------------------------------------------------------------


class TestEmotionExtraction:
    def test_extracts_emotion_from_response(self, full_assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[cheerful] Das mache ich gerne!",
            }
        )
        result = full_assistant.process("Hilf mir")
        assert result.emotion == "cheerful"

    def test_cleans_emotion_tag_from_response(self, full_assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[angry] Das war nicht klug."}
        )
        result = full_assistant.process("Test")
        assert result.response == "Das war nicht klug."
        assert "[angry]" not in result.response

    def test_no_emotion_tag_returns_neutral(self, full_assistant, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "Einfach nur Text."}
        )
        result = full_assistant.process("Test")
        assert result.emotion == "neutral"

    def test_emotion_none_without_character(
        self, mock_llm, mock_db, mock_controller, mock_tts
    ):
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
        )
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[cheerful] Hallo!"}
        )
        result = assistant.process("Test")
        assert result.emotion is None
        # Ohne Character bleibt der Tag im Text
        assert "[cheerful]" in result.response


# ---------------------------------------------------------------------------
# TTS mit Emotion
# ---------------------------------------------------------------------------


class TestTTSWithEmotion:
    def test_tts_called_with_emotion(self, full_assistant, mock_llm, mock_tts):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[sarcastic] Ach, wirklich?"}
        )
        full_assistant.process("Test")
        mock_tts.speak.assert_called_once_with("Ach, wirklich?", emotion="sarcastic")

    def test_tts_neutral_emotion(self, full_assistant, mock_llm, mock_tts):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "Ohne Tag."}
        )
        full_assistant.process("Test")
        mock_tts.speak.assert_called_once_with("Ohne Tag.", emotion="neutral")

    def test_tts_error_still_returns_result(self, full_assistant, mock_llm, mock_tts):
        mock_tts.speak.side_effect = RuntimeError("TTS kaputt")
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[cheerful] Hallo!"}
        )
        result = full_assistant.process("Test")
        assert result.response == "Hallo!"
        assert result.emotion == "cheerful"


# ---------------------------------------------------------------------------
# Avatar Integration
# ---------------------------------------------------------------------------


class TestAvatarIntegration:
    def test_avatar_shows_emotion(self, full_assistant, mock_llm, mock_avatar):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[angry] Grr!"}
        )
        full_assistant.process("Test")
        mock_avatar.show_emotion.assert_called_once_with(Emotion.ANGRY)

    def test_avatar_speaking_indicator(
        self, full_assistant, mock_llm, mock_avatar, mock_tts
    ):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Hallo"}
        )
        full_assistant.process("Test")
        # show_speaking(True) vor TTS, show_speaking(False) danach
        calls = mock_avatar.show_speaking.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] is True
        assert calls[1].args[0] is False

    def test_avatar_speaking_false_on_tts_error(
        self, full_assistant, mock_llm, mock_avatar, mock_tts
    ):
        mock_tts.speak.side_effect = RuntimeError("Fehler")
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Test"}
        )
        full_assistant.process("Test")
        # Trotz Fehler: show_speaking(False) muss aufgerufen werden
        last_call = mock_avatar.show_speaking.call_args_list[-1]
        assert last_call.args[0] is False

    def test_no_avatar_no_crash(self, assistant_with_character, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[cheerful] Alles gut!"}
        )
        result = assistant_with_character.process("Test")
        assert result.emotion == "cheerful"


# ---------------------------------------------------------------------------
# Voller Flow: Aktion + Emotion + TTS + Avatar
# ---------------------------------------------------------------------------


class TestFullFlow:
    def test_action_with_emotion(
        self, full_assistant, mock_llm, mock_controller, mock_tts, mock_avatar
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "press_key",
                "params": {"key": "enter"},
                "response": "[motivated] Enter gedrückt! Los geht's!",
            }
        )
        result = full_assistant.process("Drücke Enter")
        assert result.action_executed == "press_key"
        assert result.action_success is True
        assert result.emotion == "motivated"
        assert result.response == "Enter gedrückt! Los geht's!"
        mock_controller.press_key.assert_called_once_with("enter")
        mock_tts.speak.assert_called_once_with(
            "Enter gedrückt! Los geht's!", emotion="motivated"
        )
        mock_avatar.show_emotion.assert_called_once_with(Emotion.MOTIVATED)

    def test_result_has_emotion_field(self):
        r = AssistantResult(
            response="ok",
            action_executed=None,
            action_success=False,
            emotion="cheerful",
        )
        assert r.emotion == "cheerful"

    def test_result_emotion_default_none(self):
        r = AssistantResult(response="ok", action_executed=None, action_success=False)
        assert r.emotion is None
