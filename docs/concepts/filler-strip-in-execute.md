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

```text
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

## 2.5 Wichtig: `_strip_fillers` macht Prefix UND Suffix

**Korrektur 2026-05-11 (Codex-Reviewer P2 an Commit `b77cac8`):**
Die ursprüngliche Version dieses Konzepts behauptete, `_strip_fillers`
greife nur am Textanfang. Tatsächlich macht der Helper **beides** in
einer iterativen Schleife
([`remote_commands.py:158-170`](../../src/elder_berry/comms/remote_commands.py#L158-L170)):

```python
while prev != current:
    prev = current
    current = _FILLER_PREFIX_RE.sub("", current).strip()
    current = _FILLER_SUFFIX_RE.sub("", current).strip()  # SUFFIX
```

`_FILLER_SUFFIXES` enthält: `"bitte"`, `"mal"`, `"zeigen"`,
`"anzeigen"`, `"ausgeben"`, `"checken"`.

**Konsequenz für X4:** ein **zentraler `_strip_fillers`-Call in
`execute()`** würde User-Inhalte am Ende verstümmeln. Konkrete
Bug-Szenarien:

| Input | User-Intention | Naiv-X4 würde produzieren |
| --- | --- | --- |
| `clip: hallo bitte` | Clipboard = `"hallo bitte"` | `"hallo"` (Daten-Verlust) |
| `cloud suche bitte` | Suchbegriff `"bitte"` | Leerer Suchbegriff |
| `notiz: meld dich mal` | Notiz = `"meld dich mal"` | `"meld dich"` |
| `antworte auf #5 melde mich mal` | Mail-Draft endet auf "mal" | Draft endet auf "melde mich" |

Das betrifft jeden Handler, dessen `_cmd_*` User-Content nach dem
Command-Keyword durchschleift — `clip_write`, `note_add`,
`note_set_fact`, `mail_reply_draft`, `cloud_search` etc.

**Folge:** die ursprüngliche X4-Empfehlung wird zu **X4a** (siehe §4).

## 3. Bisheriger Workaround (nicht ausreichend)

Einzelne Patterns haben `(?:bitte\s+)?` als optionalen Prefix — zuerst
`NOTE_ADD_PATTERN`/`NOTE_SET_FACT_PATTERN`, nach Codex's Anmerkung jetzt
auch `NOTE_DELETE/SEARCH/DELETE_FACT/GET_FACT`. **Aber das deckt nur
"bitte" ab.** Die anderen 23 Filler-Prefixes bleiben kaputt:

```text
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

### Option X4a (empfohlen): zentraler Prefix-only-Strip im Orchestrator

> **Hinweis:** Eine frühere Version dieses Konzepts schlug "X4" mit
> `_strip_fillers` (Prefix + Suffix) vor. Codex-Reviewer P2 hat
> gezeigt, dass Suffix-Strip User-Inhalte am Ende verstümmelt (siehe
> §2.5). X4a ist die korrigierte Variante: **nur Prefix-Strip**.

Neuer Helper in `remote_commands.py`:

```python
def _strip_filler_prefix(text: str) -> str:
    """Entfernt nur Prefix-Filler. Im Gegensatz zu _strip_fillers wird
    der Suffix-Teil NICHT entfernt, weil execute()-Pfade User-Content
    durchschleifen (clip:, notiz:, mail-reply etc.) und der Inhalt am
    Ende auf Filler-Tokens enden darf ('hallo bitte', 'meld dich mal').
    """
    prev = None
    current = text.strip()
    while prev != current:
        prev = current
        current = _FILLER_PREFIX_RE.sub("", current).strip()
    return current or text.strip()
```

`RemoteCommandHandler.execute(command, raw_text)` strippt **einmal**
vor der Delegation an den Sub-Handler:

```python
def execute(self, command: str, raw_text: str) -> CommandResult:
    text = _strip_filler_prefix(raw_text)  # NEU, einmalig zentral
    handler = self._command_handler_map[command]
    return handler.execute(command, text, ...)
