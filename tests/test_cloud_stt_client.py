"""Tests: CloudSTTClient – Groq Whisper API."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from elder_berry.tools.cloud_stt_client import CloudSTTClient, CloudSTTError, _guess_mime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_client(**kwargs) -> CloudSTTClient:
    defaults = {"api_key": "groq-test-key"}
    defaults.update(kwargs)
    return CloudSTTClient(**defaults)


def _mock_http_client(post_response=None, post_error=None):
    mock_http = AsyncMock()
    if post_error:
        mock_http.post.side_effect = post_error
    elif post_response:
        mock_http.post.return_value = post_response
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


def _mock_response(status_code=200, json_data=None, raise_error=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "error"
    if json_data is not None:
        resp.json.return_value = json_data
    if raise_error:
        resp.raise_for_status.side_effect = raise_error
    return resp


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_valid_params(self):
        client = _make_client()
        assert client._api_key == "groq-test-key"
        assert client._model == "whisper-large-v3"
        assert client._language == "de"

    def test_custom_model(self):
        client = _make_client(model="whisper-large-v3-turbo")
        assert client._model == "whisper-large-v3-turbo"

    def test_custom_language(self):
        client = _make_client(language="en")
        assert client._language == "en"

    def test_no_language(self):
        client = _make_client(language=None)
        assert client._language is None

    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="API Key"):
            CloudSTTClient(api_key="")


# ---------------------------------------------------------------------------
# transcribe()
# ---------------------------------------------------------------------------

class TestTranscribe:
    @pytest.fixture
    def client(self):
        return _make_client()

    async def test_success(self, client):
        """Erfolgreiche Transkription gibt Text zurück."""
        resp = _mock_response(json_data={"text": "Hallo Welt"})
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.transcribe(b"\x00" * 100)

        assert result == "Hallo Welt"
        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer groq-test-key"

    async def test_empty_audio_raises(self, client):
        with pytest.raises(CloudSTTError, match="leer"):
            await client.transcribe(b"")

    async def test_auth_error(self, client):
        resp = _mock_response(status_code=401)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(CloudSTTError, match="Ungültiger Groq API Key"):
                await client.transcribe(b"\x00" * 100)

    async def test_rate_limit(self, client):
        resp = _mock_response(status_code=429)
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(CloudSTTError, match="Rate Limit"):
                await client.transcribe(b"\x00" * 100)

    async def test_http_error(self, client):
        request = httpx.Request("POST", "http://test")
        raw_resp = httpx.Response(500, request=request)
        resp = _mock_response(
            status_code=500,
            raise_error=httpx.HTTPStatusError(
                "500", request=request, response=raw_resp,
            ),
        )
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(CloudSTTError, match="HTTP 500"):
                await client.transcribe(b"\x00" * 100)

    async def test_timeout(self, client):
        mock_http = _mock_http_client(
            post_error=httpx.TimeoutException("timeout"),
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(CloudSTTError, match="Timeout"):
                await client.transcribe(b"\x00" * 100)

    async def test_network_error(self, client):
        mock_http = _mock_http_client(
            post_error=httpx.ConnectError("refused"),
        )

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(CloudSTTError, match="Netzwerkfehler"):
                await client.transcribe(b"\x00" * 100)

    async def test_language_in_request(self, client):
        """Sprach-Hint wird als Form-Data mitgesendet."""
        resp = _mock_response(json_data={"text": "test"})
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.transcribe(b"\x00" * 100)

        call_kwargs = mock_http.post.call_args.kwargs
        assert call_kwargs["data"]["language"] == "de"
        assert call_kwargs["data"]["model"] == "whisper-large-v3"

    async def test_override_language(self, client):
        """Explizite Sprache überschreibt Default."""
        resp = _mock_response(json_data={"text": "hello"})
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.transcribe(b"\x00" * 100, language="en")

        call_kwargs = mock_http.post.call_args.kwargs
        assert call_kwargs["data"]["language"] == "en"

    async def test_no_language_hint(self):
        """Ohne Sprach-Hint wird kein language-Feld gesendet."""
        client = _make_client(language=None)
        resp = _mock_response(json_data={"text": "test"})
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.transcribe(b"\x00" * 100)

        call_kwargs = mock_http.post.call_args.kwargs
        assert "language" not in call_kwargs["data"]

    async def test_custom_filename(self, client):
        """Custom Filename wird für MIME-Type genutzt."""
        resp = _mock_response(json_data={"text": "test"})
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.transcribe(b"\x00" * 100, filename="recording.mp3")

        files = mock_http.post.call_args.kwargs["files"]
        assert files["file"][0] == "recording.mp3"
        assert files["file"][2] == "audio/mpeg"

    async def test_strips_whitespace(self, client):
        """Ergebnis-Text wird getrimmt."""
        resp = _mock_response(json_data={"text": "  Hallo Welt  "})
        mock_http = _mock_http_client(post_response=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.transcribe(b"\x00" * 100)

        assert result == "Hallo Welt"


# ---------------------------------------------------------------------------
# _guess_mime()
# ---------------------------------------------------------------------------

class TestGuessMime:
    def test_ogg(self):
        assert _guess_mime("audio.ogg") == "audio/ogg"

    def test_mp3(self):
        assert _guess_mime("recording.mp3") == "audio/mpeg"

    def test_wav(self):
        assert _guess_mime("speech.wav") == "audio/wav"

    def test_flac(self):
        assert _guess_mime("audio.flac") == "audio/flac"

    def test_unknown(self):
        assert _guess_mime("file.xyz") == "application/octet-stream"

    def test_no_extension(self):
        assert _guess_mime("audio") == "application/octet-stream"
