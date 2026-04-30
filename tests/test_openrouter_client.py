"""Tests für OpenRouterClient – is_available, generate, Fehlerbehandlung."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.llm.openrouter_client import (
    OpenRouterClient,
    DEFAULT_MODEL,
    OPENROUTER_URL,
    TIMEOUT,
)


# ---------------------------------------------------------------------------
# Konstruktor / Defaults
# ---------------------------------------------------------------------------


class TestOpenRouterClientInit:
    def test_default_model(self):
        client = OpenRouterClient()
        assert client.model == DEFAULT_MODEL

    def test_custom_model(self):
        client = OpenRouterClient(model="anthropic/claude-3-haiku")
        assert client.model == "anthropic/claude-3-haiku"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
        client = OpenRouterClient()
        assert client._api_key == "or-test-key"

    def test_api_key_none_without_env(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        client = OpenRouterClient()
        client._api_key = None
        assert client._api_key is None

    def test_name_attribute(self):
        assert OpenRouterClient.name == "openrouter"


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestOpenRouterIsAvailable:
    def test_available_with_key(self):
        client = OpenRouterClient()
        client._api_key = "or-key"
        assert client.is_available() is True

    def test_not_available_without_key(self):
        client = OpenRouterClient()
        client._api_key = None
        assert client.is_available() is False

    def test_not_available_empty_key(self):
        client = OpenRouterClient()
        client._api_key = ""
        assert client.is_available() is False


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestOpenRouterGenerate:
    def _mock_post(self, content: str = "Antwort") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}],
        }
        return resp

    def _make_client(self, api_key: str = "or-test-key") -> OpenRouterClient:
        client = OpenRouterClient()
        client._api_key = api_key
        return client

    def test_happy_path(self):
        client = self._make_client()
        with patch("httpx.post", return_value=self._mock_post("Hallo!")) as mock_post:
            result = client.generate("Hi")
        assert result == "Hallo!"
        mock_post.assert_called_once()

    def test_sends_correct_url(self):
        client = self._make_client()
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("test")
        assert mock_post.call_args.args[0] == OPENROUTER_URL

    def test_sends_auth_header(self):
        client = self._make_client("my-secret-key")
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("test")
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer my-secret-key"
        assert headers["Content-Type"] == "application/json"

    def test_with_system_prompt(self):
        client = self._make_client()
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("Frage", system="Du bist Saleria.")
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["messages"]) == 2
        assert payload["messages"][0] == {
            "role": "system",
            "content": "Du bist Saleria.",
        }
        assert payload["messages"][1] == {"role": "user", "content": "Frage"}

    def test_without_system_prompt(self):
        client = self._make_client()
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("Nur Frage")
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    def test_sends_model_in_payload(self):
        client = self._make_client()
        client.model = "google/gemini-2.5-pro"
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("test")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "google/gemini-2.5-pro"

    def test_uses_configured_timeout(self):
        client = self._make_client()
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("test")
        assert mock_post.call_args.kwargs["timeout"] == TIMEOUT

    def test_raises_without_key(self):
        client = OpenRouterClient()
        client._api_key = None
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            client.generate("test")

    def test_http_status_error(self):
        client = self._make_client()
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=resp,
        )
        with patch("httpx.post", return_value=resp):
            with pytest.raises(RuntimeError, match="OpenRouter HTTP-Fehler"):
                client.generate("test")

    def test_connect_error(self):
        client = self._make_client()
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="OpenRouter nicht erreichbar"):
                client.generate("test")

    def test_timeout_error(self):
        client = self._make_client()
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(RuntimeError, match="OpenRouter nicht erreichbar"):
                client.generate("test")
