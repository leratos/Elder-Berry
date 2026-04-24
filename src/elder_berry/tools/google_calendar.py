"""GoogleCalendarClient – Google Calendar API Integration.

Liest und erstellt Termine über die Google Calendar API.
OAuth2-Tokens werden aus dem SecretStore geladen (setup via setup_google_oauth.py).

Verwendung:
    client = GoogleCalendarClient(secret_store=store)
    events = client.get_today()
    events = client.get_events(days=7)
    client.create_event("Zahnarzt", datetime(2026, 3, 20, 14, 0), duration_minutes=60)
"""
from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalendarEvent:
    """Ein Kalender-Termin."""

    summary: str
    """Titel des Termins."""

    start: datetime
    """Startzeit (timezone-aware)."""

    end: datetime
    """Endzeit (timezone-aware)."""

    location: str | None = None
    """Ort (optional)."""

    description: str | None = None
    """Beschreibung (optional)."""

    all_day: bool = False
    """True wenn Ganztags-Event."""

    event_id: str = ""
    """Google Calendar Event-ID (für Löschen/Ändern)."""

    def format_short(self) -> str:
        """Einzeilige Darstellung: '14:00-15:00 Zahnarzt (Praxis Dr. Müller) [#abc]'."""
        if self.all_day:
            time_str = "ganztags"
        else:
            # astimezone() konvertiert in System-Lokalzeit (Europe/Berlin)
            start_local = self.start.astimezone()
            end_local = self.end.astimezone()
            time_str = f"{start_local.strftime('%H:%M')}-{end_local.strftime('%H:%M')}"

        text = f"{time_str} {self.summary}"
        if self.location:
            text += f" ({self.location})"
        if self.event_id:
            text += f" [#{self.event_id}]"
        return text


