# Phase 36.2 – CalDAV Kalender (Google Calendar ersetzen)

## Kontext

Nextcloud 33 läuft auf `cloud.last-strawberry.com`. Saleria nutzt derzeit
`GoogleCalendarClient` für Termine. Dieser soll durch einen `CalDAVCalendarClient`
ersetzt werden, der gegen die Nextcloud-CalDAV-API arbeitet.

**Kritischer Punkt:** Der neue Client muss exakt dasselbe Interface implementieren
wie `GoogleCalendarClient`. Alle Konsumenten (CalendarCommands, CalendarWatcher,
BriefingScheduler, SmartContextProvider, ContextEnricher) nutzen Duck Typing –
solange die Methodensignaturen identisch sind, ist kein Umbau nötig.

## Vorbereitung

1. Lies `docs/journal.txt` (letzte 80 Zeilen) für den aktuellen Stand
2. Lies `docs/concepts/phase-36-nextcloud-integration.md` (Abschnitt 36.2)
3. Lies `src/elder_berry/tools/google_calendar.py` – DAS ist das Interface das du 1:1 nachbauen musst
4. Lies `CLAUDE.md` für Projektkonventionen
5. Erstelle Branch: `feature/phase-36-2-caldav-calendar`

## Das Interface (aus GoogleCalendarClient – exakt einhalten!)

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass(frozen=True)
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    all_day: bool = False
    event_id: str = ""

    def format_short(self) -> str:
        """'14:00-15:00 Zahnarzt (Praxis) [#abc]' oder 'ganztags Urlaub [#def]'"""
        ...
```

**CalendarEvent ist bereits definiert in `google_calendar.py`.** Der CalDAV-Client
muss dieselbe Klasse zurückgeben. NICHT neu definieren – importiere sie:
`from elder_berry.tools.google_calendar import CalendarEvent`

**Methoden die der neue Client implementieren MUSS (1:1 Signatur):**

```python
class CalDAVCalendarClient:
    def __init__(self, secret_store: SecretStore) -> None: ...
    def is_available(self) -> bool: ...
    def get_events(self, days: int = 1, max_results: int = 20) -> list[CalendarEvent]: ...
    def search_events(self, query: str, days: int = 30, max_results: int = 10) -> list[CalendarEvent]: ...
    def get_today(self) -> list[CalendarEvent]: ...
    def get_events_range(self, start: datetime, end: datetime, max_results: int = 20) -> list[CalendarEvent]: ...
    def get_tomorrow(self) -> list[CalendarEvent]: ...
    def create_event(
        self, summary: str, start: datetime, duration_minutes: int = 60,
        location: str | None = None, description: str | None = None,
        all_day: bool = False, recurrence: list[str] | None = None,
    ) -> CalendarEvent: ...
    def delete_event(self, event_id: str) -> bool: ...
    def format_events(self, events: list[CalendarEvent]) -> str: ...
```

## Neue Dateien

### 1. `src/elder_berry/tools/caldav_calendar.py`

Klasse `CalDAVCalendarClient` — CalDAV-Client für Nextcloud Calendar.

**Credentials aus SecretStore:**
- `nextcloud_url` → z.B. `https://cloud.last-strawberry.com` (gleich wie Files-Client!)
- `nextcloud_user` → Nextcloud-Benutzername
- `nextcloud_app_password` → App-Passwort (gleich wie Files-Client!)

Die Credentials sind identisch mit dem NextcloudFilesClient. Kein separates Setup nötig.

**CalDAV-URL:**
`{nextcloud_url}/remote.php/dav/calendars/{nextcloud_user}/`

**Library: `caldav`** (Pure-Python CalDAV-Client)

```python
import caldav

class CalDAVCalendarClient:
    def __init__(self, secret_store: SecretStore) -> None:
        self._store = secret_store
        self._client: caldav.DAVClient | None = None
        self._calendar: caldav.Calendar | None = None

    def _get_calendar(self) -> caldav.Calendar:
        """Lazy-Init: Verbindet mit Nextcloud CalDAV und holt den primären Kalender."""
        if self._calendar is not None:
            return self._calendar
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
        # Nimm den ersten Kalender (oder suche nach Name "Persönlich"/"Personal")
        self._calendar = calendars[0]
        return self._calendar
```

**Implementierungshinweise je Methode:**

`get_events(days, max_results)`:
- `calendar.search(start=now_utc, end=now_utc+timedelta(days), event=True, expand=True)`
- `expand=True` löst wiederkehrende Termine in Einzelinstanzen auf (wie Google singleEvents=True)
- Ergebnis nach start sortieren
- Auf max_results begrenzen
- Jedes CalDAV-Event → `_parse_event()` → `CalendarEvent`