```

Sub-Handler bekommen **immer** den prefix-gestrippten Text. `_cmd_*`
müssen nichts mehr wissen.

**Asymmetrie zu `parse_command` (gewollt, muss kommentiert werden):**

| Pfad | Verwendet | Warum |
| --- | --- | --- |
| `parse_command` | `_strip_fillers` (Prefix + Suffix) | Normalisierung für Routing — Inhalt wird hier nicht durchgereicht. |
| `execute` | `_strip_filler_prefix` (nur Prefix) | User-Content darf am Ende erhalten bleiben. |

Asymmetrie muss im Code-Kommentar explizit dokumentiert werden,
sonst greift jemand das nächste Mal zum vermeintlich konsistenten
`_strip_fillers` und reaktiviert den Suffix-Bug.

**Pro:**

- **1 Stelle**, kein Drift-Risiko.
- API für Sub-Handler unverändert (gleicher String-Parameter, nur
  prefix-gestrippt).
- Suffix-Verlust bei User-Content (siehe §2.5) ausgeschlossen.
- Bestehende `(?:bitte\s+)?`-Prefixes in Patterns werden harmlos
  redundant — Cleanup ist optional.

**Con:**

- Asymmetrie zwischen `parse_command` und `execute` muss im Code
  dokumentiert werden.
- Suffix-Filler in Floskel-Phrasen werden im execute-Pfad NICHT
  abgeschnitten. Beispiel: `"zeig mir status bitte"` → parse_command
  matched `"status"` (nach Strip), execute kriegt `"status bitte"`. Für
  reine Anzeige-Commands wie `status` ist `bitte` am Ende harmlos.
  Für Commands die `match(raw_text)` machen würde `bitte` am Ende ggf.
  den Match brechen — aber das ist bereits das aktuelle Verhalten und
  nicht Ziel dieser Phase.
- Risiko-Audit Path-Prefixe: `"schick mir bitte C:\Users\..."` →
  `_strip_filler_prefix` entfernt "schick mir bitte " →
  "C:\Users\..." → SEND_FILE_PATTERN matched. ✓ kein Datenverlust.

### Option X4b: X4 + Opt-Out-Liste

Handler die User-Content tragen (clip_write, note_add, …) bekommen den
rohen Text via Opt-Out-Flag. Andere den `_strip_fillers`-Text.

**Pro:** maximale Flexibilität, Suffix-Strip in den unkritischen Fällen
weiterhin aktiv.
**Con:** neue Konfigurationsfläche pro Handler. Drift-Gefahr (neuer
Handler vergisst Opt-Out → stiller Datenverlust). Komplexer als X4a.

### Option X4c: X4 fallenlassen

A-Fix (bitte-Prefix in Note-Patterns) ist schon in main. Alle anderen
Filler bleiben unbehandelt. Bei Bedarf pro-Pattern hinzufügen.

**Pro:** kein neues Risiko.
**Con:** lange Filler-Liste bleibt unaddressiert.

## 5. Empfehlung

**Option X4a.** Zentraler Prefix-only-Strip in `execute()`. Klein,
safe, semantisch sauber (Prefix-Filler sind Bedienungsfloskeln und
gehören nicht zum Inhalt; Suffix-Filler sind ambig und werden bewusst
nicht abgeschnitten).

Sekundär: nach X4a sind die `(?:bitte\s+)?`-Prefixes in den Patterns
funktional redundant — Cleanup-Commit optional, separater PR, niedrige
Priorität.

Implementation-Schritte:

1. `_strip_filler_prefix` in `remote_commands.py` neben `_strip_fillers`
   definieren, mit ausführlichem Kommentar zur Asymmetrie.
2. `RemoteCommandHandler.execute()` strippt vor Delegation.
3. Tests in §6 hinzufügen.
4. Smoketest gegen Live-Saleria.

## 6. Tests

**Prefix-Strip wirkt:**

- `"kannst du mir mal notiz löschen #1"` → erfolgreicher Delete
  (`_cmd_delete` bekommt `"notiz löschen #1"`).
- `"sag mir bitte was ist WLAN"` → erfolgreicher Get-Fact-Lookup.
- `"zeig mir mal todos"` → Liste (matcht ohnehin schon, aber Schutz-
  Test gegen Regress).
- `"schick mir bitte C:\Users\datei.pdf"` → Datei wird gesendet
  (Pfad bleibt intakt, nur Prefix-Filler entfernt).

**Suffix-Schutz (Codex-Reviewer-Korrektur):**

- `"clip: hallo bitte"` → Clipboard-Inhalt = `"hallo bitte"` (Suffix-
  Token bleibt erhalten, weil execute() **keinen** Suffix-Strip macht).
- `"notiz: meld dich mal"` → Notiz-Text = `"meld dich mal"`.
- `"cloud suche bitte"` → Suchbegriff = `"bitte"`.
- `"antworte auf #5 melde mich mal"` → Mail-Draft endet auf `"mal"`.

**Bridge-Level-Test:**

- `handle_remote_command(msg)` mit Filler-prefix-Text → `_cmd_*` bekommt
  den prefix-gestrippten Text und matcht; Inhalt am Ende intakt.

## 7. Risiken

- **R1 — `_strip_fillers` macht Prefix UND Suffix:** das war der Auslöser
  dieses Konzepts (Codex-Reviewer-P2). Wenn jemand X4 mit dem normalen
  `_strip_fillers` statt `_strip_filler_prefix` implementiert, kehrt der
  Suffix-Bug zurück. Mitigation: ausführlicher Code-Kommentar an
  beiden Helpern + Test-Suite, die Suffix-Tokens explizit prüft.
- **R2 — Filler in echten Notiz-Inhalten:** `"notiz: bitte daran
  denken"` → `_strip_filler_prefix` würde "bitte" nur am Textanfang
  strippen, aber `notiz:` steht davor. `_FILLER_PREFIX_RE` ist
  `^(?:filler1|...)\b` — Schutz greift.
- **R3 — `_strip_filler_prefix` muss idempotent sein:** ist es per
  Konstruktion (`while prev != current: ...` Loop wie bei
  `_strip_fillers`). Bei `Bridge.execute` wird der Text einmal
  gestrippt; `parse_command` hatte ihn schon einmal voll gestrippt.
  Doppel-Strip ist no-op.
- **R4 — Path-/URL-Werte mit Filler-Wörtern als Suffix:** der
  Prefix-only-Helper berührt das Ende nie, also sind Pfade die auf
  `bitte` oder `mal` enden (z.B. `C:\Users\bitte\`) safe.

## 8. Out of Scope

- Filler-Liste erweitern. `_FILLER_PREFIXES` deckt aktuell 24
  Floskeln ab; weitere kommen mit neuen Beobachtungen.
- Mehrsprachige Filler (EN). Saleria wird auf Deutsch betrieben.
- Inline-Filler (`"notiz bitte ergänzen löschen #1"`) — unrealistisch.
