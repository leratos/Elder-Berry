"""CalDAVCalendarClient – CalDAV Calendar Integration (Nextcloud).

Liest und erstellt Termine über die CalDAV-API einer Nextcloud-Instanz.
Credentials werden aus dem SecretStore geladen (nextcloud_url, nextcloud_user,
nextcloud_app_password – identisch mit NextcloudFilesClient).

Verwendung:
    client = CalDAVCalendarClient(secret_store=store)
    events = client.get_today()
    events = client.get_events(days=7)
    client.create_event("Zahnarzt", datetime(2026, 3, 20, 14, 0), duration_minutes=60)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from elder_berry.tools.google_calendar import CalendarEvent

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


class CalDAVCalendarClient:
    """CalDAV Calendar Client für Nextcloud.

    Verbindet sich lazy beim ersten Zugriff mit dem CalDAV-Server.
    Bei Connection-Fehlern wird der gecachte Kalender invalidiert,
    sodass der nächste Aufruf automatisch neu verbindet.
    """

    _RETRIABLE_ERRORS = (ConnectionError, OSError, TimeoutError)

    def __init__(self, secret_store: SecretStore) -> None:
        self._store = secret_store
        self._client = None
        self._calendar = None

    def _get_calendar(self):
        """Lazy-Init: Verbindet mit Nextcloud CalDAV und holt den primären Kalender."""
        if self._calendar is not None:
            return self._calendar

        import caldav

        url = self._store.get("nextcloud_url")
        user = self._store.get("nextcloud_user")
        pw = self._store.get("nextcloud_app_password")

        self._client = caldav.DAVClient(
            url=f"{url}/remote.php/dav",
            username=user,
            password=pw,
        )
        principal = self._client.principal()
        calendars = principal.calendars()
        if not calendars:
            raise RuntimeError("Kein Kalender in Nextcloud gefunden")

        # Bevorzuge "Persönlich"/"Personal", sonst nimm den ersten
        for cal in calendars:
            name = getattr(cal, "name", "") or ""
            if name.lower() in ("persönlich", "personal"):
                self._calendar = cal
                return self._calendar

        self._calendar = calendars[0]
        return self._calendar

    def _call_with_retry(self, operation):
        """Führt operation() aus, mit 1x Retry bei stale Connection."""
        try:
            return operation()
        except self._RETRIABLE_ERRORS as e:
            logger.warning(
                "CalDAV Connection-Fehler, retry mit neuer Verbindung: %s",
                e,
            )
            self._calendar = None
            self._client = None
            return operation()

    def is_available(self) -> bool:
        """Prüft ob Nextcloud CalDAV konfiguriert und erreichbar ist."""
        try:
            url = self._store.get_or_none("nextcloud_url")
            user = self._store.get_or_none("nextcloud_user")
            pw = self._store.get_or_none("nextcloud_app_password")
            if not all([url, user, pw]):
                return False
            self._get_calendar()
            return True
        except Exception:
            self._calendar = None
            self._client = None
            return False

    def get_events(self, days: int = 1, max_results: int = 20) -> list[CalendarEvent]:
        """Holt Termine für die nächsten N Tage.

        Args:
            days: Anzahl Tage ab jetzt (1 = heute).
            max_results: Maximale Anzahl Termine.

        Returns:
            Liste von CalendarEvent, chronologisch sortiert.
        """

        def _op():
            cal = self._get_calendar()
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days)

            results = cal.search(
                start=now,
                end=end,
                event=True,
                expand=True,
            )

            events = []
            for item in results:
                try:
                    events.append(self._parse_event(item))
                except (ValueError, AttributeError) as e:
                    logger.debug("Event-Parsing übersprungen: %s", e)

            events.sort(key=lambda e: e.start)
            return events[:max_results]

        return self._call_with_retry(_op)

    def search_events(
        self,
        query: str,
        days: int = 30,
        max_results: int = 10,
    ) -> list[CalendarEvent]:
        """Sucht Termine per Volltextsuche (clientseitig).

        Args:
            query: Suchbegriff (durchsucht Titel, Beschreibung, Ort).
            days: Zeitraum in Tagen ab jetzt.
            max_results: Maximale Anzahl Ergebnisse.

        Returns:
            Liste passender CalendarEvents.
        """

        def _op():
            cal = self._get_calendar()
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=days)

            results = cal.search(
                start=now,
                end=end,
                event=True,
                expand=True,
            )

            query_lower = query.lower()
            events = []
            for item in results:
                try:
                    event = self._parse_event(item)
                except (ValueError, AttributeError):
                    continue

                searchable = (event.summary or "").lower()
                if event.description:
                    searchable += " " + event.description.lower()
                if event.location:
                    searchable += " " + event.location.lower()

                if query_lower in searchable:
                    events.append(event)

            events.sort(key=lambda e: e.start)
            return events[:max_results]

        return self._call_with_retry(_op)

    def get_today(self) -> list[CalendarEvent]:
        """Termine für heute."""
        return self.get_events(days=1)

    def get_events_range(
        self,
        start: datetime,
        end: datetime,
        max_results: int = 20,
    ) -> list[CalendarEvent]:
        """Termine in einem bestimmten Zeitraum abrufen.

        Args:
            start: Beginn des Zeitraums (timezone-aware).
            end: Ende des Zeitraums (timezone-aware).
            max_results: Maximale Anzahl Termine.

        Returns:
            Liste von CalendarEvents im Zeitraum, nach Startzeit sortiert.
        """

        def _op():
            cal = self._get_calendar()
            results = cal.search(
                start=start,
                end=end,
                event=True,
                expand=True,
            )

            events = []
            for item in results:
                try:
                    events.append(self._parse_event(item))
                except (ValueError, AttributeError) as e:
                    logger.debug("Event-Parsing übersprungen: %s", e)

            events.sort(key=lambda e: e.start)
            return events[:max_results]

        return self._call_with_retry(_op)

    def get_tomorrow(self) -> list[CalendarEvent]:
        """Termine für morgen."""

        def _op():
            cal = self._get_calendar()
            now = datetime.now(timezone.utc)
            tomorrow_start = (now + timedelta(days=1)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            tomorrow_end = tomorrow_start + timedelta(days=1)

            results = cal.search(
                start=tomorrow_start,
                end=tomorrow_end,
                event=True,
                expand=True,
            )

            events = []
            for item in results:
                try:
                    events.append(self._parse_event(item))
                except (ValueError, AttributeError) as e:
                    logger.debug("Event-Parsing übersprungen: %s", e)

            events.sort(key=lambda e: e.start)
            return events

        return self._call_with_retry(_op)

    def create_event(
        self,
        summary: str,
        start: datetime,
        duration_minutes: int = 60,
        location: str | None = None,
        description: str | None = None,
        all_day: bool = False,
        recurrence: list[str] | None = None,
    ) -> CalendarEvent:
        """Erstellt einen neuen Termin.

        Args:
            summary: Titel.
            start: Startzeit (naive datetime = lokale Zeit).
            duration_minutes: Dauer in Minuten (ignoriert bei all_day=True).
            location: Ort (optional).
            description: Beschreibung (optional).
            all_day: Ganztags-Event (nur Datum, keine Uhrzeit).
            recurrence: Liste von RRULE-Strings (z.B. ["RRULE:FREQ=YEARLY"]).

        Returns:
            Der erstellte CalendarEvent.
        """

        def _op():
            cal = self._get_calendar()
            uid = str(uuid.uuid4())
            tz_name = self._get_local_timezone()

            vcal_lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Elder-Berry//CalDAV//DE",
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"SUMMARY:{summary}",
            ]

            if all_day:
                dt_start = start.strftime("%Y%m%d")
                dt_end = (start + timedelta(days=1)).strftime("%Y%m%d")
                vcal_lines.append(f"DTSTART;VALUE=DATE:{dt_start}")
                vcal_lines.append(f"DTEND;VALUE=DATE:{dt_end}")
            else:
                dt_start = start.strftime("%Y%m%dT%H%M%S")
                end = start + timedelta(minutes=duration_minutes)
                dt_end = end.strftime("%Y%m%dT%H%M%S")
                vcal_lines.append(f"DTSTART;TZID={tz_name}:{dt_start}")
                vcal_lines.append(f"DTEND;TZID={tz_name}:{dt_end}")

            if location:
                vcal_lines.append(f"LOCATION:{location}")
            if description:
                vcal_lines.append(f"DESCRIPTION:{description}")
            if recurrence:
                for rrule in recurrence:
                    vcal_lines.append(rrule)

            vcal_lines.extend(
                [
                    "END:VEVENT",
                    "END:VCALENDAR",
                ]
            )

            ical_str = "\r\n".join(vcal_lines)
            cal.save_event(ical_str)

            logger.info("Termin erstellt: %s (%s)", summary, uid)

            if all_day:
                ev_start = datetime(start.year, start.month, start.day)
                ev_end = ev_start + timedelta(days=1)
            else:
                ev_start = start
                ev_end = start + timedelta(minutes=duration_minutes)

            return CalendarEvent(
                summary=summary,
                start=ev_start,
                end=ev_end,
                location=location,
                description=description,
                all_day=all_day,
                event_id=uid,
            )

        return self._call_with_retry(_op)

    def delete_event(self, event_id: str) -> bool:
        """Löscht einen Termin per UID.

        Args:
            event_id: UID des VEVENT.

        Returns:
            True wenn erfolgreich gelöscht.

        Raises:
            RuntimeError: Wenn der Termin nicht gefunden wurde oder Server-Fehler.
        """

        def _op():
            cal = self._get_calendar()
            try:
                event = cal.event_by_uid(event_id)
                event.delete()
                logger.info("Termin gelöscht: %s", event_id)
                return True
            except Exception as e:
                error_str = str(e).lower()
                if (
                    "404" in error_str
                    or "not found" in error_str
                    or "gone" in error_str
                ):
                    logger.info("Termin bereits gelöscht/nicht gefunden: %s", event_id)
                    return True
                logger.error("Termin löschen fehlgeschlagen (%s): %s", event_id, e)
                raise RuntimeError(f"Termin löschen fehlgeschlagen: {e}") from e

        return self._call_with_retry(_op)

    def format_events(self, events: list[CalendarEvent]) -> str:
        """Formatiert eine Liste von Terminen als Text."""
        if not events:
            return "Keine Termine."

        lines = []
        current_date = None
        for event in events:
            event_date = event.start.date()
            if event_date != current_date:
                current_date = event_date
                lines.append(f"\n{event_date.strftime('%A, %d.%m.%Y')}:")
            lines.append(f"  {event.format_short()}")

        return "\n".join(lines).strip()

    @staticmethod
    def _parse_event(event) -> CalendarEvent:
        """Parst ein caldav.Event in ein CalendarEvent."""
        import icalendar

        cal = icalendar.Calendar.from_ical(event.data)
        for component in cal.walk():
            if component.name == "VEVENT":
                summary = str(component.get("SUMMARY", "(Kein Titel)"))
                dtstart = component.get("DTSTART").dt
                dtend_prop = component.get("DTEND")

                all_day = isinstance(dtstart, date) and not isinstance(
                    dtstart, datetime
                )

                if all_day:
                    start = datetime(dtstart.year, dtstart.month, dtstart.day)
                    if dtend_prop:
                        end_date = dtend_prop.dt
                        end = datetime(end_date.year, end_date.month, end_date.day)
                    else:
                        end = start + timedelta(days=1)
                else:
                    start = dtstart
                    end = dtend_prop.dt if dtend_prop else dtstart + timedelta(hours=1)

                loc = component.get("LOCATION")
                loc_str = str(loc) if loc else None
                if loc_str == "":
                    loc_str = None

                desc = component.get("DESCRIPTION")
                desc_str = str(desc) if desc else None
                if desc_str == "":
                    desc_str = None

                return CalendarEvent(
                    summary=summary,
                    start=start,
                    end=end,
                    location=loc_str,
                    description=desc_str,
                    all_day=all_day,
                    event_id=str(component.get("UID", "")),
                )

        raise ValueError("Kein VEVENT in CalDAV-Antwort gefunden")

    @staticmethod
    def _get_local_timezone() -> str:
        """Ermittelt den lokalen Timezone-Namen."""
        try:
            local_tz = datetime.now().astimezone().tzinfo
            if hasattr(local_tz, "key"):
                return local_tz.key
        except Exception:
            pass
        return "Europe/Berlin"
