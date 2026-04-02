"""Tests: AudioConverter – WAV/MP3 → OGG/Opus Konvertierung."""
import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.audio_converter import AudioConverter, AudioConverterError


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
# Mock pydub – test conversion and duration logic without ffmpeg
# ---------------------------------------------------------------------------

class TestToOggOpusMocked:
    """Tests fuer to_ogg_opus mit gemocktem pydub (kein ffmpeg nötig)."""

    def test_convert_success_mocked(self, tmp_path: Path) -> None:
        """Konvertierung erfolgreich: mock pydub.AudioSegment."""
        input_wav = tmp_path / "input.wav"
        input_wav.write_bytes(b"RIFF data")
        output_ogg = tmp_path / "input.ogg"

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=1234)  # duration_ms

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_audio

        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            result_path, duration_ms = conv.to_ogg_opus(input_wav)

        assert result_path == input_wav.with_suffix(".ogg")
        assert duration_ms == 1234
        mock_audio.export.assert_called_once()

    def test_convert_custom_output_path_mocked(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "audio.wav"
        input_wav.write_bytes(b"RIFF")
        custom_out = tmp_path / "custom.ogg"

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=500)
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_audio

        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            result_path, duration_ms = conv.to_ogg_opus(input_wav, output_path=custom_out, bitrate="32k")

        assert result_path == custom_out
        assert duration_ms == 500
        export_call = mock_audio.export.call_args
        assert export_call[1]["bitrate"] == "32k"

    def test_convert_pydub_exception_raises_converter_error(self, tmp_path: Path) -> None:
        input_wav = tmp_path / "broken.wav"
        input_wav.write_bytes(b"RIFF")

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.side_effect = Exception("corrupt audio")

        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            with pytest.raises(AudioConverterError, match="Konvertierung fehlgeschlagen"):
                conv.to_ogg_opus(input_wav)

    def test_convert_file_not_found_before_pydub(self, tmp_path: Path) -> None:
        """FileNotFoundError kommt vor pydub-Import."""
        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()
        with pytest.raises(FileNotFoundError):
            conv.to_ogg_opus(Path("/nonexistent/audio.wav"))


class TestGetDurationMocked:
    """Tests fuer get_duration_ms mit gemocktem pydub."""

    def test_get_duration_success_mocked(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "speech.wav"
        audio_file.write_bytes(b"RIFF")

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=3000)
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_audio

        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            duration = conv.get_duration_ms(audio_file)

        assert duration == 3000

    def test_get_duration_pydub_exception(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "broken.wav"
        audio_file.write_bytes(b"RIFF")

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.side_effect = Exception("decode error")

        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            with pytest.raises(AudioConverterError, match="Duration"):
                conv.get_duration_ms(audio_file)

    def test_get_duration_file_not_found(self) -> None:
        with patch("elder_berry.comms.audio_converter.shutil.which", return_value="/usr/bin/ffmpeg"):
            conv = AudioConverter()
        with pytest.raises(FileNotFoundError):
            conv.get_duration_ms(Path("/nonexistent.wav"))