class GoogleCalendarClient:
    """Google Calendar API Client.

    Lädt OAuth2-Tokens aus SecretStore, erstellt den Google API Service
    lazy beim ersten Zugriff. Tokens werden automatisch refreshed.
    """

    CALENDAR_ID = "primary"

    def __init__(self, secret_store: SecretStore) -> None:
        self._store = secret_store
        self._service = None

    def _get_service(self):
        """Lazy-Init: Erstellt Google Calendar API Service."""
        if self._service is not None:
            return self._service

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_json = self._store.get("google_oauth_tokens")
        token_data = json.loads(token_json)

        credentials = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )

        # Token refreshen wenn abgelaufen
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            # Aktualisierte Tokens speichern
            token_data["token"] = credentials.token
            self._store.set("google_oauth_tokens", json.dumps(token_data))
            logger.debug("Google OAuth Token refreshed")

        self._service = build("calendar", "v3", credentials=credentials)
        return self._service

    # Fehlertypen die auf eine tote Connection hindeuten
    _RETRIABLE_ERRORS = (ssl.SSLError, ConnectionError, OSError)

    def _call_with_retry(self, operation):
        """Führt operation() aus, mit 1x Retry bei stale Connection.

        Bei SSL-EOF oder Connection-Fehlern wird der gecachte Service
        invalidiert. Der zweite Aufruf von operation() holt sich via
        _get_service() eine frische Connection.

        Args:
            operation: Callable ohne Argumente, das _get_service() nutzt
                und den API-Call ausführt.
        """
        try:
            return operation()
        except self._RETRIABLE_ERRORS as e:
            logger.warning(
                "Google API Connection-Fehler, retry mit neuem Service: %s", e,
            )
            self._service = None
            return operation()

    def is_available(self) -> bool:
        """Prüft ob Google Calendar konfiguriert ist."""
        try:
            token_json = self._store.get_or_none("google_oauth_tokens")
            if not token_json:
                return False
            data = json.loads(token_json)
            return bool(data.get("refresh_token"))
        except Exception:
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
            service = self._get_service()
            now = datetime.now(timezone.utc)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days)).isoformat()

            result = service.events().list(
                calendarId=self.CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            return [self._parse_event(item) for item in result.get("items", [])]

        return self._call_with_retry(_op)

    def search_events(
        self, query: str, days: int = 30, max_results: int = 10,
    ) -> list[CalendarEvent]:
        """Sucht Termine per Volltextsuche.

        Args:
            query: Suchbegriff (durchsucht Titel, Beschreibung, Ort).
            days: Zeitraum in Tagen ab jetzt.
            max_results: Maximale Anzahl Ergebnisse.

        Returns:
            Liste passender CalendarEvents.
        """
        def _op():
            service = self._get_service()
            now = datetime.now(timezone.utc)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days)).isoformat()

            result = service.events().list(
                calendarId=self.CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                q=query,
            ).execute()

            return [self._parse_event(item) for item in result.get("items", [])]

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
            service = self._get_service()
            result = service.events().list(
                calendarId=self.CALENDAR_ID,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            return [self._parse_event(item) for item in result.get("items", [])]

        return self._call_with_retry(_op)

    def get_tomorrow(self) -> list[CalendarEvent]:
        """Termine für morgen."""
        def _op():
            service = self._get_service()
            now = datetime.now(timezone.utc)
            tomorrow_start = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            tomorrow_end = tomorrow_start + timedelta(days=1)

            result = service.events().list(
                calendarId=self.CALENDAR_ID,
                timeMin=tomorrow_start.isoformat(),
                timeMax=tomorrow_end.isoformat(),
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            return [self._parse_event(item) for item in result.get("items", [])]

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
        tz_name = self._get_local_timezone()

        if all_day:
            start_date = start.strftime("%Y-%m-%d")
            end_date = (start + timedelta(days=1)).strftime("%Y-%m-%d")
            body: dict = {
                "summary": summary,
                "start": {"date": start_date},
                "end": {"date": end_date},
            }
        else:
            end = start + timedelta(minutes=duration_minutes)
            body = {
                "summary": summary,
                "start": {
                    "dateTime": start.isoformat(),
                    "timeZone": tz_name,
                },
                "end": {
                    "dateTime": end.isoformat(),
                    "timeZone": tz_name,
                },
            }

        if location:
            body["location"] = location
        if description:
            body["description"] = description
        if recurrence:
            body["recurrence"] = recurrence

        def _op():
            service = self._get_service()
            created = service.events().insert(
                calendarId=self.CALENDAR_ID, body=body,
            ).execute()
            logger.info("Termin erstellt: %s (%s)", summary, created.get("id"))
            return self._parse_event(created)

        return self._call_with_retry(_op)

    def delete_event(self, event_id: str) -> bool:
        """Löscht einen Termin per Event-ID.

        Args:
            event_id: Google Calendar Event-ID.

        Returns:
            True wenn erfolgreich gelöscht.

        Raises:
            RuntimeError: Wenn der Termin nicht gefunden wurde oder API-Fehler.
        """
        def _op():
            service = self._get_service()
            try:
                service.events().delete(
                    calendarId=self.CALENDAR_ID, eventId=event_id,
                ).execute()
                logger.info("Termin gelöscht: %s", event_id)
                return True
            except Exception as e:
                # 410 Gone = bereits gelöscht (Idempotenz bei Retry)
                error_str = str(e)
                if "410" in error_str or "Gone" in error_str:
                    logger.info("Termin bereits gelöscht (410): %s", event_id)
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
    def _parse_event(item: dict) -> CalendarEvent:
        """Parst ein Google Calendar API Event-Objekt."""
        start_data = item.get("start", {})
        end_data = item.get("end", {})

        # Ganztags-Events haben "date", normale haben "dateTime"
        all_day = "date" in start_data and "dateTime" not in start_data

        if all_day:
            start = datetime.fromisoformat(start_data["date"])
            end = datetime.fromisoformat(end_data["date"])
        else:
            start = datetime.fromisoformat(start_data["dateTime"])
            end = datetime.fromisoformat(end_data["dateTime"])

        return CalendarEvent(
            summary=item.get("summary", "(Kein Titel)"),
            start=start,
            end=end,
            location=item.get("location"),
            description=item.get("description"),
            all_day=all_day,
            event_id=item.get("id", ""),
        )

    @staticmethod
    def _get_local_timezone() -> str:
        """Ermittelt den lokalen Timezone-Namen."""
        try:
            # Windows: tzname gibt z.B. ('Mitteleuropäische Zeit', 'Mitteleuropäische Sommerzeit')
            # Wir brauchen den IANA-Namen
            local_tz = datetime.now().astimezone().tzinfo
            if hasattr(local_tz, "key"):
                return local_tz.key
        except Exception:
            pass
        return "Europe/Berlin"
