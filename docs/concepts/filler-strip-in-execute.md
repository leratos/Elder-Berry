# Filler-Strip in execute() (Mini-Konzept)

**Status:** Konzept (2026-05-11)
**Branch:** TBD wenn die Phase startet
**Aufwand:** ~1 Session
**Trigger:** Codex-Reviewer P2-Anmerkung am Pattern-Routing-Bugfix
([commit `2942cc5`](../../) auf `fix/pattern-routing-note-and-calendar`).

## 1. Ausgangslage

Die Bridge routet Commands zweistufig:

1. **`parse_command(text)`** strippt führende Filler via `_strip_fillers`
   und matchet das **gestrippte** Ergebnis gegen die Handler-Patterns.
   `_FILLER_PREFIXES` enthält 24 Floskeln: `"kannst du mir mal"`,
   `"zeig mir"`, `"sag mir bitte"`, `"bitte"`, etc.
2. **`execute(command, raw_text)`** reicht den **originalen** `msg.body`
   (mit Filler) an die `_cmd_*`-Methoden des Handlers. Die rufen typisch
   `pattern.match(raw_text.strip())` — also denselben Regex auf dem
   rohen Text.

**Inkonsistenz:** der gestrippte Text passierte das Routing-Gate, aber
der rohe Text scheitert am Re-Parse-Schritt, wenn das Pattern den
Filler-Prefix nicht selbst akzeptiert.

## 2. Beispiel

```
"kannst du mir mal notiz löschen #1"
```

1. `parse_command`:
   - `_strip_fillers("kannst du mir mal notiz löschen #1")` →
     `"notiz löschen #1"`.
   - `NOTE_DELETE_PATTERN.match("notiz löschen #1")` → ✓.
   - Routing-Ergebnis: `command="note_delete"`.

2. `Bridge.handle_remote_command` ruft
   `execute("note_delete", raw_text="kannst du mir mal notiz löschen #1")`.

3. `_cmd_delete`:
   - `NOTE_DELETE_PATTERN.match("kannst du mir mal notiz löschen #1")`
     → ✗ (Pattern beginnt mit `^notiz` — der Filler-Prefix bricht den
     Match).
   - Returnt FAILURE `"Welche Notiz?"`.

User sieht: Fehlermeldung, obwohl das Routing erkannt hatte was gemeint
war. Frustrierend und schwer zu debuggen.

## 3. Bisheriger Workaround (nicht ausreichend)

Einzelne Patterns haben `(?:bitte\s+)?` als optionalen Prefix — zuerst
`NOTE_ADD_PATTERN`/`NOTE_SET_FACT_PATTERN`, nach Codex's Anmerkung jetzt
auch `NOTE_DELETE/SEARCH/DELETE_FACT/GET_FACT`. **Aber das deckt nur
"bitte" ab.** Die anderen 23 Filler-Prefixes bleiben kaputt:

```
"zeig mir mal die notizen"           → notizen, OK (parse-strip wirkt)
                                       _cmd_list nutzt keinen Re-Parse
                                       -> kein Problem hier.
"kannst du mir mal notiz löschen #1" → kaputt, siehe oben.
"sag mir bitte notiz löschen #1"     → kaputt (sag mir bitte).
"zeig mir mal notizen suche Pizza"   → kaputt.
```

Welche Handler betroffen sind: alle Handler, deren `_cmd_*`-Methoden
`pattern.match(raw_text)` machen — und das ist die Mehrheit. Nicht
betroffen: Handler die Parameter aus dem Command-Namen ableiten
(`notizen` → Liste, `wol` → Magic Packet), weil dort kein Re-Parse
nötig ist.

## 4. Optionen

### Option X1: Patterns bekommen ALLE Filler-Prefixes

```python
NOTE_DELETE_PATTERN = re.compile(
    rf"^(?:{_FILLER_PREFIX_RE.pattern})?notiz...",
    re.IGNORECASE,
)
```

**Pro:** keine API-Änderung.
**Con:** Patterns werden hässlich, Filler-Liste ist an mehreren Stellen
referenziert, Drift-Gefahr (neuer Filler → alle Patterns suchen). Die
Pattern-Tests (z.B. test_remote_commands `_PATTERN.match("...")`)
brauchen weitere Cases.

### Option X2: parse_command übergibt gestrippten Text mit

```python
# Aktuell:
def parse_command(self, text: str) -> str | None: ...

# Neu:
def parse_command(self, text: str) -> tuple[str, str] | None:
    """Returns (command, stripped_text) oder None."""
```

Bridge passt sich an: `execute(command, stripped_text or raw_text)`.
**Pro:** sauber, semantisch ehrlich (Routing UND Re-Parse arbeiten auf
demselben Text).
**Con:** Signature-Change durch die Bridge + alle Caller. Mittlerer
Refactor, gut testabdeckungsabhängig.

