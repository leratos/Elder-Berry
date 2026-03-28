"""Tests für OllamaClient – is_available, generate, Fehlerbehandlung."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.llm.ollama_client import OllamaClient, DEFAULT_MODEL, OLLAMA_BASE_URL, TIMEOUT


# ---------------------------------------------------------------------------
# Konstruktor / Defaults
# ---------------------------------------------------------------------------

class TestOllamaClientInit:
    def test_default_values(self):
        client = OllamaClient()
        assert client.model == DEFAULT_MODEL
        assert client.base_url == OLLAMA_BASE_URL.rstrip("/")
        assert client.timeout == TIMEOUT

    def test_custom_model(self):
        client = OllamaClient(model="llama3.2:3b")
        assert client.model == "llama3.2:3b"

    def test_custom_base_url_strips_trailing_slash(self):
        client = OllamaClient(base_url="http://192.168.1.10:11434/")
        assert client.base_url == "http://192.168.1.10:11434"

    def test_custom_timeout(self):
        client = OllamaClient(timeout=30.0)
        assert client.timeout == 30.0

    def test_name_attribute(self):
        assert OllamaClient.name == "ollama"


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

class TestOllamaIsAvailable:
    def test_available_on_200(self):
        client = OllamaClient()
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert client.is_available() is True
            mock_get.assert_called_once_with(
                f"{client.base_url}/api/tags", timeout=3.0,
            )

    def test_not_available_on_non_200(self):
        client = OllamaClient()
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=503)
            assert client.is_available() is False

    def test_not_available_on_connect_error(self):
        client = OllamaClient()
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert client.is_available() is False

    def test_not_available_on_timeout(self):
        client = OllamaClient()
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            assert client.is_available() is False

    def test_uses_custom_base_url(self):
        client = OllamaClient(base_url="http://remote:11434")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            client.is_available()
            mock_get.assert_called_once_with(
                "http://remote:11434/api/tags", timeout=3.0,
            )


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestOllamaGenerate:
    def _mock_post(self, content: str = "Antwort") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"message": {"content": content}}
        return resp

    def test_happy_path(self):
        client = OllamaClient()
        with patch("httpx.post", return_value=self._mock_post("Hallo!")) as mock_post:
            result = client.generate("Hi")
        assert result == "Hallo!"
        mock_post.assert_called_once()

    def test_with_system_prompt(self):
        client = OllamaClient()
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("Frage", system="Du bist Saleria.")
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["messages"]) == 2
        assert payload["messages"][0] == {"role": "system", "content": "Du bist Saleria."}
        assert payload["messages"][1] == {"role": "user", "content": "Frage"}

    def test_without_system_prompt(self):
        client = OllamaClient()
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("Nur Frage")
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    def test_sends_correct_url_and_model(self):
        client = OllamaClient(model="phi4:14b", base_url="http://tower:11434")
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("test")
        assert mock_post.call_args.args[0] == "http://tower:11434/api/chat"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "phi4:14b"
        assert payload["stream"] is False

    def test_uses_configured_timeout(self):
        client = OllamaClient(timeout=42.0)
        with patch("httpx.post", return_value=self._mock_post()) as mock_post:
            client.generate("test")
        assert mock_post.call_args.kwargs["timeout"] == 42.0

    def test_http_status_error(self):
        client = OllamaClient()
        resp = MagicMock()
        resp.status_code = 500
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=resp,
        )
        with patch("httpx.post", return_value=resp):
            with pytest.raises(RuntimeError, match="Ollama HTTP-Fehler"):
                client.generate("test")

    def test_connect_error(self):
        client = OllamaClient()
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Ollama nicht erreichbar"):
                client.generate("test")

    def test_timeout_error(self):
        client = OllamaClient()
        with patch("httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(RuntimeError, match="Ollama nicht erreichbar"):
                client.generate("test")
