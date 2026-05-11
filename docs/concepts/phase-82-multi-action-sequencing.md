# Phase 82 – Multi-Action-Sequencing 📦

**Status:** Konzept (2026-05-08), Refinement (2026-05-10)
**Branch:** `feature/phase-82-multi-action-sequencing`
**Aufwand:** ~1–2 Sessions
**Voraussetzung:** keine harte Abhängigkeit
**Roadmap-Referenz:** Folge der **Quick-Fix-Multi-Line-Iteration** vom
2026-05-08 (Commit `<wird gefüllt nach push>`). Quick-Fix deckt
gleichartige Single-Command-Batches ab; Phase 82 liefert das saubere
Action-Modell für gemischte Sequenzen.

**Refinement 2026-05-10:** Vor Etappe-1-Implementierung wurden 7 offene
Punkte mit Lera geklärt. Geänderte Abschnitte: §3.1 (Step-Allowlist),
§3.2 (Silent-Execution-Pfad + Recursion-Guard + Vorrang-Regel),
§5.1 (zusätzliche Tests), §5.2 (Pflicht-Few-Shot mit `stop`),
§7 (Akzeptanztests).

## 1. Ausgangslage

Saleria (LLM) emittiert heute pro User-Anfrage **genau eine Action**:

```json
{"action": "remote_command", "params": {"command": "todo: ..."}, "response": "..."}
```

Bei „mach mir 5 Todos" packt der LLM aktuell alle 5 in einen
Newline-separierten `command`-String — der Quick-Fix vom 2026-05-08
erkennt das, splittet zeilenweise und führt sequentiell aus, sammelt
eine Bilanz-Antwort. Das ist gut **für gleichartige Items**, aber
limitiert:

- **Heterogene Sequenzen** scheitern: „erstell die Einkaufsliste als
  Todos UND schreib eine Notiz mit dem Link zum Rezept UND setz mir
  einen Reminder für Samstag" → drei verschiedene Commands
  (`todo:`, `notiz:`, `erinner mich`), die der Quick-Fix nicht
  zusammenfassen kann (parse_command pro Zeile schon, aber Saleria
  emittiert das eher als eine Action mit gemischtem Text).
