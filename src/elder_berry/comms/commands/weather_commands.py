"""WeatherCommandHandler -- Wetter, Timer, Erinnerungen, Briefing, Training, PRs.

Extrahiert aus remote_commands.py (Refactoring).

Phase 106 (Modul-Entflechtung): Die ``_cmd_*``-Implementierung liegt in Mixins
unter ``comms/commands/weather/`` (Core / Reminder / Recurring / Misc); die
Regex-Patterns + ``_parse_duration`` in ``weather/patterns.py``. Dieses Modul
bleibt der eine Plugin-Einstieg: ``WeatherCommandHandler`` erbt die Mixins und
hält die Routing-Tabellen (``patterns``/``simple_commands``/``keywords``/
``command_descriptions``), ``execute()`` und das ``PLUGIN``-Manifest. Plugin-
Name, ``priority`` und ``source_path`` (= dieser Dateiname) bleiben stabil; die
Patterns werden re-exportiert, damit Test-Importe heil bleiben.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
)
from elder_berry.comms.commands.weather.core import CoreWeatherMixin
from elder_berry.comms.commands.weather.misc import MiscMixin
from elder_berry.comms.commands.weather.patterns import (
    RECURRING_DAILY_PATTERN,
    RECURRING_MONTHLY_PATTERN,
    RECURRING_WEEKDAY_PATTERN,
    RECURRING_WEEKLY_PATTERN,
    REMINDER_DATE_PATTERN,
    REMINDER_DELETE_PATTERN,
    REMINDER_PATTERN,
    TIMER_PATTERN,
    TRAINING_PATTERN,
    WEATHER_LOCATION_PATTERN,
    WEATHER_PATTERN,
)
from elder_berry.comms.commands.weather.recurring import RecurringReminderMixin
from elder_berry.comms.commands.weather.reminders import ReminderMixin

if TYPE_CHECKING:
    import re

    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.tools.gym_data import GymDataClient
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient


class WeatherCommandHandler(
    CoreWeatherMixin,
    ReminderMixin,
    RecurringReminderMixin,
    MiscMixin,
):
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
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        return [
            (REMINDER_DELETE_PATTERN, "reminder_delete", False, False),
            (RECURRING_WEEKLY_PATTERN, "recurring_reminder", False, False),
            (RECURRING_DAILY_PATTERN, "recurring_reminder", False, False),
            (RECURRING_WEEKDAY_PATTERN, "recurring_reminder", False, False),
            (RECURRING_MONTHLY_PATTERN, "recurring_reminder", False, False),
            (REMINDER_DATE_PATTERN, "reminder_date", False, False),
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
            "erinnere mich am <tag>/<datum> um <zeit>: <nachricht>: "
            "Einmalige Erinnerung (z.B. am Montag, am 12.05., morgen)",
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

        if command == "reminder_date":
            return self._cmd_reminder_date(raw_text)

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


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_WEATHER = """Wetter:
  wetter / wetter morgen / wetter woche / wetter <N>
  wetter in <Ort> [morgen|woche]

Timer & Erinnerungen:
  timer 20 min / timer 1 stunde
  erinnere mich um 18:00: Waesche
  erinnere mich in 2 stunden: Kuchen
  erinnere mich am Montag um 09:00: Bad Belzig anrufen
  erinnere mich am 12.05. um 09:00: Mietvertrag
  erinnere mich morgen um 08:30: Broetchen
  erinnerungen / loesche erinnerung 3 / loesche alle erinnerungen

Wiederkehrende Erinnerungen:
  erinnere mich jeden montag um 9:00: Wochenbericht
  erinnere mich taeglich um 8:00: Standup
  erinnere mich werktags um 7:30: Aufstehen

Briefing:
  briefing -- Tagesuebersicht (Wetter + Termine + Erinnerungen)

Fitness (Berry-Gym):
  training / training details / training woche
  prs -- Personal Records (letzte 30 Tage)"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    """Konstruiert WeatherCommandHandler aus dem HandlerContext.

    Anders als z.B. NoteCommandHandler hat dieser Handler KEINE harte
    Service-Abhaengigkeit -- alle Services (weather, reminder_store,
    briefing_scheduler, gym_client) sind optional. Der Handler selbst
    macht graceful degradation: parse_command erkennt "wetter" auch
    ohne Client, execute liefert dann "nicht konfiguriert"-Meldung.

    Faktisch heisst das: Plugin liefert IMMER einen Handler. Nur
    Konzept-§3.4 hat das ueber-strikt formuliert (None bei fehlendem
    Service); fuer API-Clients ohne Konstruktor-Pflichtargument ist
    graceful degradation das richtige Pattern.
    """
    return WeatherCommandHandler(
        weather=ctx.weather,
        reminder_store=ctx.reminder_store,
        briefing_scheduler=ctx.briefing_scheduler,
        gym_client=ctx.gym_client,
    )


PLUGIN = CommandPlugin(
    name="weather",
    priority=15,
    category="wetter",
    help_section=HELP_SECTION_WEATHER,
    factory=_factory,
    conflicts=("calendar",),
)
