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
