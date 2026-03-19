# Phase 17: Kalender-Watcher (Proaktive Meeting-Erinnerungen)

> **Status:** Geplant
> **Erstellt:** 2026-03-19 (Claude App)
> **Umsetzung:** Claude Code
> **Abhängigkeit:** GoogleCalendarClient (Phase 8, bereits abgeschlossen)
> **Branch:** `feature/phase-17-kalender-watcher`

---

## Übersicht

Proaktive Kalender-Erinnerungen: Saleria erinnert den Nutzer X Minuten vor
einem Termin via Matrix, ohne dass der Nutzer fragen muss.

**Abgrenzung zu bestehendem System:**
- `BriefingScheduler` = einmal täglich um 07:30, zeigt ALLE Termine des Tages
- `ReminderScheduler` = explizit gesetzte Timer/Erinnerungen ("erinnere mich um 18 Uhr")
- `CalendarWatcher` (NEU) = pollt Kalender regelmäßig, erinnert VOR jedem Termin

**Architektur:** Daemon-Thread (wie BriefingScheduler/ReminderScheduler),
pollt GoogleCalendarClient, vergleicht mit letztem bekannten Stand,
sendet Benachrichtigungen bei nahenden Terminen.

---

## VORBEREITUNG

Bevor du mit der Implementierung beginnst:

1. Lies `C:\Dev\Elder-Berry\docs\journal.txt` (letzte 80 Zeilen)
2. Lies dieses Konzept-Dokument komplett durch
3. Erstelle Branch: `git checkout -b feature/phase-17-kalender-watcher`
4. Schreibe Draft-Eintrag in journal.txt

---

## 17.1 – CalendarWatcher

### Neue Datei: `src/elder_berry/comms/calendar_watcher.py`

**Klasse:** `CalendarWatcher`

**Dependency Injection:**
```python
def __init__(
    self,
    send_alert: Callable[[str], None],
    calendar: GoogleCalendarClient,
    reminder_minutes: list[int] | None = None,
    poll_interval: int = 300,
) -> None:
    """
    Args:
        send_alert: Callback(text) → sendet an Matrix. Muss thread-safe sein.
        calendar: GoogleCalendarClient (bereits initialisiert).
        reminder_minutes: Minuten vor Termin für Erinnerung.
            Default: [15, 5] → 15 Min vorher + 5 Min vorher.
            Konfigurierbar, z.B. [30, 10, 5] oder [10].
        poll_interval: Sekunden zwischen Kalender-Abfragen.
            Default: 300 (5 Minuten). Nicht zu kurz wegen API-Rate-Limits.
    """
```

**State:**
```python
self._reminded_events: dict[str, set[int]] = {}
# Key: event_id (Google Calendar ID)
# Value: Set von reminder_minutes die schon gesendet wurden
# Beispiel: {"abc123": {15}} → 15-Min-Erinnerung schon gesendet, 5-Min noch nicht
```

**Methoden:**

```python
def start(self) -> None:
    """Startet den Watcher-Thread (Daemon, nicht-blockierend)."""

def stop(self) -> None:
    """Stoppt den Watcher-Thread sauber."""

@property
def is_running(self) -> bool:
    """True wenn der Thread aktiv ist."""

def _run(self) -> None:
    """Thread-Hauptschleife: pollt Kalender, prüft nahende Termine."""
    while self._running:
        try:
            self._check_upcoming()
        except Exception as e:
            logger.error("CalendarWatcher Check-Fehler: %s", e)
        # poll_interval in 1s-Schritten (für sauberes Shutdown)
        for _ in range(self._poll_interval):
            if not self._running:
                break
            time.sleep(1)

def _check_upcoming(self) -> None:
    """Prüft ob Termine in den nächsten max(reminder_minutes) Minuten anstehen."""
    # 1. Lade Termine der nächsten Stunde (Puffer über max reminder_minutes)
    lookahead_minutes = max(self._reminder_minutes) + 10
    events = self._calendar.get_events_range(
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc) + timedelta(minutes=lookahead_minutes),
    )
    # 2. Für jeden Termin: berechne Minuten bis Start
    now = datetime.now(timezone.utc)
    for event in events:
        if event.all_day:
            continue  # Ganztags-Events nicht erinnern
        minutes_until = (event.start - now).total_seconds() / 60
        # 3. Für jedes Erinnerungs-Intervall prüfen
        for reminder_min in self._reminder_minutes:
            if minutes_until <= reminder_min and \
               reminder_min not in self._reminded_events.get(event.event_id, set()):
                self._send_reminder(event, reminder_min)
                self._reminded_events.setdefault(event.event_id, set()).add(reminder_min)
    # 4. Cleanup: vergangene Events aus State entfernen
    self._cleanup_past_events(events)
```

