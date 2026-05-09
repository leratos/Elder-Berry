"""Tests: MailCommandHandler – E-Mail-Commands (Haupt-Handler).

Ergänzt test_mail_reply_commands.py und test_mail_delete_commands.py
um Tests für: mails, mail_search, mail_attachment, mail_by_id,
plus Interface und Pattern-Matching.
"""

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.mail_commands import (
    MAIL_ATTACHMENT_PATTERN,
    MAIL_ID_PATTERN,
    MAIL_SEARCH_PATTERN,
    MAILS_DAYS_PATTERN,
    MailCommandHandler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mail(
    msg_id="99",
    subject="Test Mail",
    sender="Max <max@test.de>",
    body_preview="Hello World",
    date=None,
    message_id="<abc@test>",
    references="",
):
    from datetime import datetime

    mail = MagicMock()
    mail.msg_id = msg_id
    mail.subject = subject
    mail.sender = sender
    mail.body_preview = body_preview
    mail.date = date or datetime(2026, 3, 27, 10, 0)
    mail.message_id = message_id
    mail.references = references
    return mail


@pytest.fixture
def email_client():
    client = MagicMock()
    client.get_unread.return_value = [_make_mail()]
    client.get_recent.return_value = [_make_mail()]
    client.format_mails.return_value = "#99 Test Mail (Max)"
    client.format_mails_detailed.return_value = "Von: Max\nBetreff: Test Mail\nBody..."
    client.search.return_value = [_make_mail()]
    client.get_attachments.return_value = [("report.pdf", b"pdf_data")]
    client.get_by_uid.return_value = _make_mail()
    return client


@pytest.fixture
def handler(email_client):
    return MailCommandHandler(email_client=email_client)


@pytest.fixture
def handler_no_client():
    return MailCommandHandler(email_client=None)


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------


class TestMailsDaysPattern:
    @pytest.mark.parametrize(
        "text,days",
        [
            ("mails 5", "5"),
            ("mail 3", "3"),
            ("mails 14", "14"),
        ],
    )
    def test_valid(self, text, days):
        m = MAILS_DAYS_PATTERN.match(text)
        assert m is not None
        assert m.group(1) == days

    def test_invalid(self):
        assert MAILS_DAYS_PATTERN.match("mails") is None


class TestMailSearchPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "mail suche Rechnung",
            "mails suche Alux",
            "suche die mail mit Rechnung",
            "suche die mail von Alux",
        ],
    )
    def test_valid(self, text):
        assert MAIL_SEARCH_PATTERN.search(text) is not None


class TestMailAttachmentPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "mail anhang 12345",
            "anhang von mail 12345",
            "mail 12345 anhang",
        ],
    )
    def test_valid(self, text):
        assert MAIL_ATTACHMENT_PATTERN.search(text) is not None


class TestMailIdPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "mail 99",
            "mail #99",
            "zeig mail 99",
            "fasse mail #99 zusammen",
        ],
    )
    def test_valid(self, text):
        assert MAIL_ID_PATTERN.match(text) is not None


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class TestMailInterface:
    def test_simple_commands(self, handler):
        assert "mails" in handler.simple_commands

    def test_patterns(self, handler):
        names = [p[1] for p in handler.patterns]
        assert "mail_reply" in names
        assert "mail_delete" in names
        assert "mail_by_id" in names
        assert "mail_search" in names

    def test_keywords(self, handler):
        kw = handler.keywords
        assert "mails" in kw
        assert "mail_delete" in kw

    def test_command_descriptions(self, handler):
        descs = handler.command_descriptions
        assert len(descs) >= 5


# ---------------------------------------------------------------------------
# Mails Command
# ---------------------------------------------------------------------------


class TestMailsCommand:
    def test_unread(self, handler, email_client):
        result = handler.execute("mails", "mails")
        assert result.success is True
        assert "Ungelesene" in result.text
        email_client.get_unread.assert_called_once()

    def test_with_days(self, handler, email_client):
        result = handler.execute("mails", "mails 5")
        assert result.success is True
        assert "5 Tage" in result.text
        email_client.get_recent.assert_called_once_with(days=5)

    def test_zusammenfassung(self, handler, email_client):
        result = handler.execute("mails", "mail zusammenfassung")
        assert result.success is True
        email_client.get_unread.assert_called()

    def test_zusammenfassung_no_mails(self, handler, email_client):
        email_client.get_unread.return_value = []
        result = handler.execute("mails", "mail zusammenfassung")
        assert result.success is True
        assert "Keine" in result.text

    def test_no_client(self, handler_no_client):
        result = handler_no_client.execute("mails", "mails")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_exception(self, handler, email_client):
        email_client.get_unread.side_effect = RuntimeError("IMAP error")
        result = handler.execute("mails", "mails")
        assert result.success is False

    def test_stores_last_mails(self, handler, email_client):
        mails = [_make_mail()]
        email_client.get_unread.return_value = mails
        handler.execute("mails", "mails")
        assert handler._last_mails == mails