`search_events(query, days, max_results)`:
- `calendar.search(start=now_utc, end=now_utc+timedelta(days), event=True, expand=True)`
- Dann clientseitig filtern: `query.lower() in event.summary.lower()` (CalDAV text-match
  ist serverspezifisch und unzuverlässig, clientseitiges Filtern ist robuster)
- Alternative: CalDAV REPORT mit `<C:text-match>` — nur wenn Nextcloud das sauber unterstützt

`get_today()`:
- Delegiert an `get_events(days=1)`

`get_tomorrow()`:
- `calendar.search(start=tomorrow_00:00_utc, end=tomorrow_23:59_utc, event=True, expand=True)`

`get_events_range(start, end, max_results)`:
- `calendar.search(start=start, end=end, event=True, expand=True)`

`create_event(summary, start, duration_minutes, location, description, all_day, recurrence)`:
- Baut ein iCalendar VEVENT
- Nutze `icalendar` Library (kommt als Dependency von `caldav`) oder baue den iCal-String manuell
- Ganztags: `DTSTART;VALUE=DATE:20260328` (kein DTEND, oder DTEND = start + 1 Tag)
- Normal: `DTSTART:20260328T140000` + `DTEND:20260328T150000` (lokal, mit TZID)
- Wiederholung: `RRULE:FREQ=YEARLY` etc. (recurrence-Liste direkt einfügen)
- `calendar.save_event(...)` oder `calendar.add_event(ical_string)`
- Rückgabe: `CalendarEvent` mit `event_id` = UID des VEVENT

`delete_event(event_id)`:
- `calendar.event_by_uid(event_id)` → `event.delete()`
- Bei 404/Gone → True zurückgeben (Idempotenz, wie bei GoogleCalendarClient)

`format_events(events)`:
- Kopiere die Implementierung 1:1 aus `GoogleCalendarClient.format_events()` —
  die ist identisch (arbeitet nur mit `CalendarEvent`-Objekten, kein API-spezifischer Code)

**`_parse_event(caldav_event)` → CalendarEvent:**
```python
@staticmethod
def _parse_event(event) -> CalendarEvent:
    """Parst ein caldav.Event in ein CalendarEvent."""
    import icalendar
    cal = icalendar.Calendar.from_ical(event.data)
    for component in cal.walk():
        if component.name == "VEVENT":
            summary = str(component.get("SUMMARY", "(Kein Titel)"))
            dtstart = component.get("DTSTART").dt
            dtend = component.get("DTEND")
            # Ganztags-Events: dtstart ist date, nicht datetime
            all_day = not isinstance(dtstart, datetime)
            if all_day:
                start = datetime(dtstart.year, dtstart.month, dtstart.day)
                end_date = dtend.dt if dtend else dtstart + timedelta(days=1)
                end = datetime(end_date.year, end_date.month, end_date.day)
            else:
                start = dtstart
                end = dtend.dt if dtend else dtstart + timedelta(hours=1)
            return CalendarEvent(
                summary=summary,
                start=start,
                end=end,
                location=str(component.get("LOCATION", "")) or None,
                description=str(component.get("DESCRIPTION", "")) or None,
                all_day=all_day,
                event_id=str(component.get("UID", "")),
            )
    raise ValueError("Kein VEVENT in CalDAV-Antwort gefunden")
```

**Fehlerbehandlung und Retry:**
- CalDAV-Verbindungsfehler: `self._calendar = None` setzen → nächster Aufruf
  verbindet neu (gleiche Strategie wie GoogleCalendarClient._call_with_retry)
- Timeout: 10s für Abfragen, 15s für Create/Delete
- Fehlerklassen: nutze die bestehenden oder einfache RuntimeError

**Timezone-Handling:**
- Nextcloud speichert Termine in UTC oder mit TZID
- `_parse_event` muss timezone-aware datetimes zurückgeben
- Für Create: verwende `Europe/Berlin` als TZID (wie GoogleCalendarClient._get_local_timezone)
- Achtung: `date` vs `datetime` — Ganztags-Events sind `date`-Objekte in icalendar

### 2. `tests/test_caldav_calendar.py`

Tests für `CalDAVCalendarClient`. CalDAV-Server komplett gemockt.

**Test-Kategorien (~25 Tests):**

Credentials & Verfügbarkeit:
- `test_init_from_secret_store` — Credentials korrekt gelesen
- `test_is_available_success` — Server erreichbar, Kalender gefunden
- `test_is_available_no_credentials` — Fehlende Credentials → False
- `test_is_available_server_unreachable` — Timeout → False
- `test_lazy_calendar_init` — _get_calendar() erst bei erstem Zugriff