### Option X3: `_cmd_*`-Methoden strippen selbst

```python
def _cmd_delete(self, raw_text: str) -> CommandResult:
    text = _strip_fillers(raw_text)  # NEU
    match = NOTE_DELETE_PATTERN.match(text.strip())
    ...
```

**Pro:** kleinste Änderung, lokal in jeder Methode.
**Con:** Filler-Import in viele Handler-Dateien (heute liegt
`_strip_fillers` in `remote_commands.py` — könnte nach
`commands/base.py` wandern). Mehrere `_cmd_*`-Methoden pro Handler
müssen alle angepasst werden.

### Option X4 (empfohlen): zentraler Strip im Orchestrator

`RemoteCommandHandler.execute(command, raw_text)` strippt **einmal**
vor der Delegation an den Sub-Handler:

```python
def execute(self, command: str, raw_text: str) -> CommandResult:
    text = _strip_fillers(raw_text)  # NEU, einmalig zentral
    handler = self._command_handler_map[command]
    return handler.execute(command, text, ...)
```

Sub-Handler bekommen **immer** den gestrippten Text. `_cmd_*` müssen
nichts mehr wissen.

**Pro:**
- **1 Stelle**, kein Drift-Risiko.
- API für Sub-Handler unverändert (gleicher String-Parameter, nur
  vorgestrippt).
- Konsistent mit der `parse_command`-Logik (beide nutzen
  `_strip_fillers`).
- Bestehende `(?:bitte\s+)?`-Prefixes in Patterns werden harmlos
  redundant — können in einem Follow-up entfernt werden, müssen aber
  nicht (Tests laufen weiter).

**Con:**
- Theoretisch: ein Handler könnte einen Filler als Datenpräfix
  brauchen (z.B. `clip: bitte schick`). `_strip_fillers` matcht
  Filler nur **am Anfang des Texts**, nicht inline — das ist sicher.
  Anführungszeichen oder Doppelpunkte schützen ohnehin.
- Risiko-Audit nötig: Send-File-Pfade mit Filler-Wort? Path mit "bitte"
  drin? Beispiel `"schick mir bitte C:\Users\..."`: `_strip_fillers`
  entfernt "schick mir bitte " → "C:\Users\..." → SEND_FILE_PATTERN
  matched. ✓ kein Datenverlust. Pfad mit `C:\bitte\` startet nicht mit
  "bitte" als Wort (steht hinter `C:\`), greift kein Filler-Prefix.

## 5. Empfehlung

**Option X4.** Zentraler Strip, eine Codezeile, keine
Handler-Pflege. Audit der Handler vorab in <30 min machbar.

Sekundär: nach X4 sind die `(?:bitte\s+)?`-Prefixes in den Patterns
funktional redundant — können in einem Cleanup-Commit gestrippt werden
(separater PR, niedrige Priorität).

## 6. Tests

- Unit-Test pro betroffenen Handler:
  - `"kannst du mir mal notiz löschen #1"` → erfolgreicher Delete.
  - `"sag mir bitte was ist WLAN"` → erfolgreicher Get-Fact-Lookup.
  - `"zeig mir mal todos"` → Liste (matcht ohnehin schon, aber als
    Schutz-Test gegen Regress).
- Bridge-Level-Test: `handle_remote_command(msg)` mit Filler-Text →
  `_cmd_*` bekommt den gestrippten Text und matcht.
- Edge: Text mit Filler-Wort im Body (`"schick mir bitte
  C:\bitte\test.txt"`) — _strip_fillers wirkt nur am Anfang,
  Path-Body bleibt intakt.

## 7. Risiken

- **R1 — Path-/URL-Werte mit Filler-Wörtern:** `_strip_fillers` greift
  nur am Textanfang (`^`), nicht inline. Pfade/URLs als Werte sind
  sicher.
- **R2 — Filler in echten Notiz-Inhalten:** `"notiz: bitte daran
  denken"` → `_strip_fillers` würde "bitte" am Anfang strippen, aber
  das ist hier nicht der Anfang (`notiz:` steht davor). `_strip_fillers`
  matcht via Regex `^(?:filler1|filler2|...)\b` — Schutz greift.
- **R3 — `_strip_fillers` muss idempotent sein:** ist es bereits
  (`while prev != current: ...` Loop). Bei `Bridge.execute` wird der
  Text einmal gestrippt; parse_command hatte ihn schon einmal
  gestrippt. Doppel-Strip ist no-op.

## 8. Out of Scope

- Filler-Liste erweitern. `_FILLER_PREFIXES` deckt aktuell 24
  Floskeln ab; weitere kommen mit neuen Beobachtungen.
- Mehrsprachige Filler (EN). Saleria wird auf Deutsch betrieben.
- Inline-Filler (`"notiz bitte ergänzen löschen #1"`) — unrealistisch.
