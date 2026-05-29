# Phase 95 - Comms-Pattern-Stabilisierung und Conflict-Abmilderung

## Status

| Schritt | Stand |
|---|---|
| Konzept | fertig |
| E0 Corpus + Keyword-Audit | ✅ implementiert (2026-05-29) |
| E1 Match-Metadaten (Dataclasses) | ✅ implementiert (2026-05-29) |
| E2 Candidate-Sammlung + kompatibler Router | ✅ implementiert (2026-05-29) |
| E3 Conflict-Tests auf Candidate-Basis | offen |
| E4 Handler-Gates | offen |
| E5 Confidence-Regeln aktivieren | offen |
| E6 PatternSpec-Migration | offen |

Ausgangspunkt: Analyse aus Journal-Eintrag `elder-berry#533`.
Simulation ausgefuehrt auf Branch `feature/phase-95-comms-pattern-simulation`.
Baseline: 6 287 Tests, 3 skipped, 5 xfailed.

---

## Simulationsbefunde (2026-05-29)

E1/E2/E0 wurden implementiert und danach gegen das reale Handler-Set
ausgefuehrt. Die Tests deckten fuenf konkrete Befunde auf, die das Konzept
praezisieren oder korrigieren.

### F1 – MultiStopRouteCommandHandler nicht im Plugin-Registry ⚠️ kritisch

`multi_stop_route_commands.py` existiert, aber `MultiStopRouteCommandHandler`
ist **nicht in `registry.py` eingetragen**. Alle Multi-Stop-Eingaben fallen
silent auf `RouteCommandHandler` durch:

```
"ich muss von zuhause zu nadine und dann zu lisa"  →  route_from_to  (erwartet: multi_stop_route)
"plane route nach leipzig"                          →  route_plan     (erwartet: multi_stop_route)
```

Zwei xfail-Guards sichern diesen Zustand in `test_command_routing_corpus.py` ab.
Naechster Schritt: Handler in `registry.py` eintragen, xfail entfernen (E4.2).

### F2 – HOW_TO_PATTERN breiter als im Konzept beschrieben ⚠️ mittel

`HOW_TO_PATTERN = ^wie\s+mache\s+ich\s+(.+)$` matcht auch rein generisches
Nachfragen ohne jeden Rezept-Intent:

```
"wie mache ich das"      →  recipe_lookup  (kein Stop-Wort-Schutz)
"wie mache ich ein backup"  →  recipe_lookup  (xfail)
"wie mache ich einen screenshot"  →  recipe_lookup  (xfail)
```

Konzept §P2 und §E4.1 beschreiben das Risiko, unterschaetzen aber dessen
Ausmas. Selbst einsilbige Platzhalter (`das`, `es`, `sowas`) reichen als
Capture-Gruppe, um das Pattern zu aktivieren.
Naechster Schritt: Stopp-Wortliste fuer inhaltsleere Capture-Gruppen oder
`fallthrough=True` bei semantisch schwachen Treffern (E4.1).

### F3 – test_keyword_map_matches_handler_keywords hatte Logic-Bug ✅ behoben

`keyword_map` ist command-indexed: `{command: [keywords]}`.
Der urspruengliche Testausdruck `kw not in km` prueft einen Keyword-String als
Dictionary-Key in einem command-indizierten Dict – das ist immer `True` fuer
normale Keyword-Strings.

Korrektur (in `test_command_keyword_conflicts.py`):

```python
all_kw_in_km = {kw for keywords in km.values() for kw in keywords}
missing = {kw for kw in direct if kw not in all_kw_in_km}
```

### F4 – Vier Keyword-Konflikte waren undeklariert ✅ behoben

Folgende Cross-Handler-Kollisionen existierten, waren aber nicht in
`EXPECTED_KEYWORD_CONFLICTS` eingetragen:

| Keyword | Handler 1 / Command | Handler 2 / Command |
|---|---|---|
| `lauter` | SystemCommandHandler / `volume` | HarmonyCommandHandler / `harmony_volume_up` |
| `leiser` | SystemCommandHandler / `volume` | HarmonyCommandHandler / `harmony_volume_down` |
| `musik an` | SystemCommandHandler / `play` | HarmonyCommandHandler / `harmony_activity_on` |
| `wer ist` | NoteCommandHandler / `note_get_fact` | ContactCommandHandler / `contact_who` |

Aufloesungen:
- `lauter` / `leiser` / `musik an`: Harmony gewinnt via Pattern-Match (Confidence 90)
  vor System-Keyword (Confidence 30). Korrekt.
- `wer ist`: Contact-Pattern (Confidence 90) gewinnt vor Note-Keyword (Confidence 45).
  Korrekt.

Alle vier in `EXPECTED_KEYWORD_CONFLICTS` nachgetragen.

### F5 – collect_candidates erzeugt Duplikat-Kandidaten ℹ️ gering

Wenn ein Command sowohl via Stufe 2b (pattern_search) als auch via Stufe 3
(keyword) matcht, erscheint er zweimal in der Kandidatenliste:

```
"plane route nach leipzig"  →  [route_plan/pattern_search/conf=70, route_plan/keyword/conf=45]
```

