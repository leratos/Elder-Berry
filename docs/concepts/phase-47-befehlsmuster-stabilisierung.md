# Phase 47 – Befehlsmuster-Stabilisierung

## Ziel

Saleria versteht Befehle nur, wenn sie exakt zum einprogrammierten Muster
passen. Ein Nutzer der noch nie die Dokumentation gelesen hat, scheitert
deshalb regelmäßig: Er schreibt "mail #5 löschen" und nichts passiert – weil
das System nur "mail löschen #5" versteht.

**Ziel dieser Phase:** Alle Befehlsmuster werden um die häufigsten natürlichen
Varianten erweitert, sodass Saleria im Alltag ohne Handbuch bedienbar ist.

### Was ist ein „Befehlsmuster"?

Saleria empfängt Textnachrichten (via Matrix). Jede Nachricht wird gegen eine
Liste von regulären Ausdrücken (Regex-Patterns) geprüft – das erste Muster das
passt, bestimmt was getan wird. Passt keins, geht die Nachricht an das LLM.

```
Nutzer schreibt:   "mail #5 löschen"
Pattern prüft:     r"(?:mails?\s+(?:löschen|...)\s*#?(\d+)?)"
Ergebnis:          KEIN MATCH → Befehl wird ignoriert / LLM antwortet allgemein
```

### Was ist das Problem?

Die Patterns wurden beim ersten Implementieren auf eine Schreibweise zugeschnitten.
Natürliche Sprache ist aber flexibel: Verb vorne, Verb hinten, mit Artikel,
mit "bitte", mit Leerzeichen in Namen. Viele naheliegende Varianten schlagen fehl.

### Was ändert sich NICHT?

- Keine neuen Features, keine neue Logik
- Keine Änderungen an Datenbanken, APIs oder der Architektur
- Nur die Regex-Strings in den Command-Handler-Dateien werden erweitert

---

## Betroffene Features & konkrete Lücken

Die folgende Tabelle listet alle identifizierten Lücken mit Priorität:

### 🔴 Kritisch (häufige, intuitive Eingaben die scheitern)

| Feature | Schlägt fehl | Soll funktionieren | Datei |
|---|---|---|---|
| Mail löschen | `mail #5 löschen`, `lösche mail 5` | Verb kann vorne oder hinten stehen | `mail_commands.py` |
| Harmony AV | `mach alles aus`, `ausschalten` | Synonym zu "alles aus" | `harmony_commands.py` |
| Harmony TV | `schalte tv ein` | Synonym zu "starte tv" / "tv" | `harmony_commands.py` |
| Wetter | `wetter übermorgen` | Fehlt komplett im Pattern | `weather_commands.py` |
| Prozess starten | `starte Visual Studio Code` | Leerzeichen in Programmnamen | `process_commands.py` |
| Lautstärke | `stell lautstärke auf 70` | "auf" zwischen Wort und Zahl | `system_commands.py` |
| Geburtstag | `geburtstag von Max` | Alternative zu "wann hat Max geburtstag" | `contact_commands.py` |

### 🟡 Mittel (spürbar, aber Workaround existiert)

| Feature | Schlägt fehl | Soll funktionieren | Datei |
|---|---|---|---|
| Wetter | `wetter Berlin` (ohne "in") | Ortsname ohne Präposition | `weather_commands.py` |
| Höflichkeit | `bitte lauter`, `bitte leiser` | "bitte"-Präfix überall | `harmony_commands.py` |
| Kalender | `neuer termin: Lunch` | Synonym zu "erstelle termin:" | `calendar_commands.py` |
| Notiz-Fakten | `wie lautet das Passwort` | Synonym zu "was ist das Passwort" | `note_commands.py` |
| Todo | `aufgabe erledigt #2` | Synonym zu "todo erledigt #2" | `todo_commands.py` |
| Geburtstag | `wann ist Annas geburtstag` (Genitiv-s) | Genitiv-Schreibweise | `contact_commands.py` |
| Mail Zusammenfassung | `fasse die Mail von Peter zusammen` | Absendername statt ID | `mail_commands.py` |

### 🟢 Niedrig (Nutzerdoku kann helfen)

