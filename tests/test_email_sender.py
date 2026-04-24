"""Tests für EmailSender (SMTP-Client)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.email_sender import EmailSender


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sender() -> EmailSender:
    return EmailSender(
        host="smtp.example.com",
        user="test@example.com",
        password="secret",
        port=465,
        use_ssl=True,
        sender_name="TestBot",
    )


@pytest.fixture
def mock_secret_store() -> MagicMock:
    store = MagicMock()
    store.get.side_effect = lambda key: {
        "email_user": "user@strato.de",
        "email_password": "pass123",
    }[key]
    store.get_or_none.side_effect = lambda key: {
        "email_smtp_host": None,
        "email_smtp_port": None,
    }.get(key)
    return store


# ---------------------------------------------------------------------------
# from_secret_store
# ---------------------------------------------------------------------------

class TestFromSecretStore:
    def test_defaults(self, mock_secret_store):
        s = EmailSender.from_secret_store(mock_secret_store)
        assert s._host == "smtp.strato.de"
        assert s._port == 465
        assert s._user == "user@strato.de"

    def test_custom_host_port(self):
        store = MagicMock()
        store.get.side_effect = lambda key: {
            "email_user": "me@gmail.com",
            "email_password": "pw",
        }[key]
        store.get_or_none.side_effect = lambda key: {
            "email_smtp_host": "smtp.gmail.com",
            "email_smtp_port": "587",
        }.get(key)
        s = EmailSender.from_secret_store(store)
        assert s._host == "smtp.gmail.com"
        assert s._port == 587


# ---------------------------------------------------------------------------
# _build_reply_message
# ---------------------------------------------------------------------------

class TestBuildReplyMessage:
    def test_headers(self, sender):
        msg = sender._build_reply_message(
            to="recipient@example.com",
            subject="Re: Test",
            body="Danke!",
            in_reply_to="<abc@mx.com>",
            references="<abc@mx.com>",
            cc="",
        )
        assert msg["To"] == "recipient@example.com"
        assert msg["Subject"] == "Re: Test"
        assert msg["From"] == "TestBot <test@example.com>"
        assert msg["In-Reply-To"] == "<abc@mx.com>"
        assert msg["References"] == "<abc@mx.com>"
        assert msg["Cc"] is None  # kein CC gesetzt

    def test_cc_header(self, sender):
        msg = sender._build_reply_message(
            to="a@b.com", subject="Re: X", body="Hi",
            in_reply_to="", references="", cc="cc@b.com",
        )
        assert msg["Cc"] == "cc@b.com"

    def test_references_fallback(self, sender):
        """References = In-Reply-To wenn keine Kette vorhanden."""
        msg = sender._build_reply_message(
            to="a@b.com", subject="Re: X", body="Hi",
            in_reply_to="<id@mx>", references="", cc="",
        )
        assert msg["References"] == "<id@mx>"

    def test_utf8_body(self, sender):
        msg = sender._build_reply_message(
            to="a@b.com", subject="Re: Ü", body="Schöne Grüße",
            in_reply_to="", references="", cc="",
        )
        content = msg.get_content()
        assert "Schöne Grüße" in content


# ---------------------------------------------------------------------------
# send_reply (mocked SMTP)
# ---------------------------------------------------------------------------

class TestSendReply:
    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_success(self, mock_connect, sender):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        result = sender.send_reply(
            to="r@b.com", subject="Re: Test", body="OK",
        )
        assert result.success is True
        assert result.to == "r@b.com"
        assert len(result.raw_msg) > 0
        assert b"Re: Test" in result.raw_msg
        mock_conn.send_message.assert_called_once()
        mock_conn.quit.assert_called_once()

    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_connection_error(self, mock_connect, sender):
        mock_connect.side_effect = OSError("Connection refused")

        result = sender.send_reply(
            to="r@b.com", subject="Re: Test", body="OK",
        )
        assert result.success is False
        assert "Verbindungsfehler" in result.error

    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_auth_error(self, mock_connect, sender):
        import smtplib
        mock_connect.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Auth failed",
        )
        result = sender.send_reply(
            to="r@b.com", subject="Re: Test", body="OK",
        )
        assert result.success is False
        assert "Authentifizierung" in result.error


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_available(self, mock_connect, sender):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        assert sender.is_available() is True

    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_not_available(self, mock_connect, sender):
        mock_connect.side_effect = OSError("refused")
        assert sender.is_available() is False