`choose_candidate()` waehlt korrekt den hoeherwertigen Kandidaten.
Die Duplikate erhoehen aber Rauschen in Logs und erschweren die Lesbarkeit
von `test_collect_candidates_multi_candidate_log`.
Naechster Schritt (optional, in E3): Stufe 3 deduplizieren, wenn der Command
bereits in Stufe 2 gewonnen hat.

---

## Kurzfassung

Saleria routet Matrix-Nachrichten aktuell in dieser Reihenfolge:

1. `MatrixBridge` prueft direkte Remote-Commands vor dem LLM.
2. `RemoteCommandHandler.parse_command()` entscheidet sequenziell:
   Hilfe, Simple-Command, Pattern-Match, Pattern-Search, Keyword.
3. Der erste Treffer gewinnt.
4. Nur wenn kein Command erkannt wird oder ein Handler explizit
   `fallthrough=True` liefert, bekommt das LLM die Chance zur Klaerung.

Das ist schnell und gut testbar, aber konfliktanfaellig. Ein zu breites
Pattern oder Keyword kann eine eigentlich freie Nutzeranfrage abfangen, bevor
Saleria semantisch entscheiden darf.

Phase 95 soll das Routing nicht "magisch" machen. Ziel ist ein kontrollierter
Umbau von First-Match-Wins zu einem nachvollziehbaren Candidate-/Confidence-
Router, plus deutlich bessere Tests gegen bekannte und zukuenftige Konflikte.

## Ist-Architektur

Relevante Dateien:

| Datei | Rolle |
|---|---|
| `src/elder_berry/comms/bridge.py` | Ruft vor dem LLM `parse_command(msg.body)` auf. |
| `src/elder_berry/comms/message_handlers.py` | Fuehrt erkannte Commands aus, behandelt `fallthrough`, `list_pick`, Retry und Action-Sequenzen. |
| `src/elder_berry/comms/remote_commands.py` | Zentraler Router fuer direkte Commands. |
| `src/elder_berry/comms/commands/base.py` | `CommandHandler`, `CommandResult`, `CommandPlugin`, `HandlerContext`. |
| `src/elder_berry/comms/commands/registry.py` | Laedt Plugins und sortiert nach `priority`. |
| `src/elder_berry/comms/commands/*_commands.py` | Domain-Handler mit `simple_commands`, `patterns`, `keywords`, `execute()`. |

Bestehende Schutzschichten:

- Plugin-Prioritaeten: niedrigere Zahl gewinnt frueher.
- `CommandPlugin.conflicts`: dokumentiert bekannte Pattern-Konflikte.
- `tests/test_plugin_pattern_conflicts.py`: samplebasierter Pattern-
  Conflict-Detector.
- Keyword-Length-Cap in `RemoteCommandHandler._MAX_KEYWORD_PHRASE_WORDS`.
- Keyword-Wortgrenzen statt Substring-Matches.
- `CommandResult.fallthrough`: Handler kann zurueck ans LLM geben.
- Einzelne Regressionstests fuer Live-Konflikte:
  - Note vs. "speichere es als Notiz".
  - Multi-Stop-Route vs. Single-Stop-Route.
  - Recipe Lookup gegen schwache Semantik-/API-Treffer.

## Problemklassen

### P1 - First-Match-Wins versteckt Konflikte

Wenn zwei Handler matchen, sieht der Router nur den ersten Treffer. Der
zweite Kandidat verschwindet. Das erschwert Debugging und Tests, weil man
nicht sieht, ob ein korrektes Ergebnis stabil ist oder nur zufaellig wegen
Priority gewinnt.

### P2 - Pattern-Konflikttest ist samplebasiert

`tests/test_plugin_pattern_conflicts.py` prueft ausgewaehlte Beispielsaetze.
Das ist gut, aber lueckenhaft. Neue breite Patterns koennen in Bereichen
kollidieren, fuer die noch kein Sample existiert.

### P3 - Keywords haben keinen vergleichbaren Conflict-Detector

Der Keyword-Pfad ist durch Length-Cap und Wortgrenzen besser geworden. Es gibt
aber keinen systematischen Test, der gleiche Keywords oder semantisch zu breite
Keyword-Phrasen ueber Handlergrenzen hinweg findet.

### P4 - Breite Search-Patterns sind schwer zu bewerten

Besonders riskant:

- `multi_stop_route`: breiter Search-Vorfilter, gewinnt vor `route`.
- `route`: `ROUTE_FROM_TO_PATTERN` und `ROUTE_PLAN_PATTERN` laufen als Search.
- `recipe`: `HOW_TO_PATTERN` (`wie mache ich ...`) ist absichtlich breit.
- `note_get_fact`: `was ist ...` / `wie lautet ...` nahe an allgemeinen Fragen.
- `contact_field_query`: natuerliche Feldfragen nahe an Note/Kalender.
- `advanced.web_search`: `suche/finde/google ...` kann andere Suchen ueberlagern.

### P5 - Handler-interne Reihenfolge bleibt Stammeswissen

Beispiel: spezifische Note-Patterns muessen vor `NOTE_ADD_PATTERN` stehen.
Das ist in Kommentaren und Tests dokumentiert, aber nicht als deklarative
Eigenschaft des Patterns modelliert.

### P6 - Fehlende Runtime-Diagnostik

Bei Live-Fehlern sieht man oft nur den Gewinner. Fuer Debugging waeren
nuetzlich:

