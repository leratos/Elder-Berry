# Phase 8.1–8.3: Wetter, Timer & Erinnerungen, Daily Briefing

> **Status:** Geplant
> **Erstellt:** 2026-03-17 (Claude App)
> **Umsetzung:** Claude Code
> **Abhängigkeit:** Phase 8 (Kalender, Mail, Gym, Chat-History) abgeschlossen
> **Branch:** `feature/phase-8-1-weather-timer-briefing`

---

## Übersicht

Phase 8 fertigbauen: drei zusammenhängende Features, in dieser Reihenfolge.
Jedes Feature ist eigenständig nutzbar, aber sie bauen aufeinander auf.

1. **8.1 – Wetter** (Open-Meteo API, kein Key nötig)
2. **8.2 – Timer & Erinnerungen** (SQLite, asyncio-Scheduler)
3. **8.3 – Daily Briefing** (Cron-artig, kombiniert Wetter + Kalender + Erinnerungen)

---

## VORBEREITUNG

Bevor du mit der Implementierung beginnst:

1. Lies `C:\Dev\Elder-Berry\docs\journal.txt` (letzte 80 Zeilen)
2. Lies dieses Konzept-Dokument komplett durch
3. Erstelle Branch: `git checkout -b feature/phase-8-1-weather-timer-briefing`
4. Schreibe Draft-Eintrag in journal.txt

---

## 8.1 – WeatherClient (Open-Meteo)

### Neue Datei: `src/elder_berry/tools/weather_client.py`

**Klasse:** `WeatherClient`

