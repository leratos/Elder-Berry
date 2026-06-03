"""AudioAnalyzer – Amplitude-Profil (AmplitudeTrack) aus TTS-Audio (Phase 83.4).

Der Bot (Rootserver/Tower) ruft den Analyzer nach der TTS-Audio-Generierung;
das Ergebnis (RMS pro 50ms-Bucket, 0.0–1.0) wird additiv per REST an den RPi5
mitgesendet, wo der ``AmplitudeLipSyncDriver`` daraus den Mund ableitet
(§4.2 / §6.3).

Geltungsbereich: nur lokaler Playback-Modus (``matrix_only`` sendet kein
Speaking-Signal, §0.2 / B1).

Decoding: ausschließlich WAV (stdlib ``wave``). XTTS/Coqui liefert WAV;
ElevenLabs-MP3 hat **bewusst** keinen Decoder (keine neue Dependency) →
``None`` → RandomLipSyncDriver-Fallback (§4.4). ``audioop`` ist auf Python 3.13
(RPi5) entfernt, daher RMS via numpy.

numpy-Import ist geguarded: fehlt numpy (z.B. CI-Mock), ist der Analyzer nicht
verfügbar und liefert ``None``; der Aufrufer fällt dann auf den
RandomLipSyncDriver zurück.
"""

from __future__ import annotations

import io
import logging
import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import numpy as _numpy_mod

    # ``np`` bewusst als ``Any`` typisieren: hält die ``is None``-Guards unter
    # mypy-strict (warn_unreachable) erreichbar, erlaubt das Monkeypatchen in
    # Tests (``audio_analyzer.np = None``) und vermeidet einen env-abhängigen
    # ``type: ignore`` (numpy fehlt im typecheck-CI; vgl. mypy-Override
    # ``numpy.*`` = ignore_missing_imports).
    np: Any = _numpy_mod
except ImportError:  # pragma: no cover - numpy ist optional (tts-neural/tower)
    np = None

logger = logging.getLogger(__name__)

# Bucket-Breite des Amplitude-Profils in Millisekunden (§4.2). Sprache wird in
# 50ms-Fenster zerlegt; pro Fenster ein RMS-Wert 0..1.
DEFAULT_BUCKET_MS = 50

# numpy-Dtype-Name je WAV-Samplebreite (Bytes). 24-bit (3) ist nicht
# unterstützt (kein nativer numpy-Integer-Typ) → Profiling liefert None.
_PCM_DTYPES = {1: "uint8", 2: "int16", 4: "int32"}


@dataclass(frozen=True)
class AmplitudeTrack:
    """Amplitude-Profil eines TTS-Audios: RMS pro Zeit-Bucket, 0.0–1.0.

    Reines DTO ohne numpy-Abhängigkeit – wird vom Analyzer (core) erzeugt, per
    REST (robot) transportiert und vom LipSyncDriver (avatar) konsumiert.

    Attributes:
        samples: RMS-Wert je Bucket (0.0 = Stille, 1.0 = Vollaussteuerung).
        duration_ms: Gesamtdauer des Audios in Millisekunden.
        bucket_ms: Bucket-Breite in Millisekunden (informativ). Der
            ``AmplitudeLipSyncDriver`` leitet die Sample-Dauer aus
            ``duration_ms / len(samples)`` ab, damit Sender und Empfänger nicht
            auf eine geteilte Konstante angewiesen sind.
    """

    samples: list[float]
    duration_ms: int
    bucket_ms: int = DEFAULT_BUCKET_MS

    def is_empty(self) -> bool:
        """``True``, wenn keine Samples vorliegen (kein nutzbares Profil)."""
        return not self.samples


