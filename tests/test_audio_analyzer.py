"""Tests für den AudioAnalyzer (Phase 83.4): WAV → AmplitudeTrack.

Enthält den Integrationstest §7-83.4: ein generiertes 1-Sekunden-WAV (Töne +
Stille) ergibt ein Amplitude-Profil, das über den AmplitudeLipSyncDriver alle
fünf Mund-Buckets sichtbar macht.

Decoding ist numpy-abhängig; Tests, die ein echtes Profil erwarten, überspringen
sauber, wenn numpy fehlt (dann liefert der Analyzer ``None`` → RandomLipSync).
Die WAV-Erzeugung selbst nutzt nur die stdlib (``array``/``wave``).
"""

from __future__ import annotations

import array
import io
import math
import wave

import pytest

from elder_berry.avatar.lip_sync import AmplitudeLipSyncDriver
from elder_berry.core import audio_analyzer as aa_module
from elder_berry.core.audio_analyzer import AmplitudeTrack, AudioAnalyzer

_MOUTH_KEYS = frozenset(
    {
        "mouth_neutral_close",
        "mouth_tiny",
        "mouth_halfopen",
        "mouth_open",
        "mouth_wide",
    }
)

_RATE = 16000  # 50ms-Bucket = 800 Samples; 200ms-Segment = 4 Buckets (sauber).


def _pcm16(kind: str, amp: float, n: int, freq: int = 220) -> array.array:
    """Erzeugt ``n`` 16-bit-Mono-Samples (stdlib, ohne numpy)."""
    out = array.array("h")
    for i in range(n):
        if kind == "silence":
            v = 0.0
        elif kind == "sine":
            v = amp * math.sin(2 * math.pi * freq * i / _RATE)
        else:  # "square" – RMS = amp (erreicht den wide-Bucket > 0.75)
            s = math.sin(2 * math.pi * freq * i / _RATE)
            v = amp * (1.0 if s >= 0 else -1.0)
        out.append(int(max(-1.0, min(1.0, v)) * 32767))
    return out


def _wav_bytes(
    segments: list[tuple[str, float, int]],
    n_channels: int = 1,
    sampwidth: int = 2,
    rate: int = _RATE,
) -> bytes:
    """Baut WAV-Bytes aus (kind, amplitude, ms)-Segmenten."""
    pcm = array.array("h")
    for kind, amp, ms in segments:
        n = int(rate * ms / 1000)
        seg = _pcm16(kind, amp, n)
        if n_channels > 1:
            # Mono → Stereo duplizieren (interleaved L/R identisch).
            stereo = array.array("h")
            for s in seg:
                for _ in range(n_channels):
                    stereo.append(s)
            seg = stereo
        pcm.extend(seg)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _five_bucket_wav() -> bytes:
    # 5 × 200ms = 1000ms; RMS pro Segment trifft je einen Bucket (§4.2).
    return _wav_bytes(
        [
            ("silence", 0.0, 200),  # 0.00 → mouth_neutral_close
            ("sine", 0.18, 200),  # RMS ~0.127 → mouth_tiny
            ("sine", 0.45, 200),  # RMS ~0.318 → mouth_halfopen
            ("sine", 0.82, 200),  # RMS ~0.580 → mouth_open
            ("square", 0.90, 200),  # RMS ~0.900 → mouth_wide
        ]
    )


def _needs_numpy() -> None:
    if not AudioAnalyzer.is_available():
        pytest.skip("numpy nicht verfügbar – Analyzer liefert None (Fallback)")


# ---------------------------------------------------------------------------
# Verfügbarkeit / AmplitudeTrack
# ---------------------------------------------------------------------------


class TestAvailabilityAndDto:
    def test_amplitude_track_is_empty(self):
        assert AmplitudeTrack(samples=[], duration_ms=0).is_empty() is True
        assert AmplitudeTrack(samples=[0.1], duration_ms=50).is_empty() is False

    def test_invalid_bucket_ms_raises(self):
        with pytest.raises(ValueError):
            AudioAnalyzer(bucket_ms=0)

    def test_unavailable_without_numpy(self, monkeypatch):
        # numpy „entfernen" → Analyzer nicht verfügbar, profile() liefert None.
        monkeypatch.setattr(aa_module, "np", None)
        assert AudioAnalyzer.is_available() is False
        assert AudioAnalyzer().profile(_wav_bytes([("sine", 0.5, 100)])) is None


