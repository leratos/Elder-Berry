"""WeatherCommandHandler-Mixin: Wetterabfrage (Open-Meteo).

Phase 106 (Modul-Entflechtung): aus ``weather_commands.py`` ausgelagert.
"""

from __future__ import annotations

import logging

from elder_berry.comms.commands.base import CommandResult, user_friendly_error
from elder_berry.comms.commands.weather._base import WeatherMixinBase
from elder_berry.comms.commands.weather.patterns import (
    WEATHER_LOCATION_PATTERN,
    WEATHER_PATTERN,
)

logger = logging.getLogger(__name__)


class CoreWeatherMixin(WeatherMixinBase):
    """Wetter abfragen: aktuell, morgen, woche, N Tage, optional mit Ort."""

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

        # Caller (_cmd_weather) filtert "if not self._weather: return".
        assert self._weather is not None
        location = self._weather.geocode(city_name)
        if not location:
            logger.warning("Ort '%s' nicht gefunden, nutze Default", city_name)
            return None

        logger.info("Wetter-Ort erkannt: '%s' → %s", city_name, location[2])
        return location
