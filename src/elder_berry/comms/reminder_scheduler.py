"""ReminderScheduler – Periodischer Check für fällige Erinnerungen.

Daemon-Thread der alle 15 Sekunden ReminderStore.get_due() prüft
und fällige Erinnerungen über einen Callback sendet.

Verwendung:
    scheduler = ReminderScheduler(
        store=reminder_store,
        send_reminder=lambda user_id, text: ...,
    )
    scheduler.start()
    ...
    scheduler.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from elder_berry.tools.reminder_store import ReminderStore

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """Periodischer Scheduler für fällige Erinnerungen.

    Pollt den ReminderStore und ruft send_reminder für jede fällige
    Erinnerung auf. Markiert sie danach als fired.
    """

    def __init__(
        self,
        store: ReminderStore,
        send_reminder: Callable[[str, str], None],
        poll_interval: int = 15,
    ) -> None:
        """
        Args:
            store: ReminderStore-Instanz.
            send_reminder: Callable(user_id, text) → sendet an Matrix.
                           Muss thread-safe sein.
            poll_interval: Sekunden zwischen Checks.
        """
        self._store = store
        self._send_reminder = send_reminder
        self._poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """True wenn der Scheduler-Thread aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet den Scheduler-Thread (nicht-blockierend)."""
        if self._running:
            logger.warning("ReminderScheduler läuft bereits")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="reminder-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("ReminderScheduler gestartet (Intervall: %ds)", self._poll_interval)

    def stop(self) -> None:
        """Stoppt den Scheduler-Thread."""
        if not self._running:
            return

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval + 5)
        self._thread = None
        logger.info("ReminderScheduler gestoppt")

    def _run(self) -> None:
        """Thread-Hauptschleife: pollt fällige Erinnerungen."""
        while self._running:
            try:
                self._check_due()
            except Exception as e:
                logger.error("ReminderScheduler Fehler: %s", e)

            # Schlafen in kleinen Schritten (für schnellen Shutdown)
            for _ in range(self._poll_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _check_due(self) -> None:
        """Prüft auf fällige Erinnerungen und sendet sie."""
        due = self._store.get_due()
        for reminder in due:
            text = f"⏰ Erinnerung: {reminder.message}"
            try:
                self._send_reminder(reminder.user_id, text)
                self._store.mark_fired(reminder.id)
                logger.info(
                    "Erinnerung #%d gesendet an %s: %s",
                    reminder.id, reminder.user_id, reminder.message,
                )
            except Exception as e:
                logger.error(
                    "Erinnerung #%d senden fehlgeschlagen: %s",
                    reminder.id, e,
                )