**API:** Open-Meteo (https://api.open-meteo.com/v1/forecast) – kostenlos, kein API-Key.

**Standort:** Aus SecretStore laden. Keys:
- `weather_latitude` (str, z.B. "52.52")
- `weather_longitude` (str, z.B. "13.41")
- `weather_city` (str, z.B. "Berlin")

Falls Keys fehlen: graceful Degradation (Fehlermeldung, kein Crash).

**Dependency Injection:**
```python
def __init__(self, secret_store: SecretStore) -> None:
```

**Lazy-Init:** httpx.Client erst beim ersten Request erstellen (wie GymDataClient).

**Methoden:**

```python
def get_current(self) -> WeatherData:
    """Aktuelles Wetter: Temperatur, Beschreibung, Wind, Luftfeuchtigkeit."""

def get_today(self) -> WeatherForecast:
    """Tagesprognose: Min/Max Temperatur, Niederschlag, Beschreibung pro Tagesabschnitt."""

def get_days(self, days: int = 3) -> list[WeatherForecast]:
    """Mehrtagesprognose (max 7 Tage)."""

def format_current(self, data: WeatherData) -> str:
    """Formatierter Text für Matrix (Emoji + Werte)."""

def format_forecast(self, forecasts: list[WeatherForecast]) -> str:
    """Formatierter Text für mehrtägige Prognose."""
```

**DTOs (frozen dataclasses):**

```python
@dataclass(frozen=True)
class WeatherData:
    temperature: float          # °C
    apparent_temperature: float # Gefühlte Temperatur
    humidity: int               # %
    wind_speed: float           # km/h
    weather_code: int           # WMO Code
    description: str            # Menschenlesbar ("Bewölkt", "Leichter Regen", ...)
    city: str                   # Standortname

@dataclass(frozen=True)
class WeatherForecast:
    date: date
    temp_min: float
    temp_max: float
    precipitation_mm: float
    precipitation_probability: int  # %
    weather_code: int
    description: str
    city: str
```

**WMO Weather Codes → Beschreibung:**
Mapping als Dict im Modul (WMO_DESCRIPTIONS). Wichtigste:
- 0: Klar, 1-3: Teilweise bewölkt bis bedeckt, 45/48: Nebel
- 51-57: Nieselregen, 61-67: Regen, 71-77: Schnee
- 80-82: Regenschauer, 85-86: Schneeschauer, 95-99: Gewitter

**Emoji-Mapping:** weather_code → Emoji (☀️🌤️⛅☁️🌫️🌧️❄️⛈️ etc.)

**Open-Meteo API-Parameter:**
```
GET https://api.open-meteo.com/v1/forecast
  ?latitude=52.52
  &longitude=13.41
  &current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code
  &daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weather_code
  &timezone=Europe/Berlin
  &forecast_days=7
```

Timezone aus `datetime.now().astimezone().tzinfo` ableiten oder hart "Europe/Berlin" (kann später konfigurierbar werden).

### Neue Datei: `tests/test_weather_client.py`

Tests analog zu `test_gym_data.py` (httpx mocken, kein echter API-Call):
- WeatherData DTO: frozen, Felder korrekt
- WeatherForecast DTO: frozen, Felder korrekt
- WMO_DESCRIPTIONS: Mapping vollständig für wichtigste Codes
- get_current(): API-Response mocken → WeatherData zurück
- get_current(): fehlerhafte API-Response → saubere Exception
- get_current(): SecretStore ohne Koordinaten → klare Fehlermeldung
- get_today(): API-Response mocken → WeatherForecast zurück
- get_days(3): → Liste mit 3 WeatherForecast
- format_current(): enthält Emoji, Temperatur, Stadt
- format_forecast(): enthält Datum, Min/Max, Niederschlag

### Integration in RemoteCommandHandler

**Datei:** `src/elder_berry/comms/remote_commands.py`

Neuer Konstruktor-Parameter:
```python
weather: WeatherClient | None = None,
```

Neue Patterns:
```python
# Regex: "wetter morgen", "wetter woche", "wetter 3" (Tage)
WEATHER_PATTERN = re.compile(
    r"^wetter\s+(morgen|heute|woche|(\d{1,2}))$",
    re.IGNORECASE,
)
```

Neuer Simple-Command: `"wetter"` in SIMPLE_COMMANDS aufnehmen.

Neue KEYWORD_MAP-Einträge:
```python
"wetter": ["wie ist das wetter", "wetter draußen", "regnet es", "temperatur",
           "brauche ich einen schirm", "brauche ich eine jacke", "wie warm",
           "wie kalt", "wettervorhersage", "prognose"],
```

Parse-Stufe: Nach den bestehenden Termin/Mail-Patterns, vor Keyword-Suche:
```python
# Stufe 8g: Wetter mit Parameter ("wetter morgen", "wetter woche")
if WEATHER_PATTERN.match(normalized):
    return "wetter"
```

Execute-Handler:
```python
if command == "wetter":
    return self._cmd_weather(raw_text)
```

`_cmd_weather` Logik:
- Kein Parameter / "heute" → `get_current()` + `get_today()`
- "morgen" → `get_days(2)`, zweiten Tag nehmen
- "woche" → `get_days(7)`
- Zahl N → `get_days(N)`

HELP_TEXT ergänzen (Abschnitt "Wetter"):
```
Wetter:
  wetter – Aktuelles Wetter
  wetter morgen – Wetterprognose morgen
  wetter woche – 7-Tage-Prognose
  wetter 3 – Prognose für 3 Tage
```

### Integration in saleria.yaml + assistant.py

System-Prompt Remote-Tool-Liste ergänzen:
```
- wetter / wetter morgen / wetter woche: Wetter und Vorhersage
```

### Integration in start_saleria.py

Nach dem Gym-Client-Block:
```python
# Weather
weather = None
try:
    from elder_berry.tools.weather_client import WeatherClient
    weather = WeatherClient(secret_store=secrets)
    logger.info("Weather: aktiv")
except Exception as e:
    logger.warning("Weather nicht verfügbar: %s", e)
```

`weather=weather` an RemoteCommandHandler übergeben.

### Tests für Integration

In `tests/test_remote_commands.py` ergänzen:
- parse: "wetter" → "wetter"
- parse: "wetter morgen" → "wetter"
- parse: "wetter woche" → "wetter"
- parse: "wetter 3" → "wetter"
- keyword: "regnet es" → "wetter"
- keyword: "brauche ich einen schirm" → "wetter"
- execute: wetter ohne Client → Fehlertext
- execute: wetter aktuell → format_current Text
- execute: wetter morgen → Prognose-Text

### Journal-Eintrag nach Abschluss 8.1

Zwischenstand in journal.txt sichern bevor 8.2 beginnt.

---

## 8.2 – Timer & Erinnerungen

### Neue Datei: `src/elder_berry/tools/reminder_store.py`

**Klasse:** `ReminderStore`

**Persistenz:** SQLite (eine Datei, neustart-sicher).
Pfad: `~/.elder-berry/reminders.db` (neben SecretStore).

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,           -- Matrix-User (für Multi-User-Fähigkeit)
    message     TEXT NOT NULL,           -- Erinnerungstext
    due_at      TEXT NOT NULL,           -- ISO 8601 UTC
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    fired       INTEGER NOT NULL DEFAULT 0,  -- 0=ausstehend, 1=gesendet
    cancelled   INTEGER NOT NULL DEFAULT 0   -- 0=aktiv, 1=gelöscht
);
```

**DTO:**
```python
@dataclass(frozen=True)
class Reminder:
    id: int
    user_id: str
    message: str
    due_at: datetime     # timezone-aware (UTC)
    created_at: datetime
    fired: bool
    cancelled: bool
