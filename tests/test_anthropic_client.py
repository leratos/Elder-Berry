"""Tests für AnthropicClient – generate, describe_image, computer_use, Fehlerbehandlung."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

_anthropic_installed = importlib.util.find_spec("anthropic") is not None
requires_anthropic = pytest.mark.skipif(
    not _anthropic_installed, reason="anthropic-Paket nicht installiert"
)

from elder_berry.llm.anthropic_client import AnthropicClient, ComputerUseAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(api_key: str = "sk-ant-test") -> AnthropicClient:
    """Erstellt einen AnthropicClient mit gesetztem Key."""
    client = AnthropicClient()
    client._api_key = api_key
    return client


def _inject_sdk_mock(client: AnthropicClient) -> MagicMock:
    """Setzt einen Mock-SDK-Client und gibt ihn zurück."""
    sdk = MagicMock()
    client._client = sdk
    return sdk


def _make_message_response(text: str = "Antwort") -> MagicMock:
    """Erstellt eine Mock-Messages-API-Antwort."""
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def _make_tool_use_block(
    action: str,
    coordinate: list[int] | None = None,
    text: str | None = None,
    scroll_direction: str | None = None,
    scroll_amount: int | None = None,
    block_id: str = "toolu_test",
) -> MagicMock:
    """Erstellt einen tool_use-Block für Computer-Use-Antworten."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "computer"
    block.id = block_id
    inp = {"action": action}
    if coordinate is not None:
        inp["coordinate"] = coordinate
    if text is not None:
        inp["text"] = text
    if scroll_direction is not None:
        inp["scroll_direction"] = scroll_direction
    if scroll_amount is not None:
        inp["scroll_amount"] = scroll_amount
    block.input = inp
    return block


# ---------------------------------------------------------------------------
# Konstruktor & Verfügbarkeit
# ---------------------------------------------------------------------------

class TestAnthropicClientInit:
    def test_default_model(self):
        client = AnthropicClient()
        assert client.model == "claude-sonnet-4-6"

    def test_custom_model(self):
        client = AnthropicClient(model="claude-opus-4-6")
        assert client.model == "claude-opus-4-6"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        client = AnthropicClient()
        assert client._api_key == "sk-from-env"

    def test_api_key_none_without_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = AnthropicClient()
        client._api_key = None  # sicherstellen
        assert client._api_key is None

    def test_client_initially_none(self):
        client = AnthropicClient()
        assert client._client is None

    def test_name_attribute(self):
        assert AnthropicClient.name == "anthropic"


class TestAnthropicAvailability:
    def test_is_available_with_key(self):
        client = _make_client("sk-ant-key")
        assert client.is_available() is True

    def test_is_not_available_without_key(self):
        client = _make_client()
        client._api_key = None
        assert client.is_available() is False

    def test_is_not_available_empty_key(self):
        client = _make_client()
        client._api_key = ""
        assert client.is_available() is False


# ---------------------------------------------------------------------------
# _get_client / _check_available
# ---------------------------------------------------------------------------