- **Action-Side-Effects-Reihenfolge** ist nicht modelliert. Wenn
  Schritt 2 vom Erfolg von Schritt 1 abhängt („wenn Mail #3 zur Person
  X ist, leg Termin in deren Kalender an"), gibt's keinen Mechanismus.
- **Aborting on Failure / Continuing**: keine konfigurable Strategie.

## 2. Ziel

Saubere First-Class-Repräsentation **mehrerer Actions pro LLM-Output**
mit kontrolliertem Lifecycle (success/failure-Reaktion, optional Daten
zwischen Steps).

**Kern-Eigenschaften:**

1. Neuer Action-Type `action_sequence` im Action-Routing.
   Format:
   ```json
   {
     "action": "action_sequence",
     "params": {
       "steps": [
         {"action": "remote_command", "params": {"command": "todo: A"}},
         {"action": "remote_command", "params": {"command": "notiz: ..."}},
         {"action": "remote_command", "params": {"command": "erinner mich Samstag"}}
       ],
       "on_failure": "continue"
     },
     "response": "..."
   }
   ```
2. Reaktionen pro Step: `success`, `failure`, `skipped` (z. B. weil
   vorheriger Step fehlschlug bei `on_failure: stop`).
3. Sammel-Antwort an den User: knappe Bilanz + nur Failures detailliert
   (Erfolge in Markdown-Liste).
4. **Rückwärtskompatibel:** Quick-Fix-Multi-Line bleibt aktiv für
   homogene Single-Command-Batches (LLM kann beide Wege gehen, je
   nachdem was er natürlicher findet).

**Nicht-Ziele:**

- Keine Daten-Pipeline zwischen Steps („Output von Step 1 ist Input
  von Step 2"). Wäre Phase 83 oder Erweiterung des bestehenden
  TaskChainRunners.
- Keine Parallelisierung. Reihenfolge ist sequenziell, deterministisch.
- Kein User-zwischenfragender Flow („Step 2 erfordert Bestätigung").
  Pending Confirmations sind weiterhin ein eigener Pfad (Phase 28).

## 3. Architektur

### 3.1 Daten

DTOs landen in `src/elder_berry/comms/action_sequence.py`. Das
`actions/`-Verzeichnis ist bereits für `ActionController` (Window/
Computer-Steuerung) belegt und semantisch weit weg von der Bridge-Schicht.

```python
# src/elder_berry/comms/action_sequence.py
@dataclass(frozen=True)
class ActionStep:
    action: str                # Etappe 1: NUR "remote_command"
    params: dict[str, Any]


@dataclass(frozen=True)
class ActionSequenceResult:
    steps_total: int
    steps_succeeded: int
    steps_failed: int
    steps_skipped: int
    step_summaries: list[str]   # kurzer Text pro Step
    failures: list[tuple[int, str, str]]  # (index, raw, reason)
```

**Refinement Etappe 1 — Step-Allowlist:** Steps werden hart auf
`action: "remote_command"` beschränkt. Andere Action-Types (z. B.
`system_status`, `multi_step`, `list_pick`) sind nicht erlaubt und
werden beim Routing als Validation-Fehler markiert. Begründung: Der
Silent-Execution-Pfad nutzt `_remote_commands.execute()`, was nur für
`remote_command` definiert ist. Erweiterung auf andere Types kommt,
wenn der Bedarf real ist — nicht spekulativ.

### 3.2 Routing-Erweiterung

`Assistant.process()` erkennt `parsed["action"] == "action_sequence"`
und reicht `params` als Pass-through durch (analog `remote_command`,
`multi_step`, `list_pick` — siehe `assistant.py:165-168`). Die Bridge
orchestriert die Step-Ausführung.

```python
# message_handlers.py:handle_assistant_message
# WICHTIG: action_sequence-Check VOR dem remote_command-Pfad,
# damit der Multi-Line-Quick-Fix nicht greift.
if (
    result.action_executed == "action_sequence"
    and result.action_success
    and result.action_params
):
    await self._handle_action_sequence(msg, result)
    return
```

**Refinement — Silent Execution:** `_handle_action_sequence` nutzt
`self._remote_commands.execute(parsed_cmd, raw_line)` direkt — exakt
denselben Pfad wie `_execute_multi_line_commands` (siehe
`message_handlers.py:1410-1472`). Kein Refactoring von
`handle_assistant_message`, kein Suppress-Flag, keine zweite Code-Linie.
Die Bridge-Send-Side-Effects entfallen automatisch, weil der
Command-Layer keine Matrix-Sends triggert.

**Refinement — Recursion-Guard:** Während der Step-Ausführung wird
`self._in_llm_command.add(msg.sender)` gesetzt (analog Quick-Fix,
`message_handlers.py:1317-1321`), in einem `try/finally` zurückgesetzt.
Zusätzlich harter Tiefen-Check: ein Step mit
`action == "action_sequence"` wird als FAILURE markiert (verhindert
nested recursion, falls der LLM verwirrt ist). Beide Schutzschichten
greifen unabhängig.

**Refinement — Vorrang `action_sequence` vs. Multi-Line:**

1. Im Routing: Wenn `action_executed == "action_sequence"`, wird
   `_handle_llm_remote_command` (und damit `_try_parse_multi_line`)
   für die Top-Level-Antwort *nicht* aufgerufen. Reihenfolge im
   `handle_assistant_message`-Dispatch ist normativ.
2. Innerhalb eines Steps: `command`-Strings werden **nicht** rekursiv
   auf Multi-Line gesplittet. Ein Step ist genau ein
   `_remote_commands.execute()`-Call. Saleria's `"todo: A\ntodo: B"`
   in einem Step läuft als Single-Command durch (parser nimmt nur
   die erste Zeile, Rest geht verloren). Erwünschtes Verhalten ist,
   dass Saleria das nicht tut — der Test dokumentiert das aktuelle
   Verhalten.

**Refinement — Pending-Confirmation-Filter (R3 detect-after-fact):**
Keine zentrale Allowlist von Pending-triggernden Commands. Stattdessen:
nach jeder Step-Ausführung wird `result.pending_confirmation` geprüft.
Ist es `True`, wird der Step als FAILURE markiert
(`reason: "Step verlangt Bestätigung — in Sequenz nicht erlaubt"`),
die ggf. gesetzte PendingAction wird verworfen, und `on_failure`
greift wie üblich. Begründung: zentrale Klassifikation würde über >7
Handler driften; detect-after-the-fact ist robust und billig. Trade-off:
manche Pending-Commands haben Side-Effects vor dem Pending (z. B.
LLM-generierter Mail-Draft). Das nehmen wir in Etappe 1 in Kauf,
Etappe 3 löst es sauber.

### 3.3 LLM-System-Prompt-Erweiterung

```
Wenn der User mehrere unabhaengige Aktionen verlangt
('mach X UND Y UND Z'), emittiere EINE Antwort mit action_sequence:

  {"action": "action_sequence", "params": {
    "steps": [{"action": "...", "params": {...}}, ...],
    "on_failure": "continue"   // oder "stop"
  }, "response": "Ich erledige das in 3 Schritten."}

Nutze action_sequence NICHT fuer 5x denselben Command (z.B. 5 Todos)
-- dafuer reicht ein remote_command mit Newline-separiertem
command-String, das System splittet das automatisch.
```

### 3.4 on_failure-Strategien

| Wert | Verhalten |
|---|---|
| `continue` (default) | Bei Step-Failure weiter mit nächstem Step. Failure ins Sammel-Reporting. |
| `stop` | Bei erstem Failure: restliche Steps als `skipped` markiert, sofort Sammel-Antwort. |

Phase 82 implementiert beide. `stop` ist sinnvoll wenn Step 2 logisch
auf Step 1 aufbaut.

## 4. Sammel-Antwort-Format

```text
✅ 3 ausgeführt · ❌ 1 fehlgeschlagen

  - Aufgabe angelegt: Zahnbürste
  - Notiz gespeichert
  - Erinnerung Samstag 10 Uhr

Fehler:
  - todo: Knopfzelle 1.5V – DB locked
```

Knapp halten. Bei sehr vielen Steps (>10): nur Bilanz + Failure-Detail,
Erfolge zusammengefasst (`"3 Todos angelegt, 2 Notizen gespeichert"`).

## 5. Etappen

### 5.1 Etappe 1 — Routing + Single-User-Sequenz (1 Session)

- `ActionStep` / `ActionSequenceResult` DTOs in
  `src/elder_berry/comms/action_sequence.py`.
- `Assistant.process()` erkennt `action_sequence`, reicht Steps an
  `AssistantResult.action_params["steps"]` durch (Pass-through, analog
  `remote_command`).
- `BridgeMessageHandler._handle_action_sequence()` mit
  `on_failure: continue` als Default. Nutzt
  `_remote_commands.execute()` direkt (kein neuer Routing-Pfad).
- Tests in **neuer** `tests/test_action_sequence.py` (klein-fokussiert,
  nicht in das schon große `test_message_handlers.py` quetschen):
  1. Alle Steps erfolgreich → Sammel-Antwort, korrekte Bilanz.
  2. Step 2 schlägt fehl, `on_failure: continue` → Step 3 läuft, Bilanz
     enthält ✅ 2 / ❌ 1.
  3. Step 2 schlägt fehl, `on_failure: stop` → Step 3 als skipped,
     Bilanz enthält ✅ 1 / ❌ 1 / ⏭ 1.
  4. Leere `steps: []` → Guard-Antwort an User („keine Aktionen").
  5. Step mit ungültiger Form (kein dict / kein `action`) → Guard-
     Antwort, gesamte Sequenz abgebrochen (kann nicht „pro Step
     failen", wenn man nicht weiß *was* der Step sein soll).
  6. Step mit `action != "remote_command"` (Form OK, aber nicht in
     Allowlist) → FAILURE pro Step mit Reason „step-action nicht
     erlaubt", andere Steps laufen normal.
  7. Step mit `action == "action_sequence"` → FAILURE (Recursion-Guard,
     Reason „nested action_sequence nicht erlaubt").
  8. Step liefert `pending_confirmation == True` → FAILURE
     (detect-after-fact), PendingAction wird verworfen.
  9. Step mit Multi-Line-Command (`"todo: A\ntodo: B"`) → läuft als
     1 Step (nicht gesplittet), dokumentiert das Verhalten.

### 5.2 Etappe 2 — System-Prompt + Few-Shot-Beispiele (½ Session)

- `_build_action_sequence_hint()` im System-Prompt.
- **Pflicht:** mindestens ein Few-Shot-Beispiel mit `on_failure: stop`,
  idealerweise eines mit logischer Step-Abhängigkeit
  („lies Mail 3 UND antworte: …"). Ohne `stop`-Beispiel lernt Saleria
  die Strategie nie und der `stop`-Pfad bleibt totes Code. Plus 1–2
  `continue`-Beispiele für heterogene Sequenzen.
- Smoketest mit echter Saleria: „erstell mir Einkaufsliste UND setz
  Reminder für Samstag" — Saleria emittiert action_sequence statt
  Multi-Line-Command oder zwei separate User-Antworten.

### 5.3 Etappe 3 — Optional: Confirm-Step-Variante (½–1 Session)

- Step kann `confirm: true` haben. Bridge fragt User nach
  Bestätigung bevor der Step läuft (analog Pending-Confirmation).
- Erst wenn dieser Use-Case in Phase 82-Real-Use auftaucht.

## 6. Risiken

- **R1 — LLM-Halluziniert leeres `steps`:** Saleria emittiert
  `action_sequence` mit `steps: []`. Mitigation: Guard im Routing,
  loggen + an User „keine Aktionen — sag mir genauer was du willst".

- **R2 — Step-Routing-Sub-Aufrufe als Endlosschleife:** Wenn ein
  Step `action: action_sequence` hat (LLM verwirrt), nested
  recursion. Mitigation: harter Tiefen-Check (max 1 Ebene), Fail-Closed
  mit Log.

- **R3 — Step 2 wartet auf User-Antwort:** Wenn ein Step
  `pending_confirmation` triggert (Mail-Reply, Restart), bricht das
  die Sequenz. Mitigation: in Etappe 1 kein Pending-Confirm-Step
  erlauben (filter beim Step-Aufbau), Etappe 3 löst das sauber.

- **R4 — Token-Budget:** Sammel-Antwort kann groß werden (10 Steps ×
  100 Zeichen Detail = 1 KB). Mitigation: bei >10 Steps Erfolge
  zusammenfassen, nur Failures detailliert.

- **R5 — Backward-Compat zur Multi-Line-Quick-Fix:** Saleria
  könnte „doppelt" antworten (action_sequence + Multi-Line). Lösung
  ist *nicht nur* der Prompt, sondern hartcodiert im Routing
  (siehe §3.2 Vorrang-Regel): action_sequence wird vor
  `_handle_llm_remote_command` dispatcht, Multi-Line-Quick-Fix wird
  nicht erreicht. Innerhalb eines Steps wird `command` *nicht*
  rekursiv gesplittet.

## 7. Tests / Akzeptanzkriterien

- `pytest tests/test_action_sequence.py` — 9 Tests aus §5.1, alle grün.
- `pytest tests/test_message_handlers.py` — kein Regress (Multi-Line-
  Quick-Fix bleibt funktional, Routing-Reihenfolge unverändert).
- E2E manuell (Etappe 2):
  1. „erstell 3 Todos für Pizza UND schreib Notiz mit Rezept-Link UND
     setz Reminder Samstag" → Saleria emittiert `action_sequence`,
     User bekommt eine Sammel-Antwort, alle drei Aktionen sind
     ausgeführt.
  2. Step 2 schlägt fehl (z. B. notiz: ohne Text) → bei `continue`
     laufen 1 und 3 trotzdem; bei `stop` wird 3 als skipped markiert.
- mypy strict für `src/elder_berry/comms/action_sequence.py` und die
  geänderten Stellen in `assistant.py` / `message_handlers.py`.
- ruff clean.

## 8. Out of Scope

- Daten-Pipelines zwischen Steps (Phase 83+ oder Bestand-TaskChainRunner).
- Parallel-Execution.
- Step-Confirmation in Etappe 1 (Etappe 3).
- Auto-Sequence-Detection aus Multi-Line: bewusst vermieden, das
  ist die Aufgabe des Quick-Fixes.

## 9. Folge-Phasen

- **Phase 83 (offen) — Action-Pipelines:** Output eines Steps wird
  Input des nächsten (z. B. „suche Mails von X" → „fasse erste
  Mail zusammen" → „setze Reminder zu Inhalt").
- **Phase 84 (offen) — Conditional Steps:** „wenn X, dann Y, sonst Z".
  Würde echte LLM-State-Machine nötig machen — aufwändig.