- welche Kandidaten haben gematcht?
- welcher Match-Typ war es?
- welcher Kandidat wurde wegen Priority/Confidence/Domain-Gate verworfen?
- warum gab es `fallthrough`?

## Ziele

1. Konflikte frueher sichtbar machen.
2. Breite Patterns absichern, ohne natuerliche Bedienung wieder kaputt zu
   machen.
3. Keywords in die Conflict-Pruefung aufnehmen.
4. Eine Candidate-Sicht einfuehren, bevor das Verhalten groesser veraendert
   wird.
5. Routing-Entscheidungen debug- und testbar machen.
6. Bestehende Handler schrittweise migrieren, nicht in einem grossen Umbau.

## Nicht-Ziele

- Kein LLM-basiertes Intent-Routing als Ersatz fuer direkte Commands.
- Keine neuen User-Features.
- Keine neuen Dependencies.
- Keine Umstellung aller Regex-Patterns auf eine externe Parsing-Library.
- Kein Entfernen des LLM-Fallbacks.
- Keine Umbenennung aller bestehenden Commands.
- Kein vollstaendiger NLP-Parser fuer deutsche Alltagssprache.

## Empfohlene Reihenfolge

Die Reihenfolge ist absichtlich konservativ: erst messen und testen, dann
klein refactoren, dann Verhalten aendern.

## E0 - Baseline, Corpus und Audit ohne Verhaltensaenderung ✅ implementiert

Ziel: Vor dem Umbau sichtbar machen, was heute matcht.

Dateien:

- `tests/test_plugin_pattern_conflicts.py` (bestehend)
- `tests/test_command_keyword_conflicts.py` (neu, implementiert)
- `tests/test_command_routing_corpus.py` (neu, implementiert)

Schritte:

1. Bestehenden `test_plugin_pattern_conflicts.py` erweitern:
   - aktuelle Sample-Liste strukturieren nach Konflikt-Cluster.
   - Recipe-, Route-, Note-, Contact- und Advanced-Samples ergaenzen.
   - Negative Samples aufnehmen, die bewusst `None` liefern muessen.
2. Keyword-Audit bauen:
   - alle geladenen Handler mit Full-Mock-`HandlerContext` instanziieren.
   - `handler.keywords` aggregieren.
   - gleiche Keyword-Strings ueber mehrere Commands melden.
   - sehr kurze Einwort-Keywords markieren.
   - Keywords mit Domain-Woertern (`mail`, `termin`, `notiz`, `route`,
     `rezept`, `kontakt`, `todo`) separat ausgeben.
3. Routing-Corpus anlegen:
   - jede Zeile: `text`, `expected_command`, `reason`, `source`.
   - `source` kann sein: `live_regression`, `known_conflict`,
     `negative_sample`, `smoke`.
4. Keine Produktionslogik aendern.

Akzeptanzkriterien:

- Bestehende Tests bleiben gruen.
- Neuer Keyword-Audit-Test ist deterministisch.
- Negative Samples wie `loesch alle`, `wie mache ich ein backup`,
  `was ist wetter`, `speichere es als notiz` sind explizit abgedeckt.

Beispiel-Corpus (Simulation-Ergebnisse, Stand 2026-05-29):

| Text | Erwartung | Label | Befund |
|---|---|---|---|
| `loesch alle` | `None` | negative | ✅ korrekt |
| `loesche alle termine` | `termin_delete` | smoke | ✅ korrekt |
| `loesche erinnerung 3` | `reminder_delete` | smoke | ✅ Weather/Reminder (prio=15) vor Calendar |
| `speichere es bitte als notiz ab` | `None` | negative | ✅ korrekt |
| `git status` | `git` | smoke | ✅ GitHandler routet alle Subcommands als "git" |
| `docker ps` | `docker` | smoke | ✅ DockerHandler routet alle Subcommands als "docker" |
| `termine woche` | `termine` | smoke | ✅ CalendarHandler liefert "termine", nicht "termin_list" |
| `wie mache ich carbonara` | `recipe_lookup` | smoke | ✅ korrekt |
| `was ist das wlan passwort` | `note_get_fact` | smoke | ✅ korrekt |
| `lauter` | `harmony_volume_up` | known_conflict | ✅ Harmony (Pattern) vor System (Keyword) |
| `wer ist max mustermann` | `contact_who` | known_conflict | ✅ Contact (Pattern) vor Note (Keyword) |
| `ich muss von zuhause zu nadine und dann zu lisa` | `multi_stop_route` | **xfail (F1)** | ⚠️ aktuell `route_from_to` – Handler fehlt im Registry |
| `plane route nach leipzig` | `multi_stop_route` | **xfail (F1)** | ⚠️ aktuell `route_plan` – Handler fehlt im Registry |
| `wie mache ich das` | `None` | **xfail (F2)** | ⚠️ aktuell `recipe_lookup` – HOW_TO zu breit |
| `wie mache ich ein backup` | `None` | **xfail (F2)** | ⚠️ aktuell `recipe_lookup` |
| `wie mache ich einen screenshot` | `None` | **xfail (F2)** | ⚠️ aktuell `recipe_lookup` |

## E1 - Deklarative Match-Metadaten vorbereiten ✅ implementiert

Ziel: Patterns und Keywords bekommen Metadaten, ohne alle Handler sofort
umzubauen.

Dateien:

