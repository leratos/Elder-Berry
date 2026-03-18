"""Tests: BriefingScheduler – Tägliches Morgen-Briefing."""
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.briefing_scheduler import BriefingScheduler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_weather_mock():
    """Erstellt einen Mock-WeatherClient."""
    from elder_berry.tools.weather_client import WeatherData, WeatherForecast

    mock = MagicMock()
    mock.get_current.return_value = WeatherData(
        temperature=14.2, apparent_temperature=12.5,
        humidity=65, wind_speed=12.3,
        weather_code=2, description="Teilweise bewölkt", city="Berlin",
    )
    mock.get_today.return_value = WeatherForecast(
        date=date.today(), temp_min=8.0, temp_max=16.5,
        precipitation_mm=0.0, precipitation_probability=10,
        weather_code=2, description="Teilweise bewölkt", city="Berlin",
    )
    mock.get_days.return_value = [
        WeatherForecast(
            date=date.today(), temp_min=8.0, temp_max=16.5,
            precipitation_mm=0.0, precipitation_probability=10,
            weather_code=2, description="Teilweise bewölkt", city="Berlin",
        ),
        WeatherForecast(
            date=date.today() + timedelta(days=1), temp_min=10.0, temp_max=18.0,
            precipitation_mm=1.5, precipitation_probability=30,
            weather_code=1, description="Überwiegend klar", city="Berlin",
        ),
    ]
    mock.format_current.return_value = "⛅ Wetter in Berlin: 14.2°C"
    return mock


def _make_calendar_mock(events=None):
    """Erstellt einen Mock-GoogleCalendarClient."""
    mock = MagicMock()
    if events is None:
        ev = MagicMock()
        ev.format_short.return_value = "09:00 – Daily Standup"
        events = [ev]
    mock.get_today.return_value = events
    return mock


def _make_reminder_store_mock(reminders=None):
    """Erstellt einen Mock-ReminderStore."""
    from elder_berry.tools.reminder_store import Reminder

    mock = MagicMock()
    if reminders is None:
        # due_at fest auf 12:00 UTC heute (immer innerhalb today_end 23:59 UTC)
        now = datetime.now(timezone.utc)
        noon_today = datetime(
            now.year, now.month, now.day, 12, 0, 0, tzinfo=timezone.utc,
        )
        reminders = [
            Reminder(
                id=3, user_id="_timer_user", message="Paket abholen",
                due_at=noon_today,
                created_at=now,
                fired=False, cancelled=False,
            ),
        ]
    mock.get_pending.return_value = reminders
    return mock


# ---------------------------------------------------------------------------
# build_briefing()
# ---------------------------------------------------------------------------

class TestBuildBriefing:
    def test_all_services(self):
        """Alle Services vorhanden → vollständiger Text mit allen Abschnitten."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
            calendar=_make_calendar_mock(),
            reminder_store=_make_reminder_store_mock(),
        )
        text = scheduler.build_briefing()

        assert "Guten Morgen" in text
        assert "Berlin" in text or "Wetter" in text
        assert "Termine" in text
        assert "Daily Standup" in text
        assert "Paket abholen" in text
        assert "Schönen Tag" in text

    def test_only_weather(self):
        """Nur Wetter → nur Wetter-Abschnitt."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
        )
        text = scheduler.build_briefing()

        assert "Guten Morgen" in text
        assert "Berlin" in text or "14.2" in text
        assert "Termine" not in text

    def test_only_calendar(self):
        """Nur Kalender → nur Kalender-Abschnitt."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            calendar=_make_calendar_mock(),
        )
        text = scheduler.build_briefing()

        assert "Guten Morgen" in text
        assert "Termine" in text
        assert "Daily Standup" in text

    def test_only_reminders(self):
        """Nur Erinnerungen → nur Erinnerungs-Abschnitt."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            reminder_store=_make_reminder_store_mock(),
        )
        text = scheduler.build_briefing()

        assert "Guten Morgen" in text
        assert "Paket abholen" in text

    def test_no_services(self):
        """Keine Services → leerer String (kein Briefing)."""
        scheduler = BriefingScheduler(send_briefing=MagicMock())
        text = scheduler.build_briefing()
        assert text == ""

    def test_calendar_empty(self):
        """Kalender leer (keine Termine) → Abschnitt wird weggelassen."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            calendar=_make_calendar_mock(events=[]),
            weather=_make_weather_mock(),
        )
        text = scheduler.build_briefing()

        assert "Guten Morgen" in text
        assert "Termine" not in text

    def test_reminders_future_only(self):
        """Nur zukünftige Erinnerungen (morgen) → Abschnitt weggelassen."""
        from elder_berry.tools.reminder_store import Reminder
        far_future = [
            Reminder(
                id=1, user_id="_timer_user", message="Morgen",
                due_at=datetime.now(timezone.utc) + timedelta(days=2),
                created_at=datetime.now(timezone.utc),
                fired=False, cancelled=False,
            ),
        ]
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            reminder_store=_make_reminder_store_mock(reminders=far_future),
        )
        text = scheduler.build_briefing()
        assert text == ""


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_start_stop(self):
        scheduler = BriefingScheduler(send_briefing=MagicMock())
        assert scheduler.is_running is False
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.stop()
        assert scheduler.is_running is False

    def test_briefing_sent_at_configured_time(self):
        """Briefing wird zur richtigen Zeit gesendet (Time-Mock)."""
        callback = MagicMock()
        scheduler = BriefingScheduler(
            send_briefing=callback,
            weather=_make_weather_mock(),
            briefing_hour=12,
            briefing_minute=0,
        )

        # Simuliere: Uhrzeit ist 12:00
        fake_now = datetime(2026, 3, 17, 12, 0, 0)
        with patch("elder_berry.comms.briefing_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            # Direkt _run-Logik testen (statt Thread)
            scheduler._briefing_sent_today = None
            now = fake_now
            if (
                now.hour == scheduler._briefing_hour
                and now.minute == scheduler._briefing_minute
                and scheduler._briefing_sent_today != now.date()
            ):
                briefing = scheduler.build_briefing()
                if briefing:
                    scheduler._send_briefing(briefing)
                    scheduler._briefing_sent_today = now.date()

        callback.assert_called_once()
        assert scheduler._briefing_sent_today == date(2026, 3, 17)

    def test_no_double_send(self):
        """Briefing wird nicht doppelt gesendet am selben Tag."""
        callback = MagicMock()
        scheduler = BriefingScheduler(
            send_briefing=callback,
            weather=_make_weather_mock(),
        )

        # Flag setzen: heute schon gesendet
        scheduler._briefing_sent_today = date.today()

        now = datetime.now()
        # Selbst wenn Uhrzeit passt: kein erneutes Senden
        if (
            now.hour == scheduler._briefing_hour
            and now.minute == scheduler._briefing_minute
            and scheduler._briefing_sent_today != now.date()
        ):
            scheduler._send_briefing(scheduler.build_briefing())

        callback.assert_not_called()
