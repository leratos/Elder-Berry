"""Tests: IMAPEmailClient – E-Mail lesen via IMAP."""
import email as email_mod
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.email_client import EmailMessage, IMAPEmailClient


# ---------------------------------------------------------------------------
# EmailMessage DTO
# ---------------------------------------------------------------------------

class TestEmailMessage:
    def test_format_short_unread(self):
        msg = EmailMessage(
            subject="Rechnung März",
            sender="Strato <billing@strato.de>",
            date=datetime(2026, 3, 16, 10, 30),
            body_preview="Ihre Rechnung...",
            is_unread=True,
        )
        result = msg.format_short()
        assert "●" in result
        assert "Rechnung März" in result
        assert "Strato" in result
        assert "16.03" in result

    def test_format_short_read(self):
        msg = EmailMessage(
            subject="Newsletter",
            sender="news@example.com",
            date=datetime(2026, 3, 15, 8, 0),
            body_preview="",
            is_unread=False,
        )
        assert "○" in msg.format_short()

    def test_format_short_long_sender_truncated(self):
        msg = EmailMessage(
            subject="Test",
            sender="Sehr Langer Absendername Der Gekürzt Werden Muss <long@example.com>",
            date=datetime(2026, 1, 1),
            body_preview="",
        )
        result = msg.format_short()
        assert "..." in result

    def test_frozen(self):
        msg = EmailMessage(
            subject="X", sender="Y", date=None, body_preview="",
        )
        with pytest.raises(AttributeError):
            msg.subject = "Z"

    def test_no_date(self):
        msg = EmailMessage(
            subject="X", sender="Y", date=None, body_preview="",
        )
        assert "?" in msg.format_short()


# ---------------------------------------------------------------------------
# IMAPEmailClient
# ---------------------------------------------------------------------------

class TestIMAPInit:
    def test_from_secret_store(self):
        store = MagicMock()
        store.get.side_effect = lambda k: {
            "email_imap_host": "imap.strato.de",
            "email_user": "user@example.com",
            "email_password": "secret",
        }[k]
        store.get_or_none.return_value = "993"

        client = IMAPEmailClient.from_secret_store(store)
        assert client._host == "imap.strato.de"
        assert client._user == "user@example.com"
        assert client._port == 993

    def test_from_secret_store_default_port(self):
        store = MagicMock()
        store.get.side_effect = lambda k: {
            "email_imap_host": "imap.strato.de",
            "email_user": "user@example.com",
            "email_password": "secret",
        }[k]
        store.get_or_none.return_value = None

        client = IMAPEmailClient.from_secret_store(store)
        assert client._port == 993


# ---------------------------------------------------------------------------
# Header-Dekodierung
# ---------------------------------------------------------------------------

class TestDecodeHeader:
    def test_plain_ascii(self):
        assert IMAPEmailClient._decode_header("Hello World") == "Hello World"

    def test_empty(self):
        assert IMAPEmailClient._decode_header("") == ""

    def test_none(self):
        assert IMAPEmailClient._decode_header(None) == ""

    def test_utf8_encoded(self):
        # MIME-encoded UTF-8 header
        raw = "=?UTF-8?B?UmVjaG51bmcgTcOkcno=?="
        result = IMAPEmailClient._decode_header(raw)
        assert "Rechnung März" in result

    def test_iso_encoded(self):
        raw = "=?ISO-8859-1?Q?=DCberweisungsbest=E4tigung?="
        result = IMAPEmailClient._decode_header(raw)
        assert "Überweisungsbestätigung" in result


# ---------------------------------------------------------------------------
# Body-Extraktion
# ---------------------------------------------------------------------------

class TestExtractBody:
    def test_plain_text(self):
        msg = email_mod.message.EmailMessage()
        msg.set_content("Hallo Welt, dies ist ein Test.")
        result = IMAPEmailClient._extract_body(msg)
        assert "Hallo Welt" in result

    def test_html_tags_removed(self):
        msg = email_mod.message.EmailMessage()
        msg.set_content(
            "<html><body><p>Hallo <b>Welt</b></p></body></html>",
            subtype="html",
        )
        result = IMAPEmailClient._extract_body(msg)
        assert "Hallo" in result
        assert "Welt" in result
        assert "<" not in result

    def test_multipart_prefers_plain(self):
        msg = email_mod.message.EmailMessage()
        msg.make_mixed()
        plain_part = email_mod.message.EmailMessage()
        plain_part.set_content("Plain text version")
        html_part = email_mod.message.EmailMessage()
        html_part.set_content("<p>HTML version</p>", subtype="html")
        msg.attach(plain_part)
        msg.attach(html_part)

        result = IMAPEmailClient._extract_body(msg)
        assert "Plain text" in result


# ---------------------------------------------------------------------------
# E-Mail Parsing (vollständig)
# ---------------------------------------------------------------------------