```python
def _send_reminder(self, event: CalendarEvent, minutes: int) -> None:
    """Formatiert und sendet eine Termin-Erinnerung."""
    time_str = event.start.astimezone().strftime("%H:%M")
    if minutes >= 60:
        time_text = f"{minutes // 60}h {minutes % 60}min" if minutes % 60 else f"{minutes // 60}h"
    else:
        time_text = f"{minutes} Minuten"

    text = f"📅 Termin in {time_text}: {event.summary} ({time_str})"
    if event.location:
        text += f"\n  📍 {event.location}"

    try:
        self._send_alert(text)
        logger.info("Kalender-Erinnerung: %s in %d Min", event.summary, minutes)
    except Exception as e:
        logger.error("Kalender-Erinnerung senden fehlgeschlagen: %s", e)

def _cleanup_past_events(self, current_events: list) -> None:
    """Entfernt vergangene Events aus dem State (Memory-Leak verhindern)."""
    current_ids = {e.event_id for e in current_events}
    past_ids = [eid for eid in self._reminded_events if eid not in current_ids]
    for eid in past_ids:
        # Nur entfernen wenn Event komplett vorbei (alle Reminder gefeuert oder Event vergangen)
        del self._reminded_events[eid]
```

---

## 17.2 – GoogleCalendarClient Erweiterung

### Geänderte Datei: `src/elder_berry/tools/google_calendar.py`

**Neue Methode (falls nicht vorhanden):**
```python
def get_events_range(self, start: datetime, end: datetime) -> list[CalendarEvent]:
    """Termine in einem bestimmten Zeitraum abrufen.

    Args:
        start: Beginn des Zeitraums (timezone-aware).
        end: Ende des Zeitraums (timezone-aware).

    Returns:
        Liste von CalendarEvents im Zeitraum, nach Startzeit sortiert.
    """
```

**Prüfe zuerst** ob `get_events(days=N)` ausreicht oder ob eine range-basierte
Methode nötig ist. `get_events(days=1)` gibt Termine des aktuellen Tages zurück –
der CalendarWatcher braucht aber einen Lookahead von ~30 Minuten, nicht den ganzen Tag.
Eine range-basierte Methode ist präziser und vermeidet unnötige API-Calls.

Falls `get_events` bereits `timeMin`/`timeMax` Parameter an die Google API übergibt,
kann `get_events_range` als Wrapper implementiert werden.

---

## 17.3 – Integration

### Geänderte Dateien

**`scripts/start_saleria.py`:**
- CalendarWatcher importieren
- Initialisieren nach `calendar` (GoogleCalendarClient):

```python
# CalendarWatcher (optional – nur wenn Calendar verfügbar)
calendar_watcher = None
if calendar:
    try:
        from elder_berry.comms.calendar_watcher import CalendarWatcher
        calendar_watcher = CalendarWatcher(
            send_alert=lambda text: None,  # Bridge setzt echten Callback
            calendar=calendar,
            reminder_minutes=[15, 5],
            poll_interval=300,
        )
        logger.info("CalendarWatcher: aktiv (Erinnerungen: 15min, 5min vor Termin)")
    except Exception as e:
        logger.warning("CalendarWatcher nicht verfügbar: %s", e)
```

