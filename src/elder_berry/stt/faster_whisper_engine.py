"""FasterWhisperEngine – lokale STT via faster-whisper (GPU-beschleunigt)."""
from __future__ import annotations

import logging
import tempfile
import wave
from pathlib import Path

from .base import STTEngine, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

# Lazy-Import: faster-whisper ist optional
try:
    from faster_whisper import WhisperModel as _WhisperModel
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _WhisperModel = None  # type: ignore[assignment]
    _FASTER_WHISPER_AVAILABLE = False

DEFAULT_MODEL = "medium"
DEFAULT_LANGUAGE = "de"


class FasterWhisperEngine(STTEngine):
    """
    Speech-to-Text via faster-whisper (CTranslate2-basiert, GPU-beschleunigt).

    Tower RTX 4070 Ti Super (16GB VRAM):
        - Empfohlen: large-v3 (beste Qualität, ~3GB VRAM)
        - Gut: medium (Kompromiss Geschwindigkeit/Qualität, ~1.5GB VRAM)

    Laptop RTX 4070 (8GB VRAM):
        - Empfohlen: medium
        - Schnell: small (geringste Latenz)

    Sprachunterstützung: 99 Sprachen, erkennt automatisch oder vorgegeben.

    Args:
        model_size: "tiny" | "base" | "small" | "medium" | "large-v3"
        device:     "auto" | "cuda" | "cpu"
        language:   ISO-Code z.B. "de" oder None für Auto-Erkennung
        compute_type: "float16" (GPU) | "int8" (CPU-schnell) | "float32"
    """

    def __init__(
        self,
        model_size: str = DEFAULT_MODEL,
        device: str = "auto",
        language: str | None = DEFAULT_LANGUAGE,
        compute_type: str = "auto",
    ) -> None:
        if not _FASTER_WHISPER_AVAILABLE:
            raise ImportError(
                "faster-whisper nicht installiert. "
                "Installiere es mit: pip install faster-whisper"
            )
        self.model_size = model_size
        self.language = language
        self._device = self._resolve_device(device)
        self._compute_type = self._resolve_compute_type(compute_type, self._device)
        self._model: _WhisperModel | None = None

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            pass
        # Ohne torch: prüfen ob CUDA-Libraries vorhanden
        try:
            import ctranslate2
            if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
                return "cuda"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def _resolve_compute_type(compute_type: str, device: str) -> str:
        if compute_type != "auto":
            return compute_type
        return "float16" if device == "cuda" else "int8"

    def is_available(self) -> bool:
        return _FASTER_WHISPER_AVAILABLE

    def load(self) -> None:
        """Lädt das Whisper-Modell explizit (sonst Lazy-Load bei erster Nutzung)."""
        if self._model is None:
            logger.info(
                "Lade Whisper-Modell '%s' auf %s (%s) ...",
                self.model_size, self._device, self._compute_type,
            )
            self._model = _WhisperModel(
                self.model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            logger.info("Whisper-Modell geladen.")

    def unload(self) -> None:
        """Entlädt das Modell (VRAM freigeben)."""
        if self._model is not None:
            del self._model
            self._model = None
            logger.info("Whisper-Modell entladen.")

    def _get_model(self) -> _WhisperModel:
        """Gibt das Modell zurück, lädt es bei Bedarf (Lazy-Load)."""
        if self._model is None:
            self.load()
        return self._model

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """
        Transkribiert eine Audio-Datei.

        Unterstützte Formate: WAV, MP3, FLAC, OGG, M4A, und alle von ffmpeg
        unterstützten Formate.

        Args:
            audio_path: Pfad zur Audio-Datei.

        Returns:
            TranscriptionResult.

        Raises:
            FileNotFoundError: Wenn Datei nicht existiert.
            RuntimeError: Bei Transkriptions-Fehler.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_path}")

        model = self._get_model()
        return self._run_transcription(model, str(audio_path))

    def transcribe_bytes(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """
        Transkribiert rohe PCM-Audio-Bytes (int16, mono).

        Schreibt temporäre WAV-Datei und ruft transcribe() auf.

        Args:
            audio_data:  PCM-Audio als Bytes (int16, mono).
            sample_rate: Sample-Rate in Hz.

        Returns:
            TranscriptionResult.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            self._write_wav(tmp_path, audio_data, sample_rate)
            return self.transcribe(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _write_wav(path: Path, pcm_bytes: bytes, sample_rate: int) -> None:
        """Schreibt PCM-Bytes als WAV-Datei."""
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)       # Mono
            wf.setsampwidth(2)       # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)

    def _run_transcription(
        self, model: _WhisperModel, audio_input: str
    ) -> TranscriptionResult:
        """Führt die Transkription aus und wandelt das Ergebnis um."""
        try:
            kwargs: dict = {
                "beam_size": 5,
                "vad_filter": True,   # Stille-Filter (reduziert Halluzinationen)
                "vad_parameters": {"min_silence_duration_ms": 500},
            }
            if self.language:
                kwargs["language"] = self.language

            segments_iter, info = model.transcribe(audio_input, **kwargs)
            segments = []
            texts = []
            total_avg_log_prob = 0.0

            for seg in segments_iter:
                segments.append(TranscriptionSegment(
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                ))
                texts.append(seg.text.strip())
                total_avg_log_prob += seg.avg_logprob

            full_text = " ".join(t for t in texts if t)

            # avg_logprob → approximative Konfidenz (log-Prob ist negativ, -0 = perfekt)
            confidence: float | None = None
            if segments:
                avg_log_prob = total_avg_log_prob / len(segments)
                import math
                confidence = max(0.0, min(1.0, math.exp(avg_log_prob)))

            return TranscriptionResult(
                text=full_text,
                language=info.language,
                confidence=confidence,
                segments=segments,
            )
        except Exception as e:
            raise RuntimeError(f"Whisper-Transkription fehlgeschlagen: {e}") from e
