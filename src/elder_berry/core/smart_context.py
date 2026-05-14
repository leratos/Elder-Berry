"""SmartContextProvider – Automatische Kontext-Anreicherung für LLM-Anfragen.

Analysiert den User-Input und entscheidet keyword-basiert, welche Datenquellen
(Calendar, Todos, Contacts, Reminders, Weather) relevant sind.
Fragt die relevanten Stores parallel ab und liefert formatierten Kontext
für den System-Prompt.

Phase 91-A: NOTES-Source ist in dieser Etappe deaktiviert; NoteStore wurde
in FactStore + NextcloudNotesClient gesplittet. Notes-Lookups kommen in
Phase 91-B/C zurueck (gegen NextcloudNotesClient).

Wird von Assistant.process() bei jeder Anfrage aufgerufen.
Graceful Degradation: fehlende oder fehlerhafte Quellen werden übersprungen.

Verwendung:
    provider = SmartContextProvider(
        calendar=calendar_client,
        task_client=task_client,
        contact_store=contact_store,
        reminder_store=reminder_store,
        weather_client=weather_client,
        default_user_id="@user:matrix.example.com",
    )
    context = provider.get_context("Was muss ich heute noch machen?")
    # → "=== Aktueller Kontext ===\\n\\n📅 Termine heute:\\n  ..."
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.google_calendar import GoogleCalendarClient
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.tools.caldav_tasks import CalDAVTaskClient
    from elder_berry.tools.weather_client import WeatherClient

logger = logging.getLogger(__name__)

# Timeout pro Datenquelle (Sekunden)
SOURCE_TIMEOUT_SECONDS = 3


class ContextSource(Enum):
    """Verfügbare Kontext-Quellen."""

    CALENDAR = "calendar"
    TODOS = "todos"
    REMINDERS = "reminders"
    NOTES = "notes"
    CONTACTS = "contacts"
    WEATHER = "weather"


# Keyword-Sets pro Quelle (lowercase, Deutsch + Englisch)
_SOURCE_KEYWORDS: dict[ContextSource, set[str]] = {
    ContextSource.CALENDAR: {
        "termin",
        "termine",
        "kalender",
        "calendar",
        "meeting",
        "besprechung",
        "verabredung",
        "event",
        "events",
        "woche",
        "wochenplan",
        "wochenende",
        "heute",
        "morgen",
        "montag",
        "dienstag",
        "mittwoch",
        "donnerstag",
        "freitag",
        "samstag",
        "sonntag",
    },
    ContextSource.TODOS: {
        "todo",
        "todos",
        "aufgabe",
        "aufgaben",
        "task",
        "tasks",
        "erledigen",
        "abarbeiten",
        "offen",
        "machen",
        "to-do",
    },
    ContextSource.REMINDERS: {
        "erinnerung",
        "erinnerungen",
        "reminder",
        "reminders",
        "fällig",
        "vergessen",
        "erinner",
    },
    # ContextSource.NOTES: in Phase 91-A deaktiviert (NoteStore-Refactor).
    # Keywords (notiz, notizen, fakt, fakten, ...) werden in Phase 91-B/C
    # gegen den FactStore + NextcloudNotesClient reaktiviert.
    ContextSource.CONTACTS: {
        "kontakt",
        "kontakte",
        "contact",
        "contacts",
        "telefon",
        "nummer",
        "email",
        "adresse",
        "anrufen",
        "telefonnummer",
        "geburtstag",
        "birthday",
        "wohnt",
        "arbeitet",
        "gruppe",
        "gruppen",
        "kategorie",
        "kategorien",
        "firma",
        "organisation",
        "jahrestag",
        "spitzname",
        "website",
        "kollege",
        "kollegin",
        "freund",
        "freundin",
    },
    ContextSource.WEATHER: {
        "wetter",
        "weather",
        "regen",
        "regnet",
        "temperatur",
        "kalt",
        "warm",
        "sonne",
        "sonnig",
        "schnee",
        "grad",
        "bewölkt",
        "wind",
        "sturm",
        "gewitter",
        "schirm",
        "jacke",
    },
}

# Phrasen die mehrere Quellen gleichzeitig triggern (längste zuerst)
_META_PHRASES: list[tuple[str, set[ContextSource]]] = [
    (
        "wie sieht mein tag aus",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
            ContextSource.WEATHER,
        },
    ),
    (
        "was steht heute an",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "plan für heute",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "was muss ich",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "was steht an",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "was hab ich",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "was habe ich",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "tagesplan",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "überblick",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
        },
    ),
    (
        "zusammenfassung",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
            ContextSource.WEATHER,
        },
    ),
    (
        "briefing",
        {
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
            ContextSource.WEATHER,
        },
    ),
]


class SmartContextProvider:
    """Analysiert User-Input und liefert relevanten Kontext aus Stores.

    Alle Datenquellen sind optional (Graceful Degradation).
    Pro Quelle gilt ein Timeout von SOURCE_TIMEOUT_SECONDS.
    """

    def __init__(
        self,
        calendar: GoogleCalendarClient | None = None,
        task_client: CalDAVTaskClient | None = None,
        contact_store: ContactStore | None = None,
        reminder_store: ReminderStore | None = None,
        weather_client: WeatherClient | None = None,
        default_user_id: str = "",
    ) -> None:
        self._calendar = calendar
        self._task_client = task_client
        self._contact_store = contact_store
        self._reminder_store = reminder_store
        self._weather_client = weather_client
        self._default_user_id = default_user_id

    def get_context(self, user_input: str) -> str:
        """Analysiert den Input und liefert formatierten Kontext.

        Args:
            user_input: Text-Eingabe des Nutzers.

        Returns:
            Formatierter Kontext-Block für den System-Prompt.
            Leerer String wenn keine relevanten Quellen erkannt.
        """
        sources = self._detect_sources(user_input)
        if not sources:
            return ""

        available = self._filter_available(sources)
        if not available:
            return ""

        results = self._query_sources(available, user_input)
        if not results:
            return ""

        return self._format_context(results)

    def _detect_sources(self, user_input: str) -> set[ContextSource]:
        """Erkennt relevante Quellen anhand von Keywords im User-Input."""
        text = user_input.lower()
        detected: set[ContextSource] = set()

        # 1. Meta-Phrasen prüfen
        for phrase, sources in _META_PHRASES:
            if phrase in text:
                detected.update(sources)

        # 2. Einzelne Keywords prüfen
        words = set(re.findall(r"[a-zäöüß\-]+", text))
        for source, keywords in _SOURCE_KEYWORDS.items():
            if words & keywords:
                detected.add(source)

        return detected

    def _filter_available(
        self,
        sources: set[ContextSource],
    ) -> set[ContextSource]:
        """Filtert auf Quellen, für die ein Store konfiguriert ist."""
        store_map = {
            ContextSource.CALENDAR: self._calendar,
            ContextSource.TODOS: self._task_client,
            ContextSource.REMINDERS: self._reminder_store,
            ContextSource.CONTACTS: self._contact_store,
            ContextSource.WEATHER: self._weather_client,
        }
        # Phase 91-A: NOTES nicht im Mapping -> wird ausgefiltert
        # (NoteStore-Refactor, Re-Enable in Phase 91-B/C).
        return {s for s in sources if store_map.get(s) is not None}

    def _query_sources(
        self,
        sources: set[ContextSource],
        user_input: str,
    ) -> dict[ContextSource, str]:
        """Fragt alle relevanten Quellen parallel ab (mit Timeout)."""
        results: dict[ContextSource, str] = {}

        with ThreadPoolExecutor(max_workers=min(len(sources), 6)) as pool:
            future_to_source: dict[Future[str], ContextSource] = {}
            for source in sources:
                fn = self._get_query_fn(source, user_input)
                future_to_source[pool.submit(fn)] = source

            try:
                for future in as_completed(
                    future_to_source,
                    timeout=SOURCE_TIMEOUT_SECONDS + 1,
                ):
                    source = future_to_source[future]
                    try:
                        result = future.result(timeout=0)
                        if result:
                            results[source] = result
                    except Exception as e:
                        logger.warning(
                            "SmartContext: %s Fehler: %s",
                            source.value,
                            e,
                        )
            except FuturesTimeoutError:
                timed_out = [
                    future_to_source[f].value for f in future_to_source if not f.done()
                ]
                if timed_out:
                    logger.warning(
                        "SmartContext: Timeout für: %s",
                        ", ".join(timed_out),
                    )

        return results

    def _get_query_fn(
        self,
        source: ContextSource,
        user_input: str,
    ) -> Callable[[], str]:
        """Gibt die passende Query-Funktion für eine Quelle zurück.

        Das match deckt heute alle ContextSource-Werte ab. Der explizite
        ``case _`` mit ``assert_never`` schuetzt dagegen, dass ein
        spaeter ergaenzter Enum-Wert lautlos ``None`` zurueckgibt --
        Caller in ``_query_sources`` wuerde sonst ``pool.submit(None)``
        machen und im Worker-Thread mit obskurem Stacktrace crashen.
        """
        match source:
            case ContextSource.CALENDAR:
                return self._query_calendar
            case ContextSource.TODOS:
                return self._query_todos
            case ContextSource.REMINDERS:
                return self._query_reminders
            case ContextSource.NOTES:
                # Phase 91-A Stub: NOTES wird nie aktiviert (Keywords + Mapping
                # entfernt). Lambda steht hier nur als Schutz vor assert_never,
                # falls Aufrufer NOTES manuell durchschleust.
                return lambda: ""
            case ContextSource.CONTACTS:
                return lambda: self._query_contacts(user_input)
            case ContextSource.WEATHER:
                return self._query_weather
            case _:
                assert_never(source)

    # --- Einzelne Query-Methoden ---

    def _query_calendar(self) -> str:
        """Holt heutige Termine.

        Vorbedingung: ``_calendar is not None`` -- gefiltert in
        ``_filter_available``. Das ``assert`` macht die Bedingung
        lokal sichtbar und gibt mypy das Narrowing.
        """
        assert self._calendar is not None
        events = self._calendar.get_today()
        if not events:
            return ""
        lines = ["📅 Termine heute:"]
        for ev in events:
            lines.append(f"  {ev.format_short()}")
        return "\n".join(lines)

    def _query_todos(self) -> str:
        """Holt offene Aufgaben als Briefing-Text."""
        assert self._task_client is not None
        return self._task_client.format_for_briefing()

    def _query_reminders(self) -> str:
        """Holt heutige und überfällige Erinnerungen."""
        assert self._reminder_store is not None
        user_id = self._default_user_id or None
        pending = self._reminder_store.get_pending(user_id)
        if not pending:
            return ""
        now = datetime.now(timezone.utc)
        today_end = datetime(
            now.year,
            now.month,
            now.day,
            23,
            59,
            59,
            tzinfo=timezone.utc,
        )
        relevant = [r for r in pending if r.due_at <= today_end]
        if not relevant:
            return ""
        lines = ["⏰ Offene Erinnerungen:"]
        for r in relevant:
            local_time = r.due_at.astimezone()
            lines.append(
                f"  #{r.id} – {r.message} (fällig: {local_time.strftime('%H:%M')})"
            )
        return "\n".join(lines)

    def _query_contacts(self, user_input: str) -> str:
        """Durchsucht ContactStore nach dem User-Input."""
        assert self._contact_store is not None
        if not self._default_user_id:
            return ""
        results = self._contact_store.search(
            self._default_user_id,
            user_input,
            3,
        )
        if not results:
            return ""
        lines = ["👤 Gefundene Kontakte:"]
        for c in results:
            lines.append(c.format_for_llm())
        return "\n\n".join(lines)

    def _query_weather(self) -> str:
        """Holt aktuelle Wetterdaten."""
        assert self._weather_client is not None
        result = self._weather_client.get_current()
        return (
            f"🌤️ Wetter: {result.description}, {result.temperature}°C"
            f" (gefühlt {result.apparent_temperature}°C)"
        )

    @staticmethod
    def _format_context(results: dict[ContextSource, str]) -> str:
        """Formatiert die Ergebnisse als Kontext-Block für den System-Prompt."""
        order = [
            ContextSource.CALENDAR,
            ContextSource.TODOS,
            ContextSource.REMINDERS,
            ContextSource.NOTES,
            ContextSource.CONTACTS,
            ContextSource.WEATHER,
        ]
        sections = [results[s] for s in order if s in results]
        if not sections:
            return ""
        header = "=== Aktueller Kontext (automatisch ermittelt) ==="
        return f"{header}\n\n" + "\n\n".join(sections)
