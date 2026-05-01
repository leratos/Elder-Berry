"""Tests für mail_delete Commands (Mail löschen via IMAP)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.mail_commands import (
    MAIL_DELETE_PATTERN,
    MailCommandHandler,
)
from elder_berry.tools.email_client import EmailMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_email(**kwargs) -> EmailMessage:
    defaults = dict(
        subject="Rechnung März",
        sender="Strato <billing@strato.de>",
        date=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        body_preview="Ihre Rechnung...",
        is_unread=False,
        msg_id="4523",
        message_id="<abc@mx.example.com>",
        references="",
    )
    defaults.update(kwargs)
    return EmailMessage(**defaults)


@pytest.fixture
def handler() -> MailCommandHandler:
    email_client = MagicMock()
    email_client.delete.return_value = True
    return MailCommandHandler(email_client=email_client)


@pytest.fixture
def handler_no_email() -> MailCommandHandler:
    return MailCommandHandler(email_client=None)


# ---------------------------------------------------------------------------
# MAIL_DELETE_PATTERN Tests
# ---------------------------------------------------------------------------


class TestMailDeletePattern:
    @pytest.mark.parametrize(
        "text",
        [
            "lösche mail #123",
            "lösche mail 123",
            "lösch die mail #456",
            "lösche die mail",
            "entferne mail #789",
            "entferne die mail",
            "mail löschen #123",
            "mail löschen",
            "lösche die letzte mail",
        ],
    )
    def test_matches(self, text: str):
        assert MAIL_DELETE_PATTERN.match(text.strip()), (
            f"Pattern sollte '{text}' matchen"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "lösche termin xyz",
            "lösche erinnerung 3",
            "lösche alle termine",
            "mail suche test",
            "mails",
            "mail 123",
        ],
    )
    def test_no_match(self, text: str):
        assert not MAIL_DELETE_PATTERN.match(text.strip()), (
            f"Pattern sollte '{text}' NICHT matchen"
        )

    def test_extracts_id_group1(self):
        """mail löschen #123 → Gruppe 1."""
        m = MAIL_DELETE_PATTERN.match("mail löschen #123")
        assert m
        uid = m.group(1) or m.group(2)
        assert uid == "123"

    def test_extracts_id_group2(self):
        """lösche mail #456 → Gruppe 2."""
        m = MAIL_DELETE_PATTERN.match("lösche mail #456")
        assert m
        uid = m.group(1) or m.group(2)
        assert uid == "456"

    def test_no_id_without_number(self):
        """lösche die mail → keine ID."""
        m = MAIL_DELETE_PATTERN.match("lösche die mail")
        assert m
        uid = m.group(1) or m.group(2) if m.lastindex and m.lastindex >= 2 else None
        # Kein Gruppen-Match mit Zahl → None
        assert uid is None or uid == ""


# ---------------------------------------------------------------------------
# _cmd_mail_delete Tests
# ---------------------------------------------------------------------------


class TestCmdMailDelete:
    def test_delete_by_id(self, handler: MailCommandHandler):
        result = handler.execute("mail_delete", "lösche mail #4523")
        assert result.success
        assert "4523" in result.text
        assert "gelöscht" in result.text
        handler._email_client.delete.assert_called_once_with("4523")

    def test_delete_last_single_mail(self, handler: MailCommandHandler):
        """Wenn nur 1 Mail in _last_mails → direkt löschen."""
        handler._last_mails = [_make_email(msg_id="999")]
        result = handler.execute("mail_delete", "lösche die mail")
        assert result.success
        assert "999" in result.text
        handler._email_client.delete.assert_called_once_with("999")

    def test_delete_last_clears_last_mails(self, handler: MailCommandHandler):
        handler._last_mails = [_make_email(msg_id="999")]
        handler.execute("mail_delete", "lösche die mail")
        assert len(handler._last_mails) == 0

    def test_delete_no_last_mails(self, handler: MailCommandHandler):
        """Keine letzte Mail → Fehlermeldung."""
        handler._last_mails = []
        result = handler.execute("mail_delete", "lösche die mail")
        assert not result.success
        assert "Keine Mail zum Löschen" in result.text

    def test_delete_multiple_last_mails_ambiguous(self, handler: MailCommandHandler):
        """Mehrere Mails in _last_mails ohne ID → Rückfrage."""
        handler._last_mails = [
            _make_email(msg_id="100"),
            _make_email(msg_id="200"),
        ]
        result = handler.execute("mail_delete", "lösche die mail")
        assert not result.success
        assert "Welche?" in result.text

    def test_delete_email_not_configured(self, handler_no_email: MailCommandHandler):
        result = handler_no_email.execute("mail_delete", "lösche mail #123")
        assert not result.success
        assert "nicht konfiguriert" in result.text

    def test_delete_imap_error(self, handler: MailCommandHandler):
        handler._email_client.delete.side_effect = RuntimeError("IMAP kaputt")
        result = handler.execute("mail_delete", "lösche mail #123")
        assert not result.success
        assert "❌" in result.text

    def test_delete_removes_from_last_mails(self, handler: MailCommandHandler):
        """Nach Löschen wird Mail aus _last_mails entfernt."""
        handler._last_mails = [
            _make_email(msg_id="100"),
            _make_email(msg_id="200"),
            _make_email(msg_id="300"),
        ]
        handler.execute("mail_delete", "lösche mail #200")
        assert len(handler._last_mails) == 2
        ids = [m.msg_id for m in handler._last_mails]
        assert "200" not in ids


# ---------------------------------------------------------------------------
# _last_mails State Tracking
# ---------------------------------------------------------------------------


class TestLastMailsTracking:
    def test_mails_sets_last_mails(self, handler: MailCommandHandler):
        mails = [_make_email(msg_id="1"), _make_email(msg_id="2")]
        handler._email_client.get_unread.return_value = mails
        handler._email_client.format_mails.return_value = "2 Mails"
        handler.execute("mails", "mails")
        assert handler._last_mails == mails

    def test_mail_by_id_sets_last_mails(self, handler: MailCommandHandler):
        mail = _make_email(msg_id="42")
        handler._email_client.get_by_uid.return_value = mail
        handler.execute("mail_by_id", "mail 42")
        assert handler._last_mails == [mail]

    def test_mail_search_sets_last_mails(self, handler: MailCommandHandler):
        mails = [_make_email(msg_id="10")]
        handler._email_client.search.return_value = mails
        handler._email_client.format_mails.return_value = "1 Mail"
        handler._email_client.format_mails_detailed.return_value = "Details"
        handler.execute("mail_search", "mail suche Rechnung")
        assert handler._last_mails == mails
