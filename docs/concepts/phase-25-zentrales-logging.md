# Phase 25 – Zentrales Logging & Error-Monitoring

> **Status:** Konzept
> **Erstellt:** 2026-03-20
> **Abhängigkeit:** MatrixBridge (Phase 6), AlertMonitor (Phase 7),
>   alle Daemon-Worker (Phase 8/17/19)

---

## Ziel

Alle Fehler im System werden zuverlässig erfasst, persistent gespeichert,
und bei kritischen Problemen wird der Nutzer proaktiv über Matrix informiert.
Aktuell gehen Fehler aus Background-Threads (ChatHistory-Summary,
CalendarWatcher, ReminderScheduler, BriefingScheduler) verloren oder
erscheinen nur im Terminal.

**Aktuell:**
```
Bridge._log_error()  → logs/error_log.txt     (nur 8 Stellen in bridge.py)
logger.error()       → Terminal/Console        (34 Dateien, kein File-Output)
Background-Threads   → logger.exception()      (nur Terminal, kein Alerting)
→ Fehler verschwinden wenn Terminal geschlossen wird
→ Nutzer erfährt nichts von stillen Ausfällen
```

**Nachher:**
```
Alle Komponenten      → Python logging          (einheitlich)
  ├─ StreamHandler    → Terminal                 (wie bisher)
  ├─ RotatingFileHandler → logs/elder_berry.log  (persistent, rotiert)
  └─ ErrorCollector   → SQLite + Matrix-Alert    (ERROR+, dedupliziert)
→ Kein Fehler geht verloren
→ Nutzer wird bei kritischen Problemen informiert
```

---

## Ist-Zustand

### Error-Log (bridge.py: `_log_error()`)
- Manuelles File-Writing in `logs/error_log.txt`
- Nur 8 Stellen in bridge.py nutzen es (command, agent, stt, document, llm, multi_step)
- Flat-Text-Format, kein Rotation, unbegrenztes Wachstum
- Kein Parsing/Suche möglich

### Python Logging (start_saleria.py)
- `logging.basicConfig()` mit StreamHandler (Console only)
- Format: `HH:MM:SS [LEVEL] name: message`
- Kein FileHandler → Log geht verloren wenn Terminal geschlossen wird
- Kein separater ERROR-Handler

### Background-Threads (8 Daemon-Worker)
| Worker | Fehler-Handling | Nutzer-Benachrichtigung |
|--------|-----------------|------------------------|
| MatrixBridge | logger.error + _log_error | Ja (Command-Fehler) |
| CalendarWatcher | logger.error | Nein |
| ReminderScheduler | logger.error | Nein |
| BriefingScheduler | logger.error | Nein |
| AlertMonitor | logger.error | Nein (Alerting = eigene Logik) |
| ChatHistory Summary | logger.exception | Nein |
| AudioDashboard | Implicit (Starlette) | Nein |

### Stärken (beibehalten)
- Alle Exceptions werden gefangen (keine stillen Crashes)
- Alle Exceptions werden geloggt (mindestens Console)
- Daemon-Threads sind sauber implementiert (while _running, stop/join)
- Command-Fehler benachrichtigen den Nutzer direkt

### Kritische Lücken
1. **Kein persistentes Log** – Terminal zu = Logs weg
2. **Stille Worker-Ausfälle** – CalendarWatcher kaputt? Nutzer merkt nichts
3. **Kein Rotation** – error_log.txt wächst unbegrenzt
4. **Keine Deduplizierung** – gleicher Fehler 100x = 100 Log-Einträge
5. **Zwei Log-Systeme** – Python logging + manuelles _log_error() parallel

---

## Lösung

### Teil 1: Python Logging zentralisieren

`logging.basicConfig()` durch `logging.config.dictConfig()` ersetzen.
Einmalig in `start_saleria.py`, wirkt für alle Logger im Projekt.

```python
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%H:%M:%S",
        },
        "file": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/elder_berry.log",
            "formatter": "file",
            "level": "INFO",
            "maxBytes": 5_000_000,    # 5 MB
            "backupCount": 3,         # elder_berry.log.1, .2, .3
            "encoding": "utf-8",
        },
        "error_collector": {
            "class": "elder_berry.core.error_collector.ErrorCollectorHandler",
            "level": "ERROR",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file", "error_collector"],
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
```

