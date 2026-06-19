"""WeatherCommandHandler-Mixin: Briefing, Training (Berry-Gym), PRs.

Phase 106 (Modul-Entflechtung): aus ``weather_commands.py`` ausgelagert.
"""

from __future__ import annotations

import logging

from elder_berry.comms.commands.base import CommandResult, user_friendly_error
from elder_berry.comms.commands.weather._base import WeatherMixinBase
from elder_berry.comms.commands.weather.patterns import TRAINING_PATTERN

logger = logging.getLogger(__name__)


class MiscMixin(WeatherMixinBase):
    """Tagesbriefing + Fitness-Daten (Berry-Gym)."""

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