# ---------------------------------------------------------------------------
# Integrationstest §7-83.4: 1-Sekunden-WAV → 5 Buckets sichtbar
# ---------------------------------------------------------------------------


class TestOneSecondWavIntegration:
    def test_profile_shape(self):
        _needs_numpy()
        track = AudioAnalyzer().profile(_five_bucket_wav())
        assert track is not None
        assert 950 <= track.duration_ms <= 1050
        # ~1000ms / 50ms ≈ 20 Buckets.
        assert 18 <= len(track.samples) <= 22
        assert all(0.0 <= s <= 1.0 for s in track.samples)

    def test_all_five_buckets_visible_via_driver(self):
        _needs_numpy()
        track = AudioAnalyzer().profile(_five_bucket_wav())
        assert track is not None
        driver = AmplitudeLipSyncDriver(track)  # kein Guard
        driver.start(0.0)
        step_s = (track.duration_ms / len(track.samples)) / 1000.0
        seen = {driver.mouth_at(i * step_s) for i in range(len(track.samples))}
        assert seen == _MOUTH_KEYS  # alle 5 Buckets sichtbar

    def test_silence_segment_closes_mouth(self):
        _needs_numpy()
        # Laut → Stille: die zweite Hälfte muss (nahezu) Null-RMS liefern.
        track = AudioAnalyzer().profile(
            _wav_bytes([("square", 0.9, 500), ("silence", 0.0, 500)])
        )
        assert track is not None
        half = len(track.samples) // 2
        # Erste Hälfte laut, zweite Hälfte still.
        assert max(track.samples[:half]) > 0.5
        assert max(track.samples[half + 1 :]) < 0.05


# ---------------------------------------------------------------------------
# Eingabe-Varianten
# ---------------------------------------------------------------------------


class TestInputVariants:
    def test_profile_from_file_path(self, tmp_path):
        _needs_numpy()
        path = tmp_path / "tone.wav"
        path.write_bytes(_wav_bytes([("sine", 0.6, 300)]))
        track = AudioAnalyzer().profile(path)
        assert track is not None
        assert track.samples and max(track.samples) > 0.0

    def test_profile_from_str_path(self, tmp_path):
        _needs_numpy()
        path = tmp_path / "tone.wav"
        path.write_bytes(_wav_bytes([("sine", 0.6, 300)]))
        assert AudioAnalyzer().profile(str(path)) is not None

    def test_stereo_is_mixed_to_mono(self):
        _needs_numpy()
        track = AudioAnalyzer().profile(
            _wav_bytes([("sine", 0.7, 400)], n_channels=2)
        )
        assert track is not None
        assert 350 <= track.duration_ms <= 450  # Dauer pro Kanal, nicht ×2

    def test_eight_bit_wav_supported(self):
        _needs_numpy()
        # 8-bit unsigned PCM (sampwidth=1) manuell bauen.
        rate = _RATE
        n = int(rate * 0.2)
        raw = bytes(
            max(0, min(255, int(128 + 100 * math.sin(2 * math.pi * 220 * i / rate))))
            for i in range(n)
        )
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)
            wf.setframerate(rate)
            wf.writeframes(raw)
        track = AudioAnalyzer().profile(buf.getvalue())
        assert track is not None
        assert max(track.samples) > 0.0


# ---------------------------------------------------------------------------
# Robustheit: kein WAV → None (→ RandomLipSync-Fallback, §4.4)
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_empty_bytes_returns_none(self):
        _needs_numpy()
        assert AudioAnalyzer().profile(b"") is None

    def test_mp3_like_bytes_returns_none(self):
        _needs_numpy()
        # ElevenLabs-MP3 wird bewusst nicht decodiert (keine neue Dep) → None.
        assert AudioAnalyzer().profile(b"ID3\x03\x00\x00\x00fake mp3 payload") is None

    def test_garbage_bytes_returns_none(self):
        _needs_numpy()
        assert AudioAnalyzer().profile(b"\x00\x01\x02\x03not a wav") is None

    def test_unsupported_type_returns_none(self):
        _needs_numpy()
        assert AudioAnalyzer().profile(12345) is None  # type: ignore[arg-type]
