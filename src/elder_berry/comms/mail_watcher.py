"""MailWatcher – proaktive Benachrichtigung bei neuen ungelesenen Mails.

Phase 101-N. Pollt periodisch die UNSEEN-UIDs
(``IMAPEmailClient.get_unread_uids``) und meldet neu aufgetauchte Mails einmalig
per Absender/Betreff in den Matrix-Raum. Details (Body-Fetch) werden nur fuer
die tatsaechlich neuen Mails geholt -- guenstig und ohne Seitenlimit, daher
robust gegen Bursts. Modelliert auf ``BriefingScheduler``/``CalendarWatcher``
(Daemon-Thread, ``Schedulable``-Protokoll für den ``SchedulerManager``).

Bewusst LLM-frei: die Hintergrund-Schleife ruft KEIN LLM auf (vermeidet
Dauer-Last und eine zusätzliche Prompt-Injection-Fläche). Priorisierung bleibt
der user-initiierten ``mails priorität`` (Triage, Phase 101-T) vorbehalten.

Der Versand läuft nicht direkt über den Matrix-Channel, sondern über den
thread-sicheren Callback ``_send_alert``, den der ``SchedulerManager`` per
``register(..., '_send_alert', prefix='📧')`` injiziert.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.tools.email_client import EmailMessage, IMAPEmailClient

logger = logging.getLogger(__name__)

# Untergrenze für das Poll-Intervall, damit der IMAP-Server nicht gehämmert
# wird (jeder Poll öffnet eine frische Verbindung).
_MIN_POLL_SECONDS = 60
# Max. einzeln gemeldete neue Mails pro Poll. Bei mehr (Burst/Flood) eine
# Sammel-Meldung mit Anzahl -- so wird weder gespammt noch etwas still
# ausgelassen (PR #318 Codex P2).
_MAX_ANNOUNCE = 10
# Cap fuer den (angreiferkontrollierten) Betreff in der Benachrichtigung.
_SUBJECT_CAP = 120


class MailWatcher:
    """Daemon-Thread, der neue ungelesene Mails proaktiv meldet."""

    def __init__(
        self,
        email_client: IMAPEmailClient | None = None,
        poll_minutes: int = 5,
    ) -> None:
        self._email_client = email_client
        self._poll_seconds = max(_MIN_POLL_SECONDS, int(poll_minutes) * 60)
        self._running = False
        self._thread: threading.Thread | None = None
        # High-Water-Mark der hoechsten bereits gesehenen IMAP-UID. IMAP-UIDs
        # sind streng monoton steigend (RFC 3501) -> nur Mails mit groesserer
        # UID sind wirklich neu. Gespeist aus der vollstaendigen UNSEEN-UID-
        # Menge (get_unread_uids, kein Seitenlimit) -> keine Burst-Trunkierung.
        self._high_water = 0
        # Erster Poll seedet nur die Baseline (bestehende Unread sind nicht neu).
        self._first_poll = True
        # Wird vom SchedulerManager.register überschrieben (thread-sicher,
        # raumgebunden). Default = stiller No-op.
        self._send_alert: Callable[[str], None] = lambda *_: None

    @property
    def is_running(self) -> bool:
        """True wenn der Watcher-Thread aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet den Watcher-Thread (nicht-blockierend)."""
        if self._running:
            logger.warning("MailWatcher läuft bereits")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="mail-watcher",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "MailWatcher gestartet (Intervall: %ds)",
            self._poll_seconds,
        )

    def stop(self) -> None:
        """Stoppt den Watcher-Thread."""
        if not self._running:
            return
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=35)
        self._thread = None
        logger.info("MailWatcher gestoppt")

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while self._running:
            try:
                self._poll_and_notify()
            except Exception as e:  # pragma: no cover - defensiv, Thread am Leben halten
                logger.warning("MailWatcher Poll fehlgeschlagen: %s", e)

            for _ in range(self._poll_seconds):
                if not self._running:
                    break  # type: ignore[unreachable]
                time.sleep(1)

    def _poll_and_notify(self) -> None:
        """Ein Poll-Durchlauf: neue UNSEEN-UIDs ermitteln und melden."""
        if not self._email_client:
            return
        # Nur die UIDs holen (guenstig, vollstaendig, kein Body-Fetch, kein
        # Seitenlimit). None = IMAP-Fehler -> nichts tun: Baseline NICHT
        # finalisieren und keine Fehlalarme. So ist ein Fehler eindeutig vom
        # leeren Posteingang ([]) unterscheidbar (PR #318 Codex P2).
        uids = self._email_client.get_unread_uids()
        if uids is None:
            return
        new_uids = self._collect_new(uids)
        if not new_uids:
            return
        # PR #318 Codex P2: ein Burst darf weder spammen noch still verloren
        # gehen -> ueber dem Cap eine Sammel-Meldung mit Anzahl statt Einzel-
        # benachrichtigungen. (UID-Erkennung ist vollstaendig, also exakt.)
        if len(new_uids) > _MAX_ANNOUNCE:
            self._send_alert(f"{len(new_uids)} neue ungelesene Mails")
            return
        # Details (Body-Fetch) nur fuer die tatsaechlich neuen Mails.
        for uid in new_uids:
            mail = self._email_client.get_by_uid(str(uid))
            if mail is not None:
                self._send_alert(self._format(mail))

    def _collect_new(self, uids: list[int]) -> list[int]:
        """Gibt die neuen UIDs (groesser als die High-Water-Mark) zurueck und
        zieht die Mark nach.

        ``uids`` ist die VOLLSTAENDIGE Unread-Menge (kein Seitenlimit), daher
        gibt es keine Burst-Trunkierung. Der erste Aufruf seedet nur die
        Baseline (gibt ``[]`` zurueck) -- bestehende Unread sind nicht "neu".
        """
        if self._first_poll:
            self._high_water = max(uids, default=0)
            self._first_poll = False
            return []
        new = sorted(u for u in uids if u > self._high_water)
        if uids:
            self._high_water = max(self._high_water, max(uids))
        return new

    @staticmethod
    def _format(mail: EmailMessage) -> str:
        """Einzeilige Benachrichtigung 'Neue Mail von X: Betreff' (CR/LF-frei)."""
        sender_short = mail.sender.split("<")[0].strip().strip('"') or mail.sender
        if len(sender_short) > 40:
            sender_short = sender_short[:37] + "..."
        # PR #318 Codex P2: auch den (angreiferkontrollierten) Betreff cappen,
        # damit eine ueberlange Subject-Zeile die Raum-Nachricht nicht aufblaeht.
        subject = mail.subject
        if len(subject) > _SUBJECT_CAP:
            subject = subject[: _SUBJECT_CAP - 3] + "..."
        text = f"Neue Mail von {sender_short}: {subject}"
        return text.replace("\r", " ").replace("\n", " ")
