# Phase 19 – Wiederkehrende Erinnerungen

> **Status:** Konzept
> **Erstellt:** 2026-03-19
> **Abhängigkeit:** ReminderStore (Phase 8), ReminderScheduler (Phase 8)

---

## Ziel

Saleria kann wiederkehrende Erinnerungen setzen: "Erinnere mich jeden Montag
um 9 an den Wochenbericht." Aktuell sind Timer und Erinnerungen einmalig
(One-Shot) – nach dem Feuern sind sie erledigt.

---

## Ist-Zustand

### ReminderStore (tools/reminder_store.py)
- SQLite-Tabelle `reminders`: id, user_id, message, due_at, created_at, fired, cancelled
- `get_due()` liefert alle Reminder mit `due_at ≤ now AND fired=0 AND cancelled=0`
- `mark_fired(id)` setzt `fired=1` → Reminder feuert nie wieder
- `cleanup_old()` löscht gefeuerte Reminder nach 30 Tagen

### ReminderScheduler (comms/reminder_scheduler.py)
- Daemon-Thread, 15s Poll-Intervall
- Ruft `store.get_due()` auf → für jeden: `send_reminder()` Callback → `mark_fired()`
- Kein Konzept von "nächster Ausführung"

### WeatherCommandHandler (comms/commands/weather_commands.py)
- Patterns: `^timer\s+(\d+)\s*(min|stunde|sek)$`
- Patterns: `^(?:erinnere mich|erinnerung)\s+(?:um|in)...`
- Parsed Zeitangaben → `reminder_store.add(user_id, message, due_at)`

### Was fehlt
- Kein Feld für Wiederholungsintervall in der DB
- Kein Mechanismus um nach dem Feuern den nächsten Termin zu berechnen
- Keine Patterns für "jeden Montag", "täglich", "alle 2 Wochen"

---

## Lösung

### DB-Schema erweitern

Neues Feld `recurrence` in der `reminders`-Tabelle:

```sql
ALTER TABLE reminders ADD COLUMN recurrence TEXT DEFAULT NULL;
```

- `NULL` = One-Shot (bisheriges Verhalten)
- Wert = Wiederholungsregel als einfacher String

### Recurrence-Format

Kein vollständiges RRULE (RFC 5545) – zu komplex für den Use-Case.
Stattdessen ein einfaches eigenes Format:

| Eingabe | recurrence-Wert | Bedeutung |
|---------|-----------------|-----------|
| "jeden Tag um 9" | `daily` | Täglich |
| "jeden Montag um 9" | `weekly:1` | Wöchentlich (Mo=1) |
| "jeden 1. um 10" | `monthly:1` | Monatlich am 1. |
| "alle 2 Wochen montags" | `biweekly:1` | Alle 2 Wochen |
| "werktags um 8" | `weekdays` | Mo–Fr |

### Scheduler-Logik anpassen

In `ReminderScheduler._run()` nach dem Feuern:

```python
for reminder in store.get_due():
    send_reminder(reminder.user_id, reminder.message)
    if reminder.recurrence:
        next_due = calculate_next_due(reminder.due_at, reminder.recurrence)
        store.reschedule(reminder.id, next_due)  # Neues due_at, fired=0
    else:
        store.mark_fired(reminder.id)
```

Neue Methoden im ReminderStore:
- `reschedule(id, new_due_at)` → setzt `due_at = new_due_at, fired = 0`

Neue Hilfsfunktion:
- `calculate_next_due(current_due, recurrence) -> datetime`

### Command-Patterns erweitern

Neue Patterns in WeatherCommandHandler:

| Pattern | Beispiel |
|---------|----------|
| `^erinnere mich jeden (montag\|dienstag\|...) um (\d{1,2}:\d{2})` | "erinnere mich jeden montag um 9:00: Wochenbericht" |
| `^erinnere mich täglich um (\d{1,2}:\d{2})` | "erinnere mich täglich um 8:00: Standup" |
| `^erinnere mich werktags um (\d{1,2}:\d{2})` | "erinnere mich werktags um 7:30: Aufstehen" |

### Verwaltungs-Commands

- `erinnerungen` → zeigt auch das Wiederholungs-Intervall an
- `erinnerung löschen <id>` → setzt `cancelled=1` (beendet die Serie)
- Optional: `erinnerung pausieren/fortsetzen <id>`

---

## Scope

### Neue/geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `tools/reminder_store.py` | `recurrence`-Feld, `reschedule()`, Migration |
| `comms/reminder_scheduler.py` | Reschedule-Logik nach Feuern |
| `comms/commands/weather_commands.py` | Neue Patterns für wiederkehrende Erinnerungen |
| `comms/remote_commands.py` | HELP_TEXT erweitern |
| `tests/test_reminder_store.py` | Tests für recurrence + reschedule |
| `tests/test_reminder_scheduler.py` | Tests für Reschedule-Logik |

### Was sich NICHT ändert
- BriefingScheduler (bleibt unabhängig, feste 07:30)
- CalendarWatcher (reagiert auf Google Calendar, nicht auf Reminders)
- ReminderStore API für One-Shot-Reminder (Rückwärtskompatibel)

---

## Offene Entscheidungen

1. **DB-Migration:** `ALTER TABLE ADD COLUMN` ist in SQLite problemlos. Bestehende
   Einträge bekommen `recurrence = NULL` → weiterhin One-Shot. Keine Migration nötig.

2. **Timezone-Handling:** ReminderStore arbeitet intern mit UTC. Wochentag-Berechnung
   muss in lokaler Zeit erfolgen (z.B. "jeden Montag" = Montag in Europe/Berlin).
   Aktuell hardcoded → sollte konfigurierbar sein oder aus System-TZ abgeleitet.

3. **Maximale Wiederholungen:** Soll eine Serie automatisch nach N Wiederholungen
   enden, oder läuft sie unendlich bis `cancelled`?
   Empfehlung: Unendlich – der Nutzer cancelled manuell.

4. **Snooze:** "Erinnere mich in 10 Minuten nochmal" als Ergänzung?
   Empfehlung: Nein in v1 – Scope klein halten.
