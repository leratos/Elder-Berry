# Phase 82.1 – Multi-Line-in-Step + Hint-Klarstellung

**Status:** Konzept (2026-05-11)
**Branch:** `feature/phase-82-1-multi-line-in-step`
**Aufwand:** ~1.5–2 Sessions
**Voraussetzung:** Phase 82 (gemerged via PR #205, Commit `0f799ba`).
**Konzept-Verweis:** [phase-82-multi-action-sequencing.md](phase-82-multi-action-sequencing.md)

## 1. Trigger

Smoketest am 2026-05-11 (Lera, gegen den Live-Bot direkt nach Phase-82-
Merge). User-Anfrage:

> erstell 3 Todos für Pizza UND schreib Notiz mit Rezept-Link UND setz
> Reminder Samstag

Saleria emittierte korrekt eine `action_sequence` mit drei Steps – aber
der erste Step packte alle 3 Todos als Newline-separierten
`command`-String:

```json
{"action": "remote_command", "params": {
  "command": "todo: Zutaten für Pizza kaufen, mittel, Einkauf\ntodo: Pizzateig vorbereiten, mittel, Kochen\ntodo: Pizza backen, mittel, Kochen"
}}
```

Per Phase-82 §3.2 Vorrang-Regel wird `command` innerhalb eines Steps
**nicht** rekursiv auf Multi-Line gesplittet. Konsequenz:
`parse_command` matcht den ganzen Multi-Line-Blob, findet keinen
passenden Command, der Step kommt als FAILURE "kein bekannter command"
zurück. Bilanz: ✅ 2 / ❌ 1, alle drei Todos sind weg.

## 2. Bewertung

Saleria's Verhalten ist intuitiv und realistisch: gleichartige Items
(3 Todos) als Multi-Line in einen Step zu packen ist eine natürliche
Token-Optimierung – sie hat den Etappe-2-Hint (`Newline-separierter
command-String reicht für homogene Batches`) auf die Sequenz übertragen.

Die ursprüngliche §3.2-Entscheidung ("Erwünschtes Verhalten ist, dass
Saleria das nicht tut") war konservativ richtig zum Zeitpunkt der
Spezifikation, hat sich aber im Real-Use als zu restriktiv erwiesen.

## 3. Entscheidung

**§3.2 wird umgekehrt:** Multi-Line-in-Step wird **erlaubt** und
transparent in Sub-Calls gesplittet, analog zum Top-Level-
Multi-Line-Quick-Fix (`_execute_multi_line_commands`).

Bedeutung für die Vorrang-Regeln:

| Pfad | Multi-Line-Verhalten |
|---|---|
| Top-Level `remote_command` mit `\n` im command | Quick-Fix splittet (bestehend, unverändert) |
| `action_sequence` Step mit `\n` im command | **NEU:** Step-Loop splittet transparent |
| `action_sequence` mit Top-Level `\n` im response | unverändert (response ist nicht-ausführbar) |

Beide Splittungs-Pfade sind nicht rekursiv: ein Sub-Command nach Split
wird nicht erneut auf `\n` geprüft.

## 4. Architektur

### 4.1 Step-Loop

`_execute_single_step` prüft nach Allowlist-Check, ob
`step.params["command"]` ein Newline enthält:

- **Single-Line:** wie gehabt, 1 `execute()`-Call → 1 `StepOutcome`.
- **Multi-Line:** Delegation an neue Methode `_execute_multi_line_step`.

### 4.2 `_execute_multi_line_step`

```python
async def _execute_multi_line_step(
    self,
    base_index: int,
    step: ActionStep,
    command: str,
    msg: IncomingMessage,
) -> list[StepOutcome]:
    """Splittet command auf '\\n', führt jeden Sub-Command einzeln aus.

    Liefert eine Liste von StepOutcomes -- ein Outcome pro Sub-Command.
    Index ist base_index für alle Sub-Outcomes (zur Rückverfolgung
    welcher Step die Sub-Outcomes erzeugt hat); die Caller-Bilanz
    addiert sie als individuelle Items zur Sammel-Antwort.
    """
```

Verhalten:

1. `lines = [l for l in command.split("\n") if l.strip()]` – leere
   Lines (z.B. `\n\n`) werden weggefiltert.
2. Pro Sub-Line: parse_command + execute (analog `_execute_single_step`),
   inklusive Pending-Confirm-Filter und Restart-Filter.
3. Sammelt Sub-Outcomes in einer Liste, returnt sie.

### 4.3 `_execute_action_sequence`

Anpassung der Outcome-Sammlung: bisher 1 Outcome pro Step. Jetzt:

```python
outcome_or_list = await self._execute_single_step(...)
if isinstance(outcome_or_list, list):
    outcomes.extend(outcome_or_list)
    succeeded += sum(1 for o in outcome_or_list if o.status == "success")
    failed    += sum(1 for o in outcome_or_list if o.status == "failure")
else:
    outcomes.append(outcome_or_list)
    if outcome_or_list.status == "success": succeeded += 1
    else: failed += 1
```

Dabei muss `_execute_single_step` so umgebaut werden, dass es
`StepOutcome | list[StepOutcome]` zurückgibt – einfacher: immer eine
Liste returnieren (Single-Line gibt `[outcome]` zurück, Multi-Line
gibt `[outcome_a, outcome_b, ...]`). Der Caller `extend`et immer.

### 4.4 on_failure-Verhalten

`stop` greift beim **ersten** Sub-Failure innerhalb eines Multi-Line-
Steps. Konkret:

1. Sub-Step 2 von 3 schlägt fehl → Sub-Step 3 wird als `skipped`
   markiert (zur Klarheit in der Bilanz).
2. `_execute_action_sequence` setzt `stop_remaining=True` → restliche
   **Top-Steps** werden ebenfalls als `skipped` markiert.

Konsistent mit "stop beim ersten Fehler" – sowohl im Multi-Line-Step
als auch in der Top-Level-Sequenz.

### 4.5 Bilanz-Format

3 Sub-Steps eines Multi-Line-Steps zählen als **3 separate Outcomes**
in der Bilanz:

```text
✅ 5 ausgeführt · ❌ 0 fehlgeschlagen

  - Aufgabe angelegt: Zutaten kaufen
  - Aufgabe angelegt: Pizzateig vorbereiten
  - Aufgabe angelegt: Pizza backen
  - Notiz gespeichert
  - Erinnerung Samstag 10 Uhr
```

Statt `1 Step mit 3 Sub-Items` – der User sieht echte Detail-Bilanz.

### 4.6 Hint-Klarstellung

`_build_action_sequence_hint()` wird erweitert:

1. **Negativ-Regel-Verschärfung:** ergänzt um expliziten Hinweis, dass
   gleichartige Items in einer heterogenen Sequenz wahlweise als
   einzelne Steps oder als ein Multi-Line-Step emittiert werden können
   – beide Wege funktionieren.
2. **Drittes Few-Shot:** "3 Todos UND Notiz UND Reminder" – zeigt
   beide Varianten (5 Steps oder 3 Steps mit Multi-Line) als
   gleichwertig.

## 5. Tests

### 5.1 Umzuschreiben

- `test_multi_line_in_step_not_split` → `test_multi_line_in_step_splits_to_subcalls`:
  1 Step mit `"todo: A\ntodo: B\ntodo: C"` → 3 execute-Calls,
  3 Outcomes in der Bilanz.

### 5.2 Neu (5)

1. **Smoketest-Reproducer:** Multi-Line-Todo-Step + Notiz-Step +
   Reminder-Step → 5 Outcomes, ✅ 5 ausgeführt, ❌ 0.
2. **Sub-Failure mit `continue`:** Sub-Step 2 von 3 schlägt fehl →
   Sub-Step 3 läuft, nächster Top-Step läuft, Bilanz ✅ N / ❌ 1.
3. **Sub-Failure mit `stop`:** Sub-Step 2 von 3 schlägt fehl →
   Sub-Step 3 als skipped, alle weiteren Top-Steps als skipped,
   Bilanz mit ⏭ entsprechend.
4. **Leerzeilen:** `"todo: A\n\ntodo: B"` → leere Linie ignoriert,
   2 Sub-Outcomes.
5. **Hint-Wording:** Hint enthält die neue Negativ-Regel-Verschärfung
   und das dritte Few-Shot mit Multi-Line-in-Step.

## 6. Risiken

- **R1 — Doppelt-gesplittete Strings:** Top-Level-`command` mit `\n`
  und ein Step-`command` mit `\n` führen jeweils zur Splittung.
  Mitigation: Splittung ist nicht rekursiv, jeder Pfad splittet genau
  einmal auf seiner Ebene.

- **R2 — Bilanz-Inflation:** Ein Multi-Line-Step mit 20 Sub-Items
  bläht die Sammel-Antwort auf. Mitigation: Phase 82 §4 Format-Regel
  greift ("bei >10 Steps Erfolge zusammenfassen, nur Failures
  detailliert"). Bleibt unverändert.

- **R3 — Sub-Step mit Pending-Confirm:** ein Sub-Command triggert
  pending_confirmation. Mitigation: gleicher Filter wie für Top-Level-
  Steps – Sub-Outcome wird FAILURE, PendingAction verworfen.

- **R4 — Sub-Step mit Restart:** analog Phase-82-PR-Review-Fix:
  FAILURE mit Reason "Restart darf nicht Teil einer Sequenz sein".

## 7. Akzeptanzkriterien

- `pytest tests/test_action_sequence.py` – alle Tests grün, inkl. der
  umgeschriebenen + 5 neuen.
- mypy --strict für die geänderten Stellen in `message_handlers.py`.
- ruff clean.
- Smoketest gegen Live-Saleria nach Merge:
  "erstell 3 Todos für Pizza UND schreib Notiz mit Rezept-Link UND
  setz Reminder Samstag" → ✅ 5 ausgeführt (3 Todos einzeln in der
  Liste), Notiz und Reminder wie gehabt.

## 8. Out of Scope

- Splittung anderer Separatoren (";", "und"-Erkennung etc.) – `\n` bleibt
  der einzige Trigger, analog Quick-Fix.
- Echte Daten-Pipelines zwischen Sub-Steps – das wäre Phase 83.
- Confirm-Steps – das wäre Phase-82-Etappe-3.