Events abrufen:
- `test_get_events_today` — search(start, end) + expand=True
- `test_get_events_multiple_days` — days=7
- `test_get_events_empty` — Keine Termine → leere Liste
- `test_get_today` — Delegiert an get_events(days=1)
- `test_get_tomorrow` — Korrekte Start/End-Berechnung
- `test_get_events_range` — Expliziter Zeitraum
- `test_get_events_max_results` — Begrenzung eingehalten
- `test_get_events_sorted` — Chronologisch sortiert

Suche:
- `test_search_events_found` — Treffer zurückgeben
- `test_search_events_no_results` — Kein Treffer → leere Liste
- `test_search_events_case_insensitive` — Suche ist case-insensitive

Event erstellen:
- `test_create_event_normal` — Mit Uhrzeit + Dauer
- `test_create_event_all_day` — Ganztags-Event
- `test_create_event_with_location` — Mit Ort
- `test_create_event_with_recurrence` — RRULE wird gesetzt
- `test_create_event_returns_calendar_event` — Rückgabe ist CalendarEvent

Event löschen:
- `test_delete_event_success` — UID gefunden → gelöscht
- `test_delete_event_not_found` — 404 → RuntimeError oder True (Idempotenz)
- `test_delete_event_already_gone` — Bereits gelöscht → True

Parsing:
- `test_parse_event_normal` — VEVENT mit DTSTART/DTEND datetime
- `test_parse_event_all_day` — VEVENT mit VALUE=DATE
- `test_parse_event_no_dtend` — Fallback auf start + 1h bzw. + 1 Tag

Connection-Recovery:
- `test_retry_after_connection_error` — Reconnect bei Netzwerkfehler

## Zu ändernde Dateien

### 3. `scripts/start_saleria.py`

In `_init_productivity_services()` — die Calendar-Initialisierung ersetzen:

```python
# Calendar: Nextcloud CalDAV (bevorzugt) oder Google Calendar (Fallback)
calendar_client = None

# Versuch 1: Nextcloud CalDAV
if secrets.get_or_none("nextcloud_url"):
    try:
        from elder_berry.tools.caldav_calendar import CalDAVCalendarClient
        cal = CalDAVCalendarClient(secret_store=secrets)
        if cal.is_available():
            calendar_client = cal
            logger.info("Calendar: Nextcloud CalDAV (%s)", secrets.get("nextcloud_url"))
    except ImportError:
        logger.debug("CalDAV: caldav-Library nicht installiert")
    except Exception as e:
        logger.warning("CalDAV nicht verfügbar: %s", e)

# Versuch 2: Google Calendar Fallback
if calendar_client is None:
    try:
        from elder_berry.tools.google_calendar import GoogleCalendarClient
        cal = GoogleCalendarClient(secret_store=secrets)
        if cal.is_available():
            calendar_client = cal
            logger.info("Calendar: Google Calendar (Fallback)")
    except ImportError:
        logger.debug("Google Calendar: google-api-python-client nicht installiert")
    except Exception as e:
        logger.warning("Google Calendar nicht verfügbar: %s", e)

if calendar_client:
    svc["calendar"] = calendar_client
else:
    logger.info("Calendar: kein Provider konfiguriert")
```

**Logik:** Nextcloud hat Priorität. Wenn Nextcloud-Credentials vorhanden UND `caldav`
installiert UND Server erreichbar → CalDAV. Sonst Fallback auf Google.
Kein Config-Flag nötig — Vorrang ergibt sich automatisch aus den vorhandenen Credentials.

### 4. `src/elder_berry/comms/commands/calendar_commands.py`

**TYPE_CHECKING Import ändern** — von spezifischem Client auf generischen Typ:

```python
if TYPE_CHECKING:
    # Duck-typed: Akzeptiert GoogleCalendarClient oder CalDAVCalendarClient
    from elder_berry.tools.google_calendar import GoogleCalendarClient as CalendarClient
```

Alternativ (sauberer, aber aufwändiger): Gar nicht ändern. Python's Duck Typing
funktioniert auch ohne korrekten Type-Hint. Der TYPE_CHECKING-Import hat keinen
Laufzeit-Effekt. Die Fehlermeldungstexte "Google Calendar nicht konfiguriert" sollten
aber auf "Kalender nicht konfiguriert" geändert werden (3 Stellen):

