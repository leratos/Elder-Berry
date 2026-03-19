# Phase 21 – Proaktive Kontext-Verknüpfung

> **Status:** Konzept
> **Erstellt:** 2026-03-19
> **Abhängigkeit:** CalendarWatcher (Phase 17), NoteStore (Phase 16),
>   IMAPEmailClient (Phase 8), ChatHistory (Phase 8)

---

## Ziel

Salerias proaktive Benachrichtigungen werden kontextbewusst. Statt nur
"Termin in 15 Minuten: Zahnarzt" kann sie relevante Informationen verknüpfen:
Notizen zum Termin, zugehörige Mails, Wetter für den Weg, etc.

**Vorher:**
> "Termin in 15 Minuten: Meeting Max"

**Nachher:**
> "Termin in 15 Minuten: Meeting Max
> Notiz: Max wollte über das Dachprojekt sprechen
> Letzte Mail von Max: Angebot im Anhang (gestern, 14:22)"

---

## Ist-Zustand

### CalendarWatcher
- Pollt Google Calendar alle 5 Minuten
- Feuert Alert bei [15, 5] Minuten vor Termin
- Alert-Format: Titel, Uhrzeit, optional Ort
- **Kein Zugriff auf andere Datenquellen**

### Verfügbare Datenquellen
| Quelle | Klasse | Zugriff |
|--------|--------|---------|
| Notizen | NoteStore | `search(query)`, `get_by_key(key)` |
| Mails | IMAPEmailClient | `search(query)`, `get_unread()` |
| Wetter | WeatherClient | `get_current()`, `get_forecast()` |
| RAG Memory | MemoryStore | `get_context(query)` |
| Gym | GymDataClient | `get_summary()` |

### Was fehlt
- CalendarWatcher hat keinen Zugriff auf diese Clients
- Kein Mechanismus für "suche relevante Infos zu einem Termin-Titel"
- Kein LLM-Call um die gesammelten Infos aufzubereiten

---

## Lösung

### Ansatz: ContextEnricher als Middleware

Neue Klasse die zwischen CalendarWatcher und Alert-Versand steht:

```
CalendarWatcher → "Meeting Max in 15 Min"
       ↓
ContextEnricher → sucht Notizen, Mails, Wetter
       ↓
LLM → formatiert alles als natürliche Nachricht
       ↓
Matrix → "Meeting Max in 15 Min. Max hat dir gestern..."
```

### ContextEnricher

```python
class ContextEnricher:
    """Reichert Events mit relevantem Kontext aus verschiedenen Quellen an."""

    def __init__(self, note_store, email_client, weather_client, memory_store, llm):
        ...

    def enrich_event(self, event_title: str, event_time: datetime,
                     event_location: str | None) -> str:
        """Sammelt Kontext aus allen Quellen und formatiert ihn."""
        context_parts = []

        # 1. Notizen durchsuchen
        notes = self.note_store.search(event_title)
        if notes:
            context_parts.append(f"Notizen: {notes[0].text}")

        # 2. Mails durchsuchen (letzte 7 Tage)
        mails = self.email_client.search(event_title, days=7)
        if mails:
            context_parts.append(f"Mail: {mails[0].subject} ({mails[0].date})")

        # 3. Wetter (wenn Ort vorhanden)
        if event_location:
            weather = self.weather_client.get_current()
            context_parts.append(f"Wetter: {weather.summary}")

        if not context_parts:
            return ""  # Kein Kontext gefunden → Standard-Alert

        # 4. LLM formatiert alles natürlich
        prompt = (
            f"Termin: {event_title} um {event_time}.\n"
            f"Kontext: {context_parts}\n"
            f"Fasse die relevanten Infos kurz zusammen."
        )
        return self.llm.generate(prompt)
```

### CalendarWatcher-Integration

`_send_reminder()` bekommt optionalen ContextEnricher:

```python
def _send_reminder(self, event, minutes):
    base_text = f"Termin in {minutes} Minuten: {event.title} ({event.time})"

    if self._enricher and minutes == max(self._reminder_minutes):
        # Nur beim ERSTEN Reminder (15 Min) anreichern, nicht beim 5-Min
        enriched = self._enricher.enrich_event(
            event.title, event.start, event.location
        )
        if enriched:
            base_text += f"\n{enriched}"

    self._send_alert(base_text)
```

---

## Sicherheit & Performance

- **Timeout pro Quelle:** Jede Suche hat ein 3s Timeout. Wenn IMAP hängt,
  wird der Alert trotzdem gesendet (ohne Mail-Kontext).
- **Nur beim ersten Reminder:** 15-Min-Alert wird angereichert, 5-Min-Alert
  bleibt schlank (keine doppelte Suche).
- **LLM-Kosten:** ~1-2 Cent pro angereichertem Alert. Bei 3-5 Terminen/Tag
  = max 10 Cent/Tag.
- **Kein Caching nötig:** Alerts feuern maximal 2x pro Event.

---

## Scope

### Neue/geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `core/context_enricher.py` | **Neu:** ContextEnricher Klasse |
| `comms/calendar_watcher.py` | ContextEnricher als optionaler DI-Parameter |
| `comms/bridge.py` | ContextEnricher instanziieren und an Watcher übergeben |
| `tests/test_context_enricher.py` | **Neu:** Tests mit gemockten Quellen |

### Was sich NICHT ändert
- NoteStore, IMAPEmailClient, WeatherClient (nur gelesen, nicht geändert)
- BriefingScheduler (bleibt unabhängig)
- ReminderScheduler (Erinnerungen ohne Kontext-Anreicherung)
- Alert-Format für 5-Min-Reminder (bleibt schlank)

---

## Offene Entscheidungen

1. **Welche Quellen durchsuchen?** Alle verfügbaren, oder konfigurierbar?
   Empfehlung: Alle verfügbaren, aber graceful degradation wenn eine Quelle
   nicht konfiguriert ist (kein IMAP-Setup → kein Mail-Kontext).

2. **LLM für Formatierung?** Oder reicht Template-basiert?
   - Template: Deterministisch, kein LLM-Call, aber steif
   - LLM: Natürlich formuliert, passt zu Salerias Charakter, aber Kosten
   - Empfehlung: LLM (Kosten sind minimal, Qualität deutlich besser)

3. **Suche nach Personennamen im Termin-Titel:**
   "Meeting Max" → suche "Max" in Mails und Notizen. Aber was wenn der Titel
   "Zahnarzt" ist? Dann ist Mail-Suche nach "Zahnarzt" wenig hilfreich.
   - Empfehlung: Immer suchen, aber nur anzeigen wenn Score/Relevanz hoch genug

4. **BriefingScheduler ebenfalls anreichern?**
   Das Morning-Briefing könnte ebenfalls von Kontext-Verknüpfung profitieren:
   "Heute: Meeting Max um 14:00 – Max hat dir gestern geschrieben."
   - Empfehlung: Ja, aber in Phase 2 (erst CalendarWatcher, dann Briefing)
