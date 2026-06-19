"""WeatherCommandHandler-Mixin: wiederkehrende Erinnerungen + Datums-Helfer.

Phase 106 (Modul-Entflechtung): aus ``weather_commands.py`` ausgelagert.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

from elder_berry.comms.commands.base import CommandResult, user_friendly_error
from elder_berry.comms.commands.weather._base import WeatherMixinBase
from elder_berry.comms.commands.weather.patterns import (
    RECURRING_DAILY_PATTERN,
    RECURRING_MONTHLY_PATTERN,
    RECURRING_WEEKDAY_PATTERN,
    RECURRING_WEEKLY_PATTERN,
)


class RecurringReminderMixin(WeatherMixinBase):
    """Wiederkehrende Erinnerungen (weekly / daily / weekdays / monthly)."""

    def _cmd_recurring_reminder(self, raw_text: str) -> CommandResult:
        """Wiederkehrende Erinnerung setzen."""
        if not self._reminder_store:
            return CommandResult(
                command="recurring_reminder",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from zoneinfo import ZoneInfo
            from elder_berry.tools.recurrence import (
                parse_recurrence,
            )

            normalized = raw_text.strip().lower()
            local_tz = ZoneInfo(self._get_timezone())

            # Weekly: "erinnere mich jeden montag um 9:00: Wochenbericht"
            m = RECURRING_WEEKLY_PATTERN.match(normalized)
            if m:
                day_name = m.group(1)
                time_str = m.group(2)
                message = (m.group(3) or "Erinnerung").strip()
                recurrence = parse_recurrence(f"jeden {day_name}")
                # parse_recurrence kann None liefern; wenn der Regex matcht
                # ist die Eingabe normalisiert und parse_recurrence garantiert
                # einen Treffer.
                assert recurrence is not None
                due = self._next_weekday_at(day_name, time_str, local_tz)
                return self._create_recurring(message, due, recurrence)

            # Daily: "erinnere mich täglich um 8:00: Standup"
            m = RECURRING_DAILY_PATTERN.match(normalized)
            if m:
                time_str = m.group(1)
                message = (m.group(2) or "Erinnerung").strip()
                due = self._today_or_tomorrow_at(time_str, local_tz)
                return self._create_recurring(message, due, "daily")

            # Weekdays: "erinnere mich werktags um 7:30: Aufstehen"
            m = RECURRING_WEEKDAY_PATTERN.match(normalized)
            if m:
                time_str = m.group(1)
                message = (m.group(2) or "Erinnerung").strip()
                due = self._next_weekday_at_time(time_str, local_tz)
                return self._create_recurring(message, due, "weekdays")

            # Monthly: "erinnere mich jeden 1. um 10:00: Miete"
            m = RECURRING_MONTHLY_PATTERN.match(normalized)
            if m:
                day = int(m.group(1))
                time_str = m.group(2)
                message = (m.group(3) or "Erinnerung").strip()
                due = self._next_monthly_at(day, time_str, local_tz)
                return self._create_recurring(message, due, f"monthly:{day}")

            return CommandResult(
                command="recurring_reminder",
                success=False,
                text="Format nicht erkannt. Beispiel: erinnere mich jeden montag um 9:00: Wochenbericht",
            )

        except Exception as e:
            return CommandResult(
                command="recurring_reminder",
                success=False,
                text=user_friendly_error(e, "Wiederkehrende Erinnerung"),
            )

    def _create_recurring(
        self,
        message: str,
        due: datetime,
        recurrence: str,
    ) -> CommandResult:
        """Erstellt eine wiederkehrende Erinnerung im Store."""
        from zoneinfo import ZoneInfo

        from elder_berry.tools.recurrence import format_recurrence

        # Caller (_cmd_recurring_reminder) filtert "if not self._reminder_store".
        assert self._reminder_store is not None
        self._reminder_store.add(
            "_timer_user",
            message,
            due,
            recurrence=recurrence,
        )
        local_time = due.astimezone(ZoneInfo(self._get_timezone()))
        rec_text = format_recurrence(recurrence)
        return CommandResult(
            command="recurring_reminder",
            success=True,
            text=(
                f"🔁 Wiederkehrende Erinnerung gesetzt: {message}\n"
                f"  Nächster Termin: {local_time.strftime('%d.%m. %H:%M')}\n"
                f"  Wiederholung: {rec_text}"
            ),
        )

    @staticmethod
    def _next_weekday_at(
        day_name: str,
        time_str: str,
        tz: tzinfo,
    ) -> datetime:
        """Berechnet den nächsten Wochentag mit Uhrzeit."""
        from elder_berry.tools.recurrence import _WEEKDAY_MAP

        target_iso = _WEEKDAY_MAP.get(day_name.lower())
        if not target_iso:
            raise ValueError(f"Unbekannter Wochentag: {day_name}")

        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)
        today_iso = now.isoweekday()  # Mo=1 .. So=7

        days_ahead = target_iso - today_iso
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0:
            # Heute, aber Uhrzeit schon vorbei → nächste Woche
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                days_ahead = 7

        target_date = (now + timedelta(days=days_ahead)).date()
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=tz,
        )

    @staticmethod
    def _today_or_tomorrow_at(time_str: str, tz: tzinfo) -> datetime:
        """Heute zur Uhrzeit, oder morgen wenn schon vorbei."""
        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _next_weekday_at_time(time_str: str, tz: tzinfo) -> datetime:
        """Nächster Werktag (Mo-Fr) zur angegebenen Uhrzeit."""
        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        # Vorspulen bis Werktag
        while candidate.weekday() >= 5:  # 5=Sa, 6=So
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def _next_monthly_at(day: int, time_str: str, tz: tzinfo) -> datetime:
        """Nächster Monatstag zur angegebenen Uhrzeit."""
        import calendar

        hour, minute = map(int, time_str.split(":"))
        now = datetime.now(tz)

        # Diesen Monat versuchen
        max_day = calendar.monthrange(now.year, now.month)[1]
        target_day = min(day, max_day)
        candidate = datetime(
            now.year,
            now.month,
            target_day,
            hour,
            minute,
            tzinfo=tz,
        )
        if candidate > now:
            return candidate

        # Nächster Monat
        year = now.year
        month = now.month + 1
        if month > 12:
            month = 1
            year += 1
        max_day = calendar.monthrange(year, month)[1]
        target_day = min(day, max_day)
        return datetime(year, month, target_day, hour, minute, tzinfo=tz)
