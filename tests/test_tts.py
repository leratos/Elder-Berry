"""Tests für TTSEngine ABC und WindowsTTSEngine – alle Aktionen gemockt."""
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tts.base import TTSEngine, VoiceInfo


# ---------------------------------------------------------------------------
# ABC-Vertrag: TTSEngine kann nicht direkt instanziiert werden
# ---------------------------------------------------------------------------

class TestTTSEngineABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            TTSEngine()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# VoiceInfo DTO
# ---------------------------------------------------------------------------

class TestVoiceInfo:
    def test_voice_info_fields(self):
        v = VoiceInfo(id="voice-1", name="Anna", language="de")
        assert v.id == "voice-1"
        assert v.name == "Anna"
        assert v.language == "de"


# ---------------------------------------------------------------------------
# Windows-Plattformprüfung
# ---------------------------------------------------------------------------

class TestPlatformCheck:
    @patch("elder_berry.tts.windows_engine.platform")
    def test_raises_on_non_windows(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        from elder_berry.tts.windows_engine import WindowsTTSEngine
        with pytest.raises(RuntimeError, match="Windows"):
            WindowsTTSEngine()

    @patch("elder_berry.tts.windows_engine.platform")
    @patch("elder_berry.tts.windows_engine.pyttsx3")
    def test_ok_on_windows(self, mock_pyttsx3, mock_platform):
        mock_platform.system.return_value = "Windows"
        mock_pyttsx3.init.return_value = MagicMock()
        from elder_berry.tts.windows_engine import WindowsTTSEngine
        engine = WindowsTTSEngine()
        assert isinstance(engine, TTSEngine)


# ---------------------------------------------------------------------------
# Hilfsfunktion: Engine mit gemockter Plattform + Engine erzeugen
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    """Erzeugt eine WindowsTTSEngine mit gemocktem pyttsx3."""
    with (
        patch("elder_berry.tts.windows_engine.platform") as mock_p,
        patch("elder_berry.tts.windows_engine.pyttsx3") as mock_pyttsx3,
    ):
        mock_p.system.return_value = "Windows"
        mock_engine = MagicMock()
        mock_pyttsx3.init.return_value = mock_engine
        from elder_berry.tts.windows_engine import WindowsTTSEngine
        tts = WindowsTTSEngine()
    return tts


# ---------------------------------------------------------------------------
# speak
# ---------------------------------------------------------------------------

class TestSpeak:
    def test_speak_calls_say_and_run(self, engine):
        engine.speak("Hallo Welt")
        engine._engine.say.assert_called_once_with("Hallo Welt")
        engine._engine.runAndWait.assert_called_once()

    def test_speak_empty_text_skips(self, engine):
        engine.speak("   ")
        engine._engine.say.assert_not_called()
        engine._engine.runAndWait.assert_not_called()


# ---------------------------------------------------------------------------
# Rate (Sprechgeschwindigkeit)
# ---------------------------------------------------------------------------

class TestRate:
    def test_get_rate(self, engine):
        engine._engine.getProperty.return_value = 200
        assert engine.get_rate() == 200
        engine._engine.getProperty.assert_called_with("rate")

    def test_set_rate(self, engine):
        engine.set_rate(150)
        engine._engine.setProperty.assert_called_once_with("rate", 150)


# ---------------------------------------------------------------------------
# Volume (TTS-Lautstärke)
# ---------------------------------------------------------------------------

class TestVolume:
    def test_get_volume(self, engine):
        engine._engine.getProperty.return_value = 0.8
        assert engine.get_volume() == 0.8
        engine._engine.getProperty.assert_called_with("volume")

    def test_set_volume(self, engine):
        engine.set_volume(0.5)
        engine._engine.setProperty.assert_called_once_with("volume", 0.5)

    def test_set_volume_rejects_out_of_range(self, engine):
        with pytest.raises(ValueError, match="0.0 und 1.0"):
            engine.set_volume(1.5)
        with pytest.raises(ValueError, match="0.0 und 1.0"):
            engine.set_volume(-0.1)


# ---------------------------------------------------------------------------
# Voices (Stimmen)
# ---------------------------------------------------------------------------

def _make_mock_voice(voice_id: str, name: str, languages=None) -> MagicMock:
    """Erzeugt ein Mock-Voice-Objekt kompatibel mit pyttsx3."""
    v = MagicMock()
    v.id = voice_id
    v.name = name
    v.languages = languages or []
    return v


class TestVoices:
    def test_get_voices(self, engine):
        engine._engine.getProperty.return_value = [
            _make_mock_voice("v1", "Anna", ["de_DE"]),
            _make_mock_voice("v2", "David", ["en_US"]),
        ]
        voices = engine.get_voices()
        assert len(voices) == 2
        assert all(isinstance(v, VoiceInfo) for v in voices)
        assert voices[0].name == "Anna"
        assert voices[1].name == "David"

    def test_get_voices_empty_languages(self, engine):
        engine._engine.getProperty.return_value = [
            _make_mock_voice("v1", "NoLang", []),
        ]
        voices = engine.get_voices()
        assert voices[0].language == ""

    def test_set_voice_valid(self, engine):
        engine._engine.getProperty.return_value = [
            _make_mock_voice("v1", "Anna", ["de_DE"]),
        ]
        engine.set_voice("v1")
        engine._engine.setProperty.assert_called_once_with("voice", "v1")

    def test_set_voice_invalid_raises(self, engine):
        engine._engine.getProperty.return_value = [
            _make_mock_voice("v1", "Anna", ["de_DE"]),
        ]
        with pytest.raises(ValueError, match="nicht gefunden"):
            engine.set_voice("nonexistent")
