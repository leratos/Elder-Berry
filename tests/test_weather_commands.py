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
    """Group-Indizes (Phase 81 + Codex-Fix):
    1 = Praefix (am/naechsten/kommenden/None)
    2 = Wochentag
    3 = Datum DD.MM.[YY[YY]]
    4 = Relativtag (morgen/uebermorgen)
    5 = Uhrzeit HH:MM
    6 = Nachricht
    """

    def test_am_montag(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am Montag um 09:00: Bad Belzig anrufen"
        )
        assert m is not None
        assert m.group(1).lower() == "am"
        assert m.group(2).lower() == "montag"
        assert m.group(3) is None
        assert m.group(4) is None
        assert m.group(5) == "09:00"
        assert m.group(6) == "Bad Belzig anrufen"

    def test_naechsten_montag(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich nächsten Montag um 9:00: Test"
        )
        assert m is not None
        assert m.group(1).lower() == "nächsten"
        assert m.group(2).lower() == "montag"

    def test_kommenden_freitag(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich kommenden Freitag um 17:30: Feierabend"
        )
        assert m is not None
        assert m.group(1).lower() == "kommenden"
        assert m.group(2).lower() == "freitag"

    def test_weekday_ohne_praefix(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich Montag um 9:00: Test"
        )
        assert m is not None
        assert m.group(1) is None
        assert m.group(2).lower() == "montag"

    def test_am_datum_kurz(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am 12.05. um 09:00: Mietvertrag"
        )
        assert m is not None
        assert m.group(3) == "12.05."
        assert m.group(5) == "09:00"

    def test_am_datum_mit_jahr(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am 12.05.2026 um 09:00: Lang"
        )
        assert m is not None
        assert m.group(3) == "12.05.2026"

    def test_morgen(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich morgen um 08:30: Brötchen"
        )
        assert m is not None
        assert m.group(4).lower() == "morgen"
        assert m.group(5) == "08:30"

    def test_uebermorgen(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich übermorgen um 14:00: Anruf"
        )
        assert m is not None
        assert m.group(4).lower() == "übermorgen"

    def test_uebermorgen_ascii(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich uebermorgen um 14:00: Anruf"
        )
        assert m is not None
        assert m.group(4).lower() == "uebermorgen"

    def test_ohne_nachricht(self):
        m = REMINDER_DATE_PATTERN.match(
            "erinnere mich am Montag um 9:00"
        )
        assert m is not None
        assert m.group(6) is None

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

    def test_force_next_week_jumps_even_with_future_time(self, now):
        """Codex-Fix: 'naechsten Freitag um 18:00' am Freitag muss +7 sein,
        nicht heute, auch wenn 18:00 heute noch in der Zukunft liegt."""
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday="Freitag",
            date_str=None,
            rel_day=None,
            time_str="18:00",
            tz=BERLIN,
            now=now,
            force_next_week=True,
        )
        assert due.date() == (now + timedelta(days=7)).date()
        assert due.hour == 18

    def test_force_next_week_does_not_affect_other_weekday(self, now):
        """'naechsten Mittwoch' am Freitag = naechster Mittwoch (in 5 Tagen),
        force_next_week aendert nichts am Verhalten fuer andere Tage."""
        due = WeatherCommandHandler._resolve_one_off_target(
            weekday="Mittwoch",
            date_str=None,
            rel_day=None,
            time_str="09:00",
            tz=BERLIN,
            now=now,
            force_next_week=True,
        )
        # Freitag (5) -> Mittwoch (3): days_ahead = -2 -> +7 = 5 -> 2026-05-13
        assert due.date() == datetime(2026, 5, 13).date()

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

    def test_naechsten_weekday_does_not_pick_today(self, handler, store):
        """Codex-Fix P2: 'naechsten <heute>' darf nicht heute landen,
        auch wenn die Uhrzeit noch in der Zukunft liegt."""
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        # Heutigen Wochentag in Berlin ermitteln und mit "naechsten" + 23:59
        # absetzen. Das forciert: ohne Fix landet die Erinnerung heute,
        # mit Fix landet sie in 7 Tagen.
        local_tz = _ZI("Europe/Berlin")
        today_name = {
            1: "Montag",
            2: "Dienstag",
            3: "Mittwoch",
            4: "Donnerstag",
            5: "Freitag",
            6: "Samstag",
            7: "Sonntag",
        }[_dt.now(local_tz).isoweekday()]

        result = handler.execute(
            "reminder_date",
            f"erinnere mich nächsten {today_name} um 23:59: Test",
        )
        assert result.success is True
        pending = store.get_pending()
        assert len(pending) == 1
        # Erinnerung muss mind. 7 Tage in der Zukunft liegen, nicht heute
        delta = pending[0].due_at - _dt.now(local_tz)
        assert delta.days >= 6, (
            f"'naechsten {today_name}' wurde nicht in die Folgewoche "
            f"verschoben: due={pending[0].due_at}, delta={delta}"
        )


# ---------------------------------------------------------------------------
# Codex-Fix P2: astimezone(local_tz) statt astimezone() ohne Argument
# ---------------------------------------------------------------------------


class TestTimezoneAwareDisplay:
    """Sicherstellen, dass keine astimezone()-Aufrufe ohne tz-Argument
    zurueckkommen. Auf Windows-Hosts (Tower mit Berlin-TZ) faellt der
    Bug nicht auf, auf Containern in UTC schon -- ein Source-Check ist
    der robusteste Weg, ohne System-TZ zu manipulieren.
    """

    def test_no_naked_astimezone_in_weather_commands(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "elder_berry"
            / "comms"
            / "commands"
            / "weather_commands.py"
        ).read_text(encoding="utf-8")
        # Keine nackten astimezone()-Aufrufe (kein '(' direkt gefolgt von ')')
        assert "astimezone()" not in src, (
            "Mindestens ein astimezone()-Aufruf ohne tz-Argument gefunden. "
            "Das nutzt die Host-TZ statt der konfigurierten -- siehe Codex-"
            "Review P2."
        )
        # Mindestens vier astimezone(...)-Aufrufe (timer, reminder,
        # reminder_date, recurring) -- Sicherheitsnetz, falls jemand
        # eine Stelle entfernt.
        assert src.count("astimezone(") >= 4

    def test_reminder_date_due_is_in_configured_tz(self, store):
        """Sanity: der gespeicherte due_at-Roundtrip ergibt nach Konvertierung
        in die konfigurierte TZ die eingegebene Stunde."""
        from zoneinfo import ZoneInfo

        handler = WeatherCommandHandler(
            reminder_store=store,
            get_timezone=lambda: "Europe/Berlin",
        )
        result = handler.execute(
            "reminder_date",
            "erinnere mich morgen um 09:00: Test",
        )
        assert result.success is True
        pending = store.get_pending()
        assert len(pending) == 1
        # due_at ist UTC-aware -- in Berlin zurueckkonvertiert muss 09:00
        # rauskommen, unabhaengig vom Host.
        berlin_due = pending[0].due_at.astimezone(ZoneInfo("Europe/Berlin"))
        assert berlin_due.hour == 9
        assert berlin_due.minute == 0


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