# ---------------------------------------------------------------------------
# Mail Search
# ---------------------------------------------------------------------------


class TestMailSearch:
    def test_search_success(self, handler, email_client):
        result = handler.execute("mail_search", "mail suche Rechnung")
        assert result.success is True
        assert "Rechnung" in result.text
        assert result.history_text is not None

    def test_search_no_results(self, handler, email_client):
        email_client.search.return_value = []
        result = handler.execute("mail_search", "mail suche XYZ")
        assert result.success is True
        assert "Keine" in result.text

    def test_search_no_client(self, handler_no_client):
        result = handler_no_client.execute("mail_search", "mail suche test")
        assert result.success is False

    def test_search_invalid_format(self, handler):
        result = handler.execute("mail_search", "suche")
        assert result.success is False

    def test_search_exception(self, handler, email_client):
        email_client.search.side_effect = RuntimeError("fail")
        result = handler.execute("mail_search", "mail suche Rechnung")
        assert result.success is False


# ---------------------------------------------------------------------------
# Mail Attachment
# ---------------------------------------------------------------------------


class TestMailAttachment:
    def test_attachment_success(self, handler, email_client):
        result = handler.execute("mail_attachment", "mail anhang 99")
        assert result.success is True
        assert result.file_paths
        assert len(result.file_paths) == 1

    def test_no_attachments(self, handler, email_client):
        email_client.get_attachments.return_value = []
        result = handler.execute("mail_attachment", "mail anhang 99")
        assert result.success is True
        assert "Keine Anhänge" in result.text

    def test_no_client(self, handler_no_client):
        result = handler_no_client.execute("mail_attachment", "mail anhang 99")
        assert result.success is False

    def test_invalid_format(self, handler):
        result = handler.execute("mail_attachment", "anhang")
        assert result.success is False

    def test_exception(self, handler, email_client):
        email_client.get_attachments.side_effect = RuntimeError("fail")
        result = handler.execute("mail_attachment", "mail anhang 99")
        assert result.success is False


# ---------------------------------------------------------------------------
# Mail by ID
# ---------------------------------------------------------------------------


class TestMailById:
    def test_by_id_success(self, handler, email_client):
        result = handler.execute("mail_by_id", "mail 99")
        assert result.success is True
        assert "#99" in result.text
        assert result.history_text is not None
        assert "Von:" in result.history_text

    def test_by_id_hash(self, handler, email_client):
        result = handler.execute("mail_by_id", "mail #99")
        assert result.success is True

    def test_mail_not_found(self, handler, email_client):
        email_client.get_by_uid.return_value = None
        result = handler.execute("mail_by_id", "mail 999")
        assert result.success is False
        assert "nicht gefunden" in result.text

    def test_no_client(self, handler_no_client):
        result = handler_no_client.execute("mail_by_id", "mail 99")
        assert result.success is False

    def test_exception(self, handler, email_client):
        email_client.get_by_uid.side_effect = RuntimeError("fail")
        result = handler.execute("mail_by_id", "mail 99")
        assert result.success is False

    def test_stores_last_mails(self, handler, email_client):
        mail = _make_mail()
        email_client.get_by_uid.return_value = mail
        handler.execute("mail_by_id", "mail 99")
        assert handler._last_mails == [mail]


# ---------------------------------------------------------------------------
# Extract Email Address
# ---------------------------------------------------------------------------


class TestExtractEmailAddress:
    def test_with_brackets(self):
        assert (
            MailCommandHandler._extract_email_address(
                "Max Mustermann <max@example.com>"
            )
            == "max@example.com"
        )

    def test_plain_email(self):
        assert (
            MailCommandHandler._extract_email_address("max@example.com")
            == "max@example.com"
        )

    def test_with_spaces(self):
        assert (
            MailCommandHandler._extract_email_address("  max@example.com  ")
            == "max@example.com"
        )


