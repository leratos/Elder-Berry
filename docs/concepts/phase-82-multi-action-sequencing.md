# Phase 82 – Multi-Action-Sequencing 📦

**Status:** Konzept (2026-05-08)
**Branch:** `feature/phase-82-multi-action-sequencing` (geplant)
**Aufwand:** ~1–2 Sessions
**Voraussetzung:** keine harte Abhängigkeit
**Roadmap-Referenz:** Folge der **Quick-Fix-Multi-Line-Iteration** vom
2026-05-08 (Commit `<wird gefüllt nach push>`). Quick-Fix deckt
gleichartige Single-Command-Batches ab; Phase 82 liefert das saubere
Action-Modell für gemischte Sequenzen.

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

```python
# in core/assistant.py oder neue actions/sequence.py
@dataclass(frozen=True)
class ActionStep:
    action: str                # "remote_command" / "system_status" / ...
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

### 3.2 Routing-Erweiterung

`Assistant.process()` erkennt `parsed["action"] == "action_sequence"`,
ruft neuen Pfad auf der Bridge-Seite (analog `multi_step` in der
TaskChain). Die Bridge orchestriert die Step-Ausführung.

```python
# message_handlers.py:handle_assistant_message
if (
    result.action_executed == "action_sequence"
    and result.action_success
    and result.action_params
):
    await self._handle_action_sequence(msg, result, chat_context)
    return
```

`_handle_action_sequence` iteriert die Steps, ruft pro Step die
existierenden Routing-Pfade auf (intern als Sub-Aufrufe ohne neue
Matrix-Antwort pro Step), sammelt Resultate, sendet eine Sammel-Antwort.

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

- `ActionStep` / `ActionSequenceResult` DTOs.
- `Assistant.process()` erkennt `action_sequence`, reicht Steps an
  `AssistantResult.action_params["steps"]` durch.
- `BridgeMessageHandler._handle_action_sequence()` mit
  `on_failure: continue` als Default.
- Tests: 4–5 Tests in `test_message_handlers.py` (alle erfolgreich,
  ein Fail mit continue, ein Fail mit stop, leere Step-Liste,
  ungültige Step-Form).

### 5.2 Etappe 2 — System-Prompt + Few-Shot-Beispiele (½ Session)

- `_build_action_sequence_hint()` im System-Prompt.
- 2–3 Few-Shot-Beispiele (heterogene Sequenz, mit `stop`, mit
  `continue`).
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
  könnte „doppelt" antworten (action_sequence + Multi-Line). LLM-
  Prompt klar formulieren, plus Routing nimmt action_sequence wenn
  vorhanden.

## 7. Tests / Akzeptanzkriterien

- `pytest tests/test_message_handlers.py::TestActionSequence`
  - 5+ Tests für Step-Lifecycle.
- E2E manuell:
  1. „erstell 3 Todos für Pizza UND schreib Notiz mit Rezept-Link UND
     setz Reminder Samstag" → Saleria emittiert `action_sequence`,
     User bekommt eine Sammel-Antwort, alle drei Aktionen sind
     ausgeführt.
  2. Step 2 schlägt fehl (z. B. notiz: ohne Text) → bei `continue`
     laufen 1 und 3 trotzdem; bei `stop` wird 3 als skipped markiert.
- mypy strict für `actions/sequence.py` (falls eigene Datei).

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
