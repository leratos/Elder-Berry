"""Tests: WolCommandHandler – Wake-on-LAN via Magic Packet."""
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.wol_commands import WolCommandHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def secret_store():
    store = MagicMock()
    store.get.return_value = "AA:BB:CC:DD:EE:FF"
    return store


@pytest.fixture
def handler(secret_store):
    return WolCommandHandler(secret_store=secret_store)


@pytest.fixture
def handler_no_store():
    return WolCommandHandler(secret_store=None)


# ---------------------------------------------------------------------------
# Interface Properties
# ---------------------------------------------------------------------------

class TestWolInterface:
    def test_simple_commands(self, handler):
        assert "wol" in handler.simple_commands

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert any("wol" in d.lower() for d in descs)

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "wol" in kw
        assert len(kw["wol"]) > 0


# ---------------------------------------------------------------------------
# Execute Routing
# ---------------------------------------------------------------------------

class TestWolExecute:
    def test_unknown_command(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False
        assert "Unbekannt" in result.text


# ---------------------------------------------------------------------------
# WoL Command
# ---------------------------------------------------------------------------

class TestWolCommand:
    @patch("elder_berry.comms.commands.wol_commands.socket.socket")
    def test_success(self, mock_sock_cls, handler):
        mock_sock = MagicMock()
        mock_sock_cls.return_value = mock_sock
        result = handler.execute("wol", "wol")
        assert result.success is True
        assert "gesendet" in result.text.lower()
        mock_sock.sendto.assert_called_once()
        # Verify magic packet structure
        packet = mock_sock.sendto.call_args[0][0]
        assert packet[:6] == b"\xff" * 6
        assert len(packet) == 6 + 6 * 16

    def test_no_secret_store(self, handler_no_store):
        result = handler_no_store.execute("wol", "wol")
        assert result.success is False
        assert "SecretStore" in result.text

    def test_mac_not_in_store(self, handler, secret_store):
        secret_store.get.side_effect = KeyError("not found")
        result = handler.execute("wol", "wol")
        assert result.success is False
        assert "tower_mac_address" in result.text

    def test_invalid_mac_length(self, handler, secret_store):
        secret_store.get.return_value = "AA:BB:CC"
        result = handler.execute("wol", "wol")
        assert result.success is False
        assert "Ungültige MAC" in result.text

    def test_invalid_mac_hex(self, handler, secret_store):
        secret_store.get.return_value = "ZZ:XX:GG:HH:II:JJ"
        result = handler.execute("wol", "wol")
        assert result.success is False
        assert "nicht hexadezimal" in result.text

    def test_mac_with_dashes(self, handler, secret_store):
        secret_store.get.return_value = "AA-BB-CC-DD-EE-FF"
        with patch("elder_berry.comms.commands.wol_commands.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock
            result = handler.execute("wol", "wol")
            assert result.success is True

    def test_mac_with_dots(self, handler, secret_store):
        secret_store.get.return_value = "AABB.CCDD.EEFF"
        with patch("elder_berry.comms.commands.wol_commands.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock
            result = handler.execute("wol", "wol")
            assert result.success is True

    @patch("elder_berry.comms.commands.wol_commands.socket.socket")
    def test_socket_error(self, mock_sock_cls, handler):
        mock_sock = MagicMock()
        mock_sock_cls.return_value = mock_sock
        mock_sock.sendto.side_effect = OSError("network down")
        result = handler.execute("wol", "wol")
        assert result.success is False
        assert "❌" in result.text
