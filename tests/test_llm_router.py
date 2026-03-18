"""Tests für LLMRouter – Anthropic/Ollama Routing-Logik."""
import importlib
from unittest.mock import MagicMock, patch

import pytest

_anthropic_installed = importlib.util.find_spec("anthropic") is not None
requires_anthropic = pytest.mark.skipif(
    not _anthropic_installed, reason="anthropic-Paket nicht installiert"
)

from elder_berry.llm.base import LLMClient
from elder_berry.llm.anthropic_client import AnthropicClient, ComputerUseAction
from elder_berry.llm.ollama_client import OllamaClient
from elder_berry.llm.openrouter_client import OpenRouterClient
from elder_berry.llm.router import LLMRouter


# ---------------------------------------------------------------------------
# Hilfsfunktion: Mock-LLMClients erzeugen
# ---------------------------------------------------------------------------

def make_mock_client(available: bool = True, response: str = "ok", name: str = "mock") -> MagicMock:
    mock = MagicMock(spec=LLMClient)
    mock.is_available.return_value = available
    mock.generate.return_value = response
    # name als Attribut setzen (nicht über MagicMock-name-Parameter – der ist reserviert)
    type(mock).name = MagicMock(return_value=name)
    mock.configure_mock(**{"name": name})
    return mock


# ---------------------------------------------------------------------------
# AnthropicClient
# ---------------------------------------------------------------------------