| Feature | Schlägt fehl | Anmerkung |
|---|---|---|
| Web-Suche | `was ist Machine Learning` | LLM-Fallback fängt das auf |
| Notiz anlegen | `neue Notiz: Buch lesen` | "notiz:" reicht normalerweise |
| Timer | `stell einen timer auf 10 min` | "timer 10 min" ist zumutbar |

---

## Architektur

### Wo leben die Patterns?

```
src/elder_berry/comms/commands/
├── base.py                  ← CommandHandler ABC (keine Patterns)
├── mail_commands.py         ← MAILS_DAYS_PATTERN, MAIL_ID_PATTERN, ...
├── calendar_commands.py     ← TERMINE_PATTERN, TERMIN_CREATE_PATTERN, ...
├── weather_commands.py      ← WEATHER_PATTERN, TIMER_PATTERN, ...
├── contact_commands.py      ← CONTACT_WHO_PATTERN, CONTACT_BIRTHDAY_PATTERN, ...
├── harmony_commands.py      ← ACTIVITY_ON_PATTERN, ALL_OFF_PATTERN, ...
├── note_commands.py         ← NOTE_ADD_PATTERN, NOTE_FACT_SET_PATTERN, ...
├── todo_commands.py         ← TODO_ADD_PATTERN, TODO_COMPLETE_PATTERN, ...
├── system_commands.py       ← VOLUME_PATTERN, AVATAR_EMOTION_PATTERN
├── process_commands.py      ← START_PROCESS_PATTERN, KILL_PROCESS_PATTERN
└── remote_commands.py       ← Orchestrator (registriert alle Handler)
```

### Wie ein Pattern ausgebaut wird

Ein Pattern ist ein Python-Regex-String. Varianten werden mit `(?:a|b)` als
Alternative hinzugefügt. Bestehende Matches bleiben 100% kompatibel.

**Beispiel – vorher:**
```python
MAIL_DELETE_PATTERN = re.compile(
    r"(?:mails?\s+(?:löschen|lösche|lösch|entferne[n]?)\s*#?(\d+)?)",
    re.IGNORECASE,
)
```

**Beispiel – nachher (ergänzt um "lösche mail X" und "mail #X löschen"):**
```python
MAIL_DELETE_PATTERN = re.compile(
    r"(?:"
    r"mails?\s+(?:löschen|lösche|lösch|entferne[n]?)\s*#?(\d+)?"  # alt
    r"|lösche?\s+mail\s*#?(\d+)"                                    # neu: verb vorne
    r"|mail\s*#?(\d+)\s+(?:löschen|lösche|lösch)"                   # neu: ID dann Verb
    r")",
    re.IGNORECASE,
)
```

### Keine Logikänderungen

Die `execute()`-Methode jedes Handlers bleibt unverändert. Nur die Pattern-
Strings oben in der Datei werden angepasst. Das Risiko für Regressionen ist
minimal, da Patterns unabhängig voneinander matchen.

### Abgrenzung: Pattern vs. LLM

Nicht jede natürlichsprachliche Variante muss per Regex abgedeckt werden.
Sehr freie Formulierungen ("Kannst du mir bitte die fünfte Mail zeigen?") sind
Aufgabe des LLM-Fallbacks. Diese Phase zielt auf die häufigsten Kurzformen.

---

## Flow

### Wie eine Nachricht verarbeitet wird (vereinfacht)

```
Matrix-Nachricht eingehend
        │
        ▼
RemoteCommandHandler.handle(text)
        │
        ├─ Iteriert über alle Handler (mail, kalender, wetter, ...)
        │
        ├─ Handler.match(text)
        │      └─ Prüft alle PATTERN.search(text) des Handlers
        │
        ├─ Erster Treffer → Handler.execute(command, raw_text)
        │      └─ Führt Aktion aus (IMAP abrufen, Kalender öffnen, ...)
        │
        └─ Kein Treffer → LLM-Fallback (freies Gespräch mit Claude/Ollama)
```

### Flow dieser Phase (Implementierung)

