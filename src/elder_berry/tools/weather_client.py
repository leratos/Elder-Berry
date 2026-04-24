"""WeatherClient – Wetterdaten von Open-Meteo abrufen.

Liest aktuelles Wetter und Vorhersagen über die Open-Meteo API.
Kostenlos, kein API-Key nötig. Standort wird aus SecretStore geladen.

Verwendung:
    client = WeatherClient(secret_store=store)
    current = client.get_current()
    today = client.get_today()
    days = client.get_days(3)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
REQUEST_TIMEOUT = 10
DEFAULT_TIMEZONE = "Europe/Berlin"

# ---------------------------------------------------------------------------
# WMO Weather Codes → Beschreibung + Emoji
# ---------------------------------------------------------------------------

WMO_DESCRIPTIONS: dict[int, str] = {
    0: "Klar",
    1: "Überwiegend klar",
    2: "Teilweise bewölkt",
    3: "Bedeckt",
    45: "Nebel",
    48: "Gefrierender Nebel",
    51: "Leichter Nieselregen",
    53: "Mäßiger Nieselregen",
    55: "Dichter Nieselregen",
    56: "Leichter gefrierender Nieselregen",
    57: "Dichter gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Mäßiger Regen",
    65: "Starker Regen",
    66: "Leichter gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Mäßiger Schneefall",
    75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer",
    81: "Mäßige Regenschauer",
    82: "Heftige Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Heftige Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit leichtem Hagel",
    99: "Gewitter mit starkem Hagel",
}

WMO_EMOJIS: dict[int, str] = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌧️",
    56: "🌧️",
    57: "🌧️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "🌨️",
    73: "🌨️",
    75: "❄️",
    77: "❄️",
    80: "🌦️",
    81: "🌧️",
    82: "🌧️",
    85: "🌨️",
    86: "❄️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WeatherData:
    """Aktuelles Wetter (Snapshot)."""

    temperature: float
    apparent_temperature: float
    humidity: int
    wind_speed: float
    weather_code: int
    description: str
    city: str


@dataclass(frozen=True)
class WeatherForecast:
    """Tagesprognose."""

    date: date
    temp_min: float
    temp_max: float
    precipitation_mm: float
    precipitation_probability: int
    weather_code: int
    description: str
    city: str


# ---------------------------------------------------------------------------
# WeatherClient
# ---------------------------------------------------------------------------

class WeatherClient:
    """Open-Meteo Wetter-Client.

    Lazy-Init: httpx.Client wird erst beim ersten Request erstellt.
    Standort-Koordinaten aus SecretStore: weather_latitude, weather_longitude, weather_city.
    """

    def __init__(self, secret_store: SecretStore) -> None:
        self._store = secret_store
        self._client = None

    def _get_client(self):
        """Lazy-Init: httpx.Client mit Timeout."""
        if self._client is not None:
            return self._client

        import httpx

        self._client = httpx.Client(timeout=REQUEST_TIMEOUT)
        return self._client

    def _get_location(self) -> tuple[str, str, str]:
        """Lädt Standort-Koordinaten aus SecretStore.

        Returns:
            (latitude, longitude, city)

        Raises:
            ValueError: Wenn Koordinaten nicht konfiguriert sind.
        """
        lat = self._store.get_or_none("weather_latitude")
        lon = self._store.get_or_none("weather_longitude")
        city = self._store.get_or_none("weather_city") or "Unbekannt"

        if not lat or not lon:
            raise ValueError(
                "Wetter-Standort nicht konfiguriert. "
                "Bitte via SecretStore setzen:\n"
                "  store.set('weather_latitude', '52.52')\n"
                "  store.set('weather_longitude', '13.41')\n"
                "  store.set('weather_city', 'Berlin')"
            )

        return lat, lon, city

    def geocode(self, city_name: str) -> tuple[str, str, str] | None:
        """Stadtname → (latitude, longitude, display_name) via Open-Meteo Geocoding.

        Returns:
            Tuple (lat, lon, name) oder None wenn nicht gefunden.
        """
        client = self._get_client()
        try:
            resp = client.get(
                GEOCODING_URL,
                params={"name": city_name, "count": 1, "language": "de"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None
            r = results[0]
            name = r.get("name", city_name)
            country = r.get("country", "")
            display = f"{name}, {country}" if country else name
            return str(r["latitude"]), str(r["longitude"]), display
        except Exception as e:
            logger.error("Geocoding fehlgeschlagen für '%s': %s", city_name, e)
            return None

    def get_current(self, location: tuple[str, str, str] | None = None) -> WeatherData:
        """Aktuelles Wetter: Temperatur, Beschreibung, Wind, Luftfeuchtigkeit.

        Args:
            location: Optionales (lat, lon, city) Tuple. Default: SecretStore.
        """
        lat, lon, city = location or self._get_location()
        client = self._get_client()

        resp = client.get(
            API_BASE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                "timezone": DEFAULT_TIMEZONE,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        current = data["current"]
        code = int(current["weather_code"])

        return WeatherData(
            temperature=float(current["temperature_2m"]),
            apparent_temperature=float(current["apparent_temperature"]),
            humidity=int(current["relative_humidity_2m"]),
            wind_speed=float(current["wind_speed_10m"]),
            weather_code=code,
            description=WMO_DESCRIPTIONS.get(code, f"Code {code}"),
            city=city,
        )

    # get_today ist jetzt oberhalb von get_days definiert (mit location-Parameter)

    def get_today(self, location: tuple[str, str, str] | None = None) -> WeatherForecast:
        """Tagesprognose: Min/Max Temperatur, Niederschlag."""
        forecasts = self.get_days(1, location=location)
        return forecasts[0]

    def get_days(
        self, days: int = 3, *, location: tuple[str, str, str] | None = None,
    ) -> list[WeatherForecast]:
        """Mehrtagesprognose (max 7 Tage).

        Args:
            days: Anzahl Tage (1-7, wird auf 7 begrenzt).
            location: Optionales (lat, lon, city) Tuple. Default: SecretStore.

        Returns:
            Liste von WeatherForecast (ein Eintrag pro Tag).
        """
        days = max(1, min(days, 7))
        lat, lon, city = location or self._get_location()
        client = self._get_client()

        resp = client.get(
            API_BASE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weather_code",
                "timezone": DEFAULT_TIMEZONE,
                "forecast_days": str(days),
            },
        )
        resp.raise_for_status()
        data = resp.json()

        daily = data["daily"]
        forecasts = []

        for i in range(len(daily["time"])):
            code = int(daily["weather_code"][i])
            forecasts.append(
                WeatherForecast(
                    date=date.fromisoformat(daily["time"][i]),
                    temp_min=float(daily["temperature_2m_min"][i]),
                    temp_max=float(daily["temperature_2m_max"][i]),
                    precipitation_mm=float(daily["precipitation_sum"][i]),
                    precipitation_probability=int(daily["precipitation_probability_max"][i]),
                    weather_code=code,
                    description=WMO_DESCRIPTIONS.get(code, f"Code {code}"),
                    city=city,
                )
            )

        return forecasts

    def format_current(self, data: WeatherData) -> str:
        """Formatierter Text für Matrix (Emoji + Werte)."""
        emoji = WMO_EMOJIS.get(data.weather_code, "🌡️")
        lines = [
            f"{emoji} Wetter in {data.city}:",
            f"  {data.description}, {data.temperature:.1f}°C (gefühlt {data.apparent_temperature:.1f}°C)",
            f"  💨 Wind: {data.wind_speed:.0f} km/h",
            f"  💧 Luftfeuchtigkeit: {data.humidity}%",
        ]
        return "\n".join(lines)

    def format_forecast(self, forecasts: list[WeatherForecast]) -> str:
        """Formatierter Text für mehrtägige Prognose."""
        if not forecasts:
            return "Keine Vorhersage verfügbar."

        city = forecasts[0].city
        lines = [f"📅 Wettervorhersage für {city}:\n"]

        for fc in forecasts:
            emoji = WMO_EMOJIS.get(fc.weather_code, "🌡️")
            day_name = _format_day_name(fc.date)
            rain = ""
            if fc.precipitation_mm > 0 or fc.precipitation_probability > 30:
                rain = f"  🌧️ {fc.precipitation_mm:.1f}mm ({fc.precipitation_probability}%)"
            lines.append(
                f"  {emoji} {day_name}: {fc.temp_min:.0f}–{fc.temp_max:.0f}°C, "
                f"{fc.description}{rain}"
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_DAY_NAMES = {
    0: "Mo", 1: "Di", 2: "Mi", 3: "Do", 4: "Fr", 5: "Sa", 6: "So",
}


def _format_day_name(d: date) -> str:
    """Formatiert Datum als 'Mo 17.03.' mit Sondernamen für heute/morgen."""
    today = date.today()
    if d == today:
        return "Heute"
    from datetime import timedelta
    if d == today + timedelta(days=1):
        return "Morgen"
    day_abbr = _DAY_NAMES.get(d.weekday(), "??")
    return f"{day_abbr} {d.strftime('%d.%m.')}"
