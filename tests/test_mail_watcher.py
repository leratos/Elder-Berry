"""Tests für MailWatcher (proaktive Neue-Mail-Benachrichtigung, Phase 101-N).

Erkennung via vollstaendiger UNSEEN-UID-Menge (get_unread_uids) + High-Water-
Mark; Details werden nur fuer tatsaechlich neue Mails geholt (get_by_uid).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from elder_berry.comms.mail_watcher import _MAX_ANNOUNCE, MailWatcher
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


def _watcher() -> MailWatcher:
    return MailWatcher(email_client=MagicMock(), poll_minutes=5)


# ---------------------------------------------------------------------------
# _collect_new (UID-Diffing + Baseline)
# ---------------------------------------------------------------------------


class TestCollectNew:
    def test_first_poll_seeds_baseline_no_new(self):
        w = _watcher()
        assert w._collect_new([1, 2]) == []
        assert w._seen == {1, 2}

    def test_new_computed_against_seen_not_marked(self):
        """_collect_new markiert NICHT (das macht der Aufrufer nach Versand)."""
        w = _watcher()
        w._seen = {1}
        w._first_poll = False
        assert w._collect_new([1, 2, 3]) == [2, 3]
        # 2,3 noch NICHT in _seen (nur auf current beschnitten)
        assert w._seen == {1}

    def test_empty_baseline_then_first_mail_is_new(self):
        w = _watcher()
        w._collect_new([])  # leerer Posteingang -> seen leer
        assert w._collect_new([101]) == [101]

    def test_prunes_read_uids_from_seen(self):
        w = _watcher()
        w._seen = {1, 2, 3}
        w._first_poll = False
        assert w._collect_new([1, 2]) == []  # 1,2 schon gesehen
        assert w._seen == {1, 2}  # 3 (gelesen) entfernt -> bounded

    def test_no_burst_truncation_in_detection(self):
        """Vollstaendige UID-Menge -> auch grosse Bursts werden komplett als
        neu erkannt (Cap greift erst beim Melden, nicht beim Erkennen)."""
        w = _watcher()
        w._collect_new([1])  # Baseline -> seen={1}
        assert w._collect_new(list(range(2, 101))) == list(range(2, 101))


# ---------------------------------------------------------------------------
# _poll_and_notify (get_unread_uids -> get_by_uid -> _send_alert)
# ---------------------------------------------------------------------------


class TestPollAndNotify:
    def test_baseline_sends_nothing(self):
        ec = MagicMock()
        ec.get_unread_uids.return_value = [1, 2]
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()
        assert sent == []
        ec.get_by_uid.assert_not_called()  # Baseline holt keine Details

    def test_new_mail_fetched_and_announced(self):
        ec = MagicMock()
        ec.get_unread_uids.side_effect = [[1], [1, 2]]
        ec.get_by_uid.return_value = _mail("2", subject="Rechnung", sender="Firma <f@x.de>")
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Baseline
        w._poll_and_notify()  # 2 ist neu
        assert len(sent) == 1
        assert "Firma" in sent[0] and "Rechnung" in sent[0]
        ec.get_by_uid.assert_called_once_with("2")

    def test_announced_mail_not_reannounced(self):
        ec = MagicMock()
        ec.get_unread_uids.side_effect = [[1], [1, 2], [1, 2]]
        ec.get_by_uid.return_value = _mail("2")
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Baseline
        w._poll_and_notify()  # 2 neu -> gemeldet + gesehen
        w._poll_and_notify()  # 2 schon gesehen -> nichts
        assert len(sent) == 1

    def test_failed_detail_fetch_retried_next_poll(self):
        """PR #318 Codex P2: get_by_uid()==None (transienter Fetch-Fehler) ->
        UID NICHT als gesehen markieren -> naechster Poll versucht erneut."""
        ec = MagicMock()
        ec.get_unread_uids.side_effect = [[1], [1, 2], [1, 2]]
        ec.get_by_uid.side_effect = [None, _mail("2", subject="Endlich")]
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Baseline
        w._poll_and_notify()  # 2 neu, Fetch schlaegt fehl -> nicht gemeldet
        assert sent == []
        w._poll_and_notify()  # erneuter Versuch -> Erfolg
        assert len(sent) == 1
        assert "Endlich" in sent[0]
        assert ec.get_by_uid.call_count == 2

    def test_imap_error_none_is_noop_and_defers_baseline(self):
        """PR #318 Codex P2: get_unread_uids()==None (Fehler) -> nichts tun,
        Baseline NICHT finalisieren."""
        ec = MagicMock()
        ec.get_unread_uids.return_value = None
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()
        assert sent == []
        assert w._first_poll is True  # aufgeschoben
        ec.get_by_uid.assert_not_called()

    def test_error_then_existing_unread_not_announced(self):
        ec = MagicMock()
        ec.get_unread_uids.side_effect = [None, [100, 101]]
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Fehler -> aufgeschoben
        w._poll_and_notify()  # Baseline 100,101 -> nicht melden
        assert sent == []

    def test_burst_over_cap_sends_summary(self):
        """PR #318 Codex P2: > _MAX_ANNOUNCE neue -> EINE Sammel-Meldung mit
        Anzahl, keine Einzel-Detailabrufe (nichts still verloren)."""
        ec = MagicMock()
        burst = list(range(2, 2 + _MAX_ANNOUNCE + 5))  # mehr als der Cap
        ec.get_unread_uids.side_effect = [[1], [1, *burst]]
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Baseline
        w._poll_and_notify()  # Burst
        assert len(sent) == 1
        assert str(len(burst)) in sent[0]
        ec.get_by_uid.assert_not_called()

    def test_get_by_uid_none_skipped(self):
        ec = MagicMock()
        ec.get_unread_uids.side_effect = [[1], [1, 2]]
        ec.get_by_uid.return_value = None  # Mail zwischenzeitlich weg
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()
        w._poll_and_notify()
        assert sent == []  # kein Crash, keine Meldung

    def test_mail_read_during_fetch_not_announced(self):
        """PR #318 Codex P2: zwischen UID-Suche und Detail-Fetch in anderem
        Client gelesen -> get_by_uid liefert is_unread=False -> keine
        Falschmeldung."""
        ec = MagicMock()
        ec.get_unread_uids.side_effect = [[1], [1, 2]]
        ec.get_by_uid.return_value = EmailMessage(
            subject="X",
            sender="A <a@b.com>",
            date=None,
            body_preview="",
            is_unread=False,  # zwischenzeitlich gelesen
            msg_id="2",
        )
        w = MailWatcher(email_client=ec, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
        w._poll_and_notify()  # Baseline
        w._poll_and_notify()  # 2 "neu", aber bereits gelesen -> nichts
        assert sent == []

    def test_no_email_client_is_noop(self):
        w = MailWatcher(email_client=None, poll_minutes=5)
        sent: list[str] = []
        w._send_alert = sent.append
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

    def test_format_caps_long_subject(self):
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
        ec.get_unread_uids.return_value = []
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
        ec.get_unread_uids.return_value = []
        w = MailWatcher(email_client=ec, poll_minutes=5)
        w.start()
        first_thread = w._thread
        w.start()
        assert w._thread is first_thread
        assert w.is_running is True
        w.stop()

    def test_stop_when_not_running_is_noop(self):
        w = MailWatcher(email_client=MagicMock(), poll_minutes=5)
        w.stop()
        assert w.is_running is False