**`src/elder_berry/comms/bridge.py` (MatrixBridge):**
- CalendarWatcher als optionaler Konstruktor-Parameter
- In `start()`: `calendar_watcher.start()` aufrufen
- In `stop()`: `calendar_watcher.stop()` aufrufen
- `send_alert`-Callback setzen (gleiche Mechanik wie AlertMonitor/BriefingScheduler)

**Kein neuer CommandHandler nötig** – CalendarWatcher ist rein proaktiv (kein User-Command).
Optionaler Zusatz: Command "erinnerungen aus/an" zum Ein-/Ausschalten → kann in v2 ergänzt werden.

---

## 17.4 – Tests

### Neue Datei: `tests/test_calendar_watcher.py`

**Tests (~15-20 Tests):**
1. Init: Default reminder_minutes=[15, 5], poll_interval=300
2. Init: Benutzerdefinierte reminder_minutes
3. _check_upcoming: Event in 10 Min → 15-Min-Reminder feuert
4. _check_upcoming: Event in 3 Min → 5-Min-Reminder feuert
5. _check_upcoming: Event in 3 Min → 15-Min UND 5-Min Reminder feuern

6. Deduplizierung: gleicher Reminder feuert NICHT zweimal beim nächsten Poll
7. _check_upcoming: Ganztags-Event → kein Reminder
8. _send_reminder: Format mit Location
9. _send_reminder: Format ohne Location
10. _send_reminder: Minuten-Text ("15 Minuten" vs "1h 30min")
11. _cleanup_past_events: vergangene Events werden entfernt
12. _cleanup_past_events: aktuelle Events bleiben im State
13. start/stop: Thread startet und stoppt sauber
14. Kalender-Fehler: API-Fehler → kein Crash, nächster Poll versucht es erneut
15. Leerer Kalender: keine Events → kein Fehler

**Mock-Strategie:**
- GoogleCalendarClient mocken (wie in test_remote_commands.py)
- `send_alert` als Mock-Callable
- `datetime.now()` patchen für deterministische Tests (freezegun oder manuell)

---

## 17.5 – Edge Cases & Bekannte Risiken

1. **API-Rate-Limits:** Google Calendar API hat 1M Queries/Tag (Free Tier).
   Bei 5-Min-Poll = 288 Calls/Tag → weit unter dem Limit.
   Trotzdem: bei API-Fehler (429, 5xx) → graceful retry beim nächsten Poll.

2. **Zeitzone:** `CalendarEvent.start` ist timezone-aware (Google API liefert UTC oder
   User-Timezone). Vergleich mit `datetime.now(timezone.utc)` muss timezone-aware sein.
   → Sicherstellen dass `minutes_until` korrekt berechnet wird.

3. **Termin-Änderungen:** User verschiebt Termin während CalendarWatcher läuft.
   → Nächster Poll holt aktualisierte Termine. State (`_reminded_events`) wird per
   event_id getrackt – verschobener Termin hat gleiche ID, aber andere Startzeit.
   Problem: Wenn 15-Min-Reminder schon gesendet und Termin auf 1h später verschoben
   → 15-Min-Reminder kommt nicht nochmal.
   **Akzeptabel für v1** – Workaround: User fragt "termine heute".

4. **Gelöschte Termine:** Event verschwindet aus der API → _cleanup_past_events
   entfernt es aus dem State. Kein Problem.

5. **Mehrere Termine gleichzeitig:** Alle werden einzeln erinnert (kein Batching).
   Bei vielen gleichzeitigen Terminen → viele Matrix-Nachrichten.
   Akzeptabel für Single-User.

---

## 17.6 – Abhängigkeiten

- **Neue Packages:** Keine
- **Bestehende Imports:** GoogleCalendarClient, CalendarEvent DTO
- **Dateien die gelesen werden müssen BEVOR implementiert wird:**
  - `src/elder_berry/tools/google_calendar.py` (API, verfügbare Methoden)
  - `src/elder_berry/comms/briefing_scheduler.py` (Referenz für Daemon-Thread-Pattern) ✅
  - `src/elder_berry/comms/bridge.py` (Integration der Scheduler-Callbacks)
  - `scripts/start_saleria.py` (Init-Kette) ✅
