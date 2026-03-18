"""WeatherCommandHandler -- Wetter, Timer, Erinnerungen, Briefing, Training, PRs.

Extrahiert aus remote_commands.py (Refactoring).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

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

# Regex: "wetter morgen", "wetter woche", "wetter 3" (Tage)
WEATHER_PATTERN = re.compile(
    r"^wetter\s+(morgen|heute|woche|(\d{1,2}))$",
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
    ) -> None:
        self._weather = weather
        self._reminder_store = reminder_store
        self._briefing_scheduler = briefing_scheduler
        self._gym_client = gym_client

    @property
    def simple_commands(self) -> set[str]:
        return {"wetter", "erinnerungen", "briefing", "training", "prs"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (REMINDER_DELETE_PATTERN, "reminder_delete", False, False),
            (WEATHER_PATTERN, "wetter", False, False),
            (TIMER_PATTERN, "timer", False, False),
            (REMINDER_PATTERN, "reminder", False, False),
            (TRAINING_PATTERN, "training", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "training": ["letztes training", "wie war mein training", "trainings woche",
                          "was habe ich trainiert", "gym", "berry-gym", "fitness"],
            "prs": ["personal record", "personal records", "bestleistung", "bestleistungen", "rekorde"],
            "wetter": ["wie ist das wetter", "wetter draußen", "regnet es", "temperatur",
                        "brauche ich einen schirm", "brauche ich eine jacke", "wie warm",
                        "wie kalt", "wettervorhersage", "prognose"],
            "erinnerungen": ["meine erinnerungen", "offene timer", "was steht an timer",
                              "welche erinnerungen", "ausstehende erinnerungen"],
            "briefing": ["guten morgen", "was steht heute an", "tagesübersicht",
                          "daily briefing", "morgen briefing", "was gibt's neues"],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "wetter":
            return self._cmd_weather(raw_text)

        if command == "timer":
            return self._cmd_timer(raw_text)

        if command == "reminder":
            return self._cmd_reminder(raw_text)

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
        """Wetter abfragen: aktuell, morgen, woche oder N Tage."""
        if not self._weather:
            return CommandResult(
                command="wetter",
                success=False,
                text="Wetter nicht verfügbar (Standort nicht konfiguriert).",
            )

        try:
            normalized = raw_text.strip().lower()
            match = WEATHER_PATTERN.match(normalized)

            if match:
                param = match.group(1)
                if param == "morgen":
                    forecasts = self._weather.get_days(2)
                    if len(forecasts) >= 2:
                        text = self._weather.format_forecast([forecasts[1]])
                    else:
                        text = self._weather.format_forecast(forecasts[-1:])
                    return CommandResult(command="wetter", success=True, text=text)

                if param == "woche":
                    forecasts = self._weather.get_days(7)
                    text = self._weather.format_forecast(forecasts)
                    return CommandResult(command="wetter", success=True, text=text)

                if param == "heute":
                    # Aktuell + Tagesprognose
                    current = self._weather.get_current()
                    today = self._weather.get_today()
                    text = self._weather.format_current(current)
                    text += "\n\n" + self._weather.format_forecast([today])
                    return CommandResult(command="wetter", success=True, text=text)

                # Zahl: N Tage
                if match.group(2):
                    days = int(match.group(2))
                    forecasts = self._weather.get_days(days)
                    text = self._weather.format_forecast(forecasts)
                    return CommandResult(command="wetter", success=True, text=text)

            # Default: aktuelles Wetter + Tagesprognose
            current = self._weather.get_current()
            today = self._weather.get_today()
            text = self._weather.format_current(current)
            text += "\n\n" + self._weather.format_forecast([today])
            return CommandResult(command="wetter", success=True, text=text)

        except Exception as e:
            logger.error("Wetter-Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="wetter",
                success=False,
                text=f"Wetter-Abfrage fehlgeschlagen: {e}",
            )

    # ------------------------------------------------------------------
    # Timer & Erinnerungen
    # ------------------------------------------------------------------

    def _cmd_timer(self, raw_text: str) -> CommandResult:
        """Timer setzen: 'timer 20 min' -> Erinnerung in 20 Minuten."""
        if not self._reminder_store:
            return CommandResult(
                command="timer", success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from datetime import timedelta, timezone
            match = TIMER_PATTERN.match(raw_text.strip().lower())
            if not match:
                return CommandResult(
                    command="timer", success=False,
                    text="Format: timer <Zahl> <min/stunde/sek>",
                )

            amount = int(match.group(1))
            unit = match.group(2)
            delta = _parse_duration(amount, unit)

            due = datetime.now(timezone.utc) + delta
            # User-ID ist hier nicht bekannt -> default User
            reminder = self._reminder_store.add("_timer_user", f"Timer ({amount} {unit})", due)

            local_time = due.astimezone()
            return CommandResult(
                command="timer", success=True,
                text=f"\u23f0 Timer gesetzt: {amount} {unit} (fällig um {local_time.strftime('%H:%M')})",
            )

        except Exception as e:
            return CommandResult(
                command="timer", success=False,
                text=f"Timer fehlgeschlagen: {e}",
            )

    def _cmd_reminder(self, raw_text: str) -> CommandResult:
        """Erinnerung setzen: Uhrzeit oder Dauer + optionale Nachricht."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder", success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from datetime import timedelta, timezone, date as date_cls
            match = REMINDER_PATTERN.match(raw_text.strip().lower())
            if not match:
                return CommandResult(
                    command="reminder", success=False,
                    text="Format: erinnere mich um HH:MM: Nachricht / erinnere mich in N min: Nachricht",
                )

            time_str = match.group(1)    # "18:00" oder None
            amount_str = match.group(2)  # "2" oder None
            unit = match.group(3)        # "stunden" oder None
            message = match.group(4) or "Erinnerung"

            if time_str:
                # Absolute Uhrzeit
                hour, minute = map(int, time_str.split(":"))
                today = date_cls.today()
                from zoneinfo import ZoneInfo
                local_tz = ZoneInfo("Europe/Berlin")
                due = datetime(today.year, today.month, today.day, hour, minute,
                               tzinfo=local_tz)
                # Wenn Uhrzeit schon vorbei: morgen
                if due < datetime.now(local_tz):
                    due += timedelta(days=1)
            else:
                # Relative Dauer
                amount = int(amount_str)
                delta = _parse_duration(amount, unit)
                due = datetime.now(timezone.utc) + delta

            reminder = self._reminder_store.add("_timer_user", message.strip(), due)
            local_time = due.astimezone()

            return CommandResult(
                command="reminder", success=True,
                text=f"\u23f0 Erinnerung gesetzt: {message.strip()} (fällig: {local_time.strftime('%d.%m. %H:%M')})",
            )

        except Exception as e:
            return CommandResult(
                command="reminder", success=False,
                text=f"Erinnerung fehlgeschlagen: {e}",
            )

    def _cmd_erinnerungen(self, raw_text: str) -> CommandResult:
        """Offene Erinnerungen anzeigen."""
        if not self._reminder_store:
            return CommandResult(
                command="erinnerungen", success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        pending = self._reminder_store.get_pending()
        text = self._reminder_store.format_pending(pending)
        return CommandResult(command="erinnerungen", success=True, text=text)

    def _cmd_reminder_delete(self, raw_text: str) -> CommandResult:
        """Erinnerung löschen: einzeln per ID oder alle."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder_delete", success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            normalized = raw_text.strip().lower()

            # "lösche alle erinnerungen"
            if "alle" in normalized:
                count = self._reminder_store.cancel_all("_timer_user")
                return CommandResult(
                    command="reminder_delete", success=True,
                    text=f"\u2705 {count} Erinnerung(en) gelöscht.",
                )

            # ID extrahieren
            match = REMINDER_DELETE_PATTERN.match(normalized)
            if match:
                id_str = match.group(1) or match.group(2)
                if id_str:
                    rid = int(id_str)
                    self._reminder_store.cancel(rid)
                    return CommandResult(
                        command="reminder_delete", success=True,
                        text=f"\u2705 Erinnerung #{rid} gelöscht.",
                    )

            return CommandResult(
                command="reminder_delete", success=False,
                text="Welche Erinnerung? Nutze: lösche erinnerung <ID> oder lösche alle erinnerungen",
            )

        except Exception as e:
            return CommandResult(
                command="reminder_delete", success=False,
                text=f"Löschen fehlgeschlagen: {e}",
            )

    # ------------------------------------------------------------------
    # Briefing
    # ------------------------------------------------------------------

    def _cmd_briefing(self) -> CommandResult:
        """Tagesübersicht: Wetter + Termine + Erinnerungen."""
        if not self._briefing_scheduler:
            return CommandResult(
                command="briefing", success=False,
                text="Briefing nicht verfügbar.",
            )

        try:
            text = self._briefing_scheduler.build_briefing()
            if not text:
                return CommandResult(
                    command="briefing", success=True,
                    text="Kein Briefing verfügbar (keine Daten konfiguriert).",
                )
            return CommandResult(command="briefing", success=True, text=text)

        except Exception as e:
            logger.error("Briefing fehlgeschlagen: %s", e)
            return CommandResult(
                command="briefing", success=False,
                text=f"Briefing fehlgeschlagen: {e}",
            )

    # ------------------------------------------------------------------
    # Phase 8: Fitness (Berry-Gym)
    # ------------------------------------------------------------------

    def _cmd_training(self, raw_text: str) -> CommandResult:
        """Trainingsdaten von Berry-Gym abrufen."""
        if not self._gym_client:
            return CommandResult(
                command="training", success=False,
                text="Berry-Gym nicht konfiguriert.\n"
                     "Setup: SecretStore().set('berry_gym_api_token', '<token>')",
            )

        normalized = raw_text.strip().lower()
        match = TRAINING_PATTERN.match(normalized)

        try:
            if match:
                sub = match.group(1).lower()
                if sub in ("details", "letztes", "letzter"):
                    training = self._gym_client.get_last_training()
                    if not training:
                        return CommandResult(
                            command="training", success=True,
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
                    command="training", success=False,
                    text="Berry-Gym API nicht erreichbar.",
                )
            text = self._gym_client.format_summary(summary)
            return CommandResult(command="training", success=True, text=text)

        except Exception as e:
            logger.error("Berry-Gym Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="training", success=False,
                text=f"Berry-Gym Fehler: {e}",
            )

    def _cmd_prs(self) -> CommandResult:
        """Personal Records von Berry-Gym."""
        if not self._gym_client:
            return CommandResult(
                command="prs", success=False,
                text="Berry-Gym nicht konfiguriert.",
            )

        try:
            prs = self._gym_client.get_prs()
            text = self._gym_client.format_prs(prs)
            return CommandResult(command="prs", success=True, text=text)
        except Exception as e:
            logger.error("Berry-Gym PRs fehlgeschlagen: %s", e)
            return CommandResult(
                command="prs", success=False,
                text=f"Berry-Gym Fehler: {e}",
            )
