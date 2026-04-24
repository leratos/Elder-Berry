"""Tests: recurrence – Berechnung und Parsing wiederkehrender Erinnerungen."""
from datetime import datetime, timezone

import pytest
from zoneinfo import ZoneInfo

from elder_berry.tools.recurrence import (
    calculate_next_due,
    format_recurrence,
    parse_recurrence,
    validate_recurrence,
)


TZ_BERLIN = "Europe/Berlin"
TZ = ZoneInfo(TZ_BERLIN)


def _dt(year, month, day, hour=9, minute=0, tz=TZ):
    """Hilfsfunktion: datetime in lokaler TZ."""
    return datetime(year, month, day, hour, minute, tzinfo=tz)


# ---------------------------------------------------------------------------
# validate_recurrence
# ---------------------------------------------------------------------------

class TestValidateRecurrence:
    def test_daily(self):
        assert validate_recurrence("daily") is True

    def test_weekdays(self):
        assert validate_recurrence("weekdays") is True

    def test_weekly_valid(self):
        assert validate_recurrence("weekly:1") is True
        assert validate_recurrence("weekly:7") is True

    def test_weekly_invalid(self):
        assert validate_recurrence("weekly:0") is False
        assert validate_recurrence("weekly:8") is False
        assert validate_recurrence("weekly") is False

    def test_biweekly_valid(self):
        assert validate_recurrence("biweekly:3") is True

    def test_biweekly_invalid(self):
        assert validate_recurrence("biweekly") is False

    def test_monthly_valid(self):
        assert validate_recurrence("monthly:1") is True
        assert validate_recurrence("monthly:31") is True

    def test_monthly_invalid(self):
        assert validate_recurrence("monthly:0") is False
        assert validate_recurrence("monthly:32") is False
        assert validate_recurrence("monthly") is False

    def test_unknown(self):
        assert validate_recurrence("yearly") is False
        assert validate_recurrence("foo:bar") is False
        assert validate_recurrence("") is False

    def test_daily_with_param_invalid(self):
        assert validate_recurrence("daily:1") is False

    def test_weekdays_with_param_invalid(self):
        assert validate_recurrence("weekdays:1") is False


# ---------------------------------------------------------------------------
# parse_recurrence
# ---------------------------------------------------------------------------

class TestParseRecurrence:
    def test_taeglich(self):
        assert parse_recurrence("täglich") == "daily"
        assert parse_recurrence("Täglich") == "daily"

    def test_werktags(self):
        assert parse_recurrence("werktags") == "weekdays"

    def test_weekly_days(self):
        assert parse_recurrence("jeden montag") == "weekly:1"
        assert parse_recurrence("jeden Dienstag") == "weekly:2"
        assert parse_recurrence("jeden mittwoch") == "weekly:3"
        assert parse_recurrence("jeden donnerstag") == "weekly:4"
        assert parse_recurrence("jeden freitag") == "weekly:5"
        assert parse_recurrence("jeden samstag") == "weekly:6"
        assert parse_recurrence("jeden sonntag") == "weekly:7"

    def test_weekly_jede_varianten(self):
        assert parse_recurrence("jede montag") == "weekly:1"
        assert parse_recurrence("jedem freitag") == "weekly:5"

    def test_biweekly(self):
        assert parse_recurrence("alle 2 wochen montags") == "biweekly:1"
        assert parse_recurrence("alle zwei wochen dienstags") == "biweekly:2"

    def test_monthly(self):
        assert parse_recurrence("jeden 1.") == "monthly:1"
        assert parse_recurrence("jeden 15.") == "monthly:15"

    def test_unknown(self):
        assert parse_recurrence("morgen") is None
        assert parse_recurrence("irgendwann") is None
        assert parse_recurrence("") is None


# ---------------------------------------------------------------------------
# format_recurrence
# ---------------------------------------------------------------------------

class TestFormatRecurrence:
    def test_daily(self):
        assert format_recurrence("daily") == "täglich"

    def test_weekdays(self):
        assert "Mo" in format_recurrence("weekdays")
        assert "Fr" in format_recurrence("weekdays")

    def test_weekly(self):
        assert format_recurrence("weekly:1") == "jeden Montag"
        assert format_recurrence("weekly:5") == "jeden Freitag"
        assert format_recurrence("weekly:7") == "jeden Sonntag"

    def test_biweekly(self):
        result = format_recurrence("biweekly:3")
        assert "2 Wochen" in result
        assert "Mittwoch" in result

    def test_monthly(self):
        result = format_recurrence("monthly:1")
        assert "1." in result
        assert "Monat" in result

    def test_unknown_passthrough(self):
        assert format_recurrence("xyz") == "xyz"