class TestParseEmail:
    def _make_raw_email(
        self,
        subject: str = "Test",
        sender: str = "test@example.com",
        body: str = "Hello",
    ) -> bytes:
        msg = email_mod.message.EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["Date"] = "Mon, 16 Mar 2026 10:30:00 +0100"
        msg.set_content(body)
        return msg.as_bytes()

    def test_parse_basic(self):
        raw = self._make_raw_email(
            subject="Rechnung",
            sender="billing@strato.de",
            body="Ihre Rechnung für März...",
        )
        result = IMAPEmailClient._parse_email(raw)
        assert result.subject == "Rechnung"
        assert "strato.de" in result.sender
        assert result.date is not None
        assert "Rechnung" in result.body_preview

    def test_parse_no_subject(self):
        raw = self._make_raw_email(subject="", body="Text")
        result = IMAPEmailClient._parse_email(raw)
        assert result.subject == "(Kein Betreff)"


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

class TestMsgId:
    def test_msg_id_default_empty(self):
        msg = EmailMessage(
            subject="X", sender="Y", date=None, body_preview="",
        )
        assert msg.msg_id == ""

    def test_msg_id_set(self):
        msg = EmailMessage(
            subject="X", sender="Y", date=None, body_preview="",
            msg_id="12345",
        )
        assert msg.msg_id == "12345"

    def test_format_short_with_msg_id(self):
        msg = EmailMessage(
            subject="Rechnung",
            sender="billing@strato.de",
            date=datetime(2026, 3, 16, 10, 30),
            body_preview="",
            msg_id="42",
        )
        result = msg.format_short()
        assert "[#42]" in result

    def test_format_short_without_msg_id(self):
        msg = EmailMessage(
            subject="Test",
            sender="a@b.com",
            date=datetime(2026, 3, 16, 10, 0),
            body_preview="",
            msg_id="",
        )
        result = msg.format_short()
        assert "[#" not in result

    def test_parse_email_with_msg_id(self):
        msg = email_mod.message.EmailMessage()
        msg["Subject"] = "Test"
        msg["From"] = "test@example.com"
        msg["Date"] = "Mon, 16 Mar 2026 10:30:00 +0100"
        msg.set_content("Body")
        raw = msg.as_bytes()

        result = IMAPEmailClient._parse_email(raw, msg_id="99")
        assert result.msg_id == "99"

    def test_parse_email_default_no_msg_id(self):
        msg = email_mod.message.EmailMessage()
        msg["Subject"] = "Test"
        msg["From"] = "test@example.com"
        msg.set_content("Body")
        raw = msg.as_bytes()

        result = IMAPEmailClient._parse_email(raw)
        assert result.msg_id == ""


class TestGetAttachments:
    def test_get_attachments_no_attachments(self):
        """Mail ohne Anhänge gibt leere Liste zurück."""
        client = IMAPEmailClient("host", "user", "pass")

        # Mail ohne Attachment bauen
        msg = email_mod.message.EmailMessage()
        msg["Subject"] = "Kein Anhang"
        msg["From"] = "test@example.com"
        msg.set_content("Nur Text")
        raw = msg.as_bytes()

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [(b"1 (RFC822 {100}", raw)])

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_attachments("12345")

        assert result == []
        mock_conn.logout.assert_called_once()

    def test_get_attachments_with_attachment(self):
        """Mail mit Anhang gibt (filename, bytes) Tupel zurück."""
        client = IMAPEmailClient("host", "user", "pass")

        # Multipart-Mail mit Attachment bauen
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg["Subject"] = "Mit Anhang"
        msg["From"] = "test@example.com"
        msg.attach(MIMEText("Body text"))

        attachment = MIMEBase("application", "pdf")
        attachment.set_payload(b"%PDF-1.4 test content")
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition", "attachment", filename="rechnung.pdf",
        )
        msg.attach(attachment)

        raw = msg.as_bytes()
        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [(b"1 (RFC822 {100}", raw)])

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_attachments("12345")

        assert len(result) == 1
        assert result[0][0] == "rechnung.pdf"
        assert len(result[0][1]) > 0

    def test_get_attachments_mail_not_found(self):
        """Nicht existierende UID wirft RuntimeError."""
        client = IMAPEmailClient("host", "user", "pass")

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [None])

        with patch.object(client, "_connect", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="nicht gefunden"):
                client.get_attachments("99999")

    def test_get_attachments_connection_error(self):
        """Verbindungsfehler wirft RuntimeError."""
        client = IMAPEmailClient("host", "user", "pass")

        with patch.object(
            client, "_connect", side_effect=ConnectionError("timeout"),
        ):
            with pytest.raises(RuntimeError, match="fehlgeschlagen"):
                client.get_attachments("12345")


