"""Tests: WeatherClient – Open-Meteo API Integration."""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.weather_client import (
    WeatherClient,
    WeatherData,
    WeatherForecast,
    WMO_DESCRIPTIONS,
    WMO_EMOJIS,
    _format_day_name,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_store(with_coords: bool = True):
    """Erstellt einen Mock-SecretStore mit oder ohne Wetter-Koordinaten."""
    store = MagicMock()
    if with_coords:
        def get_or_none(key):
            return {
                "weather_latitude": "52.52",
                "weather_longitude": "13.41",
                "weather_city": "Berlin",
            }.get(key)
        store.get_or_none.side_effect = get_or_none
    else:
        store.get_or_none.return_value = None
    return store


MOCK_CURRENT_RESPONSE = {
    "current": {
        "temperature_2m": 14.2,
        "apparent_temperature": 12.5,
        "relative_humidity_2m": 65,
        "wind_speed_10m": 12.3,
        "weather_code": 2,
    },
}

MOCK_DAILY_RESPONSE_1DAY = {
    "daily": {
        "time": ["2026-03-17"],
        "temperature_2m_max": [16.5],
        "temperature_2m_min": [8.2],
        "precipitation_sum": [2.1],
        "precipitation_probability_max": [45],
        "weather_code": [61],
    },
}

MOCK_DAILY_RESPONSE_3DAYS = {
    "daily": {
        "time": ["2026-03-17", "2026-03-18", "2026-03-19"],
        "temperature_2m_max": [16.5, 18.0, 14.2],
        "temperature_2m_min": [8.2, 9.5, 6.0],
        "precipitation_sum": [2.1, 0.0, 5.3],
        "precipitation_probability_max": [45, 10, 80],
        "weather_code": [61, 1, 63],
    },
}


# ---------------------------------------------------------------------------
# DTO-Tests
# ---------------------------------------------------------------------------

class TestWeatherData:
    def test_frozen(self):
        wd = WeatherData(
            temperature=14.2, apparent_temperature=12.5,
            humidity=65, wind_speed=12.3,
            weather_code=2, description="Teilweise bewölkt", city="Berlin",
        )
        with pytest.raises(AttributeError):
            wd.temperature = 99.0

    def test_fields(self):
        wd = WeatherData(
            temperature=14.2, apparent_temperature=12.5,
            humidity=65, wind_speed=12.3,
            weather_code=2, description="Teilweise bewölkt", city="Berlin",
        )
        assert wd.temperature == 14.2
        assert wd.apparent_temperature == 12.5
        assert wd.humidity == 65
        assert wd.wind_speed == 12.3
        assert wd.weather_code == 2
        assert wd.description == "Teilweise bewölkt"
        assert wd.city == "Berlin"


class TestWeatherForecast:
    def test_frozen(self):
        fc = WeatherForecast(
            date=date(2026, 3, 17), temp_min=8.2, temp_max=16.5,
            precipitation_mm=2.1, precipitation_probability=45,
            weather_code=61, description="Leichter Regen", city="Berlin",
        )
        with pytest.raises(AttributeError):
            fc.temp_min = 0.0

    def test_fields(self):
        fc = WeatherForecast(
            date=date(2026, 3, 17), temp_min=8.2, temp_max=16.5,
            precipitation_mm=2.1, precipitation_probability=45,
            weather_code=61, description="Leichter Regen", city="Berlin",
        )
        assert fc.date == date(2026, 3, 17)
        assert fc.temp_min == 8.2
        assert fc.temp_max == 16.5
        assert fc.precipitation_mm == 2.1
        assert fc.precipitation_probability == 45
        assert fc.weather_code == 61
        assert fc.city == "Berlin"


# ---------------------------------------------------------------------------
# WMO-Mappings
# ---------------------------------------------------------------------------

class TestWMOMappings:
    def test_descriptions_contains_main_codes(self):
        for code in [0, 1, 2, 3, 45, 61, 63, 65, 71, 80, 95]:
            assert code in WMO_DESCRIPTIONS, f"Code {code} fehlt in WMO_DESCRIPTIONS"

    def test_emojis_contains_main_codes(self):
        for code in [0, 1, 2, 3, 45, 61, 63, 65, 71, 80, 95]:
            assert code in WMO_EMOJIS, f"Code {code} fehlt in WMO_EMOJIS"

    def test_descriptions_all_strings(self):
        for code, desc in WMO_DESCRIPTIONS.items():
            assert isinstance(desc, str), f"Code {code}: {desc!r} ist kein String"

    def test_emojis_all_strings(self):
        for code, emoji in WMO_EMOJIS.items():
            assert isinstance(emoji, str), f"Code {code}: {emoji!r} ist kein String"


# ---------------------------------------------------------------------------
# get_current()
# ---------------------------------------------------------------------------

class TestGetCurrent:
    def test_success(self):
        store = _make_store()
        client = WeatherClient(secret_store=store)

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_CURRENT_RESPONSE
        mock_resp.raise_for_status.return_value = None

        with patch("elder_berry.tools.weather_client.WeatherClient._get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get.return_value = mock_resp
            mock_get.return_value = mock_http

            result = client.get_current()

        assert isinstance(result, WeatherData)
        assert result.temperature == 14.2
        assert result.apparent_temperature == 12.5
        assert result.humidity == 65
        assert result.wind_speed == 12.3
        assert result.weather_code == 2
        assert result.description == "Teilweise bewölkt"
        assert result.city == "Berlin"

    def test_no_coordinates_raises(self):
        store = _make_store(with_coords=False)
        client = WeatherClient(secret_store=store)

        with pytest.raises(ValueError, match="Wetter-Standort nicht konfiguriert"):
            client.get_current()

    def test_api_error_raises(self):
        store = _make_store()
        client = WeatherClient(secret_store=store)

        mock_resp = MagicMock()
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Error", request=MagicMock(), response=MagicMock(),
        )

        with patch("elder_berry.tools.weather_client.WeatherClient._get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get.return_value = mock_resp
            mock_get.return_value = mock_http

            with pytest.raises(httpx.HTTPStatusError):
                client.get_current()


# ---------------------------------------------------------------------------
# get_today() / get_days()
# ---------------------------------------------------------------------------

class TestGetToday:
    def test_returns_single_forecast(self):
        store = _make_store()
        client = WeatherClient(secret_store=store)

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_DAILY_RESPONSE_1DAY
        mock_resp.raise_for_status.return_value = None

        with patch("elder_berry.tools.weather_client.WeatherClient._get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get.return_value = mock_resp
            mock_get.return_value = mock_http

            result = client.get_today()

        assert isinstance(result, WeatherForecast)
        assert result.date == date(2026, 3, 17)
        assert result.temp_min == 8.2
        assert result.temp_max == 16.5


class TestGetDays:
    def test_returns_3_forecasts(self):
        store = _make_store()
        client = WeatherClient(secret_store=store)

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_DAILY_RESPONSE_3DAYS
        mock_resp.raise_for_status.return_value = None

        with patch("elder_berry.tools.weather_client.WeatherClient._get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get.return_value = mock_resp
            mock_get.return_value = mock_http

            result = client.get_days(3)

        assert len(result) == 3
        assert all(isinstance(f, WeatherForecast) for f in result)
        assert result[0].date == date(2026, 3, 17)
        assert result[1].date == date(2026, 3, 18)
        assert result[2].date == date(2026, 3, 19)

    def test_clamps_to_7(self):
        """days > 7 wird auf 7 begrenzt."""
        store = _make_store()
        client = WeatherClient(secret_store=store)

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_DAILY_RESPONSE_3DAYS
        mock_resp.raise_for_status.return_value = None

        with patch("elder_berry.tools.weather_client.WeatherClient._get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get.return_value = mock_resp
            mock_get.return_value = mock_http

            # Wird nicht 99 Tage abfragen, sondern clampt auf 7
            client.get_days(99)

            call_args = mock_http.get.call_args
            assert call_args[1]["params"]["forecast_days"] == "7"


# ---------------------------------------------------------------------------
# format_current() / format_forecast()
# ---------------------------------------------------------------------------

class TestFormatCurrent:
    def test_contains_emoji_temp_city(self):
        client = WeatherClient(secret_store=_make_store())
        data = WeatherData(
            temperature=14.2, apparent_temperature=12.5,
            humidity=65, wind_speed=12.3,
            weather_code=2, description="Teilweise bewölkt", city="Berlin",
        )
        text = client.format_current(data)
        assert "Berlin" in text
        assert "14.2°C" in text
        assert "⛅" in text  # Emoji für Code 2
        assert "12.5°C" in text  # Gefühlt
        assert "12 km/h" in text  # Wind
        assert "65%" in text  # Luftfeuchtigkeit

    def test_unknown_code_gets_default_emoji(self):
        client = WeatherClient(secret_store=_make_store())
        data = WeatherData(
            temperature=10.0, apparent_temperature=8.0,
            humidity=50, wind_speed=5.0,
            weather_code=999, description="Code 999", city="Test",
        )
        text = client.format_current(data)
        assert "🌡️" in text  # Default-Emoji


class TestFormatForecast:
    def test_contains_date_minmax_precipitation(self):
        client = WeatherClient(secret_store=_make_store())
        forecasts = [
            WeatherForecast(
                date=date(2026, 3, 17), temp_min=8.2, temp_max=16.5,
                precipitation_mm=2.1, precipitation_probability=45,
                weather_code=61, description="Leichter Regen", city="Berlin",
            ),
        ]
        text = client.format_forecast(forecasts)
        assert "Berlin" in text
        assert "8–17°C" in text or "8–16°C" in text  # temp_min/max gerundet
        assert "2.1mm" in text
        assert "45%" in text

    def test_empty_forecasts(self):
        client = WeatherClient(secret_store=_make_store())
        text = client.format_forecast([])
        assert "Keine Vorhersage" in text

    def test_no_rain_no_rain_info(self):
        """Kein Niederschlag → kein Regen-Info angezeigt."""
        client = WeatherClient(secret_store=_make_store())
        forecasts = [
            WeatherForecast(
                date=date(2026, 3, 18), temp_min=9.5, temp_max=18.0,
                precipitation_mm=0.0, precipitation_probability=10,
                weather_code=1, description="Überwiegend klar", city="Berlin",
            ),
        ]
        text = client.format_forecast(forecasts)
        assert "🌧️" not in text


# ---------------------------------------------------------------------------
# _format_day_name()
# ---------------------------------------------------------------------------

class TestFormatDayName:
    def test_today(self):
        assert _format_day_name(date.today()) == "Heute"

    def test_tomorrow(self):
        from datetime import timedelta
        assert _format_day_name(date.today() + timedelta(days=1)) == "Morgen"

    def test_other_day(self):
        # Ein festes Datum: 2026-03-20 ist ein Freitag
        result = _format_day_name(date(2026, 3, 20))
        assert "Fr" in result
        assert "20.03." in result