- `src/elder_berry/comms/commands/base.py`
- `src/elder_berry/comms/remote_commands.py`
- Tests fuer Base-Dataclasses.

Neue Dataclasses:

```python
@dataclass(frozen=True)
class CommandMatchCandidate:
    command: str
    plugin_name: str
    handler_name: str
    source: Literal["simple", "pattern_match", "pattern_search", "keyword"]
    priority: int
    confidence: int
    matched_text: str
    pattern_name: str | None = None
    keyword: str | None = None
    use_original_text: bool = False


@dataclass(frozen=True)
class RoutedCommand:
    """Konkrete Routing-Entscheidung inklusive gewaehltem Handler.

    Wichtig: Der ausgewaehlte Handler muss bis zur Ausfuehrung erhalten
    bleiben. Nur den Command-String zurueckzugeben reicht fuer den
    Candidate-Router nicht mehr, weil `_command_handler_map[command]` bei
    gleichen Command-Namen, User-Plugins oder spaeteren Overrides einen
    anderen Handler liefern kann als `choose_candidate()` ausgewaehlt hat.
    """

    command: str
    plugin_name: str
    handler: CommandHandler
    candidate: CommandMatchCandidate
```

Optional spaeter:

```python
@dataclass(frozen=True)
class PatternSpec:
    pattern: re.Pattern[str]
    command: str
    use_original_text: bool = False
    use_search: bool = False
    name: str | None = None
    confidence: int = 70
    conflict_group: str | None = None
    broad: bool = False
```

Wichtig: `PatternSpec` nicht sofort erzwingen. Bestehende Tupel bleiben
zunaechst erlaubt. Ein Helper normalisiert beide Formen.

Kompatibilitaets-Helfer:

```python
def iter_pattern_specs(handler: CommandHandler) -> Iterator[PatternSpec]:
    for item in handler.patterns:
        if isinstance(item, PatternSpec):
            yield item
        else:
            pattern, command, use_original, use_search = item
            yield PatternSpec(
                pattern=pattern,
                command=command,
                use_original_text=use_original,
                use_search=use_search,
            )
```

Akzeptanzkriterien:

- Kein Handler muss in E1 migriert werden.
- `parse_command()` liefert weiterhin exakt gleiche Ergebnisse.
- Neue interne Methode kann alle Kandidaten sammeln, wird aber noch nicht als
  Entscheidungsquelle verwendet.

## E2 - Candidate-Sammlung einbauen, Entscheidung noch kompatibel halten ✅ implementiert

Ziel: Sichtbarkeit schaffen, ohne Verhalten zu veraendern.

Dateien:

- `src/elder_berry/comms/remote_commands.py`
- `tests/test_remote_commands.py`
- neue oder erweiterte Tests: `tests/test_command_match_candidates.py`

Neue interne Methoden:

```python
def collect_candidates(self, text: str) -> list[CommandMatchCandidate]:
    """Sammelt alle Simple-, Pattern- und Keyword-Kandidaten."""

def choose_candidate(
    self,
    candidates: list[CommandMatchCandidate],
) -> CommandMatchCandidate | None:
    """Waehlt zunaechst kompatibel zum alten First-Match-Wins."""

def route_command(self, text: str) -> RoutedCommand | None:
    """Liefert den gewaehlten Command inklusive Handler-Instanz."""
```

Kompatibilitaetsregel in E2:

- Simple-Commands bleiben vor Patterns.
- `pattern.match` bleibt vor `pattern.search`.
- Keywords bleiben letzte Stufe.
- Innerhalb einer Stufe bleibt Plugin-Priority und Handler-Reihenfolge wie
  heute.
- `parse_command(text) -> str | None` bleibt als Kompatibilitaets-Wrapper
  erhalten und gibt `route_command(text).command` zurueck.
- Neue interne Ausfuehrungspfade nutzen `RoutedCommand.handler` direkt und
  nicht erneut `_command_handler_map[command]`.

Wichtige Migrationsregel:

`handle_remote_command()` darf beim Candidate-Router nicht dauerhaft nur
einen Command-String transportieren. Sonst geht die ausgewaehlte Handler-
Instanz zwischen Routing und Execution verloren. Die saubere Zielstruktur ist:

```text
Bridge -> route_command(msg.body) -> RoutedCommand
       -> handle_routed_command(msg, routed)
       -> routed.handler.execute(routed.command, msg.body)
```

Der alte Pfad `handle_remote_command(msg, command: str)` kann fuer Tests und
Legacy-Aufrufer bleiben, muss aber als Wrapper verstanden werden. Fuer neue
Routing-Entscheidungen ist `RoutedCommand` die Quelle der Wahrheit.

Logging:

- Nur auf `DEBUG`.
- Keine User-Inhalte ungekuerzt loggen. Maximal 120 Zeichen und keine Secrets.
- Beispiel:

```text
Routing candidates: winner=multi_stop_route/multi_stop_route,
discarded=[route/route_from_to, route/route_plan], text_hash=...
```

Akzeptanzkriterien:

- Alle bestehenden Routing-Tests bleiben gruen.
- Neuer Test zeigt bei Konflikttexten mehr als einen Kandidaten.
- `parse_command()` bleibt externe Kompatibilitaets-API und gibt weiter
  `str | None` zurueck.
