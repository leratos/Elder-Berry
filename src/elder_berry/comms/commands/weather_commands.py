"""WeatherCommandHandler -- Wetter, Timer, Erinnerungen, Briefing, Training, PRs.

Extrahiert aus remote_commands.py (Refactoring).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandResult,
    user_friendly_error,
)

if TYPE_CHECKING:
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.tools.gym_data import GymDataClient
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient

logger = logging.getLogger(__name__)

# Regex für Training-Subcommands: "training details", "training woche"
TRAINING_PATTERN = re.compile(
    r"^training\s+(details|woche|week|letzte[sr]?)$",
    re.IGNORECASE,
)

# Regex: "wetter morgen", "wetter woche", "wetter 3" (Tage), "wetter übermorgen"
WEATHER_PATTERN = re.compile(
    r"^wetter\s+(morgen|heute|woche|übermorgen|uebermorgen|(\d{1,2}))$",
    re.IGNORECASE,
)

# Regex: "wetter in Leipzig", "wie ist das wetter in Berlin morgen",
# "wetter Berlin" (Ort ohne Präposition – Negativliste für Zeitwörter)
_WEATHER_TIME_WORDS = r"(?:morgen|heute|übermorgen|uebermorgen|woche|draußen)"
WEATHER_LOCATION_PATTERN = re.compile(
    r"(?:wetter|temperatur).*?(?:\s+in\s+([A-ZÄÖÜa-zäöüß][\w\s\-]+?)"
    r"|\s+(?!"
    + _WEATHER_TIME_WORDS
    + r"(?:\s|$))([A-ZÄÖÜ][\wäöüß\-]+(?:\s+[A-ZÄÖÜ][\wäöüß\-]+)*))"
    r"(?:\s+(?:morgen|heute|übermorgen|uebermorgen|woche|\d{1,2}))?$",
    re.IGNORECASE,
)

# Regex: "timer 20 min", "timer 5 min", "timer 1 stunde", "timer 90 sekunden"
TIMER_PATTERN = re.compile(
    r"^timer\s+(\d+)\s*(min(?:uten?)?|h(?:ours?)?|stunden?|sek(?:unden?)?|s|m)$",
    re.IGNORECASE,
)

# Regex: "erinnere mich um 18:00: Wäsche", "erinnere mich in 2 stunden: Kuchen"
REMINDER_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"(?:um\s+(\d{1,2}:\d{2})|in\s+(\d+)\s*(min(?:uten?)?|stunden?|h))"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# Regex: "lösche erinnerung 3", "lösche alle erinnerungen"
REMINDER_DELETE_PATTERN = re.compile(
    r"(?:lösche?|entferne?|cancel)\s+(?:erinnerung(?:en)?|timer|reminder)\s*(\d+)?|"
    r"(?:erinnerung(?:en)?|timer)\s+(?:löschen|lösche|entferne)(?:\s+(\d+))?|"
    r"(?:lösche?|entferne?)\s+alle\s+(?:erinnerung(?:en)?|timer)",
    re.IGNORECASE,
)

# --- Wiederkehrende Erinnerungen ---

_WEEKDAY_NAMES = r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"

# "erinnere mich jeden montag um 9:00: Wochenbericht"
RECURRING_WEEKLY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"jede[nrm]?\s+(" + _WEEKDAY_NAMES + r")\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich täglich um 8:00: Standup"
RECURRING_DAILY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"t[äa]glich\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich werktags um 7:30: Aufstehen"
RECURRING_WEEKDAY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"werktags\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnere mich jeden 1. um 10:00: Miete"
RECURRING_MONTHLY_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"jede[nrm]?\s+(\d{1,2})\.\s+"
    r"um\s+(\d{1,2}:\d{2})"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)


def _parse_duration(amount: int, unit: str) -> timedelta:
    """Parst Zeiteinheiten in timedelta.

    Unterstützt: min/minuten/m, stunde/stunden/h, sek/sekunden/s.
    """
    from datetime import timedelta

    u = unit.lower().rstrip(".")
    if u in ("min", "minuten", "minute", "m"):
        return timedelta(minutes=amount)
    if u in ("h", "hours", "hour", "stunde", "stunden"):
        return timedelta(hours=amount)
    if u in ("sek", "sekunden", "sekunde", "s"):
        return timedelta(seconds=amount)

    raise ValueError(f"Unbekannte Zeiteinheit: {unit}")


class WeatherCommandHandler(CommandHandler):
    """Handler für Wetter, Timer, Erinnerungen, Briefing, Training, PRs."""

    def __init__(
        self,
        weather: WeatherClient | None = None,
        reminder_store: ReminderStore | None = None,
        briefing_scheduler: BriefingScheduler | None = None,
        gym_client: GymDataClient | None = None,
        get_timezone: Callable[[], str] | None = None,
    ) -> None:
        self._weather = weather
        self._reminder_store = reminder_store
        self._briefing_scheduler = briefing_scheduler
        self._gym_client = gym_client
        self._get_timezone = get_timezone or (lambda: "Europe/Berlin")

    @property
    def simple_commands(self) -> set[str]:
        return {"wetter", "erinnerungen", "briefing", "training", "prs"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (REMINDER_DELETE_PATTERN, "reminder_delete", False, False),
            (RECURRING_WEEKLY_PATTERN, "recurring_reminder", False, False),
            (RECURRING_DAILY_PATTERN, "recurring_reminder", False, False),
            (RECURRING_WEEKDAY_PATTERN, "recurring_reminder", False, False),
            (RECURRING_MONTHLY_PATTERN, "recurring_reminder", False, False),
            (WEATHER_PATTERN, "wetter", False, False),
            (WEATHER_LOCATION_PATTERN, "wetter", False, True),
            (TIMER_PATTERN, "timer", False, False),
            (REMINDER_PATTERN, "reminder", False, False),
            (TRAINING_PATTERN, "training", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "wetter [heute|morgen|woche|<N>]: Wetterabfrage und Vorhersage",
            "timer <dauer>: Timer setzen (z.B. timer 20 min, timer 1 stunde)",
            "erinnere mich um/in <zeit>: <nachricht>: Erinnerung setzen",
            "erinnere mich jeden <tag> um <zeit>: <nachricht>: Wiederkehrende Erinnerung",
            "erinnerungen: Offene Erinnerungen und Timer anzeigen",
            "lösche erinnerung <ID> / lösche alle erinnerungen: Erinnerung löschen",
            "briefing: Tagesübersicht (Wetter + Termine + Erinnerungen)",
            "training [details|woche]: Fitness-Daten (Berry-Gym)",
            "prs: Personal Records (letzte 30 Tage)",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "training": [
                "letztes training",
                "wie war mein training",
                "trainings woche",
                "was habe ich trainiert",
                "gym",
                "berry-gym",
                "fitness",
                "workout",
                "trainingsplan",
            ],
            "prs": [
                "personal record",
                "personal records",
                "bestleistung",
                "bestleistungen",
                "rekorde",
            ],
            "wetter": [
                "wie ist das wetter",
                "wie ist heute das wetter",
                "wie wird das wetter",
                "wetter draußen",
                "regnet es",
                "temperatur",
                "brauche ich einen schirm",
                "brauche ich eine jacke",
                "wie warm",
                "wie kalt",
                "wettervorhersage",
                "prognose",
                "regen",
                "sonnig",
                "sonne",
                "gewitter",
                "schnee",
                "regenschirm",
                "friert es",
                "wird es kalt",
                "wird es warm",
                "soll ich eine jacke mitnehmen",
                "wie warm ist es",
                "wie kalt ist es",
                "wetter in ",
            ],
            "erinnerungen": [
                "meine erinnerungen",
                "offene timer",
                "was steht an timer",
                "welche erinnerungen",
                "ausstehende erinnerungen",
                "laufende timer",
                "aktive erinnerungen",
            ],
            "briefing": [
                "guten morgen",
                "was steht heute an",
                "tagesübersicht",
                "daily briefing",
                "morgen briefing",
                "was gibt's neues",
                "was gibt es neues",
                "tagesbriefing",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "wetter":
            return self._cmd_weather(raw_text)

        if command == "timer":
            return self._cmd_timer(raw_text)

        if command == "reminder":
            return self._cmd_reminder(raw_text)

        if command == "recurring_reminder":
            return self._cmd_recurring_reminder(raw_text)

        if command == "erinnerungen":
            return self._cmd_erinnerungen(raw_text)

        if command == "reminder_delete":
            return self._cmd_reminder_delete(raw_text)

        if command == "briefing":
            return self._cmd_briefing()

        if command == "training":
            return self._cmd_training(raw_text)

        if command == "prs":
            return self._cmd_prs()

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    # ------------------------------------------------------------------
    # Wetter (Open-Meteo)
    # ------------------------------------------------------------------

    def _cmd_weather(self, raw_text: str) -> CommandResult:
        """Wetter abfragen: aktuell, morgen, woche, N Tage, optional mit Ort."""
        if not self._weather:
            return self.not_configured("wetter", "Wetter (Standort)", setup_step=6)

        try:
            normalized = raw_text.strip().lower()

            # Ort aus Text extrahieren ("wetter in Leipzig")
            location = self._extract_location(raw_text)

            # Zeitparameter parsen
            match = WEATHER_PATTERN.match(normalized)
            param = match.group(1) if match else None

            # Auch aus Location-Texten den Zeitparameter extrahieren
            if not param:
                for keyword in (
                    "übermorgen",
                    "uebermorgen",
                    "morgen",
                    "heute",
                    "woche",
                ):
                    if keyword in normalized:
                        param = keyword
                        break

            if param in ("übermorgen", "uebermorgen"):
                forecasts = (
                    self._weather.get_days(3)
                    if location is None
                    else self._weather.get_days(3, location=location)
                )
                if len(forecasts) >= 3:
                    text = self._weather.format_forecast([forecasts[2]])
                else:
                    text = self._weather.format_forecast(forecasts[-1:])
                return CommandResult(command="wetter", success=True, text=text)

            if param == "morgen":
                forecasts = (
                    self._weather.get_days(2)
                    if location is None
                    else self._weather.get_days(2, location=location)
                )
                if len(forecasts) >= 2:
                    text = self._weather.format_forecast([forecasts[1]])
                else:
                    text = self._weather.format_forecast(forecasts[-1:])
                return CommandResult(command="wetter", success=True, text=text)

            if param == "woche":
                forecasts = (
                    self._weather.get_days(7)
                    if location is None
                    else self._weather.get_days(7, location=location)
                )
                text = self._weather.format_forecast(forecasts)
                return CommandResult(command="wetter", success=True, text=text)

            if param == "heute":
                current = self._weather.get_current(location=location)
                today = self._weather.get_today(location=location)
                text = self._weather.format_current(current)
                text += "\n\n" + self._weather.format_forecast([today])
                return CommandResult(command="wetter", success=True, text=text)

            if match and match.group(2):
                days = int(match.group(2))
                forecasts = (
                    self._weather.get_days(days)
                    if location is None
                    else self._weather.get_days(days, location=location)
                )
                text = self._weather.format_forecast(forecasts)
                return CommandResult(command="wetter", success=True, text=text)

            # Default: aktuelles Wetter + Tagesprognose
            current = self._weather.get_current(location=location)
            today = self._weather.get_today(location=location)
            text = self._weather.format_current(current)
            text += "\n\n" + self._weather.format_forecast([today])
            return CommandResult(command="wetter", success=True, text=text)

        except Exception as e:
            logger.error("Wetter-Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="wetter",
                success=False,
                text=user_friendly_error(e, "Wetter"),
            )

    def _extract_location(
        self,
        raw_text: str,
    ) -> tuple[str, str, str] | None:
        """Extrahiert Ort aus Freitext und geocodet ihn.

        Returns:
            (lat, lon, city) oder None für Default-Standort.
        """
        match = WEATHER_LOCATION_PATTERN.search(raw_text)
        if not match:
            return None

        city_name = (match.group(1) or match.group(2) or "").strip()
        if not city_name:
            return None

        location = self._weather.geocode(city_name)
        if not location:
            logger.warning("Ort '%s' nicht gefunden, nutze Default", city_name)
            return None

        logger.info("Wetter-Ort erkannt: '%s' → %s", city_name, location[2])
        return location

    # ------------------------------------------------------------------
    # Timer & Erinnerungen
    # ------------------------------------------------------------------

    def _cmd_timer(self, raw_text: str) -> CommandResult:
        """Timer setzen: 'timer 20 min' -> Erinnerung in 20 Minuten."""
        if not self._reminder_store:
            return CommandResult(
                command="timer",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from datetime import timezone

            match = TIMER_PATTERN.match(raw_text.strip().lower())
            if not match:
                return CommandResult(
                    command="timer",
                    success=False,
                    text="Timer nicht erkannt. Beispiel: timer 20 min",
                )

            amount = int(match.group(1))
            unit = match.group(2)
            delta = _parse_duration(amount, unit)

            due = datetime.now(timezone.utc) + delta
            # User-ID ist hier nicht bekannt -> default User
            self._reminder_store.add("_timer_user", f"Timer ({amount} {unit})", due)

            local_time = due.astimezone()
            return CommandResult(
                command="timer",
                success=True,
                text=f"\u23f0 Timer gesetzt: {amount} {unit} (fällig um {local_time.strftime('%H:%M')})",
            )

        except Exception as e:
            return CommandResult(
                command="timer",
                success=False,
                text=user_friendly_error(e, "Timer"),
            )

    def _cmd_reminder(self, raw_text: str) -> CommandResult:
        """Erinnerung setzen: Uhrzeit oder Dauer + optionale Nachricht."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from datetime import timedelta, timezone, date as date_cls

            match = REMINDER_PATTERN.match(raw_text.strip().lower())
            if not match:
                return CommandResult(
                    command="reminder",
                    success=False,
                    text="Nicht erkannt. Beispiel: erinnere mich um 18:00: Wäsche\n"
                    "Oder: erinnere mich in 30 min: Kuchen aus dem Ofen",
                )

            time_str = match.group(1)  # "18:00" oder None
            amount_str = match.group(2)  # "2" oder None
            unit = match.group(3)  # "stunden" oder None
            message = match.group(4) or "Erinnerung"

            if time_str:
                # Absolute Uhrzeit
                hour, minute = map(int, time_str.split(":"))
                today = date_cls.today()
                from zoneinfo import ZoneInfo

                local_tz = ZoneInfo(self._get_timezone())
                due = datetime(
                    today.year, today.month, today.day, hour, minute, tzinfo=local_tz
                )
                # Wenn Uhrzeit schon vorbei: morgen
                if due < datetime.now(local_tz):
                    due += timedelta(days=1)
            else:
                # Relative Dauer
                amount = int(amount_str)
                delta = _parse_duration(amount, unit)
                due = datetime.now(timezone.utc) + delta

            self._reminder_store.add("_timer_user", message.strip(), due)
            local_time = due.astimezone()

            return CommandResult(
                command="reminder",
                success=True,
                text=f"\u23f0 Erinnerung gesetzt: {message.strip()} (fällig: {local_time.strftime('%d.%m. %H:%M')})",
            )

        except Exception as e:
            return CommandResult(
                command="reminder",
                success=False,
                text=user_friendly_error(e, "Erinnerung"),
            )

    def _cmd_erinnerungen(self, raw_text: str) -> CommandResult:
        """Offene Erinnerungen anzeigen."""
        if not self._reminder_store:
            return CommandResult(
                command="erinnerungen",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        pending = self._reminder_store.get_pending()
        text = self._reminder_store.format_pending(pending)
        return CommandResult(command="erinnerungen", success=True, text=text)

    def _cmd_reminder_delete(self, raw_text: str) -> CommandResult:
        """Erinnerung löschen: einzeln per ID oder alle."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder_delete",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            normalized = raw_text.strip().lower()

            # "lösche alle erinnerungen" → Bestätigung
            if "alle" in normalized:
                reminders = self._reminder_store.get_pending("_timer_user")
                count = len(reminders)
                if count == 0:
                    return CommandResult(
                        command="reminder_delete",
                        success=True,
                        text="✅ Keine offenen Erinnerungen vorhanden.",
                    )
                return CommandResult(
                    command="reminder_delete",
                    success=True,
                    text=f"🗑️ {count} Erinnerung{'en' if count != 1 else ''} "
                    "löschen? Bestätige mit 'ja'.",
                    pending_confirmation=True,
                    pending_data={
                        "action_type": "bulk_delete_reminders",
                        "count": count,
                    },
                )

            # ID extrahieren
            match = REMINDER_DELETE_PATTERN.match(normalized)
            if match:
                id_str = match.group(1) or match.group(2)
                if id_str:
                    rid = int(id_str)
                    self._reminder_store.cancel(rid)
                    return CommandResult(
                        command="reminder_delete",
                        success=True,
                        text=f"\u2705 Erinnerung #{rid} gelöscht.",
                    )

            return CommandResult(
                command="reminder_delete",
                success=False,
                text="Welche Erinnerung? Nutze: lösche erinnerung <ID> oder lösche alle erinnerungen",
            )

        except Exception as e:
            return CommandResult(
                command="reminder_delete",
                success=False,
                text=user_friendly_error(e, "Erinnerung löschen"),
            )

    def execute_delete_all_reminders(self) -> CommandResult:
        """Führt das Löschen aller Erinnerungen nach Bestätigung aus."""
        count = self._reminder_store.cancel_all("_timer_user")
        return CommandResult(
            command="reminder_delete",
            success=True,
            text=f"✅ {count} Erinnerung{'en' if count != 1 else ''} gelöscht.",
        )

    # ------------------------------------------------------------------
    # Wiederkehrende Erinnerungen
    # ------------------------------------------------------------------

    def _cmd_recurring_reminder(self, raw_text: str) -> CommandResult:
        """Wiederkehrende Erinnerung setzen."""
        if not self._reminder_store:
            return CommandResult(
                command="recurring_reminder",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from zoneinfo import ZoneInfo
            from elder_berry.tools.recurrence import (
                parse_recurrence,
            )

            normalized = raw_text.strip().lower()
            local_tz = ZoneInfo(self._get_timezone())

            # Weekly: "erinnere mich jeden montag um 9:00: Wochenbericht"
            m = RECURRING_WEEKLY_PATTERN.match(normalized)
            if m:
                day_name = m.group(1)
                time_str = m.group(2)
                message = (m.group(3) or "Erinnerung").strip()
                recurrence = parse_recurrence(f"jeden {day_name}")
                due = self._next_weekday_at(day_name, time_str, local_tz)
                return self._create_recurring(message, due, recurrence)

            # Daily: "erinnere mich täglich um 8:00: Standup"
            m = RECURRING_DAILY_PATTERN.match(normalized)
            if m:
                time_str = m.group(1)
                message = (m.group(2) or "Erinnerung").strip()
                due = self._today_or_tomorrow_at(time_str, local_tz)
                return self._create_recurring(message, due, "daily")

            # Weekdays: "erinnere mich werktags um 7:30: Aufstehen"
            m = RECURRING_WEEKDAY_PATTERN.match(normalized)
            if m:
                time_str = m.group(1)
                message = (m.group(2) or "Erinnerung").strip()
                due = self._next_weekday_at_time(time_str, local_tz)
                return self._create_recurring(message, due, "weekdays")

            # Monthly: "erinnere mich jeden 1. um 10:00: Miete"
            m = RECURRING_MONTHLY_PATTERN.match(normalized)
            if m:
                day = int(m.group(1))
                time_str = m.group(2)
                message = (m.group(3) or "Erinnerung").strip()
                due = self._next_monthly_at(day, time_str, local_tz)
                return self._create_recurring(message, due, f"monthly:{day}")

            return CommandResult(
                command="recurring_reminder",
                success=False,
                text="Format nicht erkannt. Beispiel: erinnere mich jeden montag um 9:00: Wochenbericht",
            )

        except Exception as e:
            return CommandResult(
                command="recurring_reminder",
                success=False,
                text=user_friendly_error(e, "Wiederkehrende Erinnerung"),
            )

    def _create_recurring(
        self,
        message: str,
        due: datetime,
        recurrence: str,
    ) -> CommandResult:
        """Erstellt eine wiederkehrende Erinnerung im Store."""
        from elder_berry.tools.recurrence import format_recurrence

        self._reminder_store.add(
            "_timer_user",
            message,
            due,
            recurrence=recurrence,
        )
        local_time = due.astimezone()
        rec_text = format_recurrence(recurrence)
        return CommandResult(
            command="recurring_reminder",
            success=True,
            text=(
                f"🔁 Wiederkehrende Erinnerung gesetzt: {message}\n"
                f"  Nächster Termin: {local_time.strftime('%d.%m. %H:%M')}\n"
                f"  Wiederholung: {rec_text}"
            ),
        )

    @staticmethod
    def _next_weekday_at(
        day_name: str,
        time_str: str,
        tz,
    ) -> datetime:
        """Berechnet den nächsten Wochentag mit Uhrzeit."""
        from elder_berry.tools.recurrence import _WEEKDAY_MAP

        target_iso = _WEEKDAY_MAP.get(day_name.lower())
        if not target_iso:
            raise ValueError(f"Unbekannter Wochentag: {day_name}")

        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)
        today_iso = now.isoweekday()  # Mo=1 .. So=7

        days_ahead = target_iso - today_iso
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0:
            # Heute, aber Uhrzeit schon vorbei → nächste Woche
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                days_ahead = 7

        target_date = (now + timedelta(days=days_ahead)).date()
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=tz,
        )

    @staticmethod
    def _today_or_tomorrow_at(time_str: str, tz) -> datetime:
        """Heute zur Uhrzeit, oder morgen wenn schon vorbei."""
        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _next_weekday_at_time(time_str: str, tz) -> datetime:
        """Nächster Werktag (Mo-Fr) zur angegebenen Uhrzeit."""
        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        # Vorspulen bis Werktag
        while candidate.weekday() >= 5:  # 5=Sa, 6=So
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _next_monthly_at(day: int, time_str: str, tz) -> datetime:
        """Nächster Monatstag zur angegebenen Uhrzeit."""
        import calendar

        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)

        # Diesen Monat versuchen
        max_day = calendar.monthrange(now.year, now.month)[1]
        target_day = min(day, max_day)
        candidate = datetime(
            now.year,
            now.month,
            target_day,
            hour,
            minute,
            tzinfo=tz,
        )
        if candidate > now:
            return candidate

        # Nächster Monat
        year = now.year
        month = now.month + 1
        if month > 12:
            month = 1
            year += 1
        max_day = calendar.monthrange(year, month)[1]
        target_day = min(day, max_day)
        return datetime(year, month, target_day, hour, minute, tzinfo=tz)

    # ------------------------------------------------------------------
    # Briefing
    # ------------------------------------------------------------------

    def _cmd_briefing(self) -> CommandResult:
        """Tagesübersicht: Wetter + Termine + Erinnerungen."""
        if not self._briefing_scheduler:
            return CommandResult(
                command="briefing",
                success=False,
                text="Briefing nicht verfügbar.",
            )

        try:
            text = self._briefing_scheduler.build_briefing()
            if not text:
                return CommandResult(
                    command="briefing",
                    success=True,
                    text="Kein Briefing verfügbar (keine Daten konfiguriert).",
                )
            return CommandResult(command="briefing", success=True, text=text)

        except Exception as e:
            logger.error("Briefing fehlgeschlagen: %s", e)
            return CommandResult(
                command="briefing",
                success=False,
                text=user_friendly_error(e, "Briefing"),
            )

    # ------------------------------------------------------------------
    # Phase 8: Fitness (Berry-Gym)
    # ------------------------------------------------------------------

    def _cmd_training(self, raw_text: str) -> CommandResult:
        """Trainingsdaten von Berry-Gym abrufen."""
        if not self._gym_client:
            return self.not_configured("training", "Berry-Gym", setup_step=7)

        normalized = raw_text.strip().lower()
        match = TRAINING_PATTERN.match(normalized)

        try:
            if match:
                sub = match.group(1).lower()
                if sub in ("details", "letztes", "letzter"):
                    training = self._gym_client.get_last_training()
                    if not training:
                        return CommandResult(
                            command="training",
                            success=True,
                            text="Kein Training gefunden.",
                        )
                    text = self._gym_client.format_last_training(training)
                    return CommandResult(command="training", success=True, text=text)

                if sub in ("woche", "week"):
                    trainings = self._gym_client.get_week()
                    text = self._gym_client.format_week(trainings)
                    return CommandResult(command="training", success=True, text=text)

            # Default: Summary
            summary = self._gym_client.get_summary()
            if not summary:
                return CommandResult(
                    command="training",
                    success=False,
                    text="Berry-Gym API nicht erreichbar.",
                )
            text = self._gym_client.format_summary(summary)
            return CommandResult(command="training", success=True, text=text)

        except Exception as e:
            logger.error("Berry-Gym Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="training",
                success=False,
                text=user_friendly_error(e, "Berry-Gym"),
            )

    def _cmd_prs(self) -> CommandResult:
        """Personal Records von Berry-Gym."""
        if not self._gym_client:
            return self.not_configured("prs", "Berry-Gym", setup_step=7)

        try:
            prs = self._gym_client.get_prs()
            text = self._gym_client.format_prs(prs)
            return CommandResult(command="prs", success=True, text=text)
        except Exception as e:
            logger.error("Berry-Gym PRs fehlgeschlagen: %s", e)
            return CommandResult(
                command="prs",
                success=False,
                text=user_friendly_error(e, "Berry-Gym"),
            )
