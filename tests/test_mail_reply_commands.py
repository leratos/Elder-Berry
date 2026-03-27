"""Tests für mail_reply Commands (Phase 28)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.mail_commands import (
    MAIL_REPLY_MODIFY_PATTERN,
    MAIL_REPLY_PATTERN,
    MailCommandHandler,
)
from elder_berry.tools.email_client import EmailMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_email(**kwargs) -> EmailMessage:
    defaults = dict(
        subject="Angebot Dachsanierung",
        sender="Max Mustermann <max@example.com>",
        date=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        body_preview="Sehr geehrter Herr...",
        is_unread=False,
        msg_id="4523",
        message_id="<abc123@mx.example.com>",
        references="",
    )
    defaults.update(kwargs)
    return EmailMessage(**defaults)


@pytest.fixture
def handler() -> MailCommandHandler:
    email_client = MagicMock()
    anthropic = MagicMock()
    anthropic.generate.return_value = "Vielen Dank für Ihr Angebot..."
    return MailCommandHandler(
        email_client=email_client,
        anthropic_client=anthropic,
    )


# ---------------------------------------------------------------------------
# MAIL_REPLY_PATTERN
# ---------------------------------------------------------------------------

class TestMailReplyPattern:
    def test_antworte_auf_id(self):
        m = MAIL_REPLY_PATTERN.search("antworte auf #123 positiv")
        assert m is not None

    def test_antworte_auf_mail_id(self):
        m = MAIL_REPLY_PATTERN.search("antworte auf mail 456 absagen")
        assert m is not None

    def test_gib_auf_mail(self):
        m = MAIL_REPLY_PATTERN.search(
            "gib auf mail #789 eine positive antwort",
        )
        assert m is not None

    def test_beantworte_mail_mit(self):
        m = MAIL_REPLY_PATTERN.search(
            "beantworte mail #123 mit einer zusage",
        )
        assert m is not None

    def test_mail_id_antworten_colon(self):
        m = MAIL_REPLY_PATTERN.search("mail #123 antworten: wir können am Montag")
        assert m is not None

    def test_no_match_plain_mail(self):
        m = MAIL_REPLY_PATTERN.search("mail #123")
        assert m is None

    def test_no_match_mails(self):
        m = MAIL_REPLY_PATTERN.search("mails")
        assert m is None

    def test_no_match_mail_suche(self):
        m = MAIL_REPLY_PATTERN.search("mail suche xyz")
        assert m is None


# ---------------------------------------------------------------------------
# MAIL_REPLY_MODIFY_PATTERN
# ---------------------------------------------------------------------------

class TestMailReplyModifyPattern:
    def test_match(self):
        m = MAIL_REPLY_MODIFY_PATTERN.match("#123 mach es formeller")
        assert m is not None
        assert m.group(1) == "123"
        assert m.group(2) == "mach es formeller"

    def test_no_match_without_hash(self):
        m = MAIL_REPLY_MODIFY_PATTERN.match("mach es formeller")
        assert m is None


# ---------------------------------------------------------------------------
# _parse_reply_args
# ---------------------------------------------------------------------------

class TestParseReplyArgs:
    def test_parse_id_and_instruction(self, handler):
        msg_id, inst = handler._parse_reply_args(
            "antworte auf #4523 positiv, bedanke dich",
        )
        assert msg_id == "4523"
        assert "positiv" in inst

    def test_parse_no_match(self, handler):
        msg_id, inst = handler._parse_reply_args("hallo welt")
        assert msg_id == ""
        assert inst == ""


# ---------------------------------------------------------------------------
# _extract_email_address
# ---------------------------------------------------------------------------

class TestExtractEmailAddress:
    def test_with_angle_brackets(self):
        assert (
            MailCommandHandler._extract_email_address(
                "Max Mustermann <max@example.com>",
            )
            == "max@example.com"
        )

    def test_plain_address(self):
        assert (
            MailCommandHandler._extract_email_address("max@example.com")
            == "max@example.com"
        )

    def test_with_quoted_name(self):
        assert (
            MailCommandHandler._extract_email_address(
                '"Max M" <max@example.com>',
            )
            == "max@example.com"
        )


# ---------------------------------------------------------------------------
# _cmd_mail_reply
# ---------------------------------------------------------------------------

class TestCmdMailReply:
    def test_no_email_client(self):
        h = MailCommandHandler(email_client=None, anthropic_client=MagicMock())
        r = h.execute("mail_reply", "antworte auf #123 positiv")
        assert r.success is False
        assert "nicht konfiguriert" in r.text

    def test_no_anthropic_client(self):
        h = MailCommandHandler(email_client=MagicMock(), anthropic_client=None)
        r = h.execute("mail_reply", "antworte auf #123 positiv")
        assert r.success is False
        assert "Claude API" in r.text

    def test_mail_not_found(self, handler):
        handler._email_client.get_by_uid.return_value = None
        r = handler.execute("mail_reply", "antworte auf #999 positiv")
        assert r.success is False
        assert "nicht gefunden" in r.text

    def test_success_returns_pending(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email()
        r = handler.execute("mail_reply", "antworte auf #4523 positiv")
        assert r.success is True
        assert r.pending_confirmation is True
        assert r.pending_data is not None
        assert r.pending_data["to"] == "max@example.com"
        assert r.pending_data["msg_id"] == "4523"

    def test_draft_text_in_display(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email()
        r = handler.execute("mail_reply", "antworte auf #4523 positiv")
        assert "Entwurf" in r.text
        assert "Vielen Dank" in r.text

    def test_subject_re_prefix(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email(
            subject="Angebot",
        )
        r = handler.execute("mail_reply", "antworte auf #4523 positiv")
        assert r.pending_data["subject"] == "Re: Angebot"

    def test_subject_re_already(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email(
            subject="Re: Angebot",
        )
        r = handler.execute("mail_reply", "antworte auf #4523 positiv")
        assert r.pending_data["subject"] == "Re: Angebot"

    def test_message_id_in_pending_data(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email()
        r = handler.execute("mail_reply", "antworte auf #4523 positiv")
        assert r.pending_data["in_reply_to"] == "<abc123@mx.example.com>"

    def test_anthropic_error_handled(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email()
        handler._anthropic.generate.side_effect = RuntimeError("API error")
        r = handler.execute("mail_reply", "antworte auf #4523 positiv")
        assert r.success is False
        assert "fehlgeschlagen" in r.text


# ---------------------------------------------------------------------------
# _cmd_mail_reply_modify
# ---------------------------------------------------------------------------

class TestCmdMailReplyModify:
    def test_modify_success(self, handler):
        handler._email_client.get_by_uid.return_value = _make_email()
        r = handler.execute("mail_reply_modify", "#4523 mach es formeller")
        assert r.success is True
        assert r.pending_confirmation is True
        assert "Geänderter Entwurf" in r.text

    def test_modify_mail_not_found(self, handler):
        handler._email_client.get_by_uid.return_value = None
        r = handler.execute("mail_reply_modify", "#999 formeller")
        assert r.success is False


# ---------------------------------------------------------------------------
# Keywords + Descriptions
# ---------------------------------------------------------------------------

class TestMailReplyRegistration:
    def test_keywords(self, handler):
        assert "mail_reply" in handler.keywords

    def test_command_descriptions(self, handler):
        descs = " ".join(handler.command_descriptions)
        assert "antworte" in descs.lower()

    def test_patterns_reply_before_id(self, handler):
        """MAIL_REPLY_PATTERN muss VOR MAIL_ID_PATTERN stehen."""
        patterns = handler.patterns
        reply_idx = next(
            i for i, (_, cmd, *_) in enumerate(patterns)
            if cmd == "mail_reply"
        )
        id_idx = next(
            i for i, (_, cmd, *_) in enumerate(patterns)
            if cmd == "mail_by_id"
        )
        assert reply_idx < id_idx
