"""Tests für STT – TranscriptionResult, STTEngine ABC, FasterWhisperEngine."""
from __future__ import annotations

import importlib
import wave
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.stt.base import TranscriptionResult, TranscriptionSegment

if TYPE_CHECKING:
    from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine

_faster_whisper_installed = importlib.util.find_spec("faster_whisper") is not None
requires_faster_whisper = pytest.mark.skipif(
    not _faster_whisper_installed, reason="faster-whisper nicht installiert"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wav_file(tmp_path: Path) -> Path:
    """Erstellt eine minimale 1-Sekunde WAV-Datei (16kHz mono Stille)."""
    path = tmp_path / "test.wav"
    sample_rate = 16000
    n_samples = sample_rate  # 1 Sekunde
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return path


@pytest.fixture
def pcm_bytes() -> bytes:
    """512ms Stille als PCM-Bytes (int16, mono, 16kHz)."""
    n_samples = 8000  # 16000 * 0.5
    return b"\x00\x00" * n_samples


# ---------------------------------------------------------------------------
# TranscriptionResult + TranscriptionSegment
# ---------------------------------------------------------------------------

class TestTranscriptionResult:
    def test_is_empty_true(self):
        r = TranscriptionResult(text="  ")
        assert r.is_empty() is True

    def test_is_empty_false(self):
        r = TranscriptionResult(text="Hallo Welt")
        assert r.is_empty() is False

    def test_defaults(self):
        r = TranscriptionResult(text="test")
        assert r.language is None
        assert r.confidence is None
        assert r.segments == []

    def test_with_all_fields(self):
        seg = TranscriptionSegment(start=0.0, end=1.5, text="Hallo")
        r = TranscriptionResult(
            text="Hallo",
            language="de",
            confidence=0.95,
            segments=[seg],
        )
        assert r.language == "de"
        assert r.confidence == 0.95
        assert len(r.segments) == 1

    def test_segment_frozen(self):
        seg = TranscriptionSegment(start=0.0, end=1.0, text="test")
        with pytest.raises((AttributeError, TypeError)):
            seg.text = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FasterWhisperEngine – ohne echtes Modell
# ---------------------------------------------------------------------------

@requires_faster_whisper
class TestFasterWhisperEngine:
    def _make_engine(self, **kwargs) -> "FasterWhisperEngine":
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine
        return FasterWhisperEngine(**kwargs)

    def test_is_available(self):
        engine = self._make_engine()
        assert engine.is_available() is True

    def test_default_model_size(self):
        engine = self._make_engine()
        assert engine.model_size == "medium"

    def test_custom_model_size(self):
        engine = self._make_engine(model_size="small")
        assert engine.model_size == "small"

    def test_default_language_german(self):
        engine = self._make_engine()
        assert engine.language == "de"

    def test_language_none_for_auto(self):
        engine = self._make_engine(language=None)
        assert engine.language is None

    def test_device_resolve_cpu(self, monkeypatch):
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine
        # torch nicht verfügbar → CPU
        monkeypatch.setattr("builtins.__import__",
            lambda name, *a, **kw: (_ for _ in ()).throw(ImportError()) if name == "torch" else __import__(name, *a, **kw))
        device = FasterWhisperEngine._resolve_device("cpu")
        assert device == "cpu"

    def test_compute_type_auto_cuda(self):
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine
        ct = FasterWhisperEngine._resolve_compute_type("auto", "cuda")
        assert ct == "float16"

    def test_compute_type_auto_cpu(self):
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine
        ct = FasterWhisperEngine._resolve_compute_type("auto", "cpu")
        assert ct == "int8"

    def test_transcribe_file_not_found(self):
        engine = self._make_engine()
        with pytest.raises(FileNotFoundError):
            engine.transcribe(Path("/nichtvorhanden.wav"))

    def test_transcribe_calls_model(self, wav_file: Path):
        engine = self._make_engine(device="cpu")
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "de"
        mock_seg = MagicMock()
        mock_seg.start = 0.0
        mock_seg.end = 1.0
        mock_seg.text = " Hallo Welt"
        mock_seg.avg_logprob = -0.2
        mock_model.transcribe.return_value = ([mock_seg], mock_info)
        engine._model = mock_model

        result = engine.transcribe(wav_file)
        assert result.text == "Hallo Welt"
        assert result.language == "de"
        assert result.confidence is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_transcribe_empty_result(self, wav_file: Path):
        engine = self._make_engine(device="cpu")
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "de"
        mock_model.transcribe.return_value = ([], mock_info)
        engine._model = mock_model

        result = engine.transcribe(wav_file)
        assert result.text == ""
        assert result.is_empty() is True

    def test_transcribe_multiple_segments(self, wav_file: Path):
        engine = self._make_engine(device="cpu")
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "de"
        segs = []
        for i, text in enumerate(["Hallo,", "wie", "geht's?"]):
            s = MagicMock()
            s.start = float(i)
            s.end = float(i + 1)
            s.text = f" {text}"
            s.avg_logprob = -0.1
            segs.append(s)
        mock_model.transcribe.return_value = (segs, mock_info)
        engine._model = mock_model

        result = engine.transcribe(wav_file)
        assert "Hallo," in result.text
        assert len(result.segments) == 3

    def test_transcribe_language_set_in_kwargs(self, wav_file: Path):
        engine = self._make_engine(device="cpu", language="en")
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_model.transcribe.return_value = ([], mock_info)
        engine._model = mock_model

        engine.transcribe(wav_file)
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert call_kwargs.get("language") == "en"

    def test_transcribe_no_language_for_auto(self, wav_file: Path):
        engine = self._make_engine(device="cpu", language=None)
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "fr"
        mock_model.transcribe.return_value = ([], mock_info)
        engine._model = mock_model

        engine.transcribe(wav_file)
        call_kwargs = mock_model.transcribe.call_args.kwargs
        assert "language" not in call_kwargs

    def test_transcribe_bytes_creates_wav(self, tmp_path: Path, pcm_bytes: bytes):
        engine = self._make_engine(device="cpu")
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "de"
        mock_seg = MagicMock()
        mock_seg.start = 0.0
        mock_seg.end = 0.5
        mock_seg.text = " Test"
        mock_seg.avg_logprob = -0.1
        mock_model.transcribe.return_value = ([mock_seg], mock_info)
        engine._model = mock_model

        result = engine.transcribe_bytes(pcm_bytes, sample_rate=16000)
        assert result.text == "Test"

    def test_write_wav_creates_valid_file(self, tmp_path: Path, pcm_bytes: bytes):
        from elder_berry.stt.faster_whisper_engine import FasterWhisperEngine
        path = tmp_path / "out.wav"
        FasterWhisperEngine._write_wav(path, pcm_bytes, 16000)
        assert path.exists()
        with wave.open(str(path)) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    def test_load_unload(self):
        engine = self._make_engine(device="cpu")
        with patch("elder_berry.stt.faster_whisper_engine._WhisperModel") as MockModel:
            engine.load()
            assert engine._model is not None
            MockModel.assert_called_once_with(
                "medium", device="cpu", compute_type="int8"
            )
            engine.unload()
            assert engine._model is None

    def test_lazy_load_on_transcribe(self, wav_file: Path):
        engine = self._make_engine(device="cpu")
        assert engine._model is None
        with patch.object(engine, "load") as mock_load:
            mock_model = MagicMock()
            mock_info = MagicMock()
            mock_info.language = "de"
            mock_model.transcribe.return_value = ([], mock_info)

            def fake_load():
                engine._model = mock_model
            mock_load.side_effect = fake_load

            engine.transcribe(wav_file)
            mock_load.assert_called_once()

    def test_runtime_error_on_transcription_failure(self, wav_file: Path):
        engine = self._make_engine(device="cpu")
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("CUDA out of memory")
        engine._model = mock_model

        with pytest.raises(RuntimeError, match="Whisper-Transkription fehlgeschlagen"):
            engine.transcribe(wav_file)


# ---------------------------------------------------------------------------
# FasterWhisperEngine – Paket nicht installiert
# ---------------------------------------------------------------------------

class TestFasterWhisperNotInstalled:
    def test_raises_on_init_without_package(self):
        import sys
        # faster_whisper aus sys.modules entfernen wenn vorhanden
        saved = sys.modules.pop("faster_whisper", None)
        saved_flag = None
        try:
            import elder_berry.stt.faster_whisper_engine as fw_mod
            saved_flag = fw_mod._FASTER_WHISPER_AVAILABLE
            fw_mod._FASTER_WHISPER_AVAILABLE = False
            fw_mod._WhisperModel = None
            with pytest.raises(ImportError, match="faster-whisper"):
                fw_mod.FasterWhisperEngine()
        finally:
            if saved is not None:
                sys.modules["faster_whisper"] = saved
            if saved_flag is not None:
                fw_mod._FASTER_WHISPER_AVAILABLE = saved_flag
