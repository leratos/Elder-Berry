"""Tests: AudioConverter – WAV/MP3 → OGG/Opus Konvertierung."""
import json
import struct
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.audio_converter import AudioConverter, AudioConverterError


def _fake_run(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Liefert ein CompletedProcess-artiges Mock-Objekt."""
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


def _ffprobe_json(duration_seconds: float) -> str:
    return json.dumps({"format": {"duration": str(duration_seconds)}})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def converter():
    """AudioConverter-Instanz."""
    return AudioConverter()


@pytest.fixture
def wav_file(tmp_path) -> Path:
    """Erstellt eine minimale gültige WAV-Datei (1 Sekunde Stille, 16-bit, 44100Hz)."""
    path = tmp_path / "test.wav"
    sample_rate = 44100
    duration = 1.0
    num_samples = int(sample_rate * duration)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # Stille: Nullen
        wf.writeframes(b"\x00\x00" * num_samples)

    return path


@pytest.fixture
def short_wav(tmp_path) -> Path:
    """Erstellt eine 500ms WAV-Datei."""
    path = tmp_path / "short.wav"
    sample_rate = 44100
    num_samples = int(sample_rate * 0.5)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_samples)

    return path


# ---------------------------------------------------------------------------
# Init + ffmpeg-Check
# ---------------------------------------------------------------------------

class TestInit:
    def test_ffmpeg_check(self, converter):
        # Ergebnis hängt von System ab, aber Property muss bool sein
        assert isinstance(converter.ffmpeg_available, bool)

    def test_ffmpeg_not_found(self):
        with patch("elder_berry.comms.audio_converter.shutil.which", return_value=None):
            conv = AudioConverter()
            assert conv.ffmpeg_available is False

    def test_ffmpeg_found(self):
        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()
            assert conv.ffmpeg_available is True


# ---------------------------------------------------------------------------
# to_ogg_opus (nur wenn ffmpeg verfügbar)
# ---------------------------------------------------------------------------

class TestToOggOpus:
    def test_convert_wav_to_ogg(self, converter, wav_file, tmp_path):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        ogg_path, duration_ms = converter.to_ogg_opus(wav_file)

        assert ogg_path.exists()
        assert ogg_path.suffix == ".ogg"
        assert duration_ms > 900  # ~1000ms WAV
        assert duration_ms < 1100

    def test_custom_output_path(self, converter, wav_file, tmp_path):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        custom = tmp_path / "custom_output.ogg"
        ogg_path, duration_ms = converter.to_ogg_opus(wav_file, output_path=custom)

        assert ogg_path == custom
        assert custom.exists()

    def test_default_output_path(self, converter, wav_file):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        ogg_path, _ = converter.to_ogg_opus(wav_file)
        assert ogg_path == wav_file.with_suffix(".ogg")

    def test_file_not_found(self, converter):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        with pytest.raises(FileNotFoundError):
            converter.to_ogg_opus(Path("/nonexistent/audio.wav"))

    def test_short_duration(self, converter, short_wav):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        _, duration_ms = converter.to_ogg_opus(short_wav)
        assert 400 < duration_ms < 600  # ~500ms

    def test_ogg_smaller_than_wav(self, converter, wav_file):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        wav_size = wav_file.stat().st_size
        ogg_path, _ = converter.to_ogg_opus(wav_file)
        ogg_size = ogg_path.stat().st_size

        # OGG/Opus sollte deutlich kleiner sein als WAV
        assert ogg_size < wav_size

    def test_custom_bitrate(self, converter, wav_file, tmp_path):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        low = tmp_path / "low.ogg"
        high = tmp_path / "high.ogg"

        _, dur_low = converter.to_ogg_opus(wav_file, output_path=low, bitrate="32k")
        _, dur_high = converter.to_ogg_opus(wav_file, output_path=high, bitrate="128k")

        # Beide Bitraten erzeugen valide Dateien mit korrekter Dauer
        assert low.exists() and low.stat().st_size > 0
        assert high.exists() and high.stat().st_size > 0
        assert dur_low > 0
        assert dur_high > 0


# ---------------------------------------------------------------------------
# to_ogg_opus ohne ffmpeg
# ---------------------------------------------------------------------------

class TestWithoutFfmpeg:
    def test_raises_without_ffmpeg(self, wav_file):
        with patch("elder_berry.comms.audio_converter.shutil.which", return_value=None):
            conv = AudioConverter()
            with pytest.raises(AudioConverterError, match="ffmpeg nicht verfügbar"):
                conv.to_ogg_opus(wav_file)

    def test_duration_raises_without_ffmpeg(self, wav_file):
        with patch("elder_berry.comms.audio_converter.shutil.which", return_value=None):
            conv = AudioConverter()
            with pytest.raises(AudioConverterError, match="ffmpeg nicht verfügbar"):
                conv.get_duration_ms(wav_file)


# ---------------------------------------------------------------------------
# get_duration_ms
# ---------------------------------------------------------------------------

class TestGetDuration:
    def test_wav_duration(self, converter, wav_file):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        duration = converter.get_duration_ms(wav_file)
        assert 900 < duration < 1100  # ~1000ms

    def test_short_wav_duration(self, converter, short_wav):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        duration = converter.get_duration_ms(short_wav)
        assert 400 < duration < 600  # ~500ms

    def test_file_not_found(self, converter):
        if not converter.ffmpeg_available:
            pytest.skip("ffmpeg nicht installiert")

        with pytest.raises(FileNotFoundError):
            converter.get_duration_ms(Path("/nonexistent.wav"))


# ---------------------------------------------------------------------------
# Mocked subprocess tests – Phase 55 Rewrite ohne pydub
# ---------------------------------------------------------------------------

def _make_mocked_converter():
    """AudioConverter mit simuliertem ffmpeg + ffprobe."""
    with patch(
        "elder_berry.comms.audio_converter.shutil.which",
        side_effect=lambda name: f"/usr/bin/{name}",
    ):
        return AudioConverter()


class TestInitFfprobe:
    def test_ffprobe_available_both_found(self):
        conv = _make_mocked_converter()
        assert conv.ffmpeg_available is True
        assert conv.ffprobe_available is True

    def test_ffprobe_missing(self):
        def _which(name):
            return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

        with patch(
            "elder_berry.comms.audio_converter.shutil.which",
            side_effect=_which,
        ):
            conv = AudioConverter()
        assert conv.ffmpeg_available is True
        assert conv.ffprobe_available is False


class TestToOggOpusMocked:
    """Tests für to_ogg_opus mit gemocktem subprocess (kein ffmpeg nötig)."""

    def test_convert_success_calls_ffmpeg_and_ffprobe(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "input.wav"
        input_wav.write_bytes(b"RIFF data")

        conv = _make_mocked_converter()

        responses = [
            _fake_run(),                                     # ffmpeg
            _fake_run(stdout=_ffprobe_json(1.234)),          # ffprobe
        ]
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            side_effect=responses,
        ) as mock_run:
            result_path, duration_ms = conv.to_ogg_opus(input_wav)

        assert result_path == input_wav.with_suffix(".ogg")
        assert duration_ms == 1234
        # ffmpeg-Argumente prüfen
        ffmpeg_cmd = mock_run.call_args_list[0].args[0]
        assert ffmpeg_cmd[0] == "ffmpeg"
        assert "-c:a" in ffmpeg_cmd and "libopus" in ffmpeg_cmd
        assert "-b:a" in ffmpeg_cmd and "64k" in ffmpeg_cmd
        assert str(input_wav) in ffmpeg_cmd
        # ffprobe-Argumente prüfen
        ffprobe_cmd = mock_run.call_args_list[1].args[0]
        assert ffprobe_cmd[0] == "ffprobe"
        assert "-show_entries" in ffprobe_cmd

    def test_convert_custom_output_and_bitrate(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "audio.wav"
        input_wav.write_bytes(b"RIFF")
        custom_out = tmp_path / "custom.ogg"

        conv = _make_mocked_converter()
        responses = [_fake_run(), _fake_run(stdout=_ffprobe_json(0.5))]
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            side_effect=responses,
        ) as mock_run:
            result_path, duration_ms = conv.to_ogg_opus(
                input_wav, output_path=custom_out, bitrate="32k",
            )

        assert result_path == custom_out
        assert duration_ms == 500
        ffmpeg_cmd = mock_run.call_args_list[0].args[0]
        assert str(custom_out) in ffmpeg_cmd
        assert "32k" in ffmpeg_cmd

    def test_convert_ffmpeg_nonzero_returncode(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "broken.wav"
        input_wav.write_bytes(b"not audio")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            return_value=_fake_run(stderr="Invalid data found", returncode=1),
        ):
            with pytest.raises(
                AudioConverterError, match="Konvertierung fehlgeschlagen",
            ):
                conv.to_ogg_opus(input_wav)

    def test_convert_ffmpeg_timeout(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "slow.wav"
        input_wav.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60),
        ):
            with pytest.raises(AudioConverterError, match="Timeout"):
                conv.to_ogg_opus(input_wav)

    def test_convert_ffmpeg_filenotfound(self, tmp_path: Path) -> None:
        """ffmpeg zwischen which() und run() verschwunden."""
        input_wav = tmp_path / "input.wav"
        input_wav.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            side_effect=FileNotFoundError("ffmpeg"),
        ):
            with pytest.raises(AudioConverterError, match="FileNotFoundError"):
                conv.to_ogg_opus(input_wav)

    def test_convert_ffprobe_fails_after_ffmpeg_success(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "input.wav"
        input_wav.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        responses = [
            _fake_run(),                                  # ffmpeg OK
            _fake_run(stderr="corrupt", returncode=1),    # ffprobe fails
        ]
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            side_effect=responses,
        ):
            with pytest.raises(AudioConverterError, match="Duration"):
                conv.to_ogg_opus(input_wav)

    def test_convert_file_not_found_before_ffmpeg(self, tmp_path: Path) -> None:
        """FileNotFoundError kommt raus bevor subprocess läuft."""
        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
        ) as mock_run:
            with pytest.raises(FileNotFoundError):
                conv.to_ogg_opus(Path("/nonexistent/audio.wav"))
        mock_run.assert_not_called()


class TestGetDurationMocked:
    """Tests für get_duration_ms mit gemocktem ffprobe."""

    def test_get_duration_success(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "speech.wav"
        audio_file.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            return_value=_fake_run(stdout=_ffprobe_json(3.0)),
        ):
            duration = conv.get_duration_ms(audio_file)

        assert duration == 3000

    def test_get_duration_rounds_to_int(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "speech.wav"
        audio_file.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            return_value=_fake_run(stdout=_ffprobe_json(1.2345)),
        ):
            duration = conv.get_duration_ms(audio_file)

        assert duration == 1234 or duration == 1235  # round → int

    def test_get_duration_ffprobe_error(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "broken.wav"
        audio_file.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            return_value=_fake_run(stderr="decode failed", returncode=1),
        ):
            with pytest.raises(AudioConverterError, match="Duration"):
                conv.get_duration_ms(audio_file)

    def test_get_duration_bad_json(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "weird.wav"
        audio_file.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            return_value=_fake_run(stdout="not json"),
        ):
            with pytest.raises(AudioConverterError, match="unlesbar"):
                conv.get_duration_ms(audio_file)

    def test_get_duration_missing_format_key(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "weird.wav"
        audio_file.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            return_value=_fake_run(stdout=json.dumps({"streams": []})),
        ):
            with pytest.raises(AudioConverterError, match="unlesbar"):
                conv.get_duration_ms(audio_file)

    def test_get_duration_ffprobe_timeout(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "slow.wav"
        audio_file.write_bytes(b"RIFF")

        conv = _make_mocked_converter()
        with patch(
            "elder_berry.comms.audio_converter.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=15),
        ):
            with pytest.raises(AudioConverterError, match="Timeout"):
                conv.get_duration_ms(audio_file)

    def test_get_duration_raises_when_ffprobe_missing(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "speech.wav"
        audio_file.write_bytes(b"RIFF")

        def _which(name):
            return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

        with patch(
            "elder_berry.comms.audio_converter.shutil.which",
            side_effect=_which,
        ):
            conv = AudioConverter()

        with pytest.raises(AudioConverterError, match="ffprobe"):
            conv.get_duration_ms(audio_file)

    def test_get_duration_file_not_found(self) -> None:
        conv = _make_mocked_converter()
        with pytest.raises(FileNotFoundError):
            conv.get_duration_ms(Path("/nonexistent.wav"))