**Effekt:** Jeder `logger.error()` / `logger.exception()` in jeder Datei
landet automatisch in:
1. Console (wie bisher)
2. `logs/elder_berry.log` (persistent, rotiert bei 5 MB, max 4 Dateien = 20 MB)
3. ErrorCollector (für Alerting + Deduplizierung)

### Teil 2: ErrorCollector (neuer Logging-Handler)

```python
# core/error_collector.py

class ErrorCollectorHandler(logging.Handler):
    """Logging-Handler der ERROR+ Einträge sammelt und optional alerted.

    - Deduplizierung: gleicher Fehler (Logger + Exception-Typ) wird nur
      alle 5 Minuten erneut an Matrix gesendet
    - Rate-Limiting: max 5 Alerts pro 10 Minuten (kein Matrix-Spam)
    - Optional: SQLite-Persistenz für Error-History
    """

    def __init__(self, alert_callback=None, cooldown=300, max_alerts=5):
        super().__init__(level=logging.ERROR)
        self._alert_callback = alert_callback  # Callable[[str], None]
        self._cooldown = cooldown              # Sekunden zwischen gleichen Alerts
        self._max_alerts = max_alerts           # Max Alerts pro Fenster
        self._seen: dict[str, float] = {}       # key → letzter Alert-Timestamp
        self._alert_count = 0
        self._window_start = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        # Deduplizierung
        key = f"{record.name}:{record.exc_info[1].__class__.__name__}" \
              if record.exc_info and record.exc_info[1] else record.name
        now = time.time()

        if key in self._seen and (now - self._seen[key]) < self._cooldown:
            return  # Gleicher Fehler innerhalb Cooldown → ignorieren

        self._seen[key] = now

        # Rate-Limiting
        if now - self._window_start > 600:  # 10-Minuten-Fenster
            self._alert_count = 0
            self._window_start = now

        if self._alert_callback and self._alert_count < self._max_alerts:
            self._alert_count += 1
            msg = self.format(record)
            try:
                self._alert_callback(msg)
            except Exception:
                pass  # Alert-Fehler darf nicht den Logger crashen
```

### Teil 3: Matrix-Alerting für Background-Fehler

ErrorCollector bekommt einen `alert_callback` der Fehler über Matrix sendet.
Der Callback wird in der Bridge verdrahtet (hat Zugriff auf den Channel).

```python
# In bridge.py oder start_saleria.py:

def _setup_error_alerting(bridge):
    collector = logging.getLogger().handlers[-1]  # ErrorCollectorHandler
    if isinstance(collector, ErrorCollectorHandler):
        def alert(msg):
            # Async-safe: schedule in bridge's event loop
            asyncio.run_coroutine_threadsafe(
                bridge._channel.send_text(bridge._alert_room_id, f"⚠ {msg}"),
                bridge._loop,
            )
        collector.set_alert_callback(alert)
```

### Teil 4: bridge._log_error() entfernen

`_log_error()` wird überflüssig – alle 8 Stellen in bridge.py nutzen bereits
`logger.error()` direkt davor. Das manuelle File-Writing und der
separate error_log.txt-Mechanismus werden entfernt.

**Vorher:**
```python
logger.error("Remote-Command '%s' fehlgeschlagen: %s", command, e)
self._log_error(msg.sender, msg.body, e, handler="command")
```

**Nachher:**
```python
logger.error("Remote-Command '%s' fehlgeschlagen: %s", command, e,
             extra={"sender": msg.sender, "handler": "command"})
```

Das `extra`-Dict wird vom FileHandler mit ausgegeben und vom ErrorCollector
für Kontext genutzt.

---

## Alternativen (verworfen)

### Sentry / External Error Tracking
- Zu viel Overhead für Single-User Hobby-Projekt
- Datenschutz: Fehler-Daten würden an Dritte gehen
- **Lösung: eigener ErrorCollector ist einfacher und reicht**

### SQLite Error-Datenbank
- Ermöglicht Error-History, Statistiken, Dashboard
- Aber: RotatingFileHandler + ErrorCollector decken den Bedarf ab
- **Kann später ergänzt werden wenn nötig (YAGNI)**

