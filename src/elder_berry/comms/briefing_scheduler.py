"""BriefingScheduler – Tägliches Morgen-Briefing via Matrix.

Daemon-Thread der einmal täglich zu konfigurierbarer Uhrzeit ein
Briefing zusammenstellt und über einen Callback sendet.

Kombiniert: Wetter + Kalender + Erinnerungen + Geburtstage + E-Mails + Vor einem Jahr.

Wochenende: anderer Ton, Montag-Vorschau, keine Todos/Erinnerungen.

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
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.google_calendar import GoogleCalendarClient
    from elder_berry.tools.note_store import NoteStore
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.todo_store import TodoStore
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
        todo_store: TodoStore | None = None,
        email_client: IMAPEmailClient | None = None,
        contact_store: ContactStore | None = None,
        note_store: NoteStore | None = None,
        default_user_id: str = "",
        briefing_hour: int = 7,
        briefing_minute: int = 30,
    ) -> None:
        """
        Args:
            send_briefing: Callable(text) → sendet an Matrix. Muss thread-safe sein.
            calendar: GoogleCalendarClient (optional).
            weather: WeatherClient (optional).
            reminder_store: ReminderStore (optional).
            todo_store: TodoStore (optional, Phase 30).
            email_client: IMAPEmailClient (optional, Phase 34).
            contact_store: ContactStore (optional, Phase 34 – Geburtstage).
            note_store: NoteStore (optional, Phase 34 – Vor einem Jahr).
            default_user_id: Matrix-User-ID für TodoStore-/ContactStore-Abfrage.
            briefing_hour: Stunde des Briefings (0-23, Lokalzeit).
            briefing_minute: Minute des Briefings (0-59).
        """
        self._send_briefing = send_briefing
        self._calendar = calendar
        self._weather = weather
        self._reminder_store = reminder_store
        self._todo_store = todo_store
        self._email_client = email_client
        self._contact_store = contact_store
        self._note_store = note_store
        self._default_user_id = default_user_id
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

    def build_briefing(self, now: datetime | None = None) -> str:
        """Baut den Briefing-Text zusammen. Auch manuell aufrufbar.

        Args:
            now: Optionaler Zeitpunkt (für Tests). Default: datetime.now().

        Returns:
            Formatierter Briefing-Text oder leerer String wenn keine Daten.
        """
        if now is None:
            now = datetime.now()
        is_weekend = now.weekday() >= 5  # 5=Sa, 6=So

        sections: list[str] = []

        sections.extend(self._build_weather_section())
        sections.extend(self._build_calendar_section(now, is_weekend))
        sections.extend(self._build_birthday_section(now))

        if not is_weekend:
            sections.extend(self._build_reminder_section())
            sections.extend(self._build_todo_section())

        sections.extend(self._build_email_section())
        sections.extend(self._build_flashback_section(now))

        if not sections:
            return ""

        greeting, footer = self._get_greeting_footer(is_weekend)
        return greeting + "\n\n".join(sections) + footer

    # ------------------------------------------------------------------
    # Sektions-Builder (jeweils 0 oder 1 Element zurück)
    # ------------------------------------------------------------------

    def _build_weather_section(self) -> list[str]:
        if not self._weather:
            return []
        try:
            current = self._weather.get_current()
            weather_text = self._weather.format_current(current)
            try:
                days = self._weather.get_days(2)
                if len(days) >= 2:
                    tmrw = days[1]
                    weather_text += (
                        f"\n  Morgen: {tmrw.temp_min:.0f}–{tmrw.temp_max:.0f}°C, "
                        f"{tmrw.description}"
                    )
            except Exception:
                pass
            return [weather_text]
        except Exception as e:
            logger.debug("Briefing: Wetter fehlgeschlagen: %s", e)
            return []

    def _build_calendar_section(self, now: datetime,
                                is_weekend: bool) -> list[str]:
        if not self._calendar:
            return []
        try:
            events = self._calendar.get_today()
            lines: list[str] = []
            if events:
                lines.append("📅 Termine heute:")
                for ev in events:
                    lines.append(f"  {ev.format_short()}")

            # Wochenende: Montag-Vorschau
            if is_weekend:
                days_to_monday = 2 if now.weekday() == 5 else 1
                monday = now.date() + timedelta(days=days_to_monday)
                try:
                    mon_start = datetime(
                        monday.year, monday.month, monday.day,
                        tzinfo=timezone.utc,
                    )
                    mon_end = mon_start + timedelta(days=1)
                    monday_events = self._calendar.get_events_range(
                        mon_start, mon_end,
                    )
                    if monday_events:
                        lines.append("📅 Vorschau Montag:")
                        for ev in monday_events:
                            lines.append(f"  {ev.format_short()}")
                except Exception:
                    pass

            if lines:
                return ["\n".join(lines)]
            return []
        except Exception as e:
            logger.debug("Briefing: Kalender fehlgeschlagen: %s", e)
            return []

    def _build_birthday_section(self, now: datetime) -> list[str]:
        if not self._contact_store or not self._default_user_id:
            return []
        try:
            contacts = self._contact_store.get_birthdays_today(
                self._default_user_id, today=now.date(),
            )
            if not contacts:
                return []
            lines = ["🎂 Geburtstage heute:"]
            for c in contacts:
                age_text = ""
                if c.birthday and not c.birthday.startswith("0000"):
                    try:
                        birth_year = int(c.birthday[:4])
                        age = now.year - birth_year
                        age_text = f" (wird {age})"
                    except (ValueError, IndexError):
                        pass
                lines.append(f"  {c.name}{age_text}")
            return ["\n".join(lines)]
        except Exception as e:
            logger.debug("Briefing: Geburtstage fehlgeschlagen: %s", e)
            return []

    def _build_reminder_section(self) -> list[str]:
        if not self._reminder_store:
            return []
        try:
            pending = self._reminder_store.get_pending()
            utc_now = datetime.now(timezone.utc)
            today_end = datetime(
                utc_now.year, utc_now.month, utc_now.day, 23, 59, 59,
                tzinfo=timezone.utc,
            )
            relevant = [r for r in pending if r.due_at <= today_end]
            if not relevant:
                return []
            lines = ["⏰ Offene Erinnerungen:"]
            for r in relevant:
                local_time = r.due_at.astimezone()
                lines.append(
                    f"  #{r.id} – {r.message} "
                    f"(fällig: {local_time.strftime('%H:%M')})",
                )
            return ["\n".join(lines)]
        except Exception as e:
            logger.debug("Briefing: Erinnerungen fehlgeschlagen: %s", e)
            return []

    def _build_todo_section(self) -> list[str]:
        if not self._todo_store or not self._default_user_id:
            return []
        try:
            todo_text = self._todo_store.format_for_briefing(
                self._default_user_id,
            )
            if todo_text:
                return [todo_text]
            return []
        except Exception as e:
            logger.debug("Briefing: Todos fehlgeschlagen: %s", e)
            return []

    def _build_email_section(self) -> list[str]:
        if not self._email_client:
            return []
        try:
            count = self._email_client.get_unread_count()
            if count > 0:
                return [f"📧 {count} ungelesene E-Mail{'s' if count != 1 else ''}"]
            return []
        except Exception as e:
            logger.debug("Briefing: E-Mails fehlgeschlagen: %s", e)
            return []

    def _build_flashback_section(self, now: datetime) -> list[str]:
        if not self._note_store or not self._default_user_id:
            return []
        try:
            last_year = now.year - 1
            notes = self._note_store.get_notes_from_date(
                self._default_user_id, now.month, now.day, limit=3,
            )
            # Nur Notizen die mindestens ~11 Monate alt sind
            cutoff = now - timedelta(days=330)
            old_notes = [
                n for n in notes
                if n.created_at.replace(tzinfo=None) < cutoff.replace(tzinfo=None)
            ]
            if not old_notes:
                return []
            lines = ["📅 Vor einem Jahr:"]
            for n in old_notes:
                preview = n.content[:60] + ("..." if len(n.content) > 60 else "")
                year = n.created_at.year
                lines.append(f"  ({year}) {preview}")
            return ["\n".join(lines)]
        except Exception as e:
            logger.debug("Briefing: Flashback fehlgeschlagen: %s", e)
            return []

    @staticmethod
    def _get_greeting_footer(is_weekend: bool) -> tuple[str, str]:
        if is_weekend:
            return (
                "☀️ Schönes Wochenende! Hier dein entspanntes Briefing:\n",
                "\nGenieß den Tag! 🌿",
            )
        return (
            "☀️ Guten Morgen! Dein Briefing für heute:\n",
            "\nSchönen Tag! 🌿",
        )

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
