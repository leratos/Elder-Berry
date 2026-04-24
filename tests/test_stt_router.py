"""Tests: STTRouter – STT-Routing mit Cloud-STT + Tower-Fallback."""
from unittest.mock import AsyncMock

import pytest

from elder_berry.core.stt_router import STTRouter, STTUnavailableError
from elder_berry.stt.base import TranscriptionResult
from elder_berry.tools.cloud_stt_client import CloudSTTError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_cloud(text: str = "Hallo Welt", fail: bool = False):
    """Mock-CloudSTTClient."""
    mock = AsyncMock()
    if fail:
        mock.transcribe.side_effect = CloudSTTError("API down")
    else:
        mock.transcribe.return_value = text
    return mock


def _make_tower(online: bool = True, text: str = "Tower Text", fail: bool = False):
    """Mock-TowerAgent."""
    mock = AsyncMock()
    mock.is_online = online
    if fail:
        mock.stt.side_effect = Exception("Tower STT failed")
    else:
        mock.stt.return_value = text
    return mock


def _make_router(cloud=None, tower=None):
    """STTRouter mit Mocks."""
    cl = cloud or _make_cloud()
    return STTRouter(cloud_stt=cl, tower=tower)


def _stub_run_async(result):
    """Ersatz für STTRouter._run_async; schließt die Coroutine sauber."""
    def runner(coro):
        if hasattr(coro, "close"):
            coro.close()
        return result
    return runner


# ---------------------------------------------------------------------------
# transcribe_async() – Routing-Logik
# ---------------------------------------------------------------------------

class TestTranscribeAsync:
    async def test_cloud_success(self):
        """Cloud-STT funktioniert → kein Fallback."""
        router = _make_router(cloud=_make_cloud(text="Guten Morgen"))

        result = await router.transcribe_async(b"\x00" * 100)

        assert result.text == "Guten Morgen"
        assert isinstance(result, TranscriptionResult)

    async def test_tower_fallback_on_cloud_failure(self):
        """Cloud down → Tower-Fallback."""
        tower = _make_tower(online=True, text="Tower erkannt")
        router = _make_router(
            cloud=_make_cloud(fail=True),
            tower=tower,
        )

        result = await router.transcribe_async(b"\x00" * 100)

        assert result.text == "Tower erkannt"
        tower.stt.assert_awaited_once()

    async def test_tower_offline_raises(self):
        """Cloud down + Tower offline → STTUnavailableError."""
        tower = _make_tower(online=False)
        router = _make_router(
            cloud=_make_cloud(fail=True),
            tower=tower,
        )

        with pytest.raises(STTUnavailableError, match="Kein STT verfügbar"):
            await router.transcribe_async(b"\x00" * 100)

        tower.stt.assert_not_awaited()

    async def test_no_tower_raises(self):
        """Cloud down + kein Tower → STTUnavailableError."""
        router = _make_router(cloud=_make_cloud(fail=True))

        with pytest.raises(STTUnavailableError):
            await router.transcribe_async(b"\x00" * 100)

    async def test_both_fail_raises(self):
        """Cloud down + Tower STT schlägt fehl → STTUnavailableError."""
        tower = _make_tower(online=True, fail=True)
        router = _make_router(
            cloud=_make_cloud(fail=True),
            tower=tower,
        )

        with pytest.raises(STTUnavailableError):
            await router.transcribe_async(b"\x00" * 100)

    async def test_cloud_success_skips_tower(self):
        """Wenn Cloud erfolgreich ist, wird Tower nicht angefragt."""
        tower = _make_tower()
        router = _make_router(
            cloud=_make_cloud(text="Cloud OK"),
            tower=tower,
        )

        await router.transcribe_async(b"\x00" * 100)

        tower.stt.assert_not_awaited()

    async def test_filename_passed_to_cloud(self):
        """Filename wird an CloudSTTClient weitergereicht."""
        cloud = _make_cloud()
        router = _make_router(cloud=cloud)

        await router.transcribe_async(b"\x00" * 100, filename="msg.mp3")

        cloud.transcribe.assert_awaited_once_with(
            b"\x00" * 100, filename="msg.mp3",
        )

    async def test_result_has_language(self):
        """TranscriptionResult enthält Sprache."""
        router = _make_router(cloud=_make_cloud(text="Test"))

        result = await router.transcribe_async(b"\x00" * 100)

        assert result.language == "de"


# ---------------------------------------------------------------------------
# transcribe() – Datei-basiert (sync via _run_async)
# ---------------------------------------------------------------------------

class TestTranscribe:
    def test_reads_file_and_transcribes(self, tmp_path):
        """transcribe() liest Datei und ruft Cloud-STT auf."""
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"\x00" * 200)

        router = _make_router(cloud=_make_cloud(text="Datei erkannt"))
        called = {"n": 0}
        def fake(coro):
            coro.close()
            called["n"] += 1
            return TranscriptionResult(text="Datei erkannt", language="de")
        router._run_async = fake

        result = router.transcribe(audio_file)

        assert result.text == "Datei erkannt"
        assert called["n"] == 1

    def test_passes_filename(self, tmp_path):
        """Dateiname wird an transcribe_async übergeben."""
        audio_file = tmp_path / "recording.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        router = _make_router()
        called = {"n": 0}
        def fake(coro):
            coro.close()
            called["n"] += 1
            return TranscriptionResult(text="OK")
        router._run_async = fake

        router.transcribe(audio_file)

        assert called["n"] == 1


# ---------------------------------------------------------------------------
# transcribe_bytes()
# ---------------------------------------------------------------------------

class TestTranscribeBytes:
    def test_creates_wav_and_transcribes(self):
        """transcribe_bytes() erstellt WAV und transkribiert."""
        router = _make_router()
        router._run_async = _stub_run_async(
            TranscriptionResult(text="PCM erkannt"),
        )

        # Dummy PCM: 1600 samples × 2 bytes = 3200 bytes = 0.1s bei 16kHz
        pcm_data = b"\x00\x00" * 1600
        result = router.transcribe_bytes(pcm_data, sample_rate=16000)

        assert result.text == "PCM erkannt"


# ---------------------------------------------------------------------------
# STTEngine Interface
# ---------------------------------------------------------------------------

class TestSTTEngineInterface:
    def test_is_available(self):
        router = _make_router()
        assert router.is_available() is True

    def test_load_unload(self):
        router = _make_router()
        router.load()
        assert router._loaded is True
        router.unload()
        assert router._loaded is False
