# Phase 90 -- Multi-Line-Notiz-Pattern + Vollzugs-Halluzinations-Vermeidung

**Status:** Konzept (2026-05-13)
**Branch:** `feature/phase-90-multiline-notes-und-halluzination-konzept` (Konzept)
**Folge-Branches (geplant):**
- `feature/phase-90-a-multiline-note-pattern` (Code-Fix Pattern)
- `feature/phase-90-b-vollzugs-halluzination-prompt` (Prompt-Fix Saleria)

**Aufwand:** 1 Konzept-Session + 2 Implementierungs-Sessions (je <=30 Min)
**Vorgaenger:**
- Phase 76 (Plugin-Architektur Command-Handler, `note_commands.py`)
- Phase 81b (Plugin-Vorschlag bei nicht-erkannten Commands)
- Phase 82 (Multi-Action-Sequencing, `_try_parse_multi_line`)

## Trigger

Lera-Smoketest 2026-05-13. Saleria-Dialog mit Realwelt-Effekt:

```
lera>     Speicher die Einkaufsliste als Notiz ab
saleria>  Gespeichert! Die Einkaufsliste liegt jetzt als Notiz bei dir.
[System]> Ich habe das als Befehl verstanden ('notiz: Moscow Mule
          Einkaufsliste (2 Personen)
          - Vodka (mind. 10 cl)
          - Ingwerbier (...)
          - 1 Limette (frisch)
          - Eiswuerfel
          Optional: Kupferbecher, Minze zur Garnitur'), konnte ihn
          aber keinem meiner Commands zuordnen. Ich habe Marcus eine
          Notiz hinterlassen [...]
lera>     note
saleria>  Keine Notizen vorhanden. Tipp: 'merk dir: ...' oder
          'notiz: ...'
```

Zwei Defekte hintereinander:

