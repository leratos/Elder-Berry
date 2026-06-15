"""MailWatcher – proaktive Benachrichtigung bei neuen ungelesenen Mails.

Phase 101-N. Pollt periodisch ``IMAPEmailClient.get_unread`` und meldet neu
aufgetauchte Mails einmalig per Absender/Betreff in den Matrix-Raum. Modelliert
auf ``BriefingScheduler``/``CalendarWatcher`` (Daemon-Thread, ``Schedulable``-
Protokoll für den ``SchedulerManager``).

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
# Seitengroesse pro Poll. Bewusst hoch, damit ein Burst zwischen zwei Polls
# nur in Ausnahmefaellen die Seite ueberschreitet (PR #318 Codex P2); echte
# Trunkierung wird zusaetzlich geloggt statt still ausgelassen.
_MAX_UNREAD_PER_POLL = 50
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
        # UID sind wirklich neu. Robust gegen (a) >max_results Unread + Seiten-
        # verschiebung und (b) transiente get_unread()-Fehler (liefert []), die
        # bei einem Seen-Set sonst den ganzen Posteingang als "neu" melden.
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
        """Ein Poll-Durchlauf: neue ungelesene Mails ermitteln und melden."""
        if not self._email_client:
            return
        mails = self._email_client.get_unread(max_results=_MAX_UNREAD_PER_POLL)
        # PR #318 Codex P2: Erststart-Baseline nur finalisieren, wenn der Abruf
        # WIRKLICH erfolgreich war. get_unread() liefert [] sowohl bei einem
        # transienten IMAP-Fehler als auch bei leerem Posteingang; sonst wuerde
        # ein Fehler beim Erststart die Mark auf 0 setzen und der naechste
        # erfolgreiche Poll den ganzen Posteingang als neu melden.
        # get_unread_count() (-1 = Fehler) unterscheidet beide Faelle.
        if (
            not mails
            and self._first_poll
            and self._email_client.get_unread_count() < 0
        ):
            return  # transienter Fehler beim Erststart -> Baseline aufschieben
        for mail in self._collect_new(mails):
            self._send_alert(self._format(mail))

    def _collect_new(self, mails: list[EmailMessage]) -> list[EmailMessage]:
        """Gibt die seit dem letzten Poll neu eingetroffenen Mails zurueck.

        Nutzt die High-Water-Mark auf der IMAP-UID: neu = UID groesser als die
        hoechste je gesehene. Der erste Aufruf seedet nur die Baseline (gibt
        ``[]`` zurueck) -- bestehende Unread sind nicht "neu". Ein leerer Poll
        (transienter Fehler oder leerer Posteingang) laesst die Mark unangetastet
        und meldet daher nichts faelschlich.
        """
        numbered: list[tuple[int, EmailMessage]] = []
        for m in mails:
            if not m.msg_id:
                continue
            try:
                numbered.append((int(m.msg_id), m))
            except ValueError:
                continue

        if self._first_poll:
            self._high_water = max(
                (uid for uid, _ in numbered), default=self._high_water
            )
            self._first_poll = False
            return []

        prev_hw = self._high_water
        new = [m for uid, m in numbered if uid > prev_hw]
        if numbered:
            uids = [uid for uid, _ in numbered]
            self._high_water = max(prev_hw, max(uids))
            # PR #318 Codex P2: volle Seite UND selbst die aelteste gefetchte
            # Mail ist neu -> es koennen aeltere neue Mails unterhalb der Seite
            # liegen, die nie gemeldet werden. Nicht still auslassen, sondern
            # warnen (volle Pagination waere fuer ein Personen-Postfach
            # ueberdimensioniert).
            if len(numbered) >= _MAX_UNREAD_PER_POLL and min(uids) > prev_hw:
                logger.warning(
                    "MailWatcher: Posteingang-Burst > %d zwischen Polls -- "
                    "aeltere neue Mails koennen in der Benachrichtigung fehlen.",
                    _MAX_UNREAD_PER_POLL,
                )
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