- Ein neuer Test beweist, dass der von `choose_candidate()` gewaehlte Handler
  bis `execute()` erhalten bleibt, auch wenn ein zweiter Handler denselben
  Command-Namen registriert.

## E3 - Conflict-Tests auf Candidate-Basis umstellen

Ziel: Tests pruefen das echte Routing-Modell statt nachgebauter Teil-Logik.

Dateien:

- `tests/test_plugin_pattern_conflicts.py`
- `tests/test_command_keyword_conflicts.py`
- `tests/test_command_routing_corpus.py`

Schritte:

1. Conflict-Test nutzt `collect_candidates()` statt eigener Pattern-Schleife.
2. Er prueft auch:
   - Simple-vs-Pattern-Konflikte.
   - Pattern-vs-Keyword-Konflikte.
   - Keyword-vs-Keyword-Konflikte.
3. Bekannte Konflikte muessen dokumentiert sein:
   - entweder in `CommandPlugin.conflicts`
   - oder in einer neuen lokalen Allowlist mit Begruendung.

Vorschlag fuer Allowlist-Form:

```python
EXPECTED_ROUTING_CONFLICTS = {
    "loesche erinnerung 3": {
        "winner": "reminder_delete",
        "losers": {"termin_delete"},
        "reason": "Reminder-Loeschen ist spezifischer als Kalender-Loeschen.",
    },
}
```

Regel: Eine Allowlist darf nicht nur sagen "ist halt so". Sie braucht
Gewinner, Verlierer und Begruendung.

Akzeptanzkriterien:

- Conflict-Tests decken alle Kandidatenquellen ab.
- Neue breite Patterns erzeugen ohne Dokumentation einen Testfehler.
- Testfehler sind so formuliert, dass man weiss:
  - welcher Text betroffen ist,
  - wer gewonnen hat,
  - wer ebenfalls gematcht haette,
  - welche Datei/Plugin-Priority relevant ist.

## E4 - Breite Handler gezielt absichern

Ziel: Die bekannten Risikocluster stabilisieren, bevor der Router
entscheidend intelligenter wird.

Reihenfolge innerhalb E4:

1. Recipe
2. Multi-Stop/Route
3. Note/Contact/Calendar
4. Mail/Reminder/Calendar Delete-Familie
5. Advanced Web Search / Computer Use

### E4.1 Recipe

Datei:

- `src/elder_berry/comms/commands/recipe_commands.py`
- `tests/test_recipe_command_handler.py`
- Routing-Corpus-Tests

Risiko:

- `HOW_TO_PATTERN = ^wie mache ich (.+)$` ist breit.
- Non-food-Anfragen koennen als Recipe landen.
- **Bestaetigt durch Simulation F2**: Sogar `"wie mache ich das"` (generisch,
  kein fachlicher Inhalt) matcht – jeder einsilbige Platzhalter reicht als
  Capture-Gruppe. Das ist breiter als im Konzept urspruenglich angenommen.

Empfohlene Absicherung:

- Stopp-Wortliste fuer inhaltsleere Capture-Gruppen:
  `["das", "es", "sowas", "das hier", "das ding"]`
- Alternativ: Mindest-Token-Qualitaet (Capture-Gruppe muss >= 1 Substantiv
  enthalten oder mindestens 2 Tokens haben).
- Bei unklarem `wie mache ich ...` lieber `fallthrough=True`.
- Negative Tests:
  - `wie mache ich ein backup`
  - `wie mache ich einen screenshot`
  - `wie mache ich einen termin`
  - `wie mache ich eine ueberweisung`
- Positive Tests:
  - `wie mache ich carbonara`
  - `wie mache ich gin basil smash`
  - `gib mir ein rezept fuer linsensuppe`

Keine Rueckkehr zu schwachen API-/Semantik-Treffern. Die Phase-93-Gates
bleiben massgeblich.

### E4.2 Multi-Stop vs. Route

Dateien:

- `src/elder_berry/comms/commands/multi_stop_route_commands.py`
- `src/elder_berry/comms/commands/route_commands.py`
- `src/elder_berry/comms/commands/registry.py`
- `tests/test_multi_stop_route_commands.py`
- `tests/test_route_commands.py`
- `tests/test_intent_routing.py`

Risiko:

- Beide Handler nutzen Search-Patterns.
- Multi-Stop muss vor Single-Route gewinnen, aber nur bei echtem
  Multi-Stop-Intent.
- **Kritischer Befund aus Simulation F1**: `MultiStopRouteCommandHandler`
  ist **nicht in `registry.py` eingetragen**. Der Handler ist vollstaendig
  implementiert, wird aber nie geladen. Multi-Stop-Routing faellt komplett
  auf `RouteCommandHandler` durch. Alle Multi-Stop-Tests sind aktuell als
  xfail markiert.

Pflicht-Schritt vor allen anderen E4.2-Massnahmen:

1. `MultiStopRouteCommandHandler` in `registry.py` eintragen.
2. `xfail`-Markierungen in `test_command_routing_corpus.py` entfernen.
3. Pruefen, ob die bestehende Priority-Reihenfolge (multi_stop=75, route=76)
   die Konflikte korrekt aufloest.

Empfohlene Absicherung:

- `_MULTI_STOP_PATTERN` bleibt ein breiter Vorfilter und bekommt zunaechst
  niedrige Confidence.
