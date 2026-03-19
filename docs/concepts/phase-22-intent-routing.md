# Phase 22 – Intent-Routing Verbesserung

> **Status:** Konzept
> **Erstellt:** 2026-03-19
> **Abhängigkeit:** RemoteCommandHandler (Phase 7), Assistant (Phase 1/5),
>   MatrixBridge (Phase 6)

---

## Ziel

Die Erkennung, ob eine User-Nachricht ein direkter Command oder eine
LLM-Konversation ist, wird verbessert. Aktuell gibt es Grenzfälle wo:
- Commands nicht erkannt werden (User formuliert anders als erwartet)
- Das LLM den falschen `remote_command`-String generiert
- Commands an das LLM durchrutschen, obwohl ein direkter Handler existiert

---

## Ist-Zustand

### 3-Stufen-Routing (RemoteCommandHandler.parse_command)

```
User-Input (normalisiert)
│
├─ Stufe 1: Simple Commands (exakter Match)
│  "status", "screenshot", "hilfe", "mails", "termine", ...
│
├─ Stufe 2: Pattern Matching (Regex, Handler-Reihenfolge = Priorität)
│  "wetter morgen", "timer 20 min", "termin suche xyz", ...
│
├─ Stufe 3: Keyword Matching (enthält eines der Keywords)
│  "wie ist das wetter?" → enthält "wetter" → weather_commands
│  "zeig mir meine mails" → enthält "mails" → mail_commands
│
└─ Kein Match → LLM-Fallback
```

### LLM-Routing (Bridge._handle_message)

```
1. Remote Command erkannt? → Direkt ausführen (kein LLM)
2. Claude Agent? → Anthropic API
3. Sonst → LLM (Assistant.process)
   └─ LLM kann action: "remote_command" wählen
      └─ Bridge extrahiert command aus params
      └─ Parsed erneut durch RemoteCommandHandler
```

### Probleme

1. **Keyword-Kollisionen:**
   "Lösche die Erinnerung an den Zahnarzt" → enthält "erinnerung" UND
   könnte auch "lösche" + "zahnarzt" matchen. Welcher Handler gewinnt?
   → Aktuell: Erster Handler in der Liste mit passendem Keyword.

2. **LLM generiert falschen Command-String:**
   User: "Zeig mir die Mails von gestern"
   LLM: `{"action": "remote_command", "command": "mails von gestern"}`
   → RemoteCommandHandler erkennt nur "mails" (ohne Zeitfilter).
   Der eigentliche Command wäre "mail suche [Datum]".

3. **Natürliche Sprache vs. Command-Syntax:**
   "Wie wird das Wetter morgen?" → Keyword "wetter" matcht.
   "Soll ich morgen einen Regenschirm mitnehmen?" → Kein Match, obwohl
   die Intention "Wetter morgen" ist.

4. **Riesiger System-Prompt:**
   Der statische Command-Block im System-Prompt ist ~80 Zeilen lang.
   Das LLM muss alle Commands "kennen" um den richtigen zu wählen.

---

## Lösungsoptionen

### Option A: Keyword-Verbesserung (inkrementell)

Mehr Keywords, bessere Normalisierung, Synonym-Erweiterung:
- "regenschirm" → weather_commands
- "posteingang" → mail_commands
- "zeitplan" → calendar_commands

**Vorteile:** Einfach, kein neues System
**Nachteile:** Whack-a-mole – für jede neue Formulierung ein neues Keyword.
Skaliert nicht.

**Bewertung: Kurzfristig sinnvoll, langfristig nicht ausreichend.**

### Option B: LLM-basierter Intent-Classifier (Pre-Router)

Vor dem eigentlichen LLM-Call: ein schneller, günstiger LLM-Call der nur
die Intention klassifiziert:

```
User: "Soll ich morgen einen Regenschirm mitnehmen?"
Pre-Router LLM: {"intent": "weather", "params": {"day": "morgen"}}
→ Direkt an WeatherCommandHandler routen
```

