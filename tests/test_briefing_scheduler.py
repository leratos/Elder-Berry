"""Tests: BriefingScheduler – Tägliches Morgen-Briefing."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


from elder_berry.comms.briefing_scheduler import BriefingScheduler
from elder_berry.tools.contact_store import Contact
from elder_berry.tools.note_store import Note


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Fester Wochentag für Tests die keinen bestimmten Wochentag brauchen
_WEDNESDAY = datetime(2026, 3, 25, 7, 30)  # Mittwoch


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
        text = scheduler.build_briefing(now=_WEDNESDAY)

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
        text = scheduler.build_briefing(now=_WEDNESDAY)

        assert "Guten Morgen" in text
        assert "Berlin" in text or "14.2" in text
        assert "Termine" not in text

    def test_only_calendar(self):
        """Nur Kalender → nur Kalender-Abschnitt."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            calendar=_make_calendar_mock(),
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)

        assert "Guten Morgen" in text
        assert "Termine" in text
        assert "Daily Standup" in text

    def test_only_reminders(self):
        """Nur Erinnerungen → nur Erinnerungs-Abschnitt."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            reminder_store=_make_reminder_store_mock(),
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)

        assert "Guten Morgen" in text
        assert "Paket abholen" in text

    def test_no_services(self):
        """Keine Services → leerer String (kein Briefing)."""
        scheduler = BriefingScheduler(send_briefing=MagicMock())
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert text == ""

    def test_calendar_empty(self):
        """Kalender leer (keine Termine) → Abschnitt wird weggelassen."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            calendar=_make_calendar_mock(events=[]),
            weather=_make_weather_mock(),
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)

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
        text = scheduler.build_briefing(now=_WEDNESDAY)
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
            mock_dt.side_effect = datetime

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


# ---------------------------------------------------------------------------
# Geburtstag-Sektion (Phase 34)
# ---------------------------------------------------------------------------

def _make_contact(name: str, birthday: str = "") -> Contact:
    """Erstellt einen Test-Contact."""
    now = datetime.now(timezone.utc)
    return Contact(
        id=1, user_id="@test:matrix.org", name=name,
        emails="[]", phones="[]", role="", formality="locker",
        notes="", birthday=birthday, address="", organization="",
        title="", categories="", nickname="", anniversary="",
        url="", vcard_uid="", created_at=now, updated_at=now,
    )


