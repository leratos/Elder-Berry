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
        "smtp_host": None,
        "smtp_port": None,
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
        """Phase 100-A (D1-Regression): ein per UI gesetzter Nicht-Strato-Host
        (Key smtp_host/smtp_port) MUSS verwendet werden -- frueher las der
        Sender email_smtp_host/_port und fiel still auf smtp.strato.de zurueck.
        """
        store = MagicMock()
        store.get.side_effect = lambda key: {
            "email_user": "me@gmail.com",
            "email_password": "pw",
        }[key]
        store.get_or_none.side_effect = lambda key: {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": "587",
        }.get(key)
        s = EmailSender.from_secret_store(store)
        assert s._host == "smtp.gmail.com"
        assert s._port == 587

    def test_legacy_keys_ignored(self):
        """Die alten (nie geschriebenen) email_smtp_*-Keys duerfen NICHT mehr
        gelesen werden -> ohne smtp_host bleibt es beim Strato-Default.
        """
        store = MagicMock()
        store.get.side_effect = lambda key: {
            "email_user": "me@example.com",
            "email_password": "pw",
        }[key]
        store.get_or_none.side_effect = lambda key: {
            "email_smtp_host": "smtp.should-be-ignored.com",
            "email_smtp_port": "2525",
        }.get(key)
        s = EmailSender.from_secret_store(store)
        assert s._host == "smtp.strato.de"
        assert s._port == 465

    def test_sender_name_and_signature(self):
        """Phase 100-C: email_sender_name + email_signature werden gelesen."""
        store = MagicMock()
        store.get.side_effect = lambda key: {
            "email_user": "me@example.com",
            "email_password": "pw",
        }[key]
        store.get_or_none.side_effect = lambda key: {
            "email_sender_name": "Saleria (Lera)",
            "email_signature": "Viele Grüße\nSaleria",
        }.get(key)
        s = EmailSender.from_secret_store(store)
        assert s._sender_name == "Saleria (Lera)"
        assert s._signature == "Viele Grüße\nSaleria"

    def test_sender_name_default(self, mock_secret_store):
        """Ohne email_sender_name bleibt der Default 'Saleria'."""
        s = EmailSender.from_secret_store(mock_secret_store)
        assert s._sender_name == "Saleria"
        assert s._signature == ""


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
            to="a@b.com",
            subject="Re: X",
            body="Hi",
            in_reply_to="",
            references="",
            cc="cc@b.com",
        )
        assert msg["Cc"] == "cc@b.com"

    def test_references_fallback(self, sender):
        """References = In-Reply-To wenn keine Kette vorhanden."""
        msg = sender._build_reply_message(
            to="a@b.com",
            subject="Re: X",
            body="Hi",
            in_reply_to="<id@mx>",
            references="",
            cc="",
        )
        assert msg["References"] == "<id@mx>"

    def test_utf8_body(self, sender):
        msg = sender._build_reply_message(
            to="a@b.com",
            subject="Re: Ü",
            body="Schöne Grüße",
            in_reply_to="",
            references="",
            cc="",
        )
        content = msg.get_content()
        assert "Schöne Grüße" in content

    def test_signature_appended(self):
        """Phase 100-C: konfigurierte Signatur wird mit RFC-3676-Delimiter
        unter den Body gehaengt."""
        s = EmailSender(
            host="smtp.example.com",
            user="test@example.com",
            password="secret",
            signature="Viele Grüße\nSaleria",
        )
        msg = s._build_reply_message(
            to="a@b.com",
            subject="Re: X",
            body="Hier ist die Antwort.",
            in_reply_to="",
            references="",
            cc="",
        )
        content = msg.get_content()
        assert "Hier ist die Antwort." in content
        assert "\n-- \n" in content
        assert "Viele Grüße\nSaleria" in content

    def test_no_signature_no_delimiter(self, sender):
        """Ohne Signatur kein '-- '-Delimiter."""
        msg = sender._build_reply_message(
            to="a@b.com",
            subject="Re: X",
            body="Nur Body.",
            in_reply_to="",
            references="",
            cc="",
        )
        assert "-- " not in msg.get_content()

    def test_sender_name_in_from(self):
        """Phase 100-C: konfigurierter Anzeigename erscheint im From-Header.

        (Klammern waeren RFC-5322-Kommentare und wuerden entfernt -> hier
        bewusst ein Name ohne Klammern.)
        """
        s = EmailSender(
            host="h",
            user="me@example.com",
            password="pw",
            sender_name="Saleria Mailbot",
        )
        msg = s._build_reply_message(
            to="a@b.com",
            subject="Re: X",
            body="Hi",
            in_reply_to="",
            references="",
            cc="",
        )
        assert msg["From"] == "Saleria Mailbot <me@example.com>"

    def test_subject_crlf_scrubbed(self, sender):
        """Phase 100-B (D3): CR/LF im (angreiferkontrollierten) Betreff darf
        keine zusaetzlichen Header schmuggeln."""
        msg = sender._build_reply_message(
            to="a@b.com",
            subject="Re: Hallo\r\nBcc: evil@attacker.com",
            body="Hi",
            in_reply_to="",
            references="",
            cc="",
        )
        assert "\r" not in msg["Subject"]
        assert "\n" not in msg["Subject"]
        assert msg["Bcc"] is None
        assert "evil@attacker.com" in msg["Subject"]  # als Text, nicht als Header


# ---------------------------------------------------------------------------
# send_reply (mocked SMTP)
# ---------------------------------------------------------------------------


class TestSendReply:
    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_success(self, mock_connect, sender):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        result = sender.send_reply(
            to="r@b.com",
            subject="Re: Test",
            body="OK",
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
            to="r@b.com",
            subject="Re: Test",
            body="OK",
        )
        assert result.success is False
        assert "Verbindungsfehler" in result.error

    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_auth_error(self, mock_connect, sender):
        import smtplib

        mock_connect.side_effect = smtplib.SMTPAuthenticationError(
            535,
            b"Auth failed",
        )
        result = sender.send_reply(
            to="r@b.com",
            subject="Re: Test",
            body="OK",
        )
        assert result.success is False
        assert "Authentifizierung" in result.error

    @patch("elder_berry.tools.email_sender.EmailSender._connect")
    def test_smtp_error(self, mock_connect, sender):
        """Phase 100-E: generischer SMTP-Fehler beim Senden (Testlücke)."""
        import smtplib

        mock_conn = MagicMock()
        mock_conn.send_message.side_effect = smtplib.SMTPException("boom")
        mock_connect.return_value = mock_conn
        result = sender.send_reply(
            to="r@b.com",
            subject="Re: Test",
            body="OK",
        )
        assert result.success is False
        assert "SMTP-Fehler" in result.error


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