**Vorteile:** Versteht natürliche Sprache, sprachunabhängig
**Nachteile:** Zusätzlicher LLM-Call pro Nachricht (~0.5 Cent, ~1-2s Latenz).
Bei Ollama lokal: ~0.5-1s extra, keine Kosten.

**Bewertung: Zu teuer/langsam als Standard für JEDE Nachricht.**

### Option C: Hybrid (bessere Keywords + LLM-Fallback-Feedback)

1. **Keywords erweitern** (einmalig, gründlich)
2. **LLM-Command-Prompt verbessern:** Statt einer statischen Command-Liste
   im System-Prompt → dynamische, kompakte Beschreibung:

```
Du hast diese Tools:
- wetter [heute|morgen|woche]: Wetterabfrage
- mail suche <Begriff>: E-Mails durchsuchen
- termine [heute|morgen|woche]: Kalender
...
Wähle das passende Tool und gib den exakten Command-String zurück.
```

3. **Feedback-Loop:** Wenn der LLM-generierte Command-String nicht geparst
   werden kann → Fehlermeldung ans LLM → zweiter Versuch.

**Vorteile:** Kein extra LLM-Call, bessere Trefferquote, Feedback bei Fehlern
**Nachteile:** Erfordert Prompt-Tuning

**Bewertung: Bester Kompromiss.**

---

## Empfehlung: Option C (Hybrid)

### Umsetzung in 3 Teilen

**Teil 1: Keyword-Audit**
- Alle Handler durchgehen, fehlende Synonyme/Umgangssprache ergänzen
- Konflikte identifizieren und durch Prioritäts-Reihenfolge auflösen

**Teil 2: Dynamischer Command-Prompt**
- `RemoteCommandHandler.get_command_summary() -> str`
- Generiert kompakte Tool-Beschreibung aus Handler-Metadaten
- Ersetzt den statischen Block im System-Prompt (SYSTEM_PROMPT_TEMPLATE)
- Wenn neue Commands hinzugefügt werden → Prompt aktualisiert sich automatisch

**Teil 3: Retry bei Parse-Fehler**
- In `_handle_llm_remote_command()`:
  Wenn `parse_command(cmd)` fehlschlägt → Fehlermeldung als Kontext an LLM →
  "Der Command '{cmd}' wurde nicht erkannt. Verfügbare Commands: {summary}."
  → LLM korrigiert → zweiter Versuch

---

## Scope

### Neue/geänderte Dateien
| Datei | Änderung |
|-------|----------|
| `comms/remote_commands.py` | `get_command_summary()`, Keyword-Audit |
| `comms/commands/*.py` | Keywords erweitern (alle Handler) |
| `core/assistant.py` | SYSTEM_PROMPT_TEMPLATE: dynamischer Command-Block |
| `comms/bridge.py` | Retry-Logik in `_handle_llm_remote_command()` |
| `tests/test_intent_routing.py` | **Neu:** Tests für Edge-Cases und Retry |

### Was sich NICHT ändert
- CommandHandler ABC (Interface bleibt gleich)
- 3-Stufen-Routing-Logik (bleibt, wird nur besser gefüttert)
- Claude Agent Pfad (unberührt)

---

## Offene Entscheidungen

1. **Dynamischer Prompt vs. statisch:** Der aktuelle System-Prompt hat den
   Command-Block hardcoded in assistant.py (~80 Zeilen). Soll das komplett
   durch `get_command_summary()` ersetzt werden?
   - Empfehlung: Ja – single source of truth. Handlers definieren ihre Commands,
     Prompt wird generiert.

2. **Retry-Limit:** Wie oft darf das LLM den Command korrigieren?
   - Empfehlung: 1 Retry (2 Versuche insgesamt). Danach: Fehlermeldung an User.

3. **Keyword-Sprache:** Aktuell nur Deutsch. Soll Englisch als Fallback dazu?
   ("weather" → weather_commands)
   - Empfehlung: Nein – Single-User spricht Deutsch mit Saleria.