class TestAnthropicInternals:
    @requires_anthropic
    def test_get_client_lazy_init(self):
        client = _make_client()
        assert client._client is None
        sdk = client._get_client()
        assert sdk is not None
        # Zweiter Aufruf liefert selbes Objekt
        assert client._get_client() is sdk

    def test_get_client_raises_without_package(self):
        client = _make_client()
        with patch("elder_berry.llm.anthropic_client._ANTHROPIC_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="nicht installiert"):
                client._get_client()

    def test_check_available_raises_without_key(self):
        client = _make_client()
        client._api_key = None
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            client._check_available()

    def test_check_available_raises_without_package(self):
        client = _make_client()
        with patch("elder_berry.llm.anthropic_client._ANTHROPIC_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="nicht installiert"):
                client._check_available()

    @requires_anthropic
    def test_check_available_passes_with_key_and_package(self):
        client = _make_client()
        # Darf keine Exception werfen
        client._check_available()


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestAnthropicGenerate:
    @requires_anthropic
    def test_happy_path(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("Hallo!")

        result = client.generate("Hi")
        assert result == "Hallo!"
        sdk.messages.create.assert_called_once()

    @requires_anthropic
    def test_with_system_prompt(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.generate("Frage", system="Du bist Saleria.")
        kwargs = sdk.messages.create.call_args.kwargs
        assert kwargs["system"] == "Du bist Saleria."
        assert kwargs["messages"][0]["role"] == "user"
        assert kwargs["messages"][0]["content"] == "Frage"

    @requires_anthropic
    def test_without_system_prompt(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.generate("Prompt only")
        kwargs = sdk.messages.create.call_args.kwargs
        assert "system" not in kwargs

    @requires_anthropic
    def test_max_tokens_default(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.generate("test")
        kwargs = sdk.messages.create.call_args.kwargs
        assert kwargs["max_tokens"] == 2048

    @requires_anthropic
    def test_uses_configured_model(self):
        client = _make_client()
        client.model = "claude-opus-4-6"
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.generate("test")
        kwargs = sdk.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4-6"

    def test_raises_without_key(self):
        client = _make_client()
        client._api_key = None
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            client.generate("test")

    @requires_anthropic
    def test_api_status_error(self):
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.side_effect = anthropic.APIStatusError(
            "error", response=MagicMock(status_code=500), body={},
        )
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.generate("test")

    @requires_anthropic
    def test_api_connection_error(self):
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.side_effect = anthropic.APIConnectionError(
            request=MagicMock(),
        )
        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            client.generate("test")

    @requires_anthropic
    def test_rate_limit_error(self):
        """RateLimitError ist Subklasse von APIStatusError → wird dort gefangen."""
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=MagicMock(status_code=429), body={},
        )
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.generate("test")


# ---------------------------------------------------------------------------
# describe_image()
# ---------------------------------------------------------------------------

class TestAnthropicDescribeImage:
    @requires_anthropic
    def test_happy_path(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("Ein Hund auf einer Wiese.")

        result = client.describe_image("base64data", prompt="Was siehst du?")
        assert result == "Ein Hund auf einer Wiese."
        sdk.messages.create.assert_called_once()

    @requires_anthropic
    def test_sends_correct_payload(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.describe_image(
            "imgdata", prompt="Beschreibe!", system="Sei präzise.",
            media_type="image/png",
        )
        kwargs = sdk.messages.create.call_args.kwargs
        assert kwargs["system"] == "Sei präzise."
        assert kwargs["max_tokens"] == 1024
        messages = kwargs["messages"]
        assert len(messages) == 1
        content = messages[0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[0]["source"]["data"] == "imgdata"
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "Beschreibe!"

    @requires_anthropic
    def test_without_system(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.describe_image("imgdata")
        kwargs = sdk.messages.create.call_args.kwargs
        assert "system" not in kwargs

    @requires_anthropic
    def test_default_media_type(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.return_value = _make_message_response("ok")

        client.describe_image("imgdata")
        kwargs = sdk.messages.create.call_args.kwargs
        content = kwargs["messages"][0]["content"]
        assert content[0]["source"]["media_type"] == "image/jpeg"

    def test_raises_without_key(self):
        client = _make_client()
        client._api_key = None
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            client.describe_image("imgdata")

    @requires_anthropic
    def test_api_status_error(self):
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.side_effect = anthropic.APIStatusError(
            "error", response=MagicMock(status_code=400), body={},
        )
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.describe_image("imgdata")

    @requires_anthropic
    def test_connection_error(self):
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.side_effect = anthropic.APIConnectionError(
            request=MagicMock(),
        )
        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            client.describe_image("imgdata")

    @requires_anthropic
    def test_rate_limit_error(self):
        """RateLimitError ist Subklasse von APIStatusError → wird dort gefangen."""
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=MagicMock(status_code=429), body={},
        )
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.describe_image("imgdata")


# ---------------------------------------------------------------------------
# computer_use()
# ---------------------------------------------------------------------------

class TestAnthropicComputerUse:
    @requires_anthropic
    def test_click_action(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        block = _make_tool_use_block("left_click", coordinate=[500, 300])
        resp = MagicMock()
        resp.content = [block]
        sdk.beta.messages.create.return_value = resp

        result = client.computer_use("b64", "Klick", 1920, 1080)
        assert isinstance(result, ComputerUseAction)
        assert result.action == "left_click"
        assert result.coordinate == (500, 300)

    @requires_anthropic
    def test_type_action(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        block = _make_tool_use_block("type", text="Hello")
        resp = MagicMock()
        resp.content = [block]
        sdk.beta.messages.create.return_value = resp

        result = client.computer_use("b64", "Tippe Hello", 1920, 1080)
        assert result.action == "type"
        assert result.text == "Hello"
        assert result.coordinate is None

    @requires_anthropic
    def test_scroll_action(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        block = _make_tool_use_block(
            "scroll", coordinate=[400, 500],
            scroll_direction="down", scroll_amount=3,
        )
        resp = MagicMock()
        resp.content = [block]
        sdk.beta.messages.create.return_value = resp

        result = client.computer_use("b64", "Scroll", 1920, 1080)
        assert result.scroll_direction == "down"
        assert result.scroll_amount == 3

    @requires_anthropic
    def test_sends_beta_header_and_tools(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        block = _make_tool_use_block("screenshot")
        resp = MagicMock()
        resp.content = [block]
        sdk.beta.messages.create.return_value = resp

        client.computer_use("b64", "Screenshot", 1280, 720, system="Sys")
        kwargs = sdk.beta.messages.create.call_args.kwargs
        assert kwargs["betas"] == ["computer-use-2025-11-24"]
        assert kwargs["system"] == "Sys"
        tools = kwargs["tools"]
        assert tools[0]["type"] == "computer_20251124"
        assert tools[0]["display_width_px"] == 1280
        assert tools[0]["display_height_px"] == 720

    @requires_anthropic
    def test_without_system(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        block = _make_tool_use_block("screenshot")
        resp = MagicMock()
        resp.content = [block]
        sdk.beta.messages.create.return_value = resp

        client.computer_use("b64", "Screenshot", 1920, 1080)
        kwargs = sdk.beta.messages.create.call_args.kwargs
        assert "system" not in kwargs

    @requires_anthropic
    def test_no_tool_use_raises(self):
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Kann nicht."
        resp = MagicMock()
        resp.content = [text_block]
        sdk.beta.messages.create.return_value = resp

        with pytest.raises(RuntimeError, match="Keine Aktion"):
            client.computer_use("b64", "Klick", 1920, 1080)

    def test_raises_without_key(self):
        client = _make_client()
        client._api_key = None
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            client.computer_use("b64", "Klick", 1920, 1080)

    @requires_anthropic
    def test_api_status_error(self):
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.beta.messages.create.side_effect = anthropic.APIStatusError(
            "error", response=MagicMock(status_code=500), body={},
        )
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.computer_use("b64", "Klick", 1920, 1080)

    @requires_anthropic
    def test_connection_error(self):
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.beta.messages.create.side_effect = anthropic.APIConnectionError(
            request=MagicMock(),
        )
        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            client.computer_use("b64", "Klick", 1920, 1080)

    @requires_anthropic
    def test_rate_limit_error(self):
        """RateLimitError ist Subklasse von APIStatusError → wird dort gefangen."""
        import anthropic
        client = _make_client()
        sdk = _inject_sdk_mock(client)
        sdk.beta.messages.create.side_effect = anthropic.RateLimitError(
            "rate limited", response=MagicMock(status_code=429), body={},
        )
        with pytest.raises(RuntimeError, match="Anthropic API-Fehler"):
            client.computer_use("b64", "Klick", 1920, 1080)


# ---------------------------------------------------------------------------
# _parse_computer_use_response – statische Methode
# ---------------------------------------------------------------------------

class TestParseComputerUseResponse:
    def test_extracts_click(self):
        block = _make_tool_use_block("left_click", coordinate=[100, 200], block_id="id1")
        resp = MagicMock()
        resp.content = [block]

        result = AnthropicClient._parse_computer_use_response(resp)
        assert result.action == "left_click"
        assert result.coordinate == (100, 200)
        assert result.tool_use_id == "id1"

    def test_extracts_type_with_text(self):
        block = _make_tool_use_block("type", text="foobar", block_id="id2")
        resp = MagicMock()
        resp.content = [block]

        result = AnthropicClient._parse_computer_use_response(resp)
        assert result.action == "type"
        assert result.text == "foobar"

    def test_no_coordinate_returns_none(self):
        block = _make_tool_use_block("key", text="ctrl+c")
        resp = MagicMock()
        resp.content = [block]

        result = AnthropicClient._parse_computer_use_response(resp)
        assert result.coordinate is None

    def test_text_only_response_raises(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Ich verstehe nicht."
        resp = MagicMock()
        resp.content = [text_block]

        with pytest.raises(RuntimeError, match="Keine Aktion"):
            AnthropicClient._parse_computer_use_response(resp)

    def test_mixed_content_picks_tool_use(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Ich klicke jetzt."
        tool_block = _make_tool_use_block("left_click", coordinate=[42, 84])
        resp = MagicMock()
        resp.content = [text_block, tool_block]

        result = AnthropicClient._parse_computer_use_response(resp)
        assert result.action == "left_click"

    def test_empty_content_raises(self):
        resp = MagicMock()
        resp.content = []
        with pytest.raises(RuntimeError, match="Keine Aktion"):
            AnthropicClient._parse_computer_use_response(resp)

    def test_non_computer_tool_use_ignored(self):
        block = MagicMock(spec=[])  # spec=[] → kein implizites text-Attribut
        block.type = "tool_use"
        block.name = "bash"  # nicht "computer"
        block.input = {"action": "run"}
        resp = MagicMock()
        resp.content = [block]

        with pytest.raises(RuntimeError, match="Keine Aktion"):
            AnthropicClient._parse_computer_use_response(resp)
