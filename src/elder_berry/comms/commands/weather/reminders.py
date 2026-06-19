"""WeatherCommandHandler-Mixin: Timer + einmalige Erinnerungen + Löschen.

Phase 106 (Modul-Entflechtung): aus ``weather_commands.py`` ausgelagert.
Enthält auch die public ``execute_delete_all_reminders`` (Confirmation-Flow)
und die Staticmethod ``_resolve_one_off_target`` (in Tests direkt aufgerufen).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, tzinfo

from elder_berry.comms.commands.base import CommandResult, user_friendly_error
from elder_berry.comms.commands.weather._base import WeatherMixinBase
from elder_berry.comms.commands.weather.patterns import (
    REMINDER_DATE_PATTERN,
    REMINDER_DELETE_PATTERN,
    REMINDER_PATTERN,
    TIMER_PATTERN,
    _parse_duration,
)

logger = logging.getLogger(__name__)


class ReminderMixin(WeatherMixinBase):
    """Timer, einmalige Erinnerungen, Anzeige und Löschen."""

    def _cmd_timer(self, raw_text: str) -> CommandResult:
        """Timer setzen: 'timer 20 min' -> Erinnerung in 20 Minuten."""
        if not self._reminder_store:
            return CommandResult(
                command="timer",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from datetime import timezone
            from zoneinfo import ZoneInfo

            match = TIMER_PATTERN.match(raw_text.strip().lower())
            if not match:
                return CommandResult(
                    command="timer",
                    success=False,
                    text="Timer nicht erkannt. Beispiel: timer 20 min",
                )

            amount = int(match.group(1))
            unit = match.group(2)
            delta = _parse_duration(amount, unit)

            due = datetime.now(timezone.utc) + delta
            # User-ID ist hier nicht bekannt -> default User
            self._reminder_store.add("_timer_user", f"Timer ({amount} {unit})", due)

            local_tz = ZoneInfo(self._get_timezone())
            local_time = due.astimezone(local_tz)
            return CommandResult(
                command="timer",
                success=True,
                text=f"⏰ Timer gesetzt: {amount} {unit} (fällig um {local_time.strftime('%H:%M')})",
            )

        except Exception as e:
            return CommandResult(
                command="timer",
                success=False,
                text=user_friendly_error(e, "Timer"),
            )

    def _cmd_reminder(self, raw_text: str) -> CommandResult:
        """Erinnerung setzen: Uhrzeit oder Dauer + optionale Nachricht."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from datetime import timedelta, timezone, date as date_cls
            from zoneinfo import ZoneInfo

            match = REMINDER_PATTERN.match(raw_text.strip().lower())
            if not match:
                return CommandResult(
                    command="reminder",
                    success=False,
                    text="Nicht erkannt. Beispiel: erinnere mich um 18:00: Wäsche\n"
                    "Oder: erinnere mich in 30 min: Kuchen aus dem Ofen",
                )

            time_str = match.group(1)  # "18:00" oder None
            amount_str = match.group(2)  # "2" oder None
            unit = match.group(3)  # "stunden" oder None
            message = match.group(4) or "Erinnerung"

            local_tz = ZoneInfo(self._get_timezone())

            if time_str:
                # Absolute Uhrzeit
                hour, minute = map(int, time_str.split(":"))
                today = date_cls.today()
                due = datetime(
                    today.year, today.month, today.day, hour, minute, tzinfo=local_tz
                )
                # Wenn Uhrzeit schon vorbei: morgen
                if due < datetime.now(local_tz):
                    due += timedelta(days=1)
            else:
                # Relative Dauer
                amount = int(amount_str)
                delta = _parse_duration(amount, unit)
                due = datetime.now(timezone.utc) + delta

            self._reminder_store.add("_timer_user", message.strip(), due)
            local_time = due.astimezone(local_tz)

            return CommandResult(
                command="reminder",
                success=True,
                text=f"⏰ Erinnerung gesetzt: {message.strip()} (fällig: {local_time.strftime('%d.%m. %H:%M')})",
            )

        except Exception as e:
            return CommandResult(
                command="reminder",
                success=False,
                text=user_friendly_error(e, "Erinnerung"),
            )

    def _cmd_reminder_date(self, raw_text: str) -> CommandResult:
        """Einmalige Erinnerung an Wochentag/Datum/morgen/übermorgen + Uhrzeit."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder_date",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            from zoneinfo import ZoneInfo

            match = REMINDER_DATE_PATTERN.match(raw_text.strip())
            if not match:
                return CommandResult(
                    command="reminder_date",
                    success=False,
                    text=(
                        "Format nicht erkannt. Beispiele:\n"
                        "  erinnere mich am Montag um 09:00: Bad Belzig anrufen\n"
                        "  erinnere mich am 12.05. um 09:00: Mietvertrag\n"
                        "  erinnere mich morgen um 08:30: Brötchen"
                    ),
                )

            prefix = match.group(1)
            weekday = match.group(2)
            date_str = match.group(3)
            rel_day = match.group(4)
            time_str = match.group(5)
            message = (match.group(6) or "Erinnerung").strip()

            # "naechsten/kommenden" -> immer in den naechsten 7-Tage-Zyklus,
            # auch wenn der Wochentag heute ist und die Uhrzeit noch zukuenftig.
            # "am" oder kein Praefix -> heute zulaessig (wenn Uhrzeit zukuenftig).
            force_next_week = bool(
                prefix
                and prefix.lower().rstrip(" ") in ("nächsten", "naechsten", "kommenden")
            )

            local_tz = ZoneInfo(self._get_timezone())
            due = self._resolve_one_off_target(
                weekday=weekday,
                date_str=date_str,
                rel_day=rel_day,
                time_str=time_str,
                tz=local_tz,
                force_next_week=force_next_week,
            )

            self._reminder_store.add("_timer_user", message, due)
            local_time = due.astimezone(local_tz)
            return CommandResult(
                command="reminder_date",
                success=True,
                text=(
                    f"⏰ Erinnerung gesetzt: {message} "
                    f"(fällig: {local_time.strftime('%d.%m. %H:%M')})"
                ),
            )

        except ValueError as e:
            return CommandResult(
                command="reminder_date",
                success=False,
                text=str(e),
            )
        except Exception as e:
            logger.error("reminder_date fehlgeschlagen: %s", e)
            return CommandResult(
                command="reminder_date",
                success=False,
                text=user_friendly_error(e, "Erinnerung"),
            )

    @staticmethod
    def _resolve_one_off_target(
        weekday: str | None,
        date_str: str | None,
        rel_day: str | None,
        time_str: str,
        tz: tzinfo,
        now: datetime | None = None,
        force_next_week: bool = False,
    ) -> datetime:
        """Berechnet einen einmaligen, in der Zukunft liegenden Reminder-Zeitpunkt.

        Genau einer von weekday / date_str / rel_day muss gesetzt sein.
        ``rel_day`` darf "morgen", "übermorgen" oder "uebermorgen" sein.
        Liegt das resultierende Datum bereits in der Vergangenheit, wird
        ein ValueError mit erklärendem Text geworfen – der Aufrufer sendet
        diesen direkt an den User.

        ``now`` ist optional und nur für Tests gedacht (deterministische
        Wochentag-/Datumsberechnung). Default = ``datetime.now(tz)``.

        ``force_next_week`` nur für den weekday-Pfad relevant: wenn True,
        wird auch bei "Wochentag = heute mit zukünftiger Uhrzeit" auf
        +7 Tage gesprungen. Aufrufer setzt das, wenn der User explizit
        "nächsten/kommenden" geschrieben hat.
        """
        from datetime import date as date_cls

        from elder_berry.tools.recurrence import _WEEKDAY_MAP

        hour, minute = map(int, time_str.split(":"))
        if now is None:
            now = datetime.now(tz)

        if rel_day:
            normalized = rel_day.lower()
            is_ueber = normalized.startswith("über") or normalized.startswith("ueber")
            offset_days = 2 if is_ueber else 1
            target_date = (now + timedelta(days=offset_days)).date()

        elif weekday:
            target_iso = _WEEKDAY_MAP[weekday.lower()]
            today_iso = now.isoweekday()  # Mo=1 .. So=7
            days_ahead = target_iso - today_iso
            if days_ahead < 0:
                days_ahead += 7
            elif days_ahead == 0:
                if force_next_week:
                    # Explizit "naechsten/kommenden Montag" am Montag
                    # -> immer in 7 Tagen, nicht heute.
                    days_ahead = 7
                else:
                    # heute -- nur wenn Uhrzeit noch in der Zukunft liegt
                    candidate = now.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    if candidate <= now:
                        days_ahead = 7
            target_date = (now + timedelta(days=days_ahead)).date()

        elif date_str:
            parts = date_str.split(".")
            day = int(parts[0])
            month = int(parts[1])
            if len(parts) >= 3 and parts[2]:
                year_part = int(parts[2])
                year = year_part + 2000 if year_part < 100 else year_part
            else:
                # Jahr bestimmen: dieses Jahr wenn noch zukünftig, sonst nächstes
                this_year = date_cls(now.year, month, day)
                year = now.year if this_year >= now.date() else now.year + 1
            target_date = date_cls(year, month, day)

        else:
            raise ValueError("Kein Zieldatum angegeben")

        candidate = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=tz,
        )
        if candidate <= now:
            raise ValueError(
                f"Zeitpunkt liegt bereits in der Vergangenheit: "
                f"{candidate.strftime('%d.%m.%Y %H:%M')}"
            )
        return candidate

    def _cmd_erinnerungen(self, raw_text: str) -> CommandResult:
        """Offene Erinnerungen anzeigen."""
        if not self._reminder_store:
            return CommandResult(
                command="erinnerungen",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        pending = self._reminder_store.get_pending()
        text = self._reminder_store.format_pending(pending)
        return CommandResult(command="erinnerungen", success=True, text=text)

    def _cmd_reminder_delete(self, raw_text: str) -> CommandResult:
        """Erinnerung löschen: einzeln per ID oder alle."""
        if not self._reminder_store:
            return CommandResult(
                command="reminder_delete",
                success=False,
                text="Erinnerungen nicht verfügbar.",
            )

        try:
            normalized = raw_text.strip().lower()

            # "lösche alle erinnerungen" → Bestätigung
            if "alle" in normalized:
                reminders = self._reminder_store.get_pending("_timer_user")
                count = len(reminders)
                if count == 0:
                    return CommandResult(
                        command="reminder_delete",
                        success=True,
                        text="✅ Keine offenen Erinnerungen vorhanden.",
                    )
                return CommandResult(
                    command="reminder_delete",
                    success=True,
                    text=f"🗑️ {count} Erinnerung{'en' if count != 1 else ''} "
                    "löschen? Bestätige mit 'ja'.",
                    pending_confirmation=True,
                    pending_data={
                        "action_type": "bulk_delete_reminders",
                        "count": count,
                    },
                )

            # ID extrahieren
            match = REMINDER_DELETE_PATTERN.match(normalized)
            if match:
                id_str = match.group(1) or match.group(2)
                if id_str:
                    rid = int(id_str)
                    self._reminder_store.cancel(rid)
                    return CommandResult(
                        command="reminder_delete",
                        success=True,
                        text=f"✅ Erinnerung #{rid} gelöscht.",
                    )

            return CommandResult(
                command="reminder_delete",
                success=False,
                text="Welche Erinnerung? Nutze: lösche erinnerung <ID> oder lösche alle erinnerungen",
            )

        except Exception as e:
            return CommandResult(
                command="reminder_delete",
                success=False,
                text=user_friendly_error(e, "Erinnerung löschen"),
            )

    def execute_delete_all_reminders(self) -> CommandResult:
        """Führt das Löschen aller Erinnerungen nach Bestätigung aus."""
        if self._reminder_store is None:
            return self.not_configured("reminder_delete", "Reminder")
        count = self._reminder_store.cancel_all("_timer_user")
        return CommandResult(
            command="reminder_delete",
            success=True,
            text=f"✅ {count} Erinnerung{'en' if count != 1 else ''} gelöscht.",
        )