# ---------------------------------------------------------------------------
# calculate_next_due – daily
# ---------------------------------------------------------------------------

class TestCalculateNextDueDaily:
    def test_next_day(self):
        due = _dt(2026, 3, 19, 9, 0)
        next_due = calculate_next_due(due, "daily", TZ_BERLIN)
        expected = _dt(2026, 3, 20, 9, 0)
        assert next_due == expected.astimezone(timezone.utc)

    def test_year_boundary(self):
        due = _dt(2026, 12, 31, 23, 0)
        next_due = calculate_next_due(due, "daily", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.year == 2027
        assert local.month == 1
        assert local.day == 1


# ---------------------------------------------------------------------------
# calculate_next_due – weekdays
# ---------------------------------------------------------------------------

class TestCalculateNextDueWeekdays:
    def test_friday_to_monday(self):
        # 2026-03-20 ist Freitag
        due = _dt(2026, 3, 20, 8, 0)
        next_due = calculate_next_due(due, "weekdays", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.weekday() == 0  # Montag
        assert local.day == 23

    def test_monday_to_tuesday(self):
        # 2026-03-23 ist Montag
        due = _dt(2026, 3, 23, 8, 0)
        next_due = calculate_next_due(due, "weekdays", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.weekday() == 1  # Dienstag
        assert local.day == 24

    def test_saturday_to_monday(self):
        # 2026-03-21 ist Samstag
        due = _dt(2026, 3, 21, 8, 0)
        next_due = calculate_next_due(due, "weekdays", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.weekday() == 0  # Montag
        assert local.day == 23


# ---------------------------------------------------------------------------
# calculate_next_due – weekly
# ---------------------------------------------------------------------------

class TestCalculateNextDueWeekly:
    def test_one_week_later(self):
        # 2026-03-19 Donnerstag, weekly:4 (Do=4)
        due = _dt(2026, 3, 19, 9, 0)
        next_due = calculate_next_due(due, "weekly:4", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.day == 26
        assert local.isoweekday() == 4  # Donnerstag


# ---------------------------------------------------------------------------
# calculate_next_due – biweekly
# ---------------------------------------------------------------------------

class TestCalculateNextDueBiweekly:
    def test_two_weeks_later(self):
        due = _dt(2026, 3, 19, 9, 0)
        next_due = calculate_next_due(due, "biweekly:4", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.day == 2  # 19 + 14 = 2. April
        assert local.month == 4


# ---------------------------------------------------------------------------
# calculate_next_due – monthly
# ---------------------------------------------------------------------------

class TestCalculateNextDueMonthly:
    def test_next_month(self):
        due = _dt(2026, 3, 15, 10, 0)
        next_due = calculate_next_due(due, "monthly:15", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.month == 4
        assert local.day == 15

    def test_month_end_clamp(self):
        # monthly:31 im Februar → 28. (bzw. 29.)
        due = _dt(2026, 1, 31, 10, 0)
        next_due = calculate_next_due(due, "monthly:31", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.month == 2
        assert local.day == 28  # 2026 ist kein Schaltjahr

    def test_december_to_january(self):
        due = _dt(2026, 12, 1, 10, 0)
        next_due = calculate_next_due(due, "monthly:1", TZ_BERLIN)
        local = next_due.astimezone(TZ)
        assert local.year == 2027
        assert local.month == 1
        assert local.day == 1


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_invalid_recurrence_raises(self):
        due = _dt(2026, 3, 19, 9, 0)
        with pytest.raises(ValueError, match="Ungültiges"):
            calculate_next_due(due, "yearly", TZ_BERLIN)

    def test_utc_input(self):
        """UTC-Input wird korrekt in lokale TZ konvertiert."""
        due = datetime(2026, 3, 19, 8, 0, tzinfo=timezone.utc)
        next_due = calculate_next_due(due, "daily", TZ_BERLIN)
        assert next_due.tzinfo == timezone.utc

    def test_result_always_utc(self):
        due = _dt(2026, 3, 19, 9, 0)
        for rec in ["daily", "weekly:1", "monthly:15", "weekdays", "biweekly:1"]:
            result = calculate_next_due(due, rec, TZ_BERLIN)
            assert result.tzinfo == timezone.utc
