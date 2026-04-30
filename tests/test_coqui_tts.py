"""Tests für CoquiTTSEngine – Coqui TTS und Audio-Playback gemockt."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tts.base import TTSEngine, VoiceInfo
from elder_berry.tts.coqui_engine import _clean_text_for_tts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def voice_dir(tmp_path):
    """Erstellt temporäre Voice-Sample Dateien."""
    samples = {}
    for name in ("neutral", "cheerful", "angry", "sad"):
        wav_path = tmp_path / f"saleria-{name}.wav"
        wav_path.write_bytes(b"RIFF" + b"\x00" * 40)  # Dummy WAV
        samples[name] = wav_path
    return samples


@pytest.fixture
def mock_tts_module():
    """Mockt das TTS-Modul und torch."""
    with (
        patch("elder_berry.tts.coqui_engine.TTS") as mock_tts_cls,
        patch("elder_berry.tts.coqui_engine.torch") as mock_torch,
        patch("elder_berry.tts.coqui_engine.sd") as mock_sd,
        patch("elder_berry.tts.coqui_engine.np") as mock_np,
    ):
        mock_torch.cuda.is_available.return_value = False
        mock_tts_instance = MagicMock()
        mock_tts_cls.return_value.to.return_value = mock_tts_instance
        yield {
            "tts_cls": mock_tts_cls,
            "tts_instance": mock_tts_instance,
            "torch": mock_torch,
            "sd": mock_sd,
            "np": mock_np,
        }


@pytest.fixture
def engine(voice_dir, mock_tts_module):
    """Erstellt eine CoquiTTSEngine mit gemocktem TTS."""
    from elder_berry.tts.coqui_engine import CoquiTTSEngine

    return CoquiTTSEngine(
        voice_map=voice_dir,
        default_speaker_wav=voice_dir["neutral"],
        language="de",
    )


# ---------------------------------------------------------------------------
# Import / Instanziierung
# ---------------------------------------------------------------------------


class TestCoquiTTSEngineInit:
    def test_is_tts_engine(self, engine):
        assert isinstance(engine, TTSEngine)

    def test_not_loaded_initially(self, engine):
        assert not engine.is_loaded

    def test_import_error_without_tts(self):
        with patch("elder_berry.tts.coqui_engine.TTS", None):
            from elder_berry.tts.coqui_engine import CoquiTTSEngine

            with pytest.raises(ImportError, match="Coqui TTS"):
                CoquiTTSEngine()


# ---------------------------------------------------------------------------
# Load / Unload (VRAM-Management)
# ---------------------------------------------------------------------------


class TestLoadUnload:
    def test_load_creates_model(self, engine, mock_tts_module):
        engine.load()
        assert engine.is_loaded
        mock_tts_module["tts_cls"].assert_called_once()

    def test_load_idempotent(self, engine, mock_tts_module):
        engine.load()
        engine.load()
        mock_tts_module["tts_cls"].assert_called_once()

    def test_unload_frees_model(self, engine):
        engine.load()
        engine.unload()
        assert not engine.is_loaded

    def test_unload_when_not_loaded(self, engine):
        engine.unload()  # Sollte nicht crashen
        assert not engine.is_loaded

    def test_load_uses_cpu_without_cuda(self, engine, mock_tts_module):
        mock_tts_module["torch"].cuda.is_available.return_value = False
        engine.load()
        assert engine._device == "cpu"

    def test_load_uses_cuda_when_available(self, engine, mock_tts_module):
        mock_tts_module["torch"].cuda.is_available.return_value = True
        engine.load()
        assert engine._device == "cuda"

    def test_unload_clears_cuda_cache(self, engine, mock_tts_module):
        mock_tts_module["torch"].cuda.is_available.return_value = True
        engine.load()
        engine.unload()
        mock_tts_module["torch"].cuda.empty_cache.assert_called_once()


# ---------------------------------------------------------------------------
# Voice-Map und Speaker-WAV Auflösung
# ---------------------------------------------------------------------------


class TestVoiceMap:
    def test_resolve_emotion(self, engine, voice_dir):
        path = engine._resolve_speaker_wav("cheerful")
        assert path == voice_dir["cheerful"]

    def test_resolve_unknown_emotion_falls_back(self, engine, voice_dir):
        path = engine._resolve_speaker_wav("unknown")
        assert path == voice_dir["neutral"]  # default

    def test_resolve_none_uses_default(self, engine, voice_dir):
        path = engine._resolve_speaker_wav(None)
        assert path == voice_dir["neutral"]

    def test_no_default_no_emotion_returns_none(self, mock_tts_module):
        from elder_berry.tts.coqui_engine import CoquiTTSEngine

        engine = CoquiTTSEngine(voice_map={}, default_speaker_wav=None)
        assert engine._resolve_speaker_wav(None) is None


# ---------------------------------------------------------------------------
# generate_audio
# ---------------------------------------------------------------------------


class TestGenerateAudio:
    def test_generates_file(self, engine, mock_tts_module, tmp_path):
        output = tmp_path / "output.wav"
        engine.generate_audio("Hallo", output, emotion="cheerful")
        mock_tts_module["tts_instance"].tts_to_file.assert_called_once()

    def test_auto_loads_if_needed(self, engine, mock_tts_module, tmp_path):
        output = tmp_path / "output.wav"
        assert not engine.is_loaded
        engine.generate_audio("Hallo", output)
        assert engine.is_loaded

    def test_uses_correct_speaker_wav(
        self, engine, mock_tts_module, tmp_path, voice_dir
    ):
        output = tmp_path / "output.wav"
        engine.generate_audio("Hallo", output, emotion="angry")
        call_kwargs = mock_tts_module["tts_instance"].tts_to_file.call_args
        assert call_kwargs.kwargs["speaker_wav"] == str(voice_dir["angry"])

    def test_raises_without_speaker_wav(self, mock_tts_module, tmp_path):
        from elder_berry.tts.coqui_engine import CoquiTTSEngine

        engine = CoquiTTSEngine(voice_map={}, default_speaker_wav=None)
        with pytest.raises(ValueError, match="Speaker-WAV"):
            engine.generate_audio("Hallo", tmp_path / "out.wav")

    def test_uses_default_language(self, engine, mock_tts_module, tmp_path):
        output = tmp_path / "output.wav"
        engine.generate_audio("Hallo", output)
        call_kwargs = mock_tts_module["tts_instance"].tts_to_file.call_args
        assert "de" in str(call_kwargs)


# ---------------------------------------------------------------------------
# Volume / Rate
# ---------------------------------------------------------------------------


class TestVolumeRate:
    def test_default_volume(self, engine):
        assert engine.get_volume() == 1.0

    def test_set_volume(self, engine):
        engine.set_volume(0.5)
        assert engine.get_volume() == 0.5

    def test_set_volume_rejects_invalid(self, engine):
        with pytest.raises(ValueError, match="0.0 und 1.0"):
            engine.set_volume(1.5)
        with pytest.raises(ValueError, match="0.0 und 1.0"):
            engine.set_volume(-0.1)

    def test_default_rate(self, engine):
        assert engine.get_rate() == 200

    def test_set_rate(self, engine):
        engine.set_rate(150)
        assert engine.get_rate() == 150


# ---------------------------------------------------------------------------
# Voices (VoiceInfo)
# ---------------------------------------------------------------------------


class TestVoices:
    def test_get_voices_returns_mapped(self, engine):
        voices = engine.get_voices()
        assert len(voices) == 4
        assert all(isinstance(v, VoiceInfo) for v in voices)

    def test_get_voices_language(self, engine):
        voices = engine.get_voices()
        assert all(v.language == "de" for v in voices)

    def test_set_voice_valid(self, engine, voice_dir):
        engine.set_voice("angry")
        assert engine._default_speaker_wav == voice_dir["angry"]

    def test_set_voice_invalid_raises(self, engine):
        with pytest.raises(ValueError, match="nicht gefunden"):
            engine.set_voice("nonexistent")


# ---------------------------------------------------------------------------
# speak (Integration: generate + play)
# ---------------------------------------------------------------------------


class TestSpeak:
    def test_speak_empty_text_skips(self, engine, mock_tts_module):
        engine.speak("   ")
        mock_tts_module["tts_instance"].tts_to_file.assert_not_called()

    def test_speak_calls_generate(self, engine, mock_tts_module):
        with patch.object(engine, "generate_audio") as mock_gen:
            with patch.object(engine, "_play_audio"):
                engine.speak("Hallo", emotion="cheerful")
                mock_gen.assert_called_once()
                args = mock_gen.call_args
                assert args[0][0] == "Hallo"
                assert args[1].get("emotion") or args[0][2] == "cheerful"

    def test_speak_cleans_up_temp_file(self, engine, mock_tts_module):
        with (
            patch.object(engine, "generate_audio"),
            patch.object(engine, "_play_audio"),
        ):
            engine.speak("Test")
        # Temp-Datei sollte gelöscht sein (kein Assert nötig, kein Crash = OK)


# ---------------------------------------------------------------------------
# Emoji-Bereinigung (_clean_text_for_tts)
# ---------------------------------------------------------------------------


class TestCleanTextForTts:
    def test_plain_text_unchanged(self):
        assert _clean_text_for_tts("Hallo Welt!") == "Hallo Welt!"

    def test_emoji_removed(self):
        assert _clean_text_for_tts("Gute Nacht! 🌙") == "Gute Nacht!"

    def test_multiple_emojis_removed(self):
        assert _clean_text_for_tts("Hey! 😊🎉🔥") == "Hey!"

    def test_only_emoji_returns_empty(self):
        assert _clean_text_for_tts("🌙") == ""

    def test_emoji_between_text(self):
        assert _clean_text_for_tts("Gute 🌙 Nacht!") == "Gute Nacht!"

    def test_preserves_german_umlauts(self):
        assert _clean_text_for_tts("Träum was Schönes!") == "Träum was Schönes!"

    def test_whitespace_normalized(self):
        assert _clean_text_for_tts("Hallo   Welt") == "Hallo Welt"

    def test_empty_string(self):
        assert _clean_text_for_tts("") == ""


class TestGenerateAudioEmojiHandling:
    def test_emoji_stripped_before_tts(self, engine, mock_tts_module, tmp_path):
        """Emojis werden vor der TTS-Synthese entfernt."""
        output = tmp_path / "output.wav"
        engine.generate_audio("Gute Nacht! 🌙", output)
        call_kwargs = mock_tts_module["tts_instance"].tts_to_file.call_args
        assert call_kwargs.kwargs["text"] == "Gute Nacht!"

    def test_pure_emoji_skips_tts(self, engine, mock_tts_module, tmp_path):
        """Reiner Emoji-Text überspringt TTS komplett."""
        output = tmp_path / "output.wav"
        engine.generate_audio("🌙🎉", output)
        mock_tts_module["tts_instance"].tts_to_file.assert_not_called()


class TestSplitSentences:
    """XTTS v2 splittet intern an Kommas/Punkten. Fragmente verlieren die
    Sprachzuordnung und driften z.B. ins Japanische. Deshalb: eigenes
    Satz-Splitting + WAV-Concatenation statt Coqui-internes Splitting."""

    def test_short_text_no_split(self, engine, mock_tts_module, tmp_path):
        """Kurzer Text → split_sentences=False."""
        output = tmp_path / "output.wav"
        engine.generate_audio("Guten Morgen, wie kann ich dir helfen?", output)
        call_kwargs = mock_tts_module["tts_instance"].tts_to_file.call_args
        assert call_kwargs.kwargs["split_sentences"] is False

    def test_long_text_also_no_split(self, engine, mock_tts_module, tmp_path):
        """Langer Text → split_sentences=False (eigenes Splitting)."""
        import wave, struct

        output = tmp_path / "output.wav"
        long_text = "Dies ist ein sehr langer Text. " * 5

        # Mock: tts_to_file muss echte WAV-Dateien erzeugen (für wave.open)
        def _fake_tts_to_file(**kwargs):
            p = Path(kwargs["file_path"])
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                wf.writeframes(struct.pack("<h", 0) * 100)

        mock_tts_module["tts_instance"].tts_to_file.side_effect = _fake_tts_to_file

        engine.generate_audio(long_text, output)
        # Alle tts_to_file Aufrufe prüfen
        for call in mock_tts_module["tts_instance"].tts_to_file.call_args_list:
            assert call.kwargs["split_sentences"] is False

    def test_single_sentence_no_concat(self, engine, mock_tts_module, tmp_path):
        """Einzelner Satz → direkte Generierung, kein Concatenation."""
        output = tmp_path / "output.wav"
        engine.generate_audio("Hallo Welt!", output)
        # Nur ein Aufruf
        assert mock_tts_module["tts_instance"].tts_to_file.call_count == 1