```

**Methoden:**
```python
def __init__(self, db_path: Path | None = None) -> None:
    """Öffnet/erstellt SQLite DB. Default: ~/.elder-berry/reminders.db"""

def add(self, user_id: str, message: str, due_at: datetime) -> Reminder:
    """Neue Erinnerung anlegen. due_at muss timezone-aware sein (wird als UTC gespeichert)."""

def get_pending(self, user_id: str | None = None) -> list[Reminder]:
    """Alle unfired+uncancelled Erinnerungen, optional gefiltert nach User."""

def get_due(self) -> list[Reminder]:
    """Alle Erinnerungen deren due_at <= jetzt UND noch nicht fired."""

def mark_fired(self, reminder_id: int) -> None:
    """Markiert Erinnerung als gesendet."""

def cancel(self, reminder_id: int) -> None:
    """Markiert Erinnerung als gelöscht."""

def cancel_all(self, user_id: str) -> int:
    """Löscht alle ausstehenden Erinnerungen eines Users. Gibt Anzahl zurück."""

def format_pending(self, reminders: list[Reminder]) -> str:
    """Formatierter Text für Matrix: Liste offener Erinnerungen."""
```

**Wichtig:**
- Alle Zeiten intern UTC. Beim Anzeigen in Lokalzeit konvertieren.
- Thread-safe: SQLite mit `check_same_thread=False`, eigene Connection pro Instanz.
- Cleanup: Alte fired Reminders nach 30 Tagen löschen (in get_due oder eigene Methode).

### Neue Datei: `src/elder_berry/comms/reminder_scheduler.py`

**Klasse:** `ReminderScheduler`

Daemon-Thread der periodisch (alle 15 Sekunden) `ReminderStore.get_due()` prüft
und fällige Erinnerungen über einen Callback sendet. Pattern analog zu AlertMonitor.

```python
class ReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        send_reminder: Callable[[str, str], None],  # (user_id, text) → sende an Matrix
        poll_interval: int = 15,
    ) -> None:

    def start(self) -> None:
    def stop(self) -> None:

    @property
    def is_running(self) -> bool:
```

`send_reminder` Callback bekommt `user_id` und formatierten Text.
Format: `"⏰ Erinnerung: {message}"`

**Wichtig:** Der Scheduler darf nicht crashen wenn send_reminder fehlschlägt (try/except im Loop).

### Neue Datei: `tests/test_reminder_store.py`

- Reminder DTO: frozen, Felder korrekt
- add(): Erinnerung anlegen → ID > 0
- add(): due_at ohne Timezone → Fehler (oder automatisch UTC annehmen – Entscheidung treffen)
- get_pending(): nur unfired + uncancelled
- get_pending(user_id): gefiltert nach User
- get_due(): nur due_at <= now und unfired
- get_due(): zukünftige Erinnerungen werden NICHT zurückgegeben
- mark_fired(): danach nicht mehr in get_due/get_pending
- cancel(): danach nicht mehr in get_pending
- cancel_all(): mehrere auf einmal, gibt Count zurück
- format_pending(): enthält Uhrzeit + Nachricht
- DB-Persistenz: Store schließen, neu öffnen → Daten noch da

### Neue Datei: `tests/test_reminder_scheduler.py`

- Scheduler start/stop (wie test_alert_monitor.py)
- Fällige Erinnerung → Callback wird aufgerufen
- Nicht fällige → Callback wird NICHT aufgerufen
- Callback-Fehler → Scheduler läuft weiter (kein Crash)
- Mark-fired nach Senden: Erinnerung wird nur einmal gesendet

### Integration in RemoteCommandHandler

Neue Konstruktor-Parameter:
```python
reminder_store: ReminderStore | None = None,
```

Neue Patterns:
```python
# "timer 20 minuten", "timer 5 min", "timer 1 stunde", "timer 90 sekunden"
TIMER_PATTERN = re.compile(
    r"^timer\s+(\d+)\s*(min(?:uten?)?|h(?:ours?)?|stunden?|sek(?:unden?)?|s|m)$",
    re.IGNORECASE,
)

# "erinnere mich um 18:00: Wäsche", "erinnerung 14:30 Meeting",
# "erinnere mich in 2 stunden: Kuchen aus dem Ofen"
REMINDER_PATTERN = re.compile(
    r"^(?:erinner[e]?\s+mich|erinnerung)\s+"
    r"(?:um\s+(\d{1,2}:\d{2})|in\s+(\d+)\s*(min(?:uten?)?|stunden?|h))"
    r"(?:\s*[:\s]\s*(.+))?$",
    re.IGNORECASE,
)

# "erinnerungen", "offene timer", "meine erinnerungen"
# → in SIMPLE_COMMANDS: "erinnerungen"

# "lösche erinnerung 3", "timer löschen"
REMINDER_DELETE_PATTERN = re.compile(
    r"(?:lösche?|entferne?|cancel)\s+(?:erinnerung|timer|reminder)\s*(\d+)?|"
    r"(?:erinnerung(?:en)?|timer)\s+(?:löschen|lösche|entferne)(?:\s+(\d+))?|"
    r"(?:lösche?|entferne?)\s+alle\s+(?:erinnerung(?:en)?|timer)",
    re.IGNORECASE,
)
```

KEYWORD_MAP:
```python
"erinnerungen": ["meine erinnerungen", "offene timer", "was steht an timer",
                  "welche erinnerungen", "ausstehende erinnerungen"],
```

Execute-Handler für:
- `"timer"` → Dauer parsen → `reminder_store.add(due_at=now+delta)` → Bestätigung
- `"reminder"` → Uhrzeit oder Dauer parsen + Nachricht → `reminder_store.add()` → Bestätigung
- `"erinnerungen"` → `reminder_store.get_pending()` → formatierte Liste
- `"reminder_delete"` → mit ID: `cancel(id)`, ohne ID/mit "alle": `cancel_all()`

Zeiteinheiten-Parser als Hilfsfunktion:
```python
def _parse_duration(amount: int, unit: str) -> timedelta:
    """Parst '20 min', '1 stunde', '90 sek' → timedelta."""
```

HELP_TEXT ergänzen:
```
Timer & Erinnerungen:
  timer 20 min – Timer auf 20 Minuten
  timer 1 stunde – Timer auf 1 Stunde
  erinnere mich um 18:00: Wäsche – Erinnerung zu bestimmter Uhrzeit
  erinnere mich in 2 stunden: Kuchen – Erinnerung nach Zeitspanne
  erinnerungen – Offene Erinnerungen anzeigen
  lösche erinnerung 3 – Erinnerung #3 löschen
  lösche alle erinnerungen – Alle löschen