class TestDelete:
    def test_delete_success(self):
        """Mail per UID löschen → True."""
        client = IMAPEmailClient("host", "user", "pass")

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [b"1"])
        mock_conn.select.return_value = ("OK", [b"1"])

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.delete("4523")

        assert result is True
        mock_conn.uid.assert_called_once_with(
            "store", b"4523", "+FLAGS", "(\\Deleted)",
        )
        mock_conn.expunge.assert_called_once()
        mock_conn.logout.assert_called_once()

    def test_delete_store_fails(self):
        """IMAP STORE fehlgeschlagen → RuntimeError."""
        client = IMAPEmailClient("host", "user", "pass")

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("NO", [b"error"])
        mock_conn.select.return_value = ("OK", [b"1"])

        with patch.object(client, "_connect", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="STORE fehlgeschlagen"):
                client.delete("4523")

    def test_delete_connection_error(self):
        """Verbindungsfehler → RuntimeError."""
        client = IMAPEmailClient("host", "user", "pass")

        with patch.object(
            client, "_connect", side_effect=ConnectionError("timeout"),
        ):
            with pytest.raises(RuntimeError, match="fehlgeschlagen"):
                client.delete("4523")

    def test_delete_readonly_false(self):
        """select() muss mit readonly=False aufgerufen werden."""
        client = IMAPEmailClient("host", "user", "pass")

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [b"1"])
        mock_conn.select.return_value = ("OK", [b"1"])

        with patch.object(client, "_connect", return_value=mock_conn):
            client.delete("123")

        mock_conn.select.assert_called_once_with("INBOX", readonly=False)


class TestSearch:
    def test_search_builds_correct_criteria(self):
        """search() baut korrekte IMAP OR-Suche."""
        client = IMAPEmailClient("host", "user", "pass")

        with patch.object(client, "_fetch_mails", return_value=[]) as mock_fetch:
            client.search("Rechnung", max_results=5, days=30)

        call_args = mock_fetch.call_args
        criteria = call_args[0][0]
        assert "SUBJECT" in criteria
        assert "FROM" in criteria
        assert "Rechnung" in criteria
        assert "SINCE" in criteria
        assert call_args.kwargs["max_results"] == 5


class TestFormat:
    def test_format_mails_empty(self):
        client = IMAPEmailClient("host", "user", "pass")
        assert client.format_mails([]) == "Keine E-Mails."

    def test_format_mails_list(self):
        client = IMAPEmailClient("host", "user", "pass")
        mails = [
            EmailMessage(
                subject="Mail 1",
                sender="a@b.com",
                date=datetime(2026, 3, 16, 10, 0),
                body_preview="Test",
            ),
            EmailMessage(
                subject="Mail 2",
                sender="c@d.com",
                date=datetime(2026, 3, 16, 11, 0),
                body_preview="Test 2",
            ),
        ]
        result = client.format_mails(mails)
        assert "2 E-Mail(s)" in result
        assert "Mail 1" in result
        assert "Mail 2" in result

    def test_format_detailed(self):
        client = IMAPEmailClient("host", "user", "pass")
        mails = [
            EmailMessage(
                subject="Wichtig",
                sender="Chef <chef@firma.de>",
                date=datetime(2026, 3, 16, 9, 0),
                body_preview="Bitte bis morgen erledigen.",
            ),
        ]
        result = client.format_mails_detailed(mails)
        assert "Wichtig" in result
        assert "Chef" in result
        assert "Bitte bis morgen" in result
        assert "--- Mail 1 ---" in result

    def test_format_detailed_with_msg_id(self):
        client = IMAPEmailClient("host", "user", "pass")
        mails = [
            EmailMessage(
                subject="Rechnung",
                sender="billing@strato.de",
                date=datetime(2026, 3, 16, 10, 0),
                body_preview="Ihre Rechnung",
                msg_id="42",
            ),
        ]
        result = client.format_mails_detailed(mails)
        assert "(ID: 42)" in result


# ---------------------------------------------------------------------------
# get_by_uid()
# ---------------------------------------------------------------------------

class TestGetByUid:
    def test_get_by_uid_success(self):
        """Mail per UID abrufen → EmailMessage zurück."""
        client = IMAPEmailClient("host", "user", "pass")

        # Minimale RFC822 Mail
        raw_mail = (
            b"From: sender@test.de\r\n"
            b"Subject: Testbetreff\r\n"
            b"Date: Mon, 17 Mar 2026 10:00:00 +0100\r\n"
            b"\r\n"
            b"Dies ist der Body."
        )

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [(b"1 (RFC822 ...)", raw_mail)])
        mock_conn.select.return_value = ("OK", [b"1"])

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_by_uid("99")

        assert result is not None
        assert result.subject == "Testbetreff"
        assert result.sender == "sender@test.de"
        assert "Body" in result.body_preview
        assert result.msg_id == "99"

    def test_get_by_uid_not_found(self):
        """Mail nicht gefunden → None."""
        client = IMAPEmailClient("host", "user", "pass")

        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [None])
        mock_conn.select.return_value = ("OK", [b"1"])

        with patch.object(client, "_connect", return_value=mock_conn):
            result = client.get_by_uid("999")

        assert result is None

    def test_get_by_uid_connection_error(self):
        """Verbindungsfehler → None (kein Crash)."""
        client = IMAPEmailClient("host", "user", "pass")

        with patch.object(client, "_connect", side_effect=Exception("Timeout")):
            result = client.get_by_uid("99")

        assert result is None
