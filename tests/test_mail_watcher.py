"""Tests für MailWatcher (proaktive Neue-Mail-Benachrichtigung, Phase 101-N)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from elder_berry.comms.mail_watcher import _MAX_UNREAD_PER_POLL, MailWatcher
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
        assert w._high_water == 2

    def test_second_poll_returns_only_higher_uids(self):
        w = _watcher()
        w._collect_new([_mail("1")])  # Baseline -> hw=1
        new = w._collect_new([_mail("1"), _mail("2"), _mail("3")])
        assert sorted(m.msg_id for m in new) == ["2", "3"]
        assert w._high_water == 3

    def test_not_reannounced(self):
        w = _watcher()
        w._collect_new([_mail("1")])  # Baseline
        assert [m.msg_id for m in w._collect_new([_mail("1"), _mail("2")])] == ["2"]
        assert w._collect_new([_mail("1"), _mail("2")]) == []  # nichts neu

    def test_read_mail_does_not_reannounce(self):
        """Wird eine der neuesten Mails gelesen (faellt aus dem Poll), darf
        keine aeltere faelschlich als neu gemeldet werden."""
        w = _watcher()
        w._collect_new([_mail("1"), _mail("2")])  # Baseline hw=2
        assert w._collect_new([_mail("1")]) == []  # 2 gelesen -> nichts neu

    def test_ignores_mails_without_uid(self):
        w = _watcher()
        w._collect_new([])  # Baseline leer -> hw=0
        new = w._collect_new([_mail(""), _mail("5")])
        assert [m.msg_id for m in new] == ["5"]

    def test_transient_empty_poll_no_false_alert(self):
        """PR #318 Codex P2: ein leerer Poll (IMAP-Fehler -> []) darf die Mark
        nicht zuruecksetzen, sonst wird der ganze Posteingang neu gemeldet."""
        w = _watcher()
        w._collect_new([_mail("100"), _mail("101")])  # Baseline hw=101
        assert w._collect_new([]) == []  # transienter Fehler
        assert w._high_water == 101  # Mark unangetastet
        # Naechster erfolgreicher Poll mit denselben Mails -> nichts neu
        assert w._collect_new([_mail("100"), _mail("101")]) == []

    def test_page_churn_old_uid_not_new(self):
        """Eine aeltere UID, die wieder in die (begrenzte) Seite rutscht, ist
        nicht neu (UID < High-Water)."""
        w = _watcher()
        w._collect_new([_mail("105"), _mail("104")])  # Baseline hw=105
        new = w._collect_new([_mail("104"), _mail("90")])  # 90 rutscht rein
        assert new == []

    def test_new_higher_uid_announced(self):
        w = _watcher()
        w._collect_new([_mail("100")])  # Baseline hw=100
        new = w._collect_new([_mail("101"), _mail("100")])
        assert [m.msg_id for m in new] == ["101"]
        assert w._high_water == 101

    def test_non_numeric_uid_skipped(self):
        w = _watcher()
        w._collect_new([])  # Baseline
        new = w._collect_new([_mail("abc"), _mail("7")])
        assert [m.msg_id for m in new] == ["7"]

    def test_burst_over_page_logs_warning(self, caplog):
        """PR #318 Codex P2: volle Seite + aelteste gefetchte Mail neu -> Warnung
        (moegliche ausgelassene aeltere neue Mails), nicht still."""
        w = _watcher()
        w._collect_new([_mail("100")])  # Baseline hw=100
        page = [_mail(str(u)) for u in range(300, 300 - _MAX_UNREAD_PER_POLL, -1)]
        with caplog.at_level(logging.WARNING):
            new = w._collect_new(page)
        assert len(new) == _MAX_UNREAD_PER_POLL
        assert any("Burst" in r.message for r in caplog.records)

    def test_full_page_no_warning_when_covered(self, caplog):
        """Volle Seite, aber min UID <= High-Water (kein Gap) -> keine Warnung."""
        page = [_mail(str(u)) for u in range(_MAX_UNREAD_PER_POLL, 0, -1)]
        w = _watcher()
        w._collect_new(page)  # Baseline (hw = max = _MAX_UNREAD_PER_POLL)
        with caplog.at_level(logging.WARNING):
            w._collect_new(page)  # gleiche Seite, min=1 <= hw
        assert not any("Burst" in r.message for r in caplog.records)


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

    def test_first_poll_imap_error_defers_baseline(self):
        """PR #318 Codex P2: leerer Erst-Poll mit get_unread_count==-1 (Fehler)
        finalisiert die Baseline NICHT (sonst meldet der naechste Poll alles)."""
        ec = MagicMock()
        ec.get_unread.return_value = []
        ec.get_unread_count.return_value = -1  # IMAP-Fehler
        w = MailWatcher(email_client=ec, poll_minutes=5)
        w._poll_and_notify()
        assert w._first_poll is True  # Baseline aufgeschoben

    def test_first_poll_empty_inbox_finalizes_baseline(self):
        ec = MagicMock()
        ec.get_unread.return_value = []
        ec.get_unread_count.return_value = 0  # wirklich leer
        w = MailWatcher(email_client=ec, poll_minutes=5)
        w._poll_and_notify()
        assert w._first_poll is False  # finalisiert

    def test_error_then_existing_unread_not_announced(self):
        """Erst-Poll-Fehler, dann erfolgreicher Poll mit bestehenden Unread ->
        diese sind Baseline, werden NICHT als neu gemeldet."""
        ec = MagicMock()
        ec.get_unread.side_effect = [[], [_mail("100"), _mail("101")]]
        ec.get_unread_count.return_value = -1
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Fehler -> aufgeschoben
        w._poll_and_notify()  # Baseline 100,101 -> nicht melden
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

    def test_format_caps_long_subject(self):
        """PR #318 Codex P2: ueberlanger Betreff wird gecappt."""
        text = MailWatcher._format(_mail("1", subject="S" * 400))
        assert "S" * 400 not in text
        assert len(text) < 200


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