```

### Integration in saleria.yaml + assistant.py

System-Prompt Remote-Tool-Liste ergänzen:
```
- timer <dauer>: Timer setzen (z.B. "timer 20 min")
- erinnere mich um/in <zeit>: <nachricht>: Erinnerung setzen
- erinnerungen: Offene Erinnerungen anzeigen
```

### Integration in Bridge (ReminderScheduler starten)

In `src/elder_berry/comms/bridge.py`:

Neuer Konstruktor-Parameter:
```python
reminder_scheduler: ReminderScheduler | None = None,
```

In `_run_async()` (wo auch AlertMonitor gestartet wird):
```python
if self._reminder_scheduler:
    self._reminder_scheduler.start()
```

In `stop()` und `_perform_restart()`:
```python
if self._reminder_scheduler:
    self._reminder_scheduler.stop()
```

### Integration in start_saleria.py

Nach Weather-Block:
```python
# Reminders
reminder_store = None
reminder_scheduler = None
try:
    from elder_berry.tools.reminder_store import ReminderStore
    from elder_berry.comms.reminder_scheduler import ReminderScheduler
    reminder_store = ReminderStore()
    logger.info("Reminders: aktiv (DB: %s)", reminder_store._db_path)
except Exception as e:
    logger.warning("Reminders nicht verfügbar: %s", e)
```

`reminder_store=reminder_store` an RemoteCommandHandler übergeben.

ReminderScheduler NACH Bridge-Erstellung mit thread-safe Callback:
```python
if reminder_store:
    def send_reminder(user_id: str, text: str):
        asyncio.run_coroutine_threadsafe(
            channel.send_text(room_id, text), bridge._loop
        )
    reminder_scheduler = ReminderScheduler(
        store=reminder_store,
        send_reminder=send_reminder,
    )
```

`reminder_scheduler=reminder_scheduler` an MatrixBridge übergeben.

### Tests für Integration

In `tests/test_remote_commands.py` ergänzen:
- parse: "timer 20 min" → "timer"
- parse: "timer 1 stunde" → "timer"
- parse: "erinnere mich um 18:00: Wäsche" → "reminder"
- parse: "erinnere mich in 2 stunden: Kuchen" → "reminder"
- parse: "erinnerungen" → "erinnerungen"
- parse: "lösche erinnerung 3" → "reminder_delete"
- parse: "lösche alle erinnerungen" → "reminder_delete"
- keyword: "offene timer" → "erinnerungen"
- execute: timer ohne Store → Fehlertext
- execute: timer 20 min → Bestätigungstext mit Uhrzeit
- execute: erinnerungen leer → "Keine offenen Erinnerungen"
- execute: erinnerungen mit Einträgen → formatierte Liste

### Journal-Eintrag nach Abschluss 8.2

Zwischenstand in journal.txt sichern bevor 8.3 beginnt.

---

## 8.3 – Daily Briefing

### Neue Datei: `src/elder_berry/comms/briefing_scheduler.py`

**Klasse:** `BriefingScheduler`

Daemon-Thread der einmal täglich zu konfigurierbarer Uhrzeit ein Briefing
an den Matrix-Raum sendet. Pattern analog zu AlertMonitor / ReminderScheduler.

```python
class BriefingScheduler:
    def __init__(
        self,
        send_briefing: Callable[[str], None],  # (text) → sende an Matrix
        calendar: GoogleCalendarClient | None = None,
        weather: WeatherClient | None = None,
        reminder_store: ReminderStore | None = None,
        briefing_hour: int = 7,
        briefing_minute: int = 30,
    ) -> None:

    def start(self) -> None:
    def stop(self) -> None:
    def build_briefing(self) -> str:
        """Baut den Briefing-Text zusammen. Auch manuell aufrufbar."""

    @property
    def is_running(self) -> bool:
```

**Briefing-Inhalt (build_briefing):**

```
☀️ Guten Morgen! Dein Briefing für heute:

