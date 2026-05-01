"""Tests: ElevenLabsClient – ElevenLabs TTS API."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from elder_berry.tools.elevenlabs_client import ElevenLabsClient, ElevenLabsError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_client(**kwargs) -> ElevenLabsClient:
    defaults = {"api_key": "test-key", "voice_id": "voice-123"}
    defaults.update(kwargs)
    return ElevenLabsClient(**defaults)


def _mock_http_client(
    post_response=None, get_response=None, post_error=None, get_error=None
):
    """Erstellt einen gepatchten httpx.AsyncClient context manager."""
    mock_http = AsyncMock()
    if post_error:
        mock_http.post.side_effect = post_error
    elif post_response:
        mock_http.post.return_value = post_response
    if get_error:
        mock_http.get.side_effect = get_error
    elif get_response:
        mock_http.get.return_value = get_response
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


def _mock_response(
    status_code=200, content=b"", json_data=None, raise_for_status_error=None
):
    """Erstellt ein Mock-httpx-Response (sync-Methoden als MagicMock)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = (
        content.decode("utf-8", errors="replace")
        if isinstance(content, bytes)
        else str(content)
    )
    if json_data is not None:
        resp.json.return_value = json_data
    if raise_for_status_error:
        resp.raise_for_status.side_effect = raise_for_status_error
    return resp


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_valid_params(self):
        client = _make_client()
        assert client._api_key == "test-key"
        assert client._voice_id == "voice-123"
        assert client._model == "eleven_multilingual_v2"

    def test_custom_model(self):
        client = _make_client(model="eleven_flash_v2_5")
        assert client._model == "eleven_flash_v2_5"

    def test_custom_voice_settings(self):
        client = _make_client(stability=0.8, similarity_boost=0.3)
        assert client._stability == 0.8
        assert client._similarity_boost == 0.3

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="API Key"):
            ElevenLabsClient(api_key="", voice_id="v1")

    def test_empty_voice_id_raises(self):
        with pytest.raises(ValueError, match="Voice ID"):
            ElevenLabsClient(api_key="key", voice_id="")


# ---------------------------------------------------------------------------
# synthesize()
# ---------------------------------------------------------------------------


class TestSynthesize:
    @pytest.fixture
    def client(self):
        return _make_client()

    async def test_success(self, client):
        """Erfolgreiche Synthese gibt MP3-Bytes zurück."""
        fake_mp3 = b"\xff\xfb\x90\x00" + b"\x00" * 200
        resp = _mock_response(status_code=200, content=fake_mp3)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.synthesize("Hallo Welt")

        assert result == fake_mp3
        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args
        assert "voice-123" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"]["text"] == "Hallo Welt"
        assert call_kwargs.kwargs["headers"]["xi-api-key"] == "test-key"

    async def test_empty_text_raises(self, client):
        with pytest.raises(ElevenLabsError, match="leer"):
            await client.synthesize("")

    async def test_whitespace_only_raises(self, client):
        with pytest.raises(ElevenLabsError, match="leer"):
            await client.synthesize("   ")

    async def test_auth_error(self, client):
        """401 → spezifische Fehlermeldung."""
        resp = _mock_response(status_code=401)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="Ungültiger API Key"):
                await client.synthesize("Test")

    async def test_rate_limit(self, client):
        """429 → Rate Limit / Credits-Meldung."""
        resp = _mock_response(status_code=429)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="Rate Limit"):
                await client.synthesize("Test")

    async def test_http_error(self, client):
        """Sonstige HTTP-Fehler → ElevenLabsError."""
        request = httpx.Request("POST", "http://test")
        raw_resp = httpx.Response(
            500, request=request, content=b"Internal Server Error"
        )
        resp = _mock_response(
            status_code=500,
            content=b"\x00" * 200,
            raise_for_status_error=httpx.HTTPStatusError(
                "500",
                request=request,
                response=raw_resp,
            ),
        )
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="HTTP 500"):
                await client.synthesize("Test")

    async def test_timeout(self, client):
        """Timeout → ElevenLabsError."""
        mock_http = _mock_http_client(
            post_error=httpx.TimeoutException("connect timeout"),
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="Timeout"):
                await client.synthesize("Test")

    async def test_too_small_response(self, client):
        """Antwort <100 bytes → Fehler."""
        resp = _mock_response(status_code=200, content=b"\x00" * 50)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="zu wenig Daten"):
                await client.synthesize("Test")

    async def test_network_error(self, client):
        """Netzwerkfehler → ElevenLabsError."""
        mock_http = _mock_http_client(
            post_error=httpx.ConnectError("connection refused"),
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="Netzwerkfehler"):
                await client.synthesize("Test")

    async def test_payload_contains_model_and_settings(self, client):
        """Payload enthält model_id und voice_settings."""
        resp = _mock_response(status_code=200, content=b"\xff" * 200)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.synthesize("Test")

        payload = mock_http.post.call_args.kwargs["json"]
        assert payload["model_id"] == "eleven_multilingual_v2"
        assert payload["voice_settings"]["stability"] == 0.5
        assert payload["voice_settings"]["similarity_boost"] == 0.75


# ---------------------------------------------------------------------------
# get_usage()
# ---------------------------------------------------------------------------


class TestGetUsage:
    async def test_success(self):
        client = _make_client()
        usage_data = {"character_count": 5000, "character_limit": 100000}
        resp = _mock_response(status_code=200, json_data=usage_data)
        mock_http = _mock_http_client(get_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.get_usage()

        assert result["character_count"] == 5000
        assert result["character_limit"] == 100000

    async def test_error(self):
        client = _make_client()
        mock_http = _mock_http_client(
            get_error=httpx.ConnectError("refused"),
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ElevenLabsError, match="Usage-Abfrage"):
                await client.get_usage()
