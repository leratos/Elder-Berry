"""Basis für die WeatherCommandHandler-Mixins (Phase 106).

Erbt von :class:`CommandHandler` (für ``not_configured`` etc.) und deklariert
die per Konstruktor injizierten Service-Felder für den Type-Checker. Hat keinen
eigenen ``__init__`` – ``WeatherCommandHandler`` setzt die Felder. Bleibt
abstrakt (``execute`` wird erst in der Shell-Klasse implementiert).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from elder_berry.comms.commands.base import CommandHandler

if TYPE_CHECKING:
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    from elder_berry.tools.gym_data import GymDataClient
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.weather_client import WeatherClient


class WeatherMixinBase(CommandHandler):
    """Stub-Basis: deklariert die DI-Felder + erbt CommandHandler-Helfer."""

    _weather: WeatherClient | None
    _reminder_store: ReminderStore | None
    _briefing_scheduler: BriefingScheduler | None
    _gym_client: GymDataClient | None
    _get_timezone: Callable[[], str]
