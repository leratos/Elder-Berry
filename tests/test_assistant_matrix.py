"""Tests: Assistant.process() mit audio_output Parameter (Matrix-Integration)."""
import json
from unittest.mock import MagicMock

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.core.assistant import Assistant, AssistantResult
from elder_berry.llm.base import LLMClient
from elder_berry.tts.base import TTSEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMClient)
    llm.generate.return_value = json.dumps({
        "action": None,
        "params": {},
        "response": "[neutral] Hallo, ich bin Saleria!",
    })
    return llm


@pytest.fixture
def mock_db(tmp_path):
    return ActionsDB(db_path=tmp_path / "test.db")


@pytest.fixture
def mock_controller():
    return MagicMock(spec=ActionController)


@pytest.fixture
def mock_tts():
    tts = MagicMock(spec=TTSEngine)
    # generate_audio erzeugt eine echte Datei
    def _generate(text, path, **kwargs):
        path.write_bytes(b"RIFF" + b"\x00" * 44 + b"\xff" * 1000)
    tts.generate_audio.side_effect = _generate
    return tts


@pytest.fixture
def assistant(mock_llm, mock_db, mock_controller, mock_tts):
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
    )


# ---------------------------------------------------------------------------
# audio_output Parameter
# ---------------------------------------------------------------------------

class TestAudioOutput:
    def test_process_without_audio_output(self, assistant, mock_tts):
        """Ohne audio_output: TTS spielt ab (speak), kein audio_path im Result."""
        result = assistant.process("Hallo")

        assert result.response
        assert result.audio_path is None
        # speak wurde aufgerufen (Playback-Modus)
        mock_tts.speak.assert_called_once()
        # generate_audio wurde NICHT aufgerufen
        mock_tts.generate_audio.assert_not_called()

    def test_process_with_audio_output(self, assistant, mock_tts, tmp_path):
        """Mit audio_output: TTS generiert Datei, audio_path im Result."""
        wav_path = tmp_path / "output.wav"
        result = assistant.process("Hallo", audio_output=wav_path)

        assert result.audio_path == wav_path
        assert wav_path.exists()
        # generate_audio wurde aufgerufen (Datei-Modus)
        mock_tts.generate_audio.assert_called_once()
        # speak wurde NICHT aufgerufen
        mock_tts.speak.assert_not_called()

    def test_audio_output_path_in_result(self, assistant, tmp_path):
        """audio_path im Result zeigt auf die generierte Datei."""
        wav_path = tmp_path / "saleria_response.wav"
        result = assistant.process("Wie geht es dir?", audio_output=wav_path)

        assert result.audio_path is not None
        assert result.audio_path == wav_path
        assert result.audio_path.exists()
        assert result.audio_path.stat().st_size > 0

    def test_audio_output_generate_audio_not_implemented(
        self, mock_llm, mock_db, mock_controller, tmp_path,
    ):
        """Wenn TTS kein generate_audio hat: audio_path ist None, kein Crash."""
        tts = MagicMock(spec=TTSEngine)
        tts.generate_audio.side_effect = NotImplementedError

        assistant = Assistant(
            llm=mock_llm, actions_db=mock_db,
            controller=mock_controller, tts=tts,
        )

        wav_path = tmp_path / "output.wav"
        result = assistant.process("Test", audio_output=wav_path)

        assert result.audio_path is None
        assert result.response

    def test_audio_output_generate_audio_error(
        self, mock_llm, mock_db, mock_controller, tmp_path,
    ):
        """Wenn generate_audio fehlschlägt: audio_path ist None, kein Crash."""
        tts = MagicMock(spec=TTSEngine)
        tts.generate_audio.side_effect = RuntimeError("GPU out of memory")

        assistant = Assistant(
            llm=mock_llm, actions_db=mock_db,
            controller=mock_controller, tts=tts,
        )

        wav_path = tmp_path / "output.wav"
        result = assistant.process("Test", audio_output=wav_path)

        assert result.audio_path is None
        assert result.response

    def test_audio_output_empty_input(self, assistant, tmp_path):
        """Leere Eingabe: kein Audio generiert."""
        wav_path = tmp_path / "output.wav"
        result = assistant.process("", audio_output=wav_path)

        assert result.response == "Leere Eingabe."
        assert result.audio_path is None

    def test_audio_output_no_tts(self, mock_llm, mock_db, mock_controller, tmp_path):
        """Ohne TTS-Engine: audio_path ist None."""
        assistant = Assistant(
            llm=mock_llm, actions_db=mock_db,
            controller=mock_controller, tts=None,
        )

        wav_path = tmp_path / "output.wav"
        result = assistant.process("Hallo", audio_output=wav_path)

        assert result.audio_path is None
        assert result.response


# ---------------------------------------------------------------------------
# AssistantResult.audio_path Feld
# ---------------------------------------------------------------------------

class TestAssistantResultAudioPath:
    def test_default_none(self):
        result = AssistantResult(
            response="Test", action_executed=None, action_success=False,
        )
        assert result.audio_path is None

    def test_with_path(self, tmp_path):
        p = tmp_path / "audio.wav"
        result = AssistantResult(
            response="Test", action_executed=None, action_success=False,
            audio_path=p,
        )
        assert result.audio_path == p

    def test_backward_compatible(self):
        """Bestehender Code ohne audio_path funktioniert weiterhin."""
        result = AssistantResult(
            response="Antwort",
            action_executed="press_key",
            action_success=True,
            emotion="cheerful",
        )
        assert result.audio_path is None
        assert result.emotion == "cheerful"
