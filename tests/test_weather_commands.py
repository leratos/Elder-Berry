"""Tests: WeatherCommandHandler – Patterns für wiederkehrende Erinnerungen."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from elder_berry.comms.commands.weather_commands import (
    RECURRING_DAILY_PATTERN,
    RECURRING_MONTHLY_PATTERN,
    RECURRING_WEEKDAY_PATTERN,
    RECURRING_WEEKLY_PATTERN,
    REMINDER_DATE_PATTERN,
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
# Phase 81: Einmalige Erinnerungen mit Wochentag / Datum / morgen
# ---------------------------------------------------------------------------


BERLIN = ZoneInfo("Europe/Berlin")


class TestReminderDatePattern:
    def test_am_montag(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am Montag um 09:00: Bad Belzig anrufen"
        )
        assert m is not None
        assert m.group(1).lower() == "montag"
        assert m.group(2) is None
        assert m.group(3) is None
        assert m.group(4) == "09:00"
        assert m.group(5) == "Bad Belzig anrufen"

    def test_naechsten_montag(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich nächsten Montag um 9:00: Test"
        )
        assert m is not None
        assert m.group(1).lower() == "montag"

    def test_kommenden_freitag(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich kommenden Freitag um 17:30: Feierabend"
        )
        assert m is not None
        assert m.group(1).lower() == "freitag"

    def test_weekday_ohne_praefix(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich Montag um 9:00: Test"
        )
        assert m is not None
        assert m.group(1).lower() == "montag"

    def test_am_datum_kurz(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am 12.05. um 09:00: Mietvertrag"
        )
        assert m is not None
        assert m.group(2) == "12.05."
        assert m.group(4) == "09:00"

    def test_am_datum_mit_jahr(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am 12.05.2026 um 09:00: Lang"
        )
        assert m is not None
        assert m.group(2) == "12.05.2026"

    def test_morgen(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich morgen um 08:30: Brötchen"
        )
        assert m is not None
        assert m.group(3).lower() == "morgen"
        assert m.group(4) == "08:30"

    def test_uebermorgen(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich übermorgen um 14:00: Anruf"
        )
        assert m is not None
        assert m.group(3).lower() == "übermorgen"

    def test_uebermorgen_ascii(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich uebermorgen um 14:00: Anruf"
        )
        assert m is not None
        assert m.group(3).lower() == "uebermorgen"

    def test_ohne_nachricht(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am Montag um 9:00"
        )
        assert m is not None
        assert m.group(5) is None

    def test_recurring_jeden_matcht_NICHT(self):
        """'jeden Montag' ist wiederkehrend und gehört NICHT in dieses Pattern."""
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich jeden Montag um 9:00: Wochenbericht"
        )
        # Sollte nicht matchen, weil "jeden" weder als Praefix noch als
        # Wochentag akzeptiert ist -- so bleibt RECURRING_WEEKLY_PATTERN
        # zustaendig.
        assert m is None

    def test_kein_doppelter_match_mit_reminder_pattern(self):
        """Sanity: einfaches 'erinnere mich um 18:00' darf hier NICHT matchen."""
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich um 18:00: Wäsche"
        )
        assert m is None


class TestResolveOneOffTarget:
    """Resolver-Logik (Wochentag/Datum/morgen → Future-Datetime).

    Alle Tests verwenden einen festen 'now' (Freitag 2026-05-08 12:00 Berlin),
    damit Wochentagsberechnungen deterministisch sind.
    """

    @pytest.fixture
    def now(self):
        # Freitag, 8. Mai 2026, 12:00 Europe/Berlin
        return datetime(2026, 5, 8, 12, 0, tzinfo=BERLIN)

    def test_am_montag_resolves_to_next_monday(self, now):
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday="Montag",
            date_str=None,
            rel_day=None,
            time_str="09:00",
            tz=BERLIN,
            now=now,
        )
        # Freitag → Montag = +3 Tage = 2026-05-11
        assert due.date() == datetime(2026, 5, 11).date()
        assert due.hour == 9
        assert due.minute == 0
        assert due.tzinfo == BERLIN

    def test_today_weekday_with_future_time_uses_today(self, now):
        # Heute ist Freitag, Uhrzeit 18:00 noch in der Zukunft
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday="Freitag",
            date_str=None,
            rel_day=None,
            time_str="18:00",
            tz=BERLIN,
            now=now,
        )
        assert due.date() == now.date()

    def test_today_weekday_with_past_time_jumps_one_week(self, now):
        # Heute ist Freitag, Uhrzeit 09:00 schon vorbei
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday="Freitag",
            date_str=None,
            rel_day=None,
            time_str="09:00",
            tz=BERLIN,
            now=now,
        )
        assert due.date() == (now + timedelta(days=7)).date()

    def test_morgen(self, now):
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday=None,
            date_str=None,
            rel_day="morgen",
            time_str="08:30",
            tz=BERLIN,
            now=now,
        )
        assert due.date() == (now + timedelta(days=1)).date()
        assert due.hour == 8
        assert due.minute == 30

    def test_uebermorgen(self, now):
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday=None,
            date_str=None,
            rel_day="übermorgen",
            time_str="14:00",
            tz=BERLIN,
            now=now,
        )
        assert due.date() == (now + timedelta(days=2)).date()

    def test_date_ddmm_this_year_future(self, now):
        # 12.05. liegt nach dem 8.5. → dieses Jahr
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday=None,
            date_str="12.05.",
            rel_day=None,
            time_str="09:00",
            tz=BERLIN,
            now=now,
        )
        assert due.date() == datetime(2026, 5, 12).date()

    def test_date_ddmm_already_past_jumps_to_next_year(self, now):
        # 1.5. liegt VOR dem 8.5. → nächstes Jahr
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday=None,
            date_str="1.5.",
            rel_day=None,
            time_str="09:00",
            tz=BERLIN,
            now=now,
        )
        assert due.date() == datetime(2027, 5, 1).date()

    def test_date_with_explicit_past_year_raises(self, now):
        with pytest.raises(ValueError, match="Vergangenheit"):
            WeatherCommandHandler._resolve_one_off_target(
                weekday=None,
                date_str="1.1.2024",
                rel_day=None,
                time_str="09:00",
                tz=BERLIN,
                now=now,
            )

    def test_date_with_two_digit_year(self, now):
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday=None,
            date_str="12.05.27",
            rel_day=None,
            time_str="09:00",
            tz=BERLIN,
            now=now,
        )
        assert due.year == 2027


class TestReminderDateExecution:
    def test_happy_path_creates_reminder(self, handler, store):
        result = handler.execute(
            "reminder_date",
            "erinnere mich am Montag um 09:00: Bad Belzig anrufen",
        )
        assert result.success is True
        assert "⏰" in result.text
        assert "Bad Belzig anrufen" in result.text

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].message == "Bad Belzig anrufen"
        assert pending[0].recurrence is None  # einmalig, nicht wiederkehrend

    def test_morgen_creates_reminder(self, handler, store):
        result = handler.execute(
            "reminder_date",
            "erinnere mich morgen um 08:30: Brötchen",
        )
        assert result.success is True
        assert len(store.get_pending()) == 1

    def test_no_store_returns_error(self):
        handler = WeatherCommandHandler(reminder_store=None)
        result = handler.execute(
            "reminder_date",
            "erinnere mich am Montag um 9:00: Test",
        )
        assert result.success is False
        assert "nicht verfügbar" in result.text

    def test_invalid_format_returns_friendly_error(self, handler):
        result = handler.execute(
            "reminder_date",
            "erinnere mich am sankt-nimmerleins-tag um 9:00: Test",
        )
        assert result.success is False
        assert "Format nicht erkannt" in result.text

    def test_pattern_registered_in_handler(self, handler):
        names = [p[1] for p in handler.patterns]
        assert "reminder_date" in names
        # Reihenfolge: REMINDER_DATE_PATTERN muss vor REMINDER_PATTERN stehen
        # damit "erinnere mich am Montag um 9:00" nicht erst auf das einfache
        # REMINDER_PATTERN trifft (auch wenn das semantisch nicht matchen kann,
        # ist die Reihenfolge die Vertragsgarantie).
        date_idx = next(
            i for i, p in enumerate(handler.patterns) if p[1] == "reminder_date"
        )
        reminder_idx = next(
            i for i, p in enumerate(handler.patterns) if p[1] == "reminder"
        )
        assert date_idx < reminder_idx


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
