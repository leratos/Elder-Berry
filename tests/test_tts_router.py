"""Tests: TTSRouter – TTS-Routing mit ElevenLabs + Tower-Fallback."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from elder_berry.core.tts_router import TTSRouter, TTSUnavailableError
from elder_berry.tts.base import TTSEngine, VoiceInfo
from elder_berry.tools.elevenlabs_client import ElevenLabsError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_elevenlabs(audio: bytes = b"\xff" * 200, fail: bool = False):
    """Mock-ElevenLabsClient."""
    mock = AsyncMock()
    if fail:
        mock.synthesize.side_effect = ElevenLabsError("API down")
    else:
        mock.synthesize.return_value = audio
    return mock


def _make_tower(online: bool = True, audio: bytes = b"\x00" * 300, fail: bool = False):
    """Mock-TowerAgent."""
    mock = AsyncMock()
    mock.is_online = online
    if fail:
        mock.tts.side_effect = Exception("Tower TTS failed")
    else:
        mock.tts.return_value = audio
    return mock


def _make_router(elevenlabs=None, tower=None):
    """TTSRouter mit Mocks."""
    el = elevenlabs or _make_elevenlabs()
    return TTSRouter(elevenlabs=el, tower=tower)


# ---------------------------------------------------------------------------
# synthesize() – Routing-Logik
# ---------------------------------------------------------------------------

class TestSynthesize:
    async def test_elevenlabs_success(self):
        """ElevenLabs funktioniert → kein Fallback."""
        audio = b"\xff\xfb" * 150
        router = _make_router(elevenlabs=_make_elevenlabs(audio=audio))

        result = await router.synthesize("Hallo")

        assert result == audio
        router._elevenlabs.synthesize.assert_awaited_once_with("Hallo")

    async def test_tower_fallback_on_elevenlabs_failure(self):
        """ElevenLabs down → Tower-Fallback."""
        tower_audio = b"\x00\x01" * 200
        tower = _make_tower(online=True, audio=tower_audio)
        router = _make_router(
            elevenlabs=_make_elevenlabs(fail=True),
            tower=tower,
        )

        result = await router.synthesize("Test", emotion="cheerful")

        assert result == tower_audio
        tower.tts.assert_awaited_once_with("Test", "cheerful")

    async def test_tower_offline_raises(self):
        """ElevenLabs down + Tower offline → TTSUnavailableError."""
        tower = _make_tower(online=False)
        router = _make_router(
            elevenlabs=_make_elevenlabs(fail=True),
            tower=tower,
        )

        with pytest.raises(TTSUnavailableError, match="Kein TTS verfügbar"):
            await router.synthesize("Test")

        tower.tts.assert_not_awaited()

    async def test_no_tower_raises(self):
        """ElevenLabs down + kein Tower → TTSUnavailableError."""
        router = _make_router(elevenlabs=_make_elevenlabs(fail=True))

        with pytest.raises(TTSUnavailableError):
            await router.synthesize("Test")

    async def test_both_fail_raises(self):
        """ElevenLabs down + Tower-TTS schlägt fehl → TTSUnavailableError."""
        tower = _make_tower(online=True, fail=True)
        router = _make_router(
            elevenlabs=_make_elevenlabs(fail=True),
            tower=tower,
        )

        with pytest.raises(TTSUnavailableError):
            await router.synthesize("Test")

    async def test_elevenlabs_success_skips_tower(self):
        """Wenn ElevenLabs erfolgreich ist, wird Tower nicht angefragt."""
        tower = _make_tower()
        router = _make_router(
            elevenlabs=_make_elevenlabs(audio=b"\xff" * 200),
            tower=tower,
        )

        await router.synthesize("Test")

        tower.tts.assert_not_awaited()

    async def test_emotion_passed_to_tower(self):
        """Emotion wird an Tower weitergereicht."""
        tower = _make_tower()
        router = _make_router(
            elevenlabs=_make_elevenlabs(fail=True),
            tower=tower,
        )

        await router.synthesize("Traurig", emotion="sad")

        tower.tts.assert_awaited_once_with("Traurig", "sad")


# ---------------------------------------------------------------------------
# generate_audio() – Datei-Generierung
#
# generate_audio() ist synchron und nutzt _run_async() um synthesize()
# aufzurufen. In Tests mocken wir _run_async direkt, da der synchrone
# Aufruf aus einem laufenden Event-Loop heraus sonst deadlockt.
# ---------------------------------------------------------------------------

class TestGenerateAudio:
    def test_writes_mp3_file(self, tmp_path):
        """generate_audio() schreibt MP3-Datei."""
        audio = b"\xff\xfb\x90" * 100
        router = _make_router()
        router._run_async = MagicMock(return_value=audio)

        output = tmp_path / "speech.wav"
        result = router.generate_audio("Hallo Welt", output)

        expected = tmp_path / "speech.mp3"
        assert result == expected
        assert expected.exists()
        assert expected.read_bytes() == audio

    def test_original_wav_not_created(self, tmp_path):
        """Die .wav-Datei wird NICHT erstellt (nur .mp3)."""
        router = _make_router()
        router._run_async = MagicMock(return_value=b"\xff" * 200)

        output = tmp_path / "speech.wav"
        router.generate_audio("Test", output)

        assert not output.exists()
        assert (tmp_path / "speech.mp3").exists()

    def test_fallback_audio_writes_file(self, tmp_path):
        """Auch Fallback-Audio wird korrekt geschrieben."""
        tower_audio = b"\x00\x01" * 200
        router = _make_router()
        router._run_async = MagicMock(return_value=tower_audio)

        output = tmp_path / "speech.wav"
        result = router.generate_audio("Test", output, emotion="neutral")

        assert result.exists()
        assert result.read_bytes() == tower_audio

    def test_generate_audio_returns_path(self, tmp_path):
        """Rückgabewert ist der tatsächliche Pfad (.mp3)."""
        router = _make_router()
        router._run_async = MagicMock(return_value=b"\xff" * 100)

        result = router.generate_audio("Test", tmp_path / "out.wav")

        assert result.suffix == ".mp3"
        assert result.stem == "out"

    def test_local_fallback_on_cloud_and_tower_failure(self, tmp_path):
        """ElevenLabs + Tower down → lokaler Fallback."""
        local_tts = MagicMock(spec=TTSEngine)
        expected_path = tmp_path / "speech.wav"
        local_tts.generate_audio.return_value = expected_path

        router = _make_router(elevenlabs=_make_elevenlabs(fail=True))
        router._local_tts = local_tts
        router._run_async = MagicMock(side_effect=TTSUnavailableError("down"))

        result = router.generate_audio("Test", expected_path, emotion="neutral")

        assert result == expected_path
        local_tts.generate_audio.assert_called_once_with(
            "Test", expected_path, emotion="neutral",
        )

    def test_no_local_fallback_raises(self, tmp_path):
        """Ohne lokalen Fallback → Error propagiert."""
        router = _make_router(elevenlabs=_make_elevenlabs(fail=True))
        router._run_async = MagicMock(side_effect=TTSUnavailableError("down"))

        with pytest.raises(TTSUnavailableError):
            router.generate_audio("Test", tmp_path / "speech.wav")

    def test_speak_delegates_to_local(self):
        """speak() delegiert an lokale Engine."""
        local_tts = MagicMock(spec=TTSEngine)
        router = _make_router()
        router._local_tts = local_tts

        router.speak("Hallo", emotion="cheerful")

        local_tts.speak.assert_called_once_with("Hallo", emotion="cheerful")


# ---------------------------------------------------------------------------
# TTSEngine Interface
# ---------------------------------------------------------------------------

class TestTTSEngineInterface:
    def test_speak_no_error(self):
        """speak() wirft keinen Fehler (No-Op auf Server)."""
        router = _make_router()
        router.speak("Hallo")

    def test_get_set_rate(self):
        router = _make_router()
        assert router.get_rate() == 200
        router.set_rate(150)
        assert router.get_rate() == 150

    def test_get_set_volume(self):
        router = _make_router()
        assert router.get_volume() == 1.0
        router.set_volume(0.5)
        assert router.get_volume() == 0.5

    def test_volume_out_of_range(self):
        router = _make_router()
        with pytest.raises(ValueError):
            router.set_volume(1.5)
        with pytest.raises(ValueError):
            router.set_volume(-0.1)

    def test_get_voices(self):
        router = _make_router()
        voices = router.get_voices()
        assert len(voices) == 1
        assert voices[0].id == "elevenlabs"

    def test_set_voice_no_error(self):
        """set_voice() wirft keinen Fehler (ignoriert)."""
        router = _make_router()
        router.set_voice("some-id")


# ---------------------------------------------------------------------------
# TowerAgent
# ---------------------------------------------------------------------------

class TestTowerAgent:
    def _mock_http(self, response=None, error=None):
        mock_http = AsyncMock()
        if error:
            mock_http.get.side_effect = error
            mock_http.post.side_effect = error
        else:
            mock_http.get.return_value = response
            mock_http.post.return_value = response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        return mock_http

    async def test_heartbeat_success(self):
        from elder_berry.core.tower_agent import TowerAgent

        agent = TowerAgent(tower_host="127.0.0.1:12769")

        resp = MagicMock()
        resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = resp
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        with patch("elder_berry.core.tower_agent.httpx.AsyncClient",
                    return_value=mock_client):
            with patch("elder_berry.core.tower_agent.httpx.Timeout"):
                result = await agent.heartbeat()

        assert result is True
        assert agent.is_online is True

    async def test_heartbeat_failure(self):
        from elder_berry.core.tower_agent import TowerAgent

        mock_http = self._mock_http(error=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_http):
            agent = TowerAgent(tower_host="127.0.0.1:12769")
            result = await agent.heartbeat()

        assert result is False
        assert agent.is_online is False

    async def test_tts_success(self):
        from elder_berry.core.tower_agent import TowerAgent

        fake_wav = b"\x00\x01" * 500
        resp = MagicMock()
        resp.status_code = 200
        resp.content = fake_wav
        mock_http = self._mock_http(response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            agent = TowerAgent(tower_host="127.0.0.1:12769")
            result = await agent.tts("Hallo", emotion="neutral")

        assert result == fake_wav
        payload = mock_http.post.call_args.kwargs["json"]
        assert payload["text"] == "Hallo"
        assert payload["emotion"] == "neutral"

    async def test_tts_http_error(self):
        """Tower-TTS bei HTTP-Fehler → TowerAgentError."""
        from elder_berry.core.tower_agent import TowerAgent, TowerAgentError

        mock_http = self._mock_http(
            error=httpx.ConnectError("connection refused"),
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            agent = TowerAgent(tower_host="127.0.0.1:12769")
            with pytest.raises(TowerAgentError):
                await agent.tts("Test")

    async def test_stt_success(self):
        from elder_berry.core.tower_agent import TowerAgent

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"text": "Hallo Welt"}
        mock_http = self._mock_http(response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            agent = TowerAgent(tower_host="127.0.0.1:12769")
            result = await agent.stt(b"\x00" * 100)

        assert result == "Hallo Welt"

    def test_initial_state_offline(self):
        from elder_berry.core.tower_agent import TowerAgent
        agent = TowerAgent(tower_host="127.0.0.1:12769")
        assert agent.is_online is False
        assert agent.host == "127.0.0.1:12769"

    def test_host_strip_trailing_slash(self):
        from elder_berry.core.tower_agent import TowerAgent
        agent = TowerAgent(tower_host="127.0.0.1:12769/")
        assert agent.host == "127.0.0.1:12769"

    async def test_heartbeat_non_200(self):
        """Heartbeat mit Status != 200 → offline."""
        from elder_berry.core.tower_agent import TowerAgent

        resp = MagicMock()
        resp.status_code = 503
        mock_http = self._mock_http(response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            agent = TowerAgent(tower_host="127.0.0.1:12769")
            result = await agent.heartbeat()

        assert result is False
        assert agent.is_online is False

    async def test_tts_without_emotion(self):
        """TTS ohne Emotion → kein emotion-Feld im Payload."""
        from elder_berry.core.tower_agent import TowerAgent

        resp = MagicMock()
        resp.content = b"\x00" * 100
        mock_http = self._mock_http(response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            agent = TowerAgent(tower_host="127.0.0.1:12769")
            await agent.tts("Test")

        payload = mock_http.post.call_args.kwargs["json"]
        assert "emotion" not in payload
