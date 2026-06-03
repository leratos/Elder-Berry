"""AudioAnalyzer – Amplitude-Profil (AmplitudeTrack) aus TTS-Audio (Phase 83.4).

Der Bot (Rootserver/Tower) ruft den Analyzer **einmal pro Äußerung** nach der
TTS-Audio-Generierung; das Ergebnis (RMS pro 50ms-Bucket, 0.0–1.0) wird additiv
per REST an den RPi5 mitgesendet, wo der ``AmplitudeLipSyncDriver`` daraus den
Mund ableitet (§4.2 / §6.3).

Geltungsbereich: nur lokaler Playback-Modus (``matrix_only`` sendet kein
Speaking-Signal, §0.2 / B1).

Decoding: ausschließlich WAV (stdlib ``wave``). XTTS/Coqui liefert WAV;
ElevenLabs-MP3 hat **bewusst** keinen Decoder (keine neue Dependency) →
``None`` → RandomLipSyncDriver-Fallback (§4.4).

Die RMS-Berechnung läuft mit der **stdlib** (``array`` + ``math``) – keine
numpy-Abhängigkeit. Das hält den Analyzer in jeder Umgebung verfügbar (kein
optionaler Import, deterministische CI-Coverage) und ist für eine einmalige
O(n)-Auswertung pro TTS-Clip schnell genug. ``audioop`` ist auf Python 3.13
(RPi5) entfernt und wird daher nicht genutzt.

Byte-Order-Hinweis: WAV ist little-endian; ``array`` nutzt die native
Reihenfolge. Alle Zielplattformen (x86, RPi5/ARM) sind little-endian, daher kein
Byteswap.
"""

from __future__ import annotations

import array
import io
import logging
import math
import wave
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Bucket-Breite des Amplitude-Profils in Millisekunden (§4.2). Sprache wird in
# 50ms-Fenster zerlegt; pro Fenster ein RMS-Wert 0..1.
DEFAULT_BUCKET_MS = 50

# WAV-Samplebreite (Bytes) → (array-Typecode, Max-Amplitude, Nullpunkt-Offset).
# 8-bit PCM ist unsigned (0..255, Mitte 128); 16/32-bit sind signed. 24-bit (3)
# hat keinen passenden array-Typecode → nicht unterstützt (Profiling → None).
_PCM_SPEC: dict[int, tuple[str, float, float]] = {
    1: ("B", 128.0, 128.0),
    2: ("h", 32768.0, 0.0),
    4: ("i", 2147483648.0, 0.0),
}


@dataclass(frozen=True)
class AmplitudeTrack:
    """Amplitude-Profil eines TTS-Audios: RMS pro Zeit-Bucket, 0.0–1.0.

    Reines DTO – wird vom Analyzer (core) erzeugt, per REST (robot) transportiert
    und vom LipSyncDriver (avatar) konsumiert.

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
    """Baut aus WAV-Audio ein :class:`AmplitudeTrack` (RMS pro Bucket, stdlib).

    Nur WAV (stdlib ``wave``); MP3 (ElevenLabs) wird bewusst NICHT decodiert
    (keine neue Dependency) → ``None`` → RandomLipSyncDriver-Fallback (§4.4).
    """

    def __init__(self, bucket_ms: int = DEFAULT_BUCKET_MS) -> None:
        if bucket_ms <= 0:
            raise ValueError(f"bucket_ms muss > 0 sein (war: {bucket_ms})")
        self._bucket_ms = bucket_ms

    def profile(self, audio: bytes | str | Path) -> AmplitudeTrack | None:
        """Profiliert WAV-Audio (Bytes oder Dateipfad) zu einem AmplitudeTrack.

        Args:
            audio: WAV-Bytes oder Pfad zu einer WAV-Datei.

        Returns:
            Ein :class:`AmplitudeTrack` oder ``None``, wenn das Format kein
            dekodierbares WAV ist oder das Audio leer ist – der Aufrufer fällt
            dann auf den RandomLipSyncDriver zurück. Ein nicht öffnbarer Pfad
            (auch ein versehentlicher Nicht-Pfad-Wert, der zu ``str`` wird)
            scheitert beim Öffnen → ebenfalls ``None``.
        """
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
        """Rechnet rohe PCM-Frames in RMS-Buckets (0..1) um (reine stdlib)."""
        if not raw or framerate <= 0 or n_channels <= 0:
            return None
        spec = _PCM_SPEC.get(sampwidth)
        if spec is None:
            logger.debug("Nicht unterstützte WAV-Samplebreite: %d Byte", sampwidth)
            return None
        typecode, max_amp, offset = spec

        samples = array.array(typecode)
        if samples.itemsize != sampwidth:  # pragma: no cover - plattform-exotisch
            logger.debug("array-Itemsize passt nicht zur Samplebreite")
            return None
        # Nur vollständige Frames verwenden (abgeschnittene Bytes ignorieren).
        usable_bytes = (len(raw) // sampwidth) * sampwidth
        samples.frombytes(raw[:usable_bytes])
        if not samples:  # pragma: no cover - wave liefert ganze Frames (>= 1 Sample)
            return None

        mono = self._to_mono(samples, n_channels)
        if not mono:  # pragma: no cover - mono leer nur bei leeren samples (s.o.)
            return None

        per_bucket = max(1, round(framerate * self._bucket_ms / 1000))
        out: list[float] = []
        for start in range(0, len(mono), per_bucket):
            chunk = mono[start : start + per_bucket]
            ss = 0.0
            for v in chunk:
                x = (v - offset) / max_amp
                ss += x * x
            rms = math.sqrt(ss / len(chunk))
            out.append(min(1.0, max(0.0, rms)))

        duration_ms = round(len(mono) / framerate * 1000)
        return AmplitudeTrack(out, int(duration_ms), self._bucket_ms)

    @staticmethod
    def _to_mono(samples: "array.array[int]", n_channels: int) -> list[float]:
        """Mischt interleaved Mehrkanal-Samples auf Mono (Mittel der Kanäle)."""
        if n_channels == 1:
            return list(samples)
        usable = (len(samples) // n_channels) * n_channels
        return [
            sum(samples[i : i + n_channels]) / n_channels
            for i in range(0, usable, n_channels)
        ]