# ---------------------------------------------------------------------------
# Phase 80 Etappe 3: list_items / list_type fuer ConversationListStore
# ---------------------------------------------------------------------------


class TestMailListIntegration:
    """``_cmd_mails`` und ``_cmd_mail_search`` liefern strukturierte Items,
    die der Bridge in den ConversationListStore registriert (Phase 80 §5.3).
    """

    def test_mails_unread_list_items_carries_fields(self, handler, email_client):
        """Item-Form: from / subject / msg_id / date (Konzept §3.5)."""
        from datetime import datetime

        mail = _make_mail(
            msg_id="42",
            subject="Rechnung",
            sender="Alice <alice@x.de>",
            date=datetime(2026, 4, 1, 12, 0),
        )
        email_client.get_unread.return_value = [mail]
        result = handler.execute("mails", "mails")

        assert result.list_type == "mail_inbox"
        assert result.list_items is not None
        assert len(result.list_items) == 1
        item = result.list_items[0]
        assert item["msg_id"] == "42"
        assert item["subject"] == "Rechnung"
        assert item["from"] == "Alice <alice@x.de>"
        assert item["date"] == "2026-04-01T12:00:00"

    def test_mails_days_list_items(self, handler, email_client):
        email_client.get_recent.return_value = [_make_mail(msg_id="7")]
        result = handler.execute("mails", "mails 5")
        assert result.list_type == "mail_inbox"
        assert result.list_items is not None
        assert result.list_items[0]["msg_id"] == "7"

    def test_mails_zusammenfassung_list_items(self, handler, email_client):
        email_client.get_unread.return_value = [
            _make_mail(msg_id="1"),
            _make_mail(msg_id="2"),
        ]
        result = handler.execute("mails", "mail zusammenfassung")
        assert result.list_type == "mail_inbox"
        assert result.list_items is not None
        assert [it["msg_id"] for it in result.list_items] == ["1", "2"]

    def test_mails_empty_no_list(self, handler, email_client):
        """Leere Inbox -> kein list_items, sonst registriert die Bridge eine
        leere Liste."""
        email_client.get_unread.return_value = []
        result = handler.execute("mails", "mails")
        assert result.list_items is None
        assert result.list_type is None

    def test_mails_zusammenfassung_empty_no_list(self, handler, email_client):
        email_client.get_unread.return_value = []
        result = handler.execute("mails", "mail zusammenfassung")
        assert result.list_items is None
        assert result.list_type is None

    def test_mails_no_date_serializes_empty(self, handler, email_client):
        """date=None -> leerer String (kein Crash)."""
        mail = _make_mail(msg_id="9")
        mail.date = None
        email_client.get_unread.return_value = [mail]
        result = handler.execute("mails", "mails")
        assert result.list_items is not None
        assert result.list_items[0]["date"] == ""

    def test_mail_search_list_items_match_text(self, handler, email_client):
        """Reihenfolge in list_items == User-sichtbare Nummerierung."""
        m1 = _make_mail(msg_id="100", subject="Erste")
        m2 = _make_mail(msg_id="200", subject="Zweite")
        email_client.search.return_value = [m1, m2]
        result = handler.execute("mail_search", "mail suche test")
        assert result.list_type == "mail_inbox"
        assert result.list_items is not None
        assert result.list_items[0]["msg_id"] == "100"
        assert result.list_items[1]["msg_id"] == "200"

    def test_mail_search_no_results_no_list(self, handler, email_client):
        email_client.search.return_value = []
        result = handler.execute("mail_search", "mail suche xyz")
        assert result.list_items is None
        assert result.list_type is None

    def test_mail_by_id_no_list(self, handler, email_client):
        """Show-Command soll keine Liste registrieren -- Defensive gegen
        False-Positive-Registers in der Bridge."""
        result = handler.execute("mail_by_id", "mail 99")
        assert result.list_items is None
        assert result.list_type is None

    def test_mail_attachment_no_list(self, handler, email_client):
        result = handler.execute("mail_attachment", "mail anhang 99")
        assert result.list_items is None
        assert result.list_type is None


# ---------------------------------------------------------------------------
# Unknown Command
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    def test_unknown(self, handler):
        result = handler.execute("unknown", "unknown")
        assert result.success is False