- `_cmd_termine()`: "Google Calendar nicht konfiguriert." → "Kalender nicht konfiguriert."
- `_cmd_termin_create()`: gleich
- `_cmd_termin_search()`: gleich
- `_cmd_termin_delete()`: gleich
- Docstrings: "Google Calendar Commands" → "Kalender-Commands"

### 5. `src/elder_berry/comms/briefing_scheduler.py`

TYPE_CHECKING Import anpassen (gleiche Logik wie calendar_commands):
- `from elder_berry.tools.google_calendar import GoogleCalendarClient` bleibt (TYPE_CHECKING only)
- Oder ersetzen durch: Kommentar "# Duck-typed: GoogleCalendarClient oder CalDAVCalendarClient"
- Kein Laufzeit-Effekt, kein Code-Umbau nötig

### 6. `src/elder_berry/comms/calendar_watcher.py`

Gleiche Situation wie briefing_scheduler — TYPE_CHECKING Import, kein Laufzeit-Code betroffen.

### 7. `src/elder_berry/core/smart_context.py`

Gleiche Situation — TYPE_CHECKING Import, kein Code-Umbau nötig.

### 8. `src/elder_berry/core/context_enricher.py`

Nicht direkt betroffen — nutzt Calendar nur über den Briefing-Kontext.

### 9. `pyproject.toml`

Neue optionale Dependency-Gruppe:
```toml
nextcloud = [
    "caldav>=1.0",
]
```

Die `caldav`-Library bringt `icalendar` als transitive Dependency mit.
`icalendar` wird für das Parsing der VEVENT-Daten gebraucht.

### 10. `src/elder_berry/comms/remote_commands.py`

HELP_TEXT anpassen — "Google Calendar" Referenzen entfernen:
- Der Kalender-Abschnitt im HELP_TEXT bleibt identisch (Commands ändern sich nicht)
- Nur die Fehlermeldung in CalendarCommands ändert sich (siehe oben)

## Konsumenten-Übersicht (alle nutzen dasselbe Interface)

| Komponente | Genutzte Methoden | Code-Änderung nötig? |
|---|---|---|
| CalendarCommandHandler | get_today, get_tomorrow, get_events, get_events_range, search_events, create_event, delete_event, format_events | Nur Fehlermeldungen + Docstrings |
| CalendarWatcher | get_events_range | Nein (Duck Typing) |
| BriefingScheduler | get_today, get_events_range, format_events | Nein (Duck Typing) |
| SmartContextProvider | get_today, get_events_range | Nein (Duck Typing) |
| ContextEnricher | (indirekt über BriefingScheduler) | Nein |

## Migration der Termine (manuell, nicht im Code)

Nach Implementierung und Test:
1. Google Calendar → Einstellungen → Exportieren → .ics Datei
2. Nextcloud Calendar → Import → .ics Datei hochladen
3. DAVx5 auf dem Handy: Google-Sync deaktivieren, nur noch Nextcloud
4. GoogleCalendarClient bleibt im Code als Fallback (kein Löschen)

## Architektur-Hinweise

- CalendarEvent wird aus google_calendar.py importiert (NICHT kopiert)
- format_events() kann ebenfalls importiert oder 1:1 kopiert werden
  (arbeitet nur auf CalendarEvent, kein API-Code)
- _get_local_timezone() aus GoogleCalendarClient kann als standalone Funktion
  extrahiert oder kopiert werden
- Die caldav-Library abstrahiert das CalDAV-Protokoll komplett —
  kein manuelles XML-Bauen nötig (anders als beim WebDAV-FilesClient)
- Retry-Logik: Bei Connection-Fehler `self._calendar = None` setzen,
  nächster Aufruf verbindet automatisch neu

## SecretStore Setup

Keine neuen Secrets nötig — die Nextcloud-Credentials aus Phase 36.1 reichen:
```python
from elder_berry.core.secret_store import SecretStore
s = SecretStore()
# Bereits gesetzt seit Phase 36.1:
# s.set("nextcloud_url", "https://cloud.last-strawberry.com")
# s.set("nextcloud_user", "<username>")
# s.set("nextcloud_app_password", "<app-passwort>")
```

## Reihenfolge

1. `CalDAVCalendarClient` implementieren (caldav_calendar.py)
2. Tests schreiben (test_caldav_calendar.py) — ~25 Tests, alles gemockt
3. `start_saleria.py` anpassen (CalDAV bevorzugt, Google Fallback)
4. `calendar_commands.py` Fehlermeldungen + Docstrings anpassen
5. `pyproject.toml` — `[nextcloud]` Gruppe mit `caldav>=1.0`
6. Alle Tests ausführen (bestehende + neue), 0 Fehler
7. Journal-Eintrag abschließen
8. Commit auf Branch
