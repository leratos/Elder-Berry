"""Tests für MailWatcher (proaktive Neue-Mail-Benachrichtigung, Phase 101-N)."""

from __future__ import annotations

from unittest.mock import MagicMock

from elder_berry.comms.mail_watcher import MailWatcher
from elder_berry.tools.email_client import EmailMessage


def _mail(msg_id: str, subject: str = "Betreff", sender: str = "Max <max@b.com>") -> EmailMessage:
    return EmailMessage(
        subject=subject,
        sender=sender,
        date=None,
        body_preview="",
        is_unread=True,
        msg_id=msg_id,
    )


def _watcher(mails_returning: MagicMock | None = None) -> MailWatcher:
    ec = mails_returning or MagicMock()
    return MailWatcher(email_client=ec, poll_minutes=5)


# ---------------------------------------------------------------------------
# _collect_new (Baseline + Dedup)
# ---------------------------------------------------------------------------


class TestCollectNew:
    def test_first_poll_seeds_baseline_no_new(self):
        w = _watcher()
        new = w._collect_new([_mail("1"), _mail("2")])
        assert new == []  # Baseline -> nichts ist "neu"
        assert w._seen == {"1", "2"}

    def test_second_poll_returns_only_new(self):
        w = _watcher()
        w._collect_new([_mail("1")])  # Baseline
        new = w._collect_new([_mail("1"), _mail("2"), _mail("3")])
        assert sorted(m.msg_id for m in new) == ["2", "3"]
        assert w._seen == {"1", "2", "3"}

    def test_seen_not_reannounced(self):
        w = _watcher()
        w._collect_new([_mail("1")])  # Baseline
        w._collect_new([_mail("1"), _mail("2")])  # 2 ist neu
        new = w._collect_new([_mail("1"), _mail("2")])  # nichts neu
        assert new == []

    def test_read_mail_drops_from_seen(self):
        """Verschwindet eine Mail aus get_unread (gelesen), schrumpft _seen."""
        w = _watcher()
        w._collect_new([_mail("1"), _mail("2")])  # Baseline
        w._collect_new([_mail("1")])  # 2 gelesen -> raus
        assert w._seen == {"1"}

    def test_ignores_mails_without_uid(self):
        w = _watcher()
        w._collect_new([])  # Baseline leer
        new = w._collect_new([_mail(""), _mail("5")])
        assert [m.msg_id for m in new] == ["5"]


# ---------------------------------------------------------------------------
# _poll_and_notify (Verdrahtung Poll -> Alert)
# ---------------------------------------------------------------------------


class TestPollAndNotify:
    def test_baseline_sends_nothing(self):
        ec = MagicMock()
        ec.get_unread.return_value = [_mail("1")]
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()
        assert sent == []

    def test_new_mail_triggers_alert(self):
        ec = MagicMock()
        ec.get_unread.side_effect = [
            [_mail("1")],  # Baseline
            [_mail("1"), _mail("2", subject="Rechnung", sender="Firma <f@x.de>")],
        ]
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Baseline
        w._poll_and_notify()  # 2 ist neu
        assert len(sent) == 1
        assert "Firma" in sent[0]
        assert "Rechnung" in sent[0]

    def test_no_email_client_is_noop(self):
        w = MailWatcher(email_client=None, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()
        w._poll_and_notify()
        assert sent == []


# ---------------------------------------------------------------------------
# _format
# ---------------------------------------------------------------------------


class TestFormat:
    def test_format_basic(self):
        text = MailWatcher._format(_mail("1", subject="Hallo", sender="Max <max@b.com>"))
        assert text == "Neue Mail von Max: Hallo"

    def test_format_strips_crlf(self):
        text = MailWatcher._format(
            _mail("1", subject="Zeile1\r\nZeile2", sender="A <a@b.com>")
        )
        assert "\r" not in text
        assert "\n" not in text

    def test_format_truncates_long_sender(self):
        long = "Ein sehr sehr langer Absendername der gekuerzt wird"
        text = MailWatcher._format(_mail("1", sender=f"{long} <x@y.de>"))
        assert "..." in text


# ---------------------------------------------------------------------------
# Lifecycle / Konfiguration
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_is_running_default_false(self):
        assert _watcher().is_running is False

    def test_start_stop(self):
        ec = MagicMock()
        ec.get_unread.return_value = []
        w = MailWatcher(email_client=ec, poll_minutes=5)
        w.start()
        assert w.is_running is True
        w.stop()
        assert w.is_running is False

    def test_poll_interval_clamped_to_minimum(self):
        w = MailWatcher(email_client=MagicMock(), poll_minutes=0)
        assert w._poll_seconds == 60

    def test_poll_interval_from_minutes(self):
        w = MailWatcher(email_client=MagicMock(), poll_minutes=10)
        assert w._poll_seconds == 600

    def test_double_start_is_noop(self):
        ec = MagicMock()
        ec.get_unread.return_value = []
        w = MailWatcher(email_client=ec, poll_minutes=5)
        w.start()
        first_thread = w._thread
        w.start()  # zweiter Start -> Warnung, kein neuer Thread
        assert w._thread is first_thread
        assert w.is_running is True
        w.stop()

    def test_stop_when_not_running_is_noop(self):
        w = MailWatcher(email_client=MagicMock(), poll_minutes=5)
        w.stop()  # darf nicht crashen
        assert w.is_running is False