🌤️ Wetter: 14°C, teilweise bewölkt. Später Regen ab 15 Uhr (8mm).
   Morgen: 11-17°C, sonnig.

📅 Termine heute:
   09:00 – Daily Standup
   14:00 – Zahnarzt

⏰ Offene Erinnerungen:
   #3 – Paket abholen (fällig: 12:00)

Schönen Tag! 🌿
```

Regeln:
- Abschnitte nur anzeigen wenn Daten vorhanden (kein leeres "Termine: keine")
- Wenn ein Service fehlt (z.B. kein Wetter konfiguriert): Abschnitt weglassen
- Wenn ALLES fehlt: kein Briefing senden (stille Degradation)
- Wetter: `get_current()` + `get_today()` für heute, morgen als Vorschau
- Kalender: `get_today()` → formatierte Liste
- Erinnerungen: `get_pending()` → nur die heutigen/überfälligen

**Timing-Logik:**
- Thread prüft jede 30 Sekunden ob `now.hour == briefing_hour and now.minute == briefing_minute`
- Flag `_briefing_sent_today: date | None` → verhindert Doppelsendung
- Um Mitternacht: Flag zurücksetzen

**Kein manueller Trigger als Command:** Das Briefing kann über `build_briefing()` auch
manuell aufgerufen werden, z.B. als Command "briefing". Aber das ist optional –
der Hauptzweck ist die automatische Morgennachricht.

### Neue Datei: `tests/test_briefing_scheduler.py`

- build_briefing(): alle Services vorhanden → vollständiger Text mit allen Abschnitten
- build_briefing(): nur Kalender → nur Kalender-Abschnitt
- build_briefing(): nur Wetter → nur Wetter-Abschnitt
- build_briefing(): nur Reminders → nur Reminder-Abschnitt
- build_briefing(): keine Services → leerer String (kein Briefing)
- build_briefing(): Kalender leer (keine Termine) → Abschnitt wird weggelassen
- Scheduler: start/stop Lifecycle
- Scheduler: Briefing wird zur richtigen Zeit gesendet (Time-Mock)
- Scheduler: Briefing wird nicht doppelt gesendet am selben Tag

### Integration in RemoteCommandHandler (optional, aber empfohlen)

Neuer Simple-Command: `"briefing"` in SIMPLE_COMMANDS.

KEYWORD_MAP:
```python
"briefing": ["guten morgen", "was steht heute an", "tagesübersicht",
             "daily briefing", "morgen briefing", "was gibt's neues"],
```

Execute-Handler:
```python
if command == "briefing":
    return self._cmd_briefing()
```

Braucht Zugriff auf den BriefingScheduler (neuer Konstruktor-Parameter) oder
direkt auf die drei Clients (calendar, weather, reminder_store).

Empfehlung: `BriefingScheduler` wird übergeben, `_cmd_briefing()` ruft `build_briefing()` auf.

HELP_TEXT:
```
Briefing:
  briefing – Tagesübersicht (Wetter + Termine + Erinnerungen)
```

### Integration in saleria.yaml + assistant.py

System-Prompt Remote-Tool-Liste ergänzen:
```
- briefing: Tagesübersicht (Wetter, Termine, Erinnerungen)
```

### Integration in start_saleria.py

Nach ReminderScheduler-Block:
```python
# Daily Briefing
briefing_scheduler = None
try:
    from elder_berry.comms.briefing_scheduler import BriefingScheduler
    briefing_scheduler = BriefingScheduler(
        send_briefing=lambda text: asyncio.run_coroutine_threadsafe(
            channel.send_text(room_id, text), bridge._loop
        ),
        calendar=calendar,
        weather=weather,
        reminder_store=reminder_store,
        briefing_hour=7,
        briefing_minute=30,
    )
    logger.info("Daily Briefing: aktiv (07:30)")
except Exception as e:
    logger.warning("Daily Briefing nicht verfügbar: %s", e)