```
1. Pattern-Analyse (✅ abgeschlossen)
   └─ Alle Patterns gegen realistische Eingaben getestet
   └─ Lücken dokumentiert (Tabelle oben)

2. Pattern-Erweiterung (je Datei)
   └─ mail_commands.py        → MAIL_DELETE + MAIL_ID erweitern
   └─ harmony_commands.py     → ALL_OFF + ACTIVITY_ON + VOL erweitern
   └─ weather_commands.py     → WEATHER "übermorgen" + WEATHER_LOC ohne "in"
   └─ system_commands.py      → VOLUME "auf X" Syntax
   └─ process_commands.py     → START/KILL mit Leerzeichen im Namen
   └─ contact_commands.py     → BIRTHDAY Varianten
   └─ calendar_commands.py    → TERMIN_CREATE "neuer termin"
   └─ note_commands.py        → NOTE_FACT_GET "wie lautet"
   └─ todo_commands.py        → TODO_COMPLETE für "aufgabe erledigt"

3. Tests erweitern
   └─ Für jedes geänderte Pattern: neue Testfälle hinzufügen
   └─ Sowohl neue Varianten (müssen matchen) als auch
      bestehende Eingaben (dürfen nicht brechen)

4. Manuelle Stichprobe
   └─ 2-3 Befehle pro Feature live via Matrix testen
```

### Teststrategie

Jeder Handler hat eine eigene Testdatei unter `tests/`. Pattern-Tests sind
reine Unit-Tests ohne Netzwerk oder Abhängigkeiten:

```python
# Beispiel aus tests/test_mail_commands.py
def test_mail_delete_verb_vorne():
    """'lösche mail 5' soll matchen (war vorher eine Lücke)."""
    assert MAIL_DELETE_PATTERN.search("lösche mail 5")
    assert MAIL_DELETE_PATTERN.search("lösche mail #5")

def test_mail_delete_id_dann_verb():
    """'mail #5 löschen' soll matchen (war vorher eine Lücke)."""
    assert MAIL_DELETE_PATTERN.search("mail #5 löschen")

def test_mail_delete_original_noch_ok():
    """Bestehende Syntax darf nicht brechen."""
    assert MAIL_DELETE_PATTERN.search("mail löschen #5")
    assert MAIL_DELETE_PATTERN.search("mails löschen #3")
```

---

## Abgrenzung & Nicht-Ziele

| Nicht in Phase 47 | Warum |
|---|---|
| Neue Befehle / Features | Scope-Creep – nur bestehende stabilisieren |
| KI-basiertes Intent-Matching | Eigenes Konzept (Phase 22) |
| Vollständige NLP-Freitext-Erkennung | Aufwand unverhältnismäßig |
| Änderungen am LLM-Fallback | Nicht nötig für diese Fixes |
| UI-Anpassungen im Dashboard | Kein Bezug |
| Mail nach Absender zusammenfassen | Feature-Request, eigene Phase |

---

## Dateien (Übersicht)

| Datei | Änderung |
|---|---|
| `src/elder_berry/comms/commands/mail_commands.py` | MAIL_DELETE + MAIL_ID |
| `src/elder_berry/comms/commands/harmony_commands.py` | ALL_OFF + ACTIVITY_ON + VOL |
| `src/elder_berry/comms/commands/weather_commands.py` | WEATHER + WEATHER_LOCATION |
| `src/elder_berry/comms/commands/system_commands.py` | VOLUME |
| `src/elder_berry/comms/commands/process_commands.py` | START + STOP |
| `src/elder_berry/comms/commands/contact_commands.py` | CONTACT_FIELD_QUERY |
| `src/elder_berry/comms/commands/calendar_commands.py` | TERMIN_CREATE |
| `src/elder_berry/comms/commands/note_commands.py` | NOTE_FACT_GET |
| `src/elder_berry/comms/commands/todo_commands.py` | TODO_COMPLETE |
| `tests/test_mail_commands.py` | Neue Testfälle |
| `tests/test_harmony_commands.py` | Neue Testfälle |
| `tests/test_weather_commands.py` | Neue Testfälle |
| _(weitere test_*.py nach Bedarf)_ | |

## Erwartetes Ergebnis

Nach Phase 47 funktionieren alle in der Tabelle markierten 🔴-Fälle und die
meisten 🟡-Fälle zuverlässig. Alle bestehenden Tests bleiben grün.
Ein Nutzer kann Saleria ohne Dokumentation für die Alltagsaufgaben nutzen.
