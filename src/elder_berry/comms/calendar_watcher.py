"""CalendarWatcher – Proaktive Kalender-Erinnerungen (Daemon-Thread).

Pollt GoogleCalendarClient regelmäßig und sendet Benachrichtigungen
X Minuten vor Terminen via Matrix.

Abgrenzung:
- BriefingScheduler = einmal täglich um 07:30
- ReminderScheduler = explizit gesetzte Timer/Erinnerungen
- CalendarWatcher  = automatisch X Minuten vor jedem Termin

Verwendung:
    watcher = CalendarWatcher(
        send_alert=lambda text: ...,
        calendar=google_calendar_client,
        reminder_minutes=[15, 5],
        poll_interval=300,
    )
    watcher.start()
    pass
    watcher.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from elder_berry.core.context_enricher import ContextEnricher
    from elder_berry.tools.google_calendar import CalendarEvent, GoogleCalendarClient

logger = logging.getLogger(__name__)


class CalendarWatcher:
    """Daemon-Thread der proaktiv vor Kalender-Terminen erinnert.

    Pollt GoogleCalendarClient alle `poll_interval` Sekunden.
    Sendet Erinnerungen `reminder_minutes` Minuten vor jedem Termin.
    Dedupliziert: gleicher Reminder feuert nicht doppelt.
    Überspringt Ganztags-Events.
    """

    def __init__(
        self,
        send_alert: Callable[[str], None],
        calendar: GoogleCalendarClient,
        reminder_minutes: list[int] | None = None,
        poll_interval: int = 300,
        context_enricher: ContextEnricher | None = None,
    ) -> None:
        """
        Args:
            send_alert: Callable(text) → sendet an Matrix. Muss thread-safe sein.
            calendar: GoogleCalendarClient (bereits initialisiert).
            reminder_minutes: Minuten vor Termin für Erinnerungen.
                Default: [15, 5] → 15 Min vorher + 5 Min vorher.
            poll_interval: Sekunden zwischen Kalender-Abfragen.
                Default: 300 (5 Minuten). Nicht zu kurz wegen API-Rate-Limits.
            context_enricher: Optionaler ContextEnricher für angereicherte Alerts.
                Wird nur beim ERSTEN Reminder (max(reminder_minutes)) genutzt.
        """
        self._send_alert = send_alert
        self._calendar = calendar
        self._reminder_minutes: list[int] = sorted(
            reminder_minutes or [15, 5], reverse=True
        )
        self._poll_interval = poll_interval
        self._context_enricher = context_enricher

        # State: event_id → Set von bereits gesendeten reminder_minutes
        self._reminded_events: dict[str, set[int]] = {}

        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """True wenn der Watcher-Thread aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet den Watcher-Thread (Daemon, nicht-blockierend)."""
        if self._running:
            logger.warning("CalendarWatcher läuft bereits")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="CalendarWatcher",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "CalendarWatcher gestartet (Erinnerungen: %s Min vor Termin, Poll: %ss)",
            self._reminder_minutes,
            self._poll_interval,
        )

    def stop(self) -> None:
        """Stoppt den Watcher-Thread sauber."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("CalendarWatcher gestoppt")

    def _run(self) -> None:
        """Thread-Hauptschleife: pollt Kalender, prüft nahende Termine."""
        while self._running:
            try:
                self._check_upcoming()
            except Exception as e:
                logger.error("CalendarWatcher Check-Fehler: %s", e)

            # poll_interval in 1s-Schritten für sauberes Shutdown
            for _ in range(self._poll_interval):
                # mypy narrowt self._running im while-Body auf Literal[True];
                # in der Praxis setzt stop() das Flag aus einem anderen Thread.
                if not self._running:
                    break  # type: ignore[unreachable]
                time.sleep(1)

    def _check_upcoming(self) -> None:
        """Prüft ob Termine in den nächsten max(reminder_minutes) + 10 Minuten anstehen."""
        lookahead_minutes = max(self._reminder_minutes) + 10
        now = datetime.now(timezone.utc)
        end = now + timedelta(minutes=lookahead_minutes)

        try:
            events = self._calendar.get_events_range(start=now, end=end)
        except Exception as e:
            logger.warning("CalendarWatcher: Kalender-Abfrage fehlgeschlagen: %s", e)
            return

        for event in events:
            if event.all_day:
                continue  # Ganztags-Events nicht erinnern

            minutes_until = (event.start - now).total_seconds() / 60

            for reminder_min in self._reminder_minutes:
                already_sent = self._reminded_events.get(event.event_id, set())
                if minutes_until <= reminder_min and reminder_min not in already_sent:
                    self._send_reminder(event, reminder_min)
                    self._reminded_events.setdefault(event.event_id, set()).add(
                        reminder_min
                    )

        self._cleanup_past_events(events)

    def _send_reminder(self, event: CalendarEvent, minutes: int) -> None:
        """Formatiert und sendet eine Termin-Erinnerung.

        Beim ERSTEN Reminder (max(reminder_minutes)) wird der Alert mit
        Kontext aus IMAP, Wetter, Memory etc. angereichert – sofern ein
        ContextEnricher konfiguriert ist. (Phase 91-A: Note-Lookups
        temporaer deaktiviert bis NextcloudNotesClient ausgerollt ist.)
        Spätere Reminder bleiben schlank.
        """
        time_str = event.start.astimezone().strftime("%H:%M")

        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            time_text = f"{hours}h {mins}min" if mins else f"{hours}h"
        else:
            time_text = f"{minutes} Minuten"

        text = f"📅 Termin in {time_text}: **{event.summary}** ({time_str})"
        if event.location:
            text += f"\n  📍 {event.location}"

        # Kontext-Anreicherung nur beim ersten Reminder
        if self._context_enricher and minutes == max(self._reminder_minutes):
            try:
                result = self._context_enricher.enrich_event(
                    title=event.summary,
                    event_time=event.start,
                    location=event.location,
                )
                if result.has_context and result.formatted:
                    text += f"\n\n{result.formatted}"
            except Exception as e:
                logger.warning(
                    "Kontext-Anreicherung fehlgeschlagen für '%s': %s",
                    event.summary,
                    e,
                )

        try:
            self._send_alert(text)
            logger.info(
                "Kalender-Erinnerung gesendet: %s in %d Min",
                event.summary,
                minutes,
            )
        except Exception as e:
            logger.error("Kalender-Erinnerung senden fehlgeschlagen: %s", e)

    def _cleanup_past_events(self, current_events: list[CalendarEvent]) -> None:
        """Entfernt vergangene Events aus dem State (Memory-Leak verhindern)."""
        current_ids = {e.event_id for e in current_events}
        past_ids = [eid for eid in self._reminded_events if eid not in current_ids]
        for eid in past_ids:
            del self._reminded_events[eid]