- `is_multi_stop_candidate()` bleibt das fachliche Gate.
- Wenn das Gate `True` liefert, wird der Kandidat zu einem starken
  `validated_multi_stop` hochgestuft. Seine Confidence muss dann hoeher sein
  als die Single-Route-Kandidaten, damit echte Multi-Stop-Saetze weiterhin
  vor `route_from_to` / `route_plan` gewinnen.
- Wenn das Gate `False` liefert, darf das nicht als normales
  `fallthrough=True` bis zum LLM laufen. Im Candidate-Router bedeutet das:
  Multi-Stop-Kandidat verwerfen und den naechsten passenden Kandidaten
  pruefen, typischerweise `route_plan` oder `route_from_to`.
- `fallthrough=True` bleibt nur fuer den alten Execute-Pfad relevant. In der
  neuen Router-Logik ist "Gate failed" eine Kandidaten-Invalidierung, kein
  sofortiger Sprung zu `handle_assistant_message()`.
- Candidate-Test fuer:
  - `ich muss von zuhause zu nadine und dann zu lisa`
  - `plane route nach leipzig`
  - `wie komme ich zu lisa`
  - `muss von zuhause zu nadine`
  - `muss von zuhause zu nadine und vorher tanken`

Beispiel-Confidence:

| Kandidat | Bedingung | Confidence |
|---|---|---:|
| `multi_stop_route` | Vorfilter matcht, Gate noch nicht bewertet | 40 |
| `multi_stop_route` | `is_multi_stop_candidate(text) == True` | 95 |
| `multi_stop_route` | Gate `False` | Kandidat verwerfen |
| `route_from_to` | Pattern matcht | 85 |
| `route_plan` | Pattern matcht | 80 |

### E4.3 Note, Contact und Calendar

Dateien:

- `src/elder_berry/comms/commands/note_commands.py`
- `src/elder_berry/comms/commands/contact_commands.py`
- `src/elder_berry/comms/commands/calendar_commands.py`
- zugehoerige Tests

Risiko:

- `was ist ...`, `wie lautet ...`, `wann ist ...`, `geburtstag ...` liegen
  semantisch nah beieinander.

Empfohlene Absicherung:

- Domain-Negativlisten nicht weiter ad hoc wachsen lassen, sondern zentral
  kommentieren:
  - `wetter`, `termin`, `mail`, `todo`, `kontakt`, `erinnerung`, `timer`,
    `route`, `rezept`
- Note-Faktabfrage bei Miss weiterhin `fallthrough=True`.
- Kontakt-Feldfragen nur mit klaren Feldmarkern:
  - Geburtstag, Adresse, Telefon, Mail-Adresse.
- Kalender-Delete nur mit explizitem Termin-Marker oder vorheriger Liste.

### E4.4 Delete-Familie

Dateien:

- `weather_commands.py` fuer Reminder/Timer.
- `calendar_commands.py`.
- `mail_commands.py`.
- `note_commands.py`.
- `todo_commands.py`.

Risiko:

- `loesche`, `entferne`, `storniere`, `vergiss` sind generisch.

Regel:

- Ein Delete-Pattern muss einen Domain-Marker haben:
  - `mail`, `termin`, `erinnerung`, `timer`, `notiz`, `todo`, `aufgabe`.
- Markerlose Deletes duerfen nicht im generischen Direct-Command-Router
  landen. Der Router bekommt im aktuellen Direct-Matrix-Pfad nur `msg.body`;
  er kennt ohne Zusatzkontext weder Sender noch `ConversationListStore`.
- Wenn eine Auswahl aus einer aktiven Liste geloescht werden soll, bleibt das
  im bestehenden `list_pick`-/ConversationList-Pfad. Dieser Pfad kennt
  `sender`, `list_type` und den konkreten Listeneintrag.
- Falls Phase 95 spaeter markerlose Listenkontext-Deletes direkt routen soll,
  braucht `route_command()` eine explizite `RoutingContext`-Struktur, z.B.
  `sender`, `room_id`, `conversation_list_store` und aktive `list_type`s.
  Ohne diesen Kontext darf der Router keine Ausnahme "aktiver Listenkontext"
  anwenden.
- `loesch alle` bleibt ungeroutet.

### E4.5 Advanced

Datei:

- `src/elder_berry/comms/commands/advanced_commands.py`

Risiko:

- `suche/finde/google ...` kann fachliche Suchen uebernehmen.
- `klick/tippe/drueck ...` kann echte Textfragen abfangen.

Regel:

- Web Search bleibt explizit, aber nicht als Fallback fuer beliebige Fragen.
- Computer Use bleibt nur fuer klare UI-Aktionsverben.
- `finde meine mail von max` darf nicht Web Search werden, wenn Mail-Suche
  plausibel ist.

## E5 - Schrittweise Confidence-Regeln aktivieren

Ziel: Candidate-Router darf erstmals anders entscheiden als First-Match-Wins,
aber nur fuer dokumentierte Konfliktgruppen.

Grundregel:

```text
exact/simple > anchored_pattern > domain_pattern > broad_pattern > keyword
```

Vorgeschlagene Confidence-Werte:

| Quelle | Default |
|---|---:|
| Simple exact | 100 |
| Anchored Pattern (`match`, klarer Domain-Marker) | 90 |
| Anchored Pattern ohne starken Domain-Marker | 75 |
| Search Pattern mit Domain-Gate | 70 |
| Broad Candidate Pattern | 50 |
| Keyword Phrase, >=2 Woerter | 45 |
| Keyword Einwort | 30 |

Tie-Breaker:

1. Hoehere Confidence.
2. Spezifischere Quelle.
3. Niedrigere Plugin-Priority.
4. Bisherige Handler-Reihenfolge.

Wichtig:

- Confidence ist kein ML-Score.
- Werte muessen deterministisch und lokal nachvollziehbar sein.
- Kein semantisches Raten im Router.

Akzeptanzkriterien:

- Verhaltensaenderungen nur fuer Tests, die explizit angepasst wurden.
- Jede geaenderte Routingentscheidung hat einen Corpus-Test.
- Debug-Log zeigt alte und neue Entscheidung bei Konflikten.

## E6 - PatternSpec-Migration pro Handler

Ziel: Kritische Handler bekommen explizite Pattern-Metadaten.

Empfohlene Reihenfolge:

1. `recipe_commands.py`
2. `multi_stop_route_commands.py`
3. `route_commands.py`
4. `note_commands.py`
5. `calendar_commands.py`
6. `mail_commands.py`
7. `weather_commands.py`
8. `advanced_commands.py`
9. Restliche Handler nur bei Bedarf.

Beispiel:

```python
@property
def patterns(self) -> list[PatternSpec]:
    return [
        PatternSpec(
            name="recipe_explicit",
            pattern=RECIPE_PATTERN,
            command="recipe_lookup",
            confidence=90,
            conflict_group="recipe",
        ),
        PatternSpec(
            name="recipe_how_to",
            pattern=HOW_TO_PATTERN,
            command="recipe_lookup",
            confidence=50,
            conflict_group="how_to",
            broad=True,
        ),
    ]
```

Akzeptanzkriterien:

- Kritische Handler sind migriert.
- Unkritische Handler koennen Tupel weiter nutzen.
- Kein Big-Bang-Refactor.

## Teststrategie

### Focused Tests

Nach E0/E1:

```powershell
.\.venv\Scripts\python -m pytest `
  tests/test_plugin_pattern_conflicts.py `
  tests/test_parse_command_keyword_heuristic.py `
  tests/test_pattern_routing_note_and_calendar.py `
  tests/test_pattern_stabilisierung.py `
  tests/test_intent_routing.py `
  tests/test_remote_commands.py -q
```

Nach Router-Aenderungen:

```powershell
.\.venv\Scripts\python -m pytest `
  tests/test_remote_commands.py `
  tests/test_plugin_pattern_conflicts.py `
  tests/test_command_keyword_conflicts.py `
  tests/test_command_routing_corpus.py `
  tests/test_intent_routing.py -q
```

Nach Handler-Gates:

```powershell
.\.venv\Scripts\python -m pytest `
  tests/test_recipe_command_handler.py `
  tests/test_multi_stop_route_commands.py `
  tests/test_route_commands.py `
  tests/test_note_commands.py `
  tests/test_contact_commands.py `
  tests/test_calendar_commands.py `
  tests/test_mail_commands.py `
  tests/test_weather_commands.py -q
```

Typecheck:

```powershell
.\.venv\Scripts\python -m mypy `
  src/elder_berry/core `
  src/elder_berry/tools `
  src/elder_berry/web `
  src/elder_berry/comms
```

Hinweis: In der Analyse lief der Focused-Slice mit
`.\.venv\Scripts\python -m pytest ... -q` gruen: 224 passed.

### Negative Tests sind Pflicht

Jedes neue breite Pattern braucht mindestens:

- 2 positive Beispiele.
- 2 negative Beispiele.
- 1 Konfliktbeispiel mit erwarteter Gewinnerentscheidung.

Beispiele:

| Handler | Positive | Negative |
|---|---|---|
| Recipe | `rezept carbonara`, `wie mache ich linsensuppe` | `wie mache ich backup`, `wie mache ich screenshot` |
| Route | `route nach leipzig`, `von zuhause zu lisa` | `was ist route 66`, `route im code anzeigen` |
| Note | `was ist wlan passwort`, `wie lautet mein pin` | `was ist wetter`, `was ist termin morgen` |
| Calendar | `loesche termin zahnarzt`, `termine morgen` | `loesch alle`, `was ist der terminus` |
| Advanced | `suche dachdecker plattenburg`, `klick auf ok` | `suche in mails max`, `finde kontakt lisa` |

## Runtime-Diagnostik

Minimaler erster Schritt:

- `RemoteCommandHandler` loggt bei `DEBUG` nur wenn mehr als ein Kandidat
  existiert.
- Text wird gekuerzt oder gehasht.
- Keine Mailinhalte, Notizinhalte, Tokens oder Dateipfade ungefiltert loggen.

Moegliches Format:

```text
command_routing candidates=3 winner=recipe/recipe_lookup
  candidate[0]=recipe/recipe_lookup source=pattern_match confidence=50
  candidate[1]=advanced/web_search source=keyword confidence=45
  candidate[2]=note/note_get_fact source=keyword confidence=30
  text_preview="wie mache ich ..."