class TestAnthropicClient:
    def test_is_available_with_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()
        assert client.is_available() is True

    def test_is_not_available_without_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = AnthropicClient()
        client._api_key = None
        assert client.is_available() is False

    def test_generate_raises_without_key(self):
        client = AnthropicClient()
        client._api_key = None
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            client.generate("test")

    @requires_anthropic
    def test_generate_returns_content(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Hallo von Sonnet!")]

        mock_sdk_client = MagicMock()
        mock_sdk_client.messages.create.return_value = mock_message
        client._client = mock_sdk_client

        result = client.generate("Hallo")
        assert result == "Hallo von Sonnet!"

    @requires_anthropic
    def test_generate_includes_system_prompt(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="ok")]
        mock_sdk_client = MagicMock()
        mock_sdk_client.messages.create.return_value = mock_message
        client._client = mock_sdk_client

        client.generate("Prompt", system="Du bist Saleria.")
        call_kwargs = mock_sdk_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Du bist Saleria."
        assert call_kwargs["messages"][0]["content"] == "Prompt"

    @requires_anthropic
    def test_generate_no_system_omits_system_param(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="ok")]
        mock_sdk_client = MagicMock()
        mock_sdk_client.messages.create.return_value = mock_message
        client._client = mock_sdk_client

        client.generate("Prompt ohne System")
        call_kwargs = mock_sdk_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    def test_name_attribute(self):
        assert AnthropicClient.name == "anthropic"

    @requires_anthropic
    def test_api_status_error_raises_runtime(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        import anthropic
        client = AnthropicClient()
        mock_sdk_client = MagicMock()
        mock_sdk_client.messages.create.side_effect = anthropic.APIStatusError(
            "error", response=MagicMock(status_code=429), body={}
        )
        client._client = mock_sdk_client
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.generate("test")


# ---------------------------------------------------------------------------
# ComputerUseAction DTO
# ---------------------------------------------------------------------------

class TestComputerUseAction:
    def test_frozen_dataclass(self):
        action = ComputerUseAction(action="left_click", coordinate=(500, 300))
        assert action.action == "left_click"
        assert action.coordinate == (500, 300)
        with pytest.raises(AttributeError):
            action.action = "type"  # type: ignore[misc]

    def test_defaults(self):
        action = ComputerUseAction(action="screenshot")
        assert action.coordinate is None
        assert action.text is None
        assert action.scroll_direction is None
        assert action.scroll_amount is None
        assert action.tool_use_id == ""

    def test_scroll_fields(self):
        action = ComputerUseAction(
            action="scroll",
            coordinate=(400, 300),
            scroll_direction="down",
            scroll_amount=3,
        )
        assert action.scroll_direction == "down"
        assert action.scroll_amount == 3

    def test_type_action_with_text(self):
        action = ComputerUseAction(action="type", text="Hallo Welt!")
        assert action.text == "Hallo Welt!"


# ---------------------------------------------------------------------------
# AnthropicClient.computer_use()
# ---------------------------------------------------------------------------

class TestAnthropicComputerUse:
    def test_computer_use_raises_without_key(self):
        client = AnthropicClient()
        client._api_key = None
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            client.computer_use("base64data", "klick auf OK", 1024, 768)

    @requires_anthropic
    def test_computer_use_click(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "computer"
        tool_block.id = "toolu_123"
        tool_block.input = {
            "action": "left_click",
            "coordinate": [500, 300],
        }

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        mock_sdk_client = MagicMock()
        mock_sdk_client.beta.messages.create.return_value = mock_response
        client._client = mock_sdk_client

        result = client.computer_use("base64png", "Klick auf den Button", 1920, 1080)

        assert isinstance(result, ComputerUseAction)
        assert result.action == "left_click"
        assert result.coordinate == (500, 300)
        assert result.tool_use_id == "toolu_123"

    @requires_anthropic
    def test_computer_use_type(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "computer"
        tool_block.id = "toolu_456"
        tool_block.input = {"action": "type", "text": "Hello World"}

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        mock_sdk_client = MagicMock()
        mock_sdk_client.beta.messages.create.return_value = mock_response
        client._client = mock_sdk_client

        result = client.computer_use("base64png", "Tippe Hello World", 1920, 1080)

        assert result.action == "type"
        assert result.text == "Hello World"
        assert result.coordinate is None

    @requires_anthropic
    def test_computer_use_scroll(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "computer"
        tool_block.id = "toolu_789"
        tool_block.input = {
            "action": "scroll",
            "coordinate": [400, 500],
            "scroll_direction": "down",
            "scroll_amount": 5,
        }

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        mock_sdk_client = MagicMock()
        mock_sdk_client.beta.messages.create.return_value = mock_response
        client._client = mock_sdk_client

        result = client.computer_use("base64png", "Scroll runter", 1920, 1080)

        assert result.action == "scroll"
        assert result.scroll_direction == "down"
        assert result.scroll_amount == 5

    @requires_anthropic
    def test_computer_use_no_tool_use_raises(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Ich kann das Element nicht finden."

        mock_response = MagicMock()
        mock_response.content = [text_block]

        mock_sdk_client = MagicMock()
        mock_sdk_client.beta.messages.create.return_value = mock_response
        client._client = mock_sdk_client

        with pytest.raises(RuntimeError, match="Keine Aktion"):
            client.computer_use("base64png", "Klick auf XYZ", 1920, 1080)

    @requires_anthropic
    def test_computer_use_sends_correct_params(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "computer"
        tool_block.id = "toolu_abc"
        tool_block.input = {"action": "screenshot"}

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        mock_sdk_client = MagicMock()
        mock_sdk_client.beta.messages.create.return_value = mock_response
        client._client = mock_sdk_client

        client.computer_use(
            "base64png", "Mach einen Screenshot", 1280, 720, system="Du bist Saleria."
        )

        call_kwargs = mock_sdk_client.beta.messages.create.call_args.kwargs
        assert call_kwargs["betas"] == ["computer-use-2025-11-24"]
        assert call_kwargs["system"] == "Du bist Saleria."
        assert call_kwargs["max_tokens"] == 1024

        tools = call_kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "computer_20251124"
        assert tools[0]["display_width_px"] == 1280
        assert tools[0]["display_height_px"] == 720

        messages = call_kwargs["messages"]
        user_content = messages[0]["content"]
        assert user_content[0]["type"] == "image"
        assert user_content[0]["source"]["data"] == "base64png"
        assert user_content[1]["type"] == "text"
        assert user_content[1]["text"] == "Mach einen Screenshot"

    @requires_anthropic
    def test_computer_use_key_action(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client = AnthropicClient()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "computer"
        tool_block.id = "toolu_key"
        tool_block.input = {"action": "key", "text": "ctrl+s"}

        mock_response = MagicMock()
        mock_response.content = [tool_block]

        mock_sdk_client = MagicMock()
        mock_sdk_client.beta.messages.create.return_value = mock_response
        client._client = mock_sdk_client

        result = client.computer_use("base64png", "Drück Strg+S", 1920, 1080)

        assert result.action == "key"
        assert result.text == "ctrl+s"


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

    def test_name_attribute(self):
        assert OllamaClient.name == "ollama"


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

    def test_name_attribute(self):
        assert OpenRouterClient.name == "openrouter"


# ---------------------------------------------------------------------------
# LLMRouter – neue primary/fallback Signatur
# ---------------------------------------------------------------------------

class TestLLMRouter:
    def test_prefers_primary_when_available(self):
        primary = make_mock_client(available=True, response="Anthropic-Antwort", name="anthropic")
        fallback = make_mock_client(available=True, response="Ollama-Antwort", name="ollama")
        router = LLMRouter(primary=primary, fallback=fallback)
        assert router.generate("test") == "Anthropic-Antwort"
        fallback.generate.assert_not_called()

    def test_falls_back_to_fallback(self):
        primary = make_mock_client(available=False, name="anthropic")
        fallback = make_mock_client(available=True, response="Ollama-Antwort", name="ollama")
        router = LLMRouter(primary=primary, fallback=fallback)
        assert router.generate("test") == "Ollama-Antwort"

    def test_raises_when_neither_available(self):
        router = LLMRouter(
            primary=make_mock_client(available=False),
            fallback=make_mock_client(available=False),
        )
        with pytest.raises(RuntimeError, match="Kein LLM-Backend"):
            router.generate("test")

    def test_active_backend_primary(self):
        primary = make_mock_client(available=True, name="anthropic")
        fallback = make_mock_client(available=True, name="ollama")
        router = LLMRouter(primary=primary, fallback=fallback)
        assert router.active_backend == "anthropic"

    def test_active_backend_fallback(self):
        primary = make_mock_client(available=False, name="anthropic")
        fallback = make_mock_client(available=True, name="ollama")
        router = LLMRouter(primary=primary, fallback=fallback)
        assert router.active_backend == "ollama"

    def test_active_backend_none(self):
        router = LLMRouter(
            primary=make_mock_client(available=False),
            fallback=make_mock_client(available=False),
        )
        assert router.active_backend == "none"

    def test_is_available_true_if_one_works(self):
        router = LLMRouter(
            primary=make_mock_client(available=False),
            fallback=make_mock_client(available=True),
        )
        assert router.is_available() is True

    def test_is_available_false_if_none_works(self):
        router = LLMRouter(
            primary=make_mock_client(available=False),
            fallback=make_mock_client(available=False),
        )
        assert router.is_available() is False

    def test_create_default_returns_router_instance(self):
        router = LLMRouter.create_default()
        assert isinstance(router, LLMRouter)

    def test_create_default_primary_is_anthropic(self):
        router = LLMRouter.create_default()
        assert isinstance(router._primary, AnthropicClient)

    def test_create_default_fallback_is_ollama(self):
        router = LLMRouter.create_default()
        assert isinstance(router._fallback, OllamaClient)

    def test_create_default_custom_models(self):
        router = LLMRouter.create_default(
            primary_model="claude-opus-4-6",
            fallback_model="llama3.2:3b",
        )
        assert router._primary.model == "claude-opus-4-6"
        assert router._fallback.model == "llama3.2:3b"