1. **Vollzugs-Halluzination:** Saleria sagt "Gespeichert!" obwohl der
   Speicher-Versuch noch nicht stattgefunden hat. Die LLM-Response
   wird in [`message_handlers.py:1337-1339`](../../src/elder_berry/comms/message_handlers.py#L1337-L1339)
   gesendet **vor** der Command-Ausfuehrung -- die Response basiert
   also auf der Vorhersage, dass der Command klappt.
2. **Pattern-Bug:** Das `NOTE_ADD_PATTERN` in
   [`note_commands.py:42-45`](../../src/elder_berry/comms/commands/note_commands.py#L42-L45)
   matcht den mehrzeiligen `command_text` nicht -- der Note-Add wird
   nie ausgefuehrt. User bekommt nichts gespeichert.

Effekt fuer Lera: Saleria luegt aktiv ("Gespeichert!"), eine Sekunde
spaeter widerspricht das System sich selbst (Fallback-Meldung), und
beim `note`-Aufruf ist nichts da. Vertrauensbruch -- Saleria-Aussagen
sind nicht verlaesslich.

## Abgrenzung

### Was Phase 90 NICHT ist

- **Kein** Multi-Line-Refactor von `_try_parse_multi_line`. Die
  bestehende Heuristik (alle Zeilen muessen Commands sein, sonst
  Single-Path) bleibt. Phase 90-A faellt korrekt auf den Single-Path
  zurueck, sobald NOTE_ADD_PATTERN mehrzeilig matcht.
- **Kein** Refactor des LLM-Response-Sequencings (Response vs.
  Command-Ergebnis-Order). Phase 90-B bleibt auf Prompt-Ebene.
- **Kein** Verallgemeinerung des Vollzugs-Halluzinations-Fixes auf
  alle Action-Types (`press_key`, `mail senden`, `kalender termin`).
  Phase 90-B aktualisiert die Beispiele im Saleria-Prompt; eine
  generelle "Response-darf-nicht-Vollzug-suggerieren"-Regel kommt
  als Section-Refresh, nicht als neue Strukturregel.
- **Kein** `NOTE_SET_FACT_PATTERN`-Multi-Line-Support (s. unten).

### Verwandte Phasen

- **Phase 89 (Saleria-Initiativ-Followup):** behandelt eine andere
  Halluzinations-Klasse (Initiativ-Frage ohne Kontext). Phase 90-B
  ist *Vor*-Vollzugs-Halluzination (LLM behauptet Aktion erledigt
  bevor sie laeuft); Phase 89 ist *Verschollene*-Initiativ-Frage
  (LLM stellt Frage, vergisst sie beim naechsten Turn).
- **Phase 82.1 (Multi-Line-in-Step):** behandelt Multi-*Command*-
  Batches innerhalb eines LLM-Outputs (5x `todo: ...`). Phase 90-A
  behandelt Multi-*Line-Inhalt* in **einem** Command (1x
  `notiz: ...\n- ...\n- ...`). Disjunkt.

## Ziel

1. **90-A:** Mehrzeiliger `notiz:`-Inhalt wird korrekt als
   Single-Note-Add erkannt und mit vollem Inhalt (Newlines erhalten)
   im NoteStore abgelegt.
2. **90-B:** Saleria emittiert fuer `remote_command` (und analoge
   Action-Types) **Ankuendigungs-Responses** ("Ich speichere die
   Notiz...") statt **Vollzugs-Responses** ("Gespeichert!"). Wenn
   der Command fehlschlaegt, ist der User nicht im Glauben gelassen,
   etwas sei passiert.

## Out-of-Scope

- Multi-Line-Inhalt fuer `merk dir: <key> ist <value>` -- der
  greedy `(.+?)\s+(?:ist|=|:)\s+(.+)`-Split kann mit `re.DOTALL`
  unerwartete Trennstellen erzeugen (z.B. "merk dir: code ist
  hier\nimport os" -- wo ist der Wert?). KV-Fakten sind per Design
  Single-Line; mehrzeilige Inhalte gehoeren in Freitext-Notizen
  (`notiz: ...`).
- Strukturelle Response-Order-Aenderung (Command zuerst, Response
  nach Ergebnis). Hat Latenz-Kosten (User sieht 2-5s lang nichts
  bei langsamen Commands wie Web-Search) und ist invasiver Refactor
  des AssistantResult-Flows. Separates Konzept falls Vollzugs-
  Halluzination nach Phase 90-B noch persistiert.
- Backfill-Migration: bereits geschriebene Notizen sind nicht
  betroffen (Pattern-Bug verhinderte das Schreiben, es gibt also
  nichts zu reparieren).

## Ausgangslage

### Befund 90-A: NOTE_ADD_PATTERN

Aktuell:

```python
# src/elder_berry/comms/commands/note_commands.py:42-45
NOTE_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz[:\s]+(.+)$",
    re.IGNORECASE,
)
```

Ohne `re.DOTALL` matcht `.` keine Newlines. Mit Multi-Line-Input
`"notiz: Moscow Mule...\n- Vodka..."`:

- `(.+)` matcht greedy bis zum ersten `\n` (also "Moscow Mule...").
- `$` muss nun matchen. Ohne `re.MULTILINE` matcht `$` nur am
  String-Ende (oder vor trailing newline). Da nach "Moscow Mule"
  noch `\n- Vodka...` folgt, **kein Match**.

Repro 2026-05-13 (`.venv/Scripts/python.exe -c "..."`):

```
ohne DOTALL: None
mit  DOTALL: "Moscow Mule Einkaufsliste (2 Personen)\n- Vodka..."
```

### Befund 90-A.1: parse_command-Pipeline

[`remote_commands.py:412-497`](../../src/elder_berry/comms/remote_commands.py#L412-L497)
hat drei Stufen:

1. **Stufe 1:** Hilfe-Sonderfaelle (`hilfe`, `hilfe <kategorie>`).
2. **Stufe 2a:** `pattern.match(check_text)` -- hier scheitert
   NOTE_ADD_PATTERN aktuell.
3. **Stufe 2b:** `pattern.search(check_text)` -- nur fuer
   `use_search=True`-Patterns. NOTE_ADD_PATTERN ist `use_search=False`.
4. **Stufe 3:** Keyword-Suche -- aber mit Length-Cap
   `MAX_KEYWORD_PHRASE_WORDS=8`. Der Multi-Line-Text hat deutlich
   mehr Woerter, der Keyword-Fallback ist auch tot.

→ `parse_command` returnt `None` → Retry (Phase 81b) → auch nichts →
Fallback-Meldung.

### Befund 90-A.2: _try_parse_multi_line

[`message_handlers.py:1850-1870`](../../src/elder_berry/comms/message_handlers.py#L1850-L1870)
splittet `command_text` an `\n` und versucht **jede** Zeile als
eigenstaendigen Command zu parsen:

- Zeile 1 (`notiz: Moscow Mule...`) → matcht `note_add` (single-line)
- Zeile 2 (`- Vodka...`) → kein Command-Pattern → `return None`

Verhalten ist nach 90-A korrekt: Multi-Line wird verworfen, der
Single-Path uebernimmt, und dort matcht NOTE_ADD_PATTERN dann
dank DOTALL den **gesamten** Multi-Line-Text als einen Note-Add.
Keine Aenderung an `_try_parse_multi_line` noetig.

**Edge-Case** (Pruefen im Test): Was wenn ALLE Zeilen einzeln als
Commands parsen, aber gemeinsam als Multi-Line-Notiz gemeint sind?
Z.B. wenn jede Zeile zufaellig mit einem Command-Keyword anfaengt
(unwahrscheinlich, aber konstruierbar). Antwort: dann gewinnt
Multi-Line-Batch -- akzeptables Verhalten, da bisherige Heuristik
und nicht Regression-Auslöser. Falls Lera spaeter "alle Zeilen
beginnen mit 'todo:'"-Edge-Cases sieht, eigenes Konzept.

### Befund 90-B: Vollzugs-Halluzinations-Pfad

[`message_handlers.py:1337-1339`](../../src/elder_berry/comms/message_handlers.py#L1337-L1339):

```python
if llm_result.response:
    self._chat_history.add(msg.sender, "assistant", llm_result.response)
    await self._channel.send_text(msg.room_id, llm_result.response)
```

Response wird **vor** `parse_command` und **vor** Command-Ausfuehrung
gesendet. Das ist konsistent mit anderen Action-Types (User sieht
sofort "Ich kuemmere mich darum..." bevor der Command tickt), aber
nur dann harmlos, wenn die Response eine **Ankuendigung** ist.

Saleria-Prompt
[`saleria.yaml:66-75`](../../src/elder_berry/character/saleria.yaml#L66-L75)
hat genau ein Beispiel fuer `remote_command`:

```yaml
Beispiel: {"action": "remote_command",
           "params": {"command": "mail suche Rechnung"},
           "response": "[cheerful] Ich suche mal nach der Rechnung..."}
```

"Ich suche mal..." ist sauber als Ankuendigung formuliert. Aber:
- Es gibt nur **ein** Beispiel.
- Keine explizite **Negativ-Regel** ("nicht 'Erledigt!' sagen").
- Keine Erinnerung beim `notiz:`-Use-Case.

LLM extrapoliert vom Beispiel -- bei `notiz: ...` schaltet Saleria
auf "Gespeichert!" weil das fuer Notizen "natuerlich" klingt.

### Eigenkritik / Kontext-Honesty

- Das Vollzugs-Halluzinations-Problem ist nicht **erst** Phase 90.
  Der Code-Pfad sendet seit Phase 76+ die Response vor Command-
  Ausfuehrung. Es ist Phase 90 nur deshalb, weil der Pattern-Bug
  das Problem fuer Lera spuerbar gemacht hat -- ohne Pattern-Bug
  haette Saleria "Gespeichert!" gesagt, der Command waere geklappt,
  und niemand haette die Halluzination bemerkt. Pattern-Fix allein
  wuerde das Problem also "lautlos verstecken". Deshalb 90-B
  mitnehmen, auch wenn 90-A das User-Symptom faktisch behebt.
- 90-B ist Prompt-only -- keine harte Garantie. Eine LLM kann sich
  trotz expliziter Anweisung nicht an Ankuendigungs-Stil halten,
  besonders bei kleineren Modellen. Restrisiko (s.u.).

## Architektur

### 90-A: Pattern-Fix

Einzeiliger Code-Wechsel:

```python
NOTE_ADD_PATTERN = re.compile(
    r"^(?:bitte\s+)?notiz[:\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
```

`re.DOTALL` (Alias `re.S`) erweitert `.` um Newline-Match. Effekt:
- `(.+)` frisst greedy ALLES nach `notiz: ` bis zum String-Ende.
- `$` ohne `re.MULTILINE` matcht weiter nur am String-Ende.
- `_cmd_add_note` (`note_commands.py:253-269`) ruft `match.group(1).strip()`
  -- `strip()` entfernt trailing Newlines, behaelt aber interne `\n`.
- `NoteStore.add_note(user_id, content)` speichert den vollen
  Multi-Line-Content; `format_short()` truncated bei Anzeige.

Disjunkte Patterns (kein Nebenwirkungs-Risiko):
- NOTE_SET_FACT_PATTERN: kein DOTALL, bleibt single-line (Out-of-Scope).
- NOTE_DELETE_PATTERN/NOTE_SEARCH_PATTERN: Reihenfolge in
  `patterns` stellt sicher, dass sie VOR NOTE_ADD geprueft werden.
  NOTE_ADD ist die generische Catch-All-Variante.
- NOTE_GET_FACT_PATTERN: Negative Lookahead schuetzt vor Domain-
  Keywords; multi-line Inhalt waere ohnehin kein "was ist X?".

### 90-B: Prompt-Refresh fuer Vollzugs-Ankuendigungen

Aenderung in
[`src/elder_berry/character/saleria.yaml`](../../src/elder_berry/character/saleria.yaml)
im `system_prompt_template` -- konkret in der
`remote_command`-Sektion:

Vorher (Z.66-75, gekuerzt):

```yaml
- remote_command: Remote-Befehl ausfuehren.
  [...]
  Beispiel: {"command": "mail suche Rechnung"},
            "response": "[cheerful] Ich suche mal nach der Rechnung..."
```

Nachher (Diff-Skizze, finaler Wortlaut in 90-B-PR):

```yaml
- remote_command: Remote-Befehl ausfuehren.
  [...]
  WICHTIG: deine "response" ist eine ANKUENDIGUNG, kein
  Vollzugs-Statement. Sage "Ich speichere die Notiz..." oder
  "Ich suche..." -- NICHT "Gespeichert!" oder "Fertig!".
  Der Command laeuft NACH deiner Response; ob er klappt, weisst
  du nicht. Wenn er fehlschlaegt, zeigt das System eine
  Fehlermeldung -- deine "Erledigt!"-Aussage waere dann eine Luege.
  Beispiele:
    {"command": "mail suche Rechnung",
     "response": "[cheerful] Ich suche mal nach der Rechnung..."}
    {"command": "notiz: Einkaufsliste\n- Vodka\n- Limette",
     "response": "[neutral] Ich lege die Notiz an..."}
```

Zwei Aenderungen:
1. **Explizite Negativ-Regel** mit Begruendung (Command laeuft
   NACH Response).
2. **Zweites Beispiel** mit `notiz:` + Newlines im Command-Wert
   (zeigt der LLM zusaetzlich die korrekte Encoding-Form).

Anti-Scope: keine Aenderung am Code-Pfad, kein Defer-Send-Mechanismus,
kein Two-Phase-Response. Sollte 90-B nicht ausreichen (Halluzination
bleibt), kommt eine Code-Phase 90-C mit Deferred-Response.

## Etappen

### 90-A: Pattern-Fix (PR1)

Branch: `feature/phase-90-a-multiline-note-pattern` (von main-Spitze).

Dateien:
- `src/elder_berry/comms/commands/note_commands.py`:
  - Z.42-45: `re.IGNORECASE` → `re.IGNORECASE | re.DOTALL`.
  - 1-Zeilen-Kommentar oberhalb des Patterns: warum DOTALL
    (Multi-Line-Notizen, Phase 90-A, Lera-Smoketest 2026-05-13).
- `tests/test_note_commands.py`:
  - Neuer Test `test_note_add_multiline_content_preserved`:
    Input mit 5 Zeilen, mock NoteStore, assertion dass
    `add_note(user_id, content)` mit `\n`-haltigem Content
    aufgerufen wurde.
  - Neuer Test `test_note_add_multiline_strip_only_outer`:
    leading/trailing Whitespace + Newlines werden gestrippt,
    interne Newlines bleiben.
- `tests/test_pattern_routing_note_and_calendar.py`:
  - Neuer Test `test_multiline_notiz_routes_to_note_add`:
    `parse_command("notiz: Liste\n- A\n- B")` → `"note_add"`.

Anti-Scope:
- Kein `_try_parse_multi_line`-Refactor.
- Kein NOTE_SET_FACT-Multi-Line.
- Kein Hilfe-Text-Update (Single-Line-Beispiel `notiz: ...` bleibt
  -- multi-line ist ein User-Bonus, kein primaerer Use-Case).

Quality-Gates:
- `pytest tests/test_note_commands.py tests/test_pattern_routing_note_and_calendar.py`
- `pytest --full` (Regressionscheck, erwartet: +3 passed, sonst keine
  Veraenderung).
- `mypy --strict src` (Pattern-Aenderung sollte 0 Typ-Issues haben).
- `ruff check src/elder_berry/comms/commands/note_commands.py`.

### 90-B: Prompt-Refresh (PR2)

Branch: `feature/phase-90-b-vollzugs-halluzination-prompt` (von 90-A-Merge).

Dateien:
- `src/elder_berry/character/saleria.yaml`:
  - `system_prompt_template`, `remote_command`-Sektion: Negativ-
    Regel + zweites Beispiel (notiz mit Newlines).
- `tests/`:
  - Pruefe Bestehende Saleria-Prompt-Tests
    (`tests/test_saleria_*.py` oder `tests/test_character_*.py`,
    siehe `git ls-files tests | grep -i saleria`):
    Wenn Tests den Prompt-String wortlaut-pinnen, anpassen.
  - Kein neuer Test fuer "LLM emittiert keine Vollzugs-Antwort":
    waere ein Integrations-Test gegen das echte LLM, zu fragil und
    aus dem Konzept-Scope draussen. Statt dessen Doku-Test:
    `test_saleria_remote_command_prompt_contains_announce_rule`
    der prueft, dass der Negativ-Regel-Wortlaut ("ANKUENDIGUNG"
    oder "Vollzugs-Statement", endgueltig in PR-Wortlaut fixiert)
    im generierten Prompt vorkommt.

Anti-Scope:
- Keine Aenderung an `src/elder_berry/core/prompts.py` (das ist
  Elder-Berry-Default, Saleria ist die aktive Persona). Falls Lera
  das spiegelt, separate Phase.
- Kein Code-Pfad-Refactor (Response-Order).

Quality-Gates:
- `pytest tests/test_saleria_*.py` (falls vorhanden) +
  `tests/test_character_*.py`.
- Manuelle Verifikation: Saleria-Restart + Replay des Smoketests
  ("Speicher die Einkaufsliste als Notiz ab"). Erwartet:
  Response = "Ich lege die Notiz an..." (oder Aequivalent), und
  nach Pattern-Fix von 90-A: tatsaechlich gespeichert.

### 90-C (kontingent, NICHT im Konzept-Scope)

Falls Halluzinationen nach 90-B persistieren (Smoketest binnen
2 Wochen zeigt 2+ Vollzugs-Statements): separates Konzept zur
Defer-Send-Response. Anti-Scope-Schutz: Nicht jetzt entwerfen,
sondern erst messen.

## Tests (Zusammenfassung)

| Test | Phase | Zweck |
|------|-------|-------|
| `test_note_add_multiline_content_preserved` | 90-A | Newlines im Note-Content erhalten |
| `test_note_add_multiline_strip_only_outer` | 90-A | Outer-Strip, kein Inner-Strip |
| `test_multiline_notiz_routes_to_note_add` | 90-A | parse_command erkennt Multi-Line `notiz:` |
| `test_saleria_remote_command_prompt_contains_announce_rule` | 90-B | Prompt enthaelt Negativ-Regel |
| Manuell: Smoketest-Replay | 90-B | Realwelt-Effekt verifiziert |

## Definition of Done

- **90-A:** Multi-Line-`notiz:`-Input via Matrix/Saleria erzeugt
  einen NoteStore-Eintrag mit vollem Multi-Line-Content. `notizen`
  zeigt die Notiz. `notiz loeschen #<id>` funktioniert weiter
  unveraendert.
- **90-B:** Saleria-Prompt enthaelt die Negativ-Regel; manueller
  Smoketest zeigt "Ich speichere..."-Response statt "Gespeichert!"-
  Halluzination.
- **Beide PRs gemerged**, Production-Restart auf Tower/Laptop/RPi5.
- **Journal abgeschlossen.**

## Restrisiken

1. **LLM-Compliance schwach (90-B):** Negativ-Regel im Prompt
   schuetzt nicht hart. Kleinere Modelle koennten dennoch
   "Gespeichert!" emittieren. Mitigation: in 2 Wochen Re-Eval mit
   Smoketest-Sample; 90-C als Code-Fix vorgemerkt.
2. **DOTALL-Regression im Edge-Case (90-A):** Wenn ein Multi-Line-
   `notiz:`-Input zufaellig durch Stufe-2a-Match VOR den
   spezifischen Patterns (note_delete, note_search) durchschlaegt,
   kann der falsche Command gewinnen. Mitigation: in `patterns`-
   Liste in `note_commands.py:127-137` steht NOTE_ADD bereits
   NACH NOTE_DELETE/NOTE_SEARCH (Phase-76-Smoketest-Fix), die
   Reihenfolge schuetzt schon. Trotzdem im 90-A-Test verifizieren
   (`test_multiline_notiz_does_not_eat_note_delete`).
3. **NoteStore-Storage-Limits:** Wenn die LLM einen extrem grossen
   Multi-Line-Content emittiert (>10 KB), wird das ungefiltert
   gespeichert. Aktuell hat NoteStore keinen Content-Size-Cap.
   **Nicht** in Phase 90 fixen (separates Capacity-Konzept, falls
   Lera Realwelt-Effekt sieht); aber im Konzept dokumentieren.
4. **Conversation-History-Bloat (90-A):** Multi-Line-Notes landen
   im chat_history; Token-Budget der Folge-LLM-Calls steigt. Bei
   ueblichen Einkaufslisten <500 Tokens unkritisch. Bei
   Code-Snippet-Notizen oder ganzen Mail-Bodies: Restrisiko, aber
   bereits durch Phase-23-Rolling-Summary abgemildert.
5. **Section 11 von Phase-85-Doc (Carry-over):** Phase 87.B-Konzept
   hat einen separaten Section-11-V11-Migration-Folge-Punkt
   vermerkt. Phase 90 beruehrt das nicht und aendert keine
   Sanitizer-Docs.

## Anhang: Code-Repro 2026-05-13

```python
import re

NOTE_ADD_PATTERN_OLD = re.compile(
    r"^(?:bitte\s+)?notiz[:\s]+(.+)$", re.IGNORECASE
)
NOTE_ADD_PATTERN_NEW = re.compile(
    r"^(?:bitte\s+)?notiz[:\s]+(.+)$", re.IGNORECASE | re.DOTALL
)

text = "notiz: Moscow Mule Einkaufsliste (2 Personen)\n- Vodka\n- Limette"
print("alt:", NOTE_ADD_PATTERN_OLD.match(text))  # None
print("neu:", NOTE_ADD_PATTERN_NEW.match(text).group(1)[:50])
# "Moscow Mule Einkaufsliste (2 Personen)\n- Vodka..."
```
