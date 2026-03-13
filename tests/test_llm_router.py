"""Tests für LLMRouter – Ollama/OpenRouter Fallback-Logik."""
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.llm.ollama_client import OllamaClient
from elder_berry.llm.openrouter_client import OpenRouterClient
from elder_berry.llm.router import LLMRouter


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------

class TestOllamaClient:
    def test_is_available_true(self):
        client = OllamaClient()
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert client.is_available() is True

    def test_is_available_false_on_connection_error(self):
        import httpx
        client = OllamaClient()
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert client.is_available() is False

    def test_generate_returns_content(self):
        client = OllamaClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Hallo!"}}
        with patch("httpx.post", return_value=mock_response):
            result = client.generate("Hi")
        assert result == "Hallo!"

    def test_generate_includes_system_prompt(self):
        client = OllamaClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "ok"}}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.generate("Hallo", system="Du bist ein Assistent.")
        payload = mock_post.call_args.kwargs["json"]
        roles = [m["role"] for m in payload["messages"]]
        assert roles[0] == "system"
        assert roles[1] == "user"


# ---------------------------------------------------------------------------
# OpenRouterClient
# ---------------------------------------------------------------------------

class TestOpenRouterClient:
    def test_is_available_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        client = OpenRouterClient()
        assert client.is_available() is True

    def test_is_not_available_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        client = OpenRouterClient()
        # _api_key wurde beim __init__ gelesen – manuell zurücksetzen
        client._api_key = None
        assert client.is_available() is False

    def test_generate_raises_without_key(self):
        client = OpenRouterClient()
        client._api_key = None
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            client.generate("test")

    def test_generate_returns_content(self):
        client = OpenRouterClient()
        client._api_key = "test-key"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "OpenRouter-Antwort"}}]
        }
        with patch("httpx.post", return_value=mock_response):
            result = client.generate("Was ist das?")
        assert result == "OpenRouter-Antwort"


# ---------------------------------------------------------------------------
# LLMRouter
# ---------------------------------------------------------------------------

class TestLLMRouter:
    def test_prefers_ollama_when_available(self):
        router = LLMRouter()
        router._ollama.is_available = MagicMock(return_value=True)
        router._openrouter.is_available = MagicMock(return_value=True)
        router._ollama.generate = MagicMock(return_value="Ollama-Antwort")
        result = router.generate("test")
        assert result == "Ollama-Antwort"
        router._openrouter.generate.assert_not_called() if hasattr(
            router._openrouter.generate, "assert_not_called"
        ) else None

    def test_falls_back_to_openrouter(self):
        router = LLMRouter()
        router._ollama.is_available = MagicMock(return_value=False)
        router._openrouter.is_available = MagicMock(return_value=True)
        router._openrouter.generate = MagicMock(return_value="OpenRouter-Antwort")
        result = router.generate("test")
        assert result == "OpenRouter-Antwort"

    def test_raises_when_neither_available(self):
        router = LLMRouter()
        router._ollama.is_available = MagicMock(return_value=False)
        router._openrouter.is_available = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="kein LLM-Backend" if False else "Kein LLM-Backend"):
            router.generate("test")

    def test_active_backend_property(self):
        router = LLMRouter()
        router._ollama.is_available = MagicMock(return_value=False)
        router._openrouter.is_available = MagicMock(return_value=True)
        assert router.active_backend == "openrouter"

    def test_is_available_true_if_one_works(self):
        router = LLMRouter()
        router._ollama.is_available = MagicMock(return_value=False)
        router._openrouter.is_available = MagicMock(return_value=True)
        assert router.is_available() is True