class AudioAnalyzer:
    """Baut aus WAV-Audio ein :class:`AmplitudeTrack` (RMS pro Bucket).

    Nur WAV (stdlib ``wave``); MP3 (ElevenLabs) wird bewusst NICHT decodiert
    (keine neue Dependency) → ``None`` → RandomLipSyncDriver-Fallback (§4.4).
    numpy-Import ist geguarded: fehlt numpy, ist der Analyzer nicht verfügbar
    und liefert ``None``.
    """

    def __init__(self, bucket_ms: int = DEFAULT_BUCKET_MS) -> None:
        if bucket_ms <= 0:
            raise ValueError(f"bucket_ms muss > 0 sein (war: {bucket_ms})")
        self._bucket_ms = bucket_ms

    @staticmethod
    def is_available() -> bool:
        """``True``, wenn numpy verfügbar ist (sonst kein Profiling möglich)."""
        return np is not None

    def profile(self, audio: bytes | str | Path) -> AmplitudeTrack | None:
        """Profiliert WAV-Audio (Bytes oder Dateipfad) zu einem AmplitudeTrack.

        Args:
            audio: WAV-Bytes oder Pfad zu einer WAV-Datei.

        Returns:
            Ein :class:`AmplitudeTrack` oder ``None``, wenn numpy fehlt, das
            Format kein dekodierbares WAV ist oder das Audio leer ist – der
            Aufrufer fällt dann auf den RandomLipSyncDriver zurück. Ein nicht
            öffnbarer Pfad (auch ein versehentlich nicht-WAV/Nicht-Pfad-Wert,
            der zu ``str`` wird) scheitert beim Öffnen → ebenfalls ``None``.
        """
        if np is None:
            return None
        if isinstance(audio, bytes):
            return self._open_and_profile(io.BytesIO(audio))
        # str | Path (oder ein versehentlicher Fremdtyp) → als Pfad behandeln;
        # ein nicht öffnbarer Pfad liefert in _open_and_profile sauber None.
        return self._open_and_profile(str(audio))

    def _open_and_profile(
        self, source: io.BytesIO | str
    ) -> AmplitudeTrack | None:
        """Öffnet die WAV-Quelle und delegiert an :meth:`_profile_pcm`."""
        try:
            with wave.open(source, "rb") as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
        except (wave.Error, OSError, EOFError) as exc:
            logger.debug("WAV-Decode fehlgeschlagen: %s", exc)
            return None
        return self._profile_pcm(raw, n_channels, sampwidth, framerate)

    def _profile_pcm(
        self, raw: bytes, n_channels: int, sampwidth: int, framerate: int
    ) -> AmplitudeTrack | None:
        """Rechnet rohe PCM-Frames in RMS-Buckets (0..1) um (numpy vorausgesetzt)."""
        if not raw or framerate <= 0 or n_channels <= 0:
            return None
        dtype = _PCM_DTYPES.get(sampwidth)
        if dtype is None:
            logger.debug("Nicht unterstützte WAV-Samplebreite: %d Byte", sampwidth)
            return None

        data = np.frombuffer(raw, dtype=getattr(np, dtype)).astype(np.float64)
        if data.size == 0:
            return None

        if sampwidth == 1:
            # 8-bit PCM ist unsigned (0..255) → auf 0 zentrieren.
            data = data - 128.0
            max_amp = 128.0
        else:
            max_amp = float(2 ** (8 * sampwidth - 1))

        if n_channels > 1:
            # Mehrkanal → Mono (Mittel über die Kanäle).
            usable = (data.size // n_channels) * n_channels
            if usable == 0:
                return None
            data = data[:usable].reshape(-1, n_channels).mean(axis=1)

        norm = data / max_amp
        per_bucket = max(1, int(round(framerate * self._bucket_ms / 1000.0)))
        n_buckets = int(math.ceil(norm.size / per_bucket))

        samples: list[float] = []
        for i in range(n_buckets):
            chunk = norm[i * per_bucket : (i + 1) * per_bucket]
            if chunk.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            samples.append(min(1.0, max(0.0, rms)))

        if not samples:
            return None

        duration_ms = int(round(norm.size / framerate * 1000.0))
        return AmplitudeTrack(samples, duration_ms, self._bucket_ms)