### JSON Structured Logging
- python-json-logger für maschinenlesbare Logs
- Aber: Logs werden von Menschen gelesen, nicht von Maschinen
- Terminal-Output wird unlesbar
- **Flat-Text ist für diesen Use-Case besser**

---

## Scope

### Neue Dateien
| Datei | Beschreibung |
|-------|-------------|
| `core/error_collector.py` | ErrorCollectorHandler (logging.Handler) |

### Geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `scripts/start_saleria.py` | dictConfig statt basicConfig, ErrorCollector Setup |
| `comms/bridge.py` | `_log_error()` entfernen, alert_callback verdrahten |
| `tests/test_error_collector.py` | Tests für Deduplizierung, Rate-Limit, Alerting |

### Was sich NICHT ändert
- Bestehende `logger.error()`/`logger.exception()` Aufrufe (funktionieren weiter)
- Bestehende Command-Fehler-Responses an Nutzer (bleiben wie sie sind)
- AlertMonitor (bleibt für Disk/Prozess-Alerts, eigene Logik)
- Daemon-Thread Architektur (while _running, stop/join)

---

## Sicherheit

### Rate-Limiting (Matrix-Spam verhindern)
- Max 5 Error-Alerts pro 10 Minuten
- Deduplizierung: gleicher Fehler (Logger + Exception-Typ) nur alle 5 Minuten
- Bei API-Ausfall (z.B. Google Calendar down): 1 Alert statt 100

### Log-Rotation (Disk-Overflow verhindern)
- RotatingFileHandler: 5 MB pro Datei, max 4 Dateien = 20 MB
- Alte Logs werden automatisch überschrieben
- Kein unbegrenztes Wachstum wie bei aktuellem error_log.txt

### Thread-Safety
- Python logging ist thread-safe by design (Lock pro Handler)
- ErrorCollector braucht eigenen Lock nur für _seen Dict

### Keine sensiblen Daten in Logs
- Keine Passwörter, Tokens, API-Keys in Log-Messages
- Sender-IDs (Matrix) sind OK (kein PII im eigentlichen Sinne)
- Mail-Bodies werden NICHT geloggt (nur Betreff/Absender in Command-Output)

---

## Migration

### Schritt 1: Logging-Config umstellen
- `basicConfig()` → `dictConfig()` in start_saleria.py
- RotatingFileHandler hinzufügen
- **Sofort wirksam für alle bestehenden Logger**

### Schritt 2: ErrorCollector implementieren
- Neuer logging.Handler
- Deduplizierung + Rate-Limiting
- Tests

### Schritt 3: Matrix-Alerting verdrahten
- alert_callback an ErrorCollector übergeben
- Bridge stellt den Callback bereit (Channel + Loop verfügbar)

### Schritt 4: _log_error() entfernen
- Alle 8 Stellen in bridge.py: `self._log_error()` entfernen
- `extra={}` Dict an bestehende `logger.error()` Aufrufe anhängen
- `error_log_dir` Parameter aus Bridge entfernen
- `logs/error_log.txt` wird nicht mehr beschrieben (kann gelöscht werden)

### Rückwärtskompatibilität
- Alle bestehenden `logger.error()` Aufrufe funktionieren unverändert
- Nur `_log_error()` wird entfernt (interne Bridge-Methode, kein Public API)
- error_log_dir Parameter wird deprecated (bleibt kurz als No-Op)

---

## Offene Entscheidungen

1. **Alert-Room:** Gleicher Matrix-Room wie Chat, oder separater Error-Room?
   - Empfehlung: Gleicher Room (alert_room_id existiert bereits für AlertMonitor)
   - Separater Room wäre sauberer, aber Overhead für Single-User

2. **Log-Level für File:** INFO oder WARNING?
   - INFO: vollständiges Bild, aber größere Dateien
   - WARNING: nur Probleme, kompakter
   - Empfehlung: INFO (5 MB Rotation ist großzügig genug)

3. **Error-History in SQLite?**
   - Ermöglicht: "zeig mir die letzten Fehler", Error-Dashboard
   - Aber: RotatingFileHandler reicht für Debugging
   - Empfehlung: Nein in v1, kann später ergänzt werden

4. **Alert-Format:** Kurz (1 Zeile) oder ausführlich (mit Traceback)?
   - Empfehlung: Kurz für Matrix (`⚠ CalendarWatcher: APIError`),
     Traceback steht im Log-File