```

`briefing_scheduler=briefing_scheduler` an MatrixBridge übergeben.

Bridge startet/stoppt BriefingScheduler analog zu AlertMonitor und ReminderScheduler.

### Integration in Bridge

Neuer Konstruktor-Parameter:
```python
briefing_scheduler: BriefingScheduler | None = None,
```

Start/Stop analog zu den anderen Schedulern.

---

## Zusammenfassung: Alle Dateien

### Neue Dateien
| Datei | Klasse | Zeilen (geschätzt) |
|---|---|---|
| `src/elder_berry/tools/weather_client.py` | WeatherClient | ~180 |
| `src/elder_berry/tools/reminder_store.py` | ReminderStore | ~160 |
| `src/elder_berry/comms/reminder_scheduler.py` | ReminderScheduler | ~80 |
| `src/elder_berry/comms/briefing_scheduler.py` | BriefingScheduler | ~140 |
| `tests/test_weather_client.py` | Tests | ~200 |
| `tests/test_reminder_store.py` | Tests | ~180 |
| `tests/test_reminder_scheduler.py` | Tests | ~80 |
| `tests/test_briefing_scheduler.py` | Tests | ~120 |

### Geänderte Dateien
| Datei | Änderungen |
|---|---|
| `src/elder_berry/comms/remote_commands.py` | +weather/timer/reminder/briefing Commands, Patterns, KEYWORD_MAP, HELP_TEXT |
| `src/elder_berry/comms/bridge.py` | +reminder_scheduler, +briefing_scheduler Parameter, start/stop |
| `src/elder_berry/character/saleria.yaml` | +wetter, +timer, +erinnerungen, +briefing in Remote-Tool-Liste |
| `src/elder_berry/core/assistant.py` | System-Prompt analog zu saleria.yaml (falls Fallback-Template) |
| `scripts/start_saleria.py` | +WeatherClient, +ReminderStore, +ReminderScheduler, +BriefingScheduler Init |
| `tests/test_remote_commands.py` | +Tests für alle neuen Commands (parse + execute) |
| `tests/test_comms.py` | +Tests für Bridge mit Reminder/Briefing-Scheduler |

### Keine Änderung nötig
- `pyproject.toml` – keine neuen Dependencies (httpx für Open-Meteo bereits vorhanden, sqlite3 ist Stdlib)
- `PROJECT_ROADMAP.md` – Items werden auf ✅ gesetzt nach Abschluss

---

## Reihenfolge der Implementierung

1. **WeatherClient** + Tests → Integration in RemoteCommandHandler → Tests
2. **Journal-Zwischenstand**
3. **ReminderStore** + Tests → **ReminderScheduler** + Tests → Integration → Tests
4. **Journal-Zwischenstand**
5. **BriefingScheduler** + Tests → Integration → Tests
6. **Alle Tests laufen lassen** (`pytest tests/ -v`)
7. **Journal-Abschluss-Eintrag**
8. **Git commit** auf Branch `feature/phase-8-1-weather-timer-briefing`

---

## Qualitäts-Checkliste (vor Commit)

- [ ] Alle neuen Klassen haben Docstrings (Modul + Klasse + Public Methods)
- [ ] Alle neuen DTOs sind `@dataclass(frozen=True)`
- [ ] Kein `import *`, alle Imports explizit
- [ ] TYPE_CHECKING für Typ-Hints die nur zur Analyse gebraucht werden
- [ ] Logger pro Modul: `logger = logging.getLogger(__name__)`
- [ ] Keine hartcodierten Pfade (pathlib, SecretStore)
- [ ] Graceful Degradation: fehlende Dependencies → Fehlertext, kein Crash
- [ ] HELP_TEXT aktualisiert mit allen neuen Commands
- [ ] saleria.yaml Remote-Tool-Liste aktualisiert
- [ ] assistant.py Fallback-Template aktualisiert (falls vorhanden)
- [ ] Alle Tests grün (`pytest tests/ -v`)
- [ ] Journal-Eintrag geschrieben
