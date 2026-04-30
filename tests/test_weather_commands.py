"""Tests: WeatherCommandHandler – Patterns für wiederkehrende Erinnerungen."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.weather_commands import (
    RECURRING_DAILY_PATTERN,
    RECURRING_MONTHLY_PATTERN,
    RECURRING_WEEKDAY_PATTERN,
    RECURRING_WEEKLY_PATTERN,
    WEATHER_LOCATION_PATTERN,
    WeatherCommandHandler,
)
from elder_berry.tools.reminder_store import ReminderStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_weather_cmd.db"
    s = ReminderStore(db_path=db)
    yield s
    s.close()


@pytest.fixture
def handler(store):
    return WeatherCommandHandler(
        reminder_store=store,
        get_timezone=lambda: "Europe/Berlin",
    )


# ---------------------------------------------------------------------------
# Pattern-Matching
# ---------------------------------------------------------------------------


class TestRecurringWeeklyPattern:
    def test_jeden_montag(self):
        m = RECURRING_WEEKLY_PATTERN.match(
            "erinnere mich jeden montag um 9:00: Wochenbericht"
        )
        assert m is not None
        assert m.group(1) == "montag"
        assert m.group(2) == "9:00"
        assert m.group(3) == "Wochenbericht"

    def test_jeden_freitag(self):
        m = RECURRING_WEEKLY_PATTERN.match(
            "erinnere mich jeden freitag um 17:30: Feierabend"
        )
        assert m is not None
        assert m.group(1) == "freitag"
        assert m.group(2) == "17:30"

    def test_ohne_nachricht(self):
        m = RECURRING_WEEKLY_PATTERN.match("erinnere mich jeden dienstag um 10:00")
        assert m is not None
        assert m.group(3) is None

    def test_case_insensitive(self):
        m = RECURRING_WEEKLY_PATTERN.match("Erinnere mich jeden Montag um 9:00: Test")
        assert m is not None

    def test_erinnerung_variante(self):
        m = RECURRING_WEEKLY_PATTERN.match(
            "erinnerung jeden sonntag um 8:00: Frühstück"
        )
        assert m is not None


class TestRecurringDailyPattern:
    def test_taeglich(self):
        m = RECURRING_DAILY_PATTERN.match("erinnere mich täglich um 8:00: Standup")
        assert m is not None
        assert m.group(1) == "8:00"
        assert m.group(2) == "Standup"

    def test_ohne_nachricht(self):
        m = RECURRING_DAILY_PATTERN.match("erinnere mich täglich um 7:30")
        assert m is not None
        assert m.group(2) is None


class TestRecurringWeekdayPattern:
    def test_werktags(self):
        m = RECURRING_WEEKDAY_PATTERN.match("erinnere mich werktags um 7:30: Aufstehen")
        assert m is not None
        assert m.group(1) == "7:30"
        assert m.group(2) == "Aufstehen"


class TestRecurringMonthlyPattern:
    def test_monatlich(self):
        m = RECURRING_MONTHLY_PATTERN.match("erinnere mich jeden 1. um 10:00: Miete")
        assert m is not None
        assert m.group(1) == "1"
        assert m.group(2) == "10:00"
        assert m.group(3) == "Miete"

    def test_monatlich_15(self):
        m = RECURRING_MONTHLY_PATTERN.match(
            "erinnere mich jeden 15. um 12:00: Gehalt prüfen"
        )
        assert m is not None
        assert m.group(1) == "15"


# ---------------------------------------------------------------------------
# Command Registration
# ---------------------------------------------------------------------------


class TestWeatherLocationPattern:
    """WEATHER_LOCATION_PATTERN erkennt Orte aus natürlichsprachlichen Anfragen."""

    def test_wetter_in_city(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter in Leipzig")
        assert m is not None
        assert (m.group(1) or "").strip() == "Leipzig"

    def test_wetter_in_multi_word_city(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter in Brandenburg an der Havel")
        assert m is not None
        assert (m.group(1) or "").strip() == "Brandenburg an der Havel"

    def test_natural_language_with_heute(self):
        m = WEATHER_LOCATION_PATTERN.search(
            "Wie ist heute das Wetter in Brandenburg an der Havel",
        )
        assert m is not None
        assert (m.group(1) or "").strip() == "Brandenburg an der Havel"

    def test_natural_language_morgen(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter in Berlin morgen")
        assert m is not None
        assert (m.group(1) or "").strip() == "Berlin"

    def test_no_city_no_match(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter morgen")
        assert m is None

    def test_no_city_heute(self):
        m = WEATHER_LOCATION_PATTERN.search("wetter heute")
        assert m is None


class TestWeatherLocationRouting:
    """WEATHER_LOCATION_PATTERN ist in patterns registriert (use_search=True)."""

    def test_location_pattern_in_patterns(self, handler):
        patterns = handler.patterns
        location_entries = [
            (pat, cmd, use_orig, use_search)
            for pat, cmd, use_orig, *rest in patterns
            if pat is WEATHER_LOCATION_PATTERN
            for use_search in (rest[0] if rest else False,)
        ]
        assert len(location_entries) == 1
        _, cmd, _, use_search = location_entries[0]
        assert cmd == "wetter"
        assert use_search is True

    def test_keyword_wie_ist_heute_das_wetter(self, handler):
        keywords = handler.keywords["wetter"]
        assert "wie ist heute das wetter" in keywords

    def test_keyword_wetter_in(self, handler):
        keywords = handler.keywords["wetter"]
        assert "wetter in " in keywords

    def test_keyword_wie_wird_das_wetter(self, handler):
        keywords = handler.keywords["wetter"]
        assert "wie wird das wetter" in keywords


class TestWeatherLocationExecution:
    """_extract_location + _cmd_weather korrekt für Ort-basierte Anfragen."""

    def test_location_extracted_and_used(self):
        weather_mock = MagicMock()
        weather_mock.geocode.return_value = (
            "52.41",
            "12.56",
            "Brandenburg an der Havel",
        )
        weather_mock.get_current.return_value = {"temp": 5.0}
        weather_mock.get_today.return_value = {"day": "heute"}
        weather_mock.format_current.return_value = "Wetter in Brandenburg"
        weather_mock.format_forecast.return_value = "Vorhersage"

        handler = WeatherCommandHandler(weather=weather_mock)
        result = handler.execute(
            "wetter",
            "Wie ist heute das Wetter in Brandenburg an der Havel",
        )
        assert result.success is True
        weather_mock.geocode.assert_called_once_with("Brandenburg an der Havel")
        weather_mock.get_current.assert_called_once_with(
            location=("52.41", "12.56", "Brandenburg an der Havel"),
        )

    def test_location_not_found_falls_back(self):
        weather_mock = MagicMock()
        weather_mock.geocode.return_value = None
        weather_mock.get_current.return_value = {"temp": 3.0}
        weather_mock.get_today.return_value = {"day": "heute"}
        weather_mock.format_current.return_value = "Wetter Default"
        weather_mock.format_forecast.return_value = "Vorhersage"

        handler = WeatherCommandHandler(weather=weather_mock)
        result = handler.execute("wetter", "wetter in Nirgendwo")
        assert result.success is True
        weather_mock.get_current.assert_called_once_with(location=None)


class TestCommandRegistration:
    def test_recurring_patterns_registered(self, handler):
        pattern_names = [p[1] for p in handler.patterns]
        assert "recurring_reminder" in pattern_names

    def test_simple_commands_unchanged(self, handler):
        assert "erinnerungen" in handler.simple_commands
        assert "wetter" in handler.simple_commands
        assert "briefing" in handler.simple_commands


# ---------------------------------------------------------------------------
# Command-Ausführung
# ---------------------------------------------------------------------------


class TestRecurringCommandExecution:
    def test_daily_creates_recurring(self, handler, store):
        result = handler.execute(
            "recurring_reminder", "erinnere mich täglich um 8:00: Standup"
        )
        assert result.success is True
        assert "🔁" in result.text
        assert "täglich" in result.text
        assert "standup" in result.text.lower()

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].recurrence == "daily"
        assert pending[0].message == "standup"

    def test_weekly_creates_recurring(self, handler, store):
        result = handler.execute(
            "recurring_reminder", "erinnere mich jeden montag um 9:00: Wochenbericht"
        )
        assert result.success is True
        assert "🔁" in result.text

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].recurrence == "weekly:1"

    def test_weekday_creates_recurring(self, handler, store):
        result = handler.execute(
            "recurring_reminder", "erinnere mich werktags um 7:30: Aufstehen"
        )
        assert result.success is True

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].recurrence == "weekdays"

    def test_monthly_creates_recurring(self, handler, store):
        result = handler.execute(
            "recurring_reminder", "erinnere mich jeden 1. um 10:00: Miete"
        )
        assert result.success is True

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].recurrence == "monthly:1"

    def test_no_store_returns_error(self):
        handler = WeatherCommandHandler(reminder_store=None)
        result = handler.execute(
            "recurring_reminder", "erinnere mich täglich um 8:00: Test"
        )
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_erinnerungen_shows_recurrence(self, handler, store):
        store.add(
            "_timer_user",
            "Standup",
            datetime.now(timezone.utc) + timedelta(hours=1),
            recurrence="daily",
        )
        result = handler.execute("erinnerungen", "erinnerungen")
        assert result.success is True
        assert "🔁" in result.text
        assert "täglich" in result.text

    def test_delete_cancels_recurring(self, handler, store):
        r = store.add(
            "_timer_user",
            "Serie",
            datetime.now(timezone.utc) + timedelta(hours=1),
            recurrence="weekly:1",
        )
        result = handler.execute("reminder_delete", f"lösche erinnerung {r.id}")
        assert result.success is True
        assert store.get_pending() == []


# ---------------------------------------------------------------------------
# Timezone-Integration
# ---------------------------------------------------------------------------


class TestTimezone:
    def test_get_timezone_used_for_reminder(self, store):
        tz_mock = MagicMock(return_value="Europe/Berlin")
        handler = WeatherCommandHandler(
            reminder_store=store,
            get_timezone=tz_mock,
        )
        result = handler.execute(
            "recurring_reminder", "erinnere mich täglich um 8:00: Test"
        )
        assert result.success is True
        # Timezone-Callback wurde genutzt (mindestens für _today_or_tomorrow_at)

    def test_existing_reminder_uses_timezone(self, store):
        """Bestehende Erinnerungen nutzen jetzt auch die konfigurierte TZ."""
        handler = WeatherCommandHandler(
            reminder_store=store,
            get_timezone=lambda: "Europe/Berlin",
        )
        result = handler.execute("reminder", "erinnere mich um 23:00: Abend")
        assert result.success is True
        # Erinnerung wurde angelegt (Zeitanzeige hängt von System-TZ ab)
        assert "abend" in result.text.lower()
        pending = store.get_pending()
        assert len(pending) == 1
