"""BriefingScheduler – Tägliches Morgen-Briefing via Matrix.

Daemon-Thread der einmal täglich zu konfigurierbarer Uhrzeit ein
Briefing zusammenstellt und über einen Callback sendet.

Kombiniert: Wetter + Kalender + Erinnerungen.

Verwendung:
    scheduler = BriefingScheduler(
        send_briefing=lambda text: ...,
        weather=weather_client,
        calendar=calendar_client,
        reminder_store=reminder_store,
    )
    scheduler.start()
    ...
    scheduler.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from elder_berry.tools.google_calendar import GoogleCalendarClient
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient

logger = logging.getLogger(__name__)


class BriefingScheduler:
    """Täglicher Briefing-Scheduler.

    Prüft alle 30 Sekunden ob die konfigurierte Briefing-Uhrzeit erreicht ist.
    Sendet maximal einmal pro Tag.
    """

    def __init__(
        self,
        send_briefing: Callable[[str], None],
        calendar: GoogleCalendarClient | None = None,
        weather: WeatherClient | None = None,
        reminder_store: ReminderStore | None = None,
        briefing_hour: int = 7,
        briefing_minute: int = 30,
    ) -> None:
        """
        Args:
            send_briefing: Callable(text) → sendet an Matrix. Muss thread-safe sein.
            calendar: GoogleCalendarClient (optional).
            weather: WeatherClient (optional).
            reminder_store: ReminderStore (optional).
            briefing_hour: Stunde des Briefings (0-23, Lokalzeit).
            briefing_minute: Minute des Briefings (0-59).
        """
        self._send_briefing = send_briefing
        self._calendar = calendar
        self._weather = weather
        self._reminder_store = reminder_store
        self._briefing_hour = briefing_hour
        self._briefing_minute = briefing_minute
        self._thread: threading.Thread | None = None
        self._running = False
        self._briefing_sent_today: date | None = None

    @property
    def is_running(self) -> bool:
        """True wenn der Scheduler-Thread aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet den Scheduler-Thread (nicht-blockierend)."""
        if self._running:
            logger.warning("BriefingScheduler läuft bereits")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="briefing-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "BriefingScheduler gestartet (Briefing: %02d:%02d)",
            self._briefing_hour, self._briefing_minute,
        )

    def stop(self) -> None:
        """Stoppt den Scheduler-Thread."""
        if not self._running:
            return

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=35)
        self._thread = None
        logger.info("BriefingScheduler gestoppt")

    def build_briefing(self) -> str:
        """Baut den Briefing-Text zusammen. Auch manuell aufrufbar.

        Returns:
            Formatierter Briefing-Text oder leerer String wenn keine Daten.
        """
        sections: list[str] = []

        # --- Wetter ---
        if self._weather:
            try:
                current = self._weather.get_current()
                today = self._weather.get_today()
                weather_text = self._weather.format_current(current)

                # Morgen als Vorschau
                try:
                    days = self._weather.get_days(2)
                    if len(days) >= 2:
                        from elder_berry.tools.weather_client import WMO_EMOJIS
                        tmrw = days[1]
                        emoji = WMO_EMOJIS.get(tmrw.weather_code, "🌡️")
                        weather_text += (
                            f"\n  Morgen: {tmrw.temp_min:.0f}–{tmrw.temp_max:.0f}°C, "
                            f"{tmrw.description}"
                        )
                except Exception:
                    pass

                sections.append(weather_text)
            except Exception as e:
                logger.debug("Briefing: Wetter fehlgeschlagen: %s", e)

        # --- Kalender ---
        if self._calendar:
            try:
                events = self._calendar.get_today()
                if events:
                    lines = ["📅 Termine heute:"]
                    for ev in events:
                        lines.append(f"  {ev.format_short()}")
                    sections.append("\n".join(lines))
            except Exception as e:
                logger.debug("Briefing: Kalender fehlgeschlagen: %s", e)

        # --- Erinnerungen ---
        if self._reminder_store:
            try:
                pending = self._reminder_store.get_pending()
                # Nur heutige und überfällige
                now = datetime.now(timezone.utc)
                today_end = datetime(
                    now.year, now.month, now.day, 23, 59, 59,
                    tzinfo=timezone.utc,
                )
                relevant = [
                    r for r in pending
                    if r.due_at <= today_end
                ]
                if relevant:
                    lines = ["⏰ Offene Erinnerungen:"]
                    for r in relevant:
                        local_time = r.due_at.astimezone()
                        lines.append(
                            f"  #{r.id} – {r.message} (fällig: {local_time.strftime('%H:%M')})"
                        )
                    sections.append("\n".join(lines))
            except Exception as e:
                logger.debug("Briefing: Erinnerungen fehlgeschlagen: %s", e)

        # --- Zusammenbauen ---
        if not sections:
            return ""

        greeting = "☀️ Guten Morgen! Dein Briefing für heute:\n"
        footer = "\nSchönen Tag! 🌿"

        return greeting + "\n\n".join(sections) + footer

    def _run(self) -> None:
        """Thread-Hauptschleife: prüft ob Briefing-Zeit erreicht ist."""
        while self._running:
            try:
                now = datetime.now()

                # Mitternacht: Flag zurücksetzen
                if self._briefing_sent_today and self._briefing_sent_today != now.date():
                    self._briefing_sent_today = None

                # Briefing senden wenn Zeit passt und noch nicht gesendet
                if (
                    now.hour == self._briefing_hour
                    and now.minute == self._briefing_minute
                    and self._briefing_sent_today != now.date()
                ):
                    briefing = self.build_briefing()
                    if briefing:
                        try:
                            self._send_briefing(briefing)
                            logger.info("Daily Briefing gesendet")
                        except Exception as e:
                            logger.error("Briefing senden fehlgeschlagen: %s", e)
                    self._briefing_sent_today = now.date()

            except Exception as e:
                logger.error("BriefingScheduler Fehler: %s", e)

            # 30 Sekunden schlafen (in kleinen Schritten für Shutdown)
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)