```

Optional spaeter:

- Debug-Command `routing debug <text>` nur fuer lokale Entwicklung.
- Dashboard-Ansicht im Plugin-Inspector.

## Sicherheits- und Datenschutz-Hinweise

- Routing-Logs duerfen keine sensiblen Inhalte leaken.
- Keywords wie `passwort`, `pin`, `iban`, `token` muessen im Preview maskiert
  werden.
- Keine neuen Dependencies.
- Kein externer Service fuer Routing-Entscheidungen.
- LLM-Fallback bleibt bewusst getrennt; der Router soll nicht anfangen,
  freie Inhalte an Provider zu senden.

## Rollout-Plan

Empfohlene PR-Aufteilung:

| PR | Inhalt | Risiko |
|---|---|---|
| PR 1 | E0 Corpus + Keyword-Audit, keine Produktionslogik | niedrig |
| PR 2 | E1/E2 Candidate-Sammlung + kompatible Entscheidung | mittel |
| PR 3 | E3 Conflict-Tests auf Candidate-Basis | niedrig bis mittel |
| PR 4 | E4 Handler-Gates fuer Recipe/Route/Note/Delete-Familie | mittel |
| PR 5 | E5 Confidence-Regeln fuer dokumentierte Konfliktgruppen | hoch |
| PR 6 | E6 PatternSpec-Migration kritischer Handler | mittel |

Wenn Zeit knapp ist:

1. E0 und E3 liefern den groessten Sofortnutzen fuer CI.
2. E4.1 Recipe und E4.2 Route loesen die aktuell sichtbarsten Live-Risiken.
3. E5 kann warten, bis genug Corpus-Daten vorhanden sind.

## Definition of Done fuer Phase 95

- [x] Routing-Corpus existiert und enthaelt positive, negative und
      konfliktkritische Beispiele (`test_command_routing_corpus.py`).
- [x] Keyword-Konflikte werden in CI sichtbar (`test_command_keyword_conflicts.py`).
- [x] `collect_candidates()` existiert und ist getestet.
- [x] `parse_command()` bleibt kompatibel – Corpus dokumentiert alle
      Abweichungen als xfail.
- [ ] **F1 beheben**: `MultiStopRouteCommandHandler` in `registry.py` eintragen
      und xfail-Guards entfernen.
- [ ] **F2 eingrenzen**: HOW_TO_PATTERN-Stopp-Wortliste oder `fallthrough=True`
      fuer inhaltsleere Capture-Gruppen.
- [ ] Kritische breite Handler haben Domain-Gates oder explizites `fallthrough`.
- [ ] Runtime-Debugging fuer Mehrfachkandidaten existiert.
- [ ] Focused Routing-Tests sind gruen.
- [ ] mypy fuer `comms` bleibt gruen.
- [ ] Journal-Eintraege dokumentieren Start, wichtige Entscheidungen,
      Tests und offene Folgearbeit.

## Offene Entscheidungen

1. Soll `PatternSpec` direkt in `CommandHandler.patterns` typisiert werden,
   oder dauerhaft parallel zu Tupeln erlaubt bleiben?
2. Soll `CommandPlugin.conflicts` erweitert werden, z.B. zu
   `RoutingConflict` mit Gewinner/Verlierer/Grund?
3. Soll es einen lokalen Debug-Command `routing debug <text>` geben, oder
   reichen Logs und Tests?
4. Wie streng sollen Einwort-Keywords werden? Vorschlag: Einwort-Keywords
   nur noch fuer Simple-Commands oder mit Domain-Marker.
5. Soll `fallthrough=True` auch einen maschinenlesbaren Grund tragen, z.B.
   `fallthrough_reason="weak_recipe_intent"`?

## Bekannte technische Schulden

- `CommandPlugin.requires` existiert, wird aber fuer Sortier-/Konfliktlogik
  praktisch nicht genutzt.
- `conflicts` ist nur Plugin-Name, nicht command- oder pattern-genau.
- Handler-interne Pattern-Reihenfolge ist nicht maschinenlesbar.
- Keyword-Map wird global fuer Backwards-Compat aktualisiert.
- Einige Commands nutzen `pattern.search`, obwohl sie fachlich eher
  ankern sollten.
- Breite Domains verlassen sich auf nachgelagerte Execute-Gates statt auf
  klare Router-Konfidenz.
- **F1**: `MultiStopRouteCommandHandler` fehlt im Registry – stilles
  Fallthrough auf `RouteCommandHandler` seit Implementierung des Handlers.
- **F5**: `collect_candidates()` liefert Duplikat-Kandidaten wenn Pattern
  und Keyword denselben Command matchen (Stufen 2b + 3 ueberlappen).
  `choose_candidate()` behandelt das korrekt, aber das Rauschen ist
  unnoetig. Deduplizierung in E3 empfohlen.

## Manuelle Smoke-Tests

Nach E4/E5 live per Matrix testen:

```text
loesch alle
loesche alle termine
loesche erinnerung 3
speichere es bitte als notiz ab
was ist das wlan passwort
was ist das wetter morgen
gib mir ein rezept fuer carbonara
wie mache ich ein backup
ich muss von zuhause zu Nadine und dann zu Lisa
plane route nach Leipzig
suche in meinen mails nach Rechnung
suche Dachdecker Plattenburg
```

Erwartung: Unklare Saetze gehen lieber ans LLM als an den falschen Handler.
Das ist der zentrale Qualitaetsmassstab dieser Phase.