class TestBirthdaySection:
    def test_birthday_with_age(self):
        """Geburtstag mit bekanntem Jahr → zeigt Alter."""
        contact_store = MagicMock()
        contact_store.get_upcoming_birthdays.return_value = [
            _make_contact("Max Mustermann", "1984-03-28"),
        ]
        contact_store.get_upcoming_anniversaries.return_value = []
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            contact_store=contact_store,
            default_user_id="@test:matrix.org",
        )
        now = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=now)

        assert "🎂" in text
        assert "Max Mustermann" in text
        assert "(wird 42)" in text

    def test_birthday_unknown_year(self):
        """Geburtstag mit Jahr 0000 → kein Alter."""
        contact_store = MagicMock()
        contact_store.get_upcoming_birthdays.return_value = [
            _make_contact("Lisa", "0000-03-28"),
        ]
        contact_store.get_upcoming_anniversaries.return_value = []
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            contact_store=contact_store,
            default_user_id="@test:matrix.org",
        )
        now = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=now)

        assert "Lisa" in text
        assert "wird" not in text

    def test_no_birthdays(self):
        """Keine Geburtstage → Sektion fehlt."""
        contact_store = MagicMock()
        contact_store.get_upcoming_birthdays.return_value = []
        contact_store.get_upcoming_anniversaries.return_value = []
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            contact_store=contact_store,
            default_user_id="@test:matrix.org",
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert "🎂" not in text

    def test_no_contact_store(self):
        """Kein ContactStore → keine Geburtstage, kein Fehler."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert "🎂" not in text
        assert "Guten Morgen" in text


# ---------------------------------------------------------------------------
# E-Mail-Sektion (Phase 34)
# ---------------------------------------------------------------------------

class TestEmailSection:
    def test_unread_emails(self):
        """Ungelesene Mails > 0 → Sektion angezeigt."""
        email_client = MagicMock()
        email_client.get_unread_count.return_value = 5
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            email_client=email_client,
        )
        text = scheduler.build_briefing()

        assert "📧" in text
        assert "5 ungelesene E-Mails" in text

    def test_single_email(self):
        """Genau 1 Mail → Singular."""
        email_client = MagicMock()
        email_client.get_unread_count.return_value = 1
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            email_client=email_client,
        )
        text = scheduler.build_briefing()

        assert "1 ungelesene E-Mail" in text
        assert "E-Mails" not in text

    def test_no_unread_emails(self):
        """0 ungelesene Mails → Sektion fehlt."""
        email_client = MagicMock()
        email_client.get_unread_count.return_value = 0
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            email_client=email_client,
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert "📧" not in text

    def test_email_error(self):
        """get_unread_count() wirft Exception → graceful skip."""
        email_client = MagicMock()
        email_client.get_unread_count.side_effect = ConnectionError("IMAP down")
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            email_client=email_client,
            weather=_make_weather_mock(),
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert "📧" not in text
        assert "Guten Morgen" in text


# ---------------------------------------------------------------------------
# Vor-einem-Jahr-Sektion (Phase 34)
# ---------------------------------------------------------------------------

def _make_note(content: str, created_at: datetime) -> Note:
    """Erstellt eine Test-Note."""
    return Note(
        id=1, user_id="@test:matrix.org", key=None,
        content=content, tags=[],
        created_at=created_at, updated_at=created_at,
    )


class TestFlashbackSection:
    def test_flashback_with_notes(self):
        """Notizen von vor einem Jahr → Sektion angezeigt."""
        note_store = MagicMock()
        old_date = datetime(2025, 3, 28, 10, 0, 0, tzinfo=timezone.utc)
        note_store.get_notes_from_date.return_value = [
            _make_note("Dachprojekt gestartet", old_date),
        ]
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            note_store=note_store,
            default_user_id="@test:matrix.org",
        )
        now = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=now)

        assert "📅 Vor einem Jahr" in text
        assert "Dachprojekt gestartet" in text
        assert "(2025)" in text

    def test_flashback_no_notes(self):
        """Keine alten Notizen → Sektion fehlt."""
        note_store = MagicMock()
        note_store.get_notes_from_date.return_value = []
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            note_store=note_store,
            default_user_id="@test:matrix.org",
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Vor einem Jahr" not in text

    def test_flashback_recent_notes_filtered(self):
        """Notizen von vor wenigen Tagen → nicht angezeigt (< 330 Tage)."""
        note_store = MagicMock()
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        note_store.get_notes_from_date.return_value = [
            _make_note("Gestern notiert", recent),
        ]
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            note_store=note_store,
            default_user_id="@test:matrix.org",
        )
        text = scheduler.build_briefing(now=_WEDNESDAY)
        assert "Vor einem Jahr" not in text


# ---------------------------------------------------------------------------
# Wochenend-Variante (Phase 34)
# ---------------------------------------------------------------------------

class TestWeekendVariant:
    def test_weekend_greeting(self):
        """Samstag → Wochenend-Greeting."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
        )
        # 2026-03-28 ist ein Samstag
        saturday = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=saturday)

        assert "Schönes Wochenende" in text
        assert "Genieß den Tag" in text

    def test_weekday_greeting(self):
        """Montag → normaler Greeting."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
        )
        monday = datetime(2026, 3, 23, 7, 30)
        text = scheduler.build_briefing(now=monday)

        assert "Guten Morgen" in text
        assert "Schönen Tag" in text

    def test_weekend_no_todos(self):
        """Wochenende → Aufgaben werden übersprungen."""
        task_client = MagicMock()
        task_client.format_for_briefing.return_value = "📋 Offene Aufgaben: Einkaufen"
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
            task_client=task_client,
        )
        saturday = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=saturday)

        assert "Aufgaben" not in text
        task_client.format_for_briefing.assert_not_called()

    def test_weekend_no_reminders(self):
        """Wochenende → Erinnerungen werden übersprungen."""
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
            reminder_store=_make_reminder_store_mock(),
        )
        saturday = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=saturday)

        assert "Erinnerungen" not in text
        assert "Paket abholen" not in text

    def test_weekday_has_todos(self):
        """Wochentag → Aufgaben werden angezeigt."""
        task_client = MagicMock()
        task_client.format_for_briefing.return_value = "📋 Offene Aufgaben: Einkaufen"
        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            weather=_make_weather_mock(),
            task_client=task_client,
        )
        monday = datetime(2026, 3, 23, 7, 30)
        text = scheduler.build_briefing(now=monday)

        assert "Aufgaben" in text
        assert "Einkaufen" in text

    def test_weekend_monday_preview(self):
        """Samstag → Montag-Termine als Vorschau."""
        calendar = MagicMock()
        calendar.get_today.return_value = []
        monday_ev = MagicMock()
        monday_ev.format_short.return_value = "10:00 – Teammeeting"
        calendar.get_events_range.return_value = [monday_ev]

        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            calendar=calendar,
        )
        saturday = datetime(2026, 3, 28, 7, 30)
        text = scheduler.build_briefing(now=saturday)

        assert "Vorschau Montag" in text
        assert "Teammeeting" in text

    def test_sunday_monday_preview(self):
        """Sonntag → Montag ist +1 Tag."""
        calendar = MagicMock()
        calendar.get_today.return_value = []
        monday_ev = MagicMock()
        monday_ev.format_short.return_value = "09:00 – Standup"
        calendar.get_events_range.return_value = [monday_ev]

        scheduler = BriefingScheduler(
            send_briefing=MagicMock(),
            calendar=calendar,
        )
        sunday = datetime(2026, 3, 29, 7, 30)
        text = scheduler.build_briefing(now=sunday)

        assert "Vorschau Montag" in text
        assert "Standup" in text
