# Elder-Berry Agent Instructions

Sei ehrlich, beschönige nichts, sei kritisch und weise aktiv auf
Logiklücken, Sicherheitsrisiken, fehlende Tests und technische Schulden hin.
Wenn etwas unklar ist, frage nach statt Annahmen als Fakten zu behandeln.

Diese Datei ist die allgemeine Arbeitsanweisung für LLM-gestützte Coding-
Agents in diesem Repository. Tool-spezifische Dateien wie `CLAUDE.md` sollen
auf diese Datei verweisen, statt ein zweites Regelwerk zu pflegen.

## Projektgedächtnis

Projekt: elder-berry

Aktives Projektgedächtnis ist das Bramble-MCP-Journal
(<https://journal.last-strawberry.com/mcp/>, projektgebundenes Token).

Zu Beginn jeder Session:

1. `journal_guide()` aufrufen und befolgen — die kanonischen, geteilten
   Journal-Konventionen (Status, Tags, Korrektur-/`resolves`-Modell,
   Open-Item-Semantik, Session-Start/Ende, DoD). Diese Regeln hier NICHT
   wiederholen.
2. `journal_context(project="elder-berry", n_recent=10)` lesen
   (Fallback: `journal_read(project="elder-berry", n=20)`).

Dieses Dokument ergänzt den Guide nur um Projekt-Spezifika (Tech-Stack,
Test-Runner, Build/Run, Repo-Layout, Branch-Konventionen).

### Elder-Berry-spezifische Ergänzungen zum Session-Start

- Lies zusätzlich relevante lokale Dokumente, wenn sie zum Arbeitsumfang
  gehören:
  - `PROJECT_ROADMAP.md` nur für Planungs-/Scope-Fragen.
  - `docs/concepts/...` vor Beginn einer Phase oder Änderung am betreffenden
    Konzeptbereich.
  - `docs/architecture.md` für Architektur, Hardware und Klassenübersicht.
- Wenn die Bramble-MCP-Tools nicht verfügbar sind, sage das ausdrücklich.
  Nutze dann nur als groben Fallback: `CHANGELOG.md` -> `git log --oneline -30`
  -> letzte gemergte PR-Beschreibungen. Markiere den Stand dann als
  grobkörnig und rate nicht.

## Planung Vor Ausführung

- Nach dem Lesen des Projektgedächtnisses erstelle einen kurzen Plan.
- Warte auf explizite Bestätigung, bevor du mit einer neuen Phase oder
  größeren Code-Änderung beginnst.
- Bei Dateiänderungen: nenne vorher die Dateien, die du ändern wirst.
- Lies bestehende Dateien vor dem Schreiben, auch wenn du ihren Inhalt zu
  kennen glaubst.
- Wenn der Nutzer ausdrücklich direkte Umsetzung verlangt, arbeite trotzdem
  kontrolliert: Kontext lesen, betroffene Dateien nennen, dann umsetzen.

## Code-Generierung

- Neue Code-Dateien: maximal ca. 400 Zeilen pro Datei-Chunk.
- Templates (HTML, Jinja2): nie inline in Python erzeugen, sondern als separate
  Template-Dateien.
- Verwende relative Pfade vom Projekt-Root, z. B. `src/elder_berry/...` und
  `tests/...`.
- Vollqualifizierte Pfade nur verwenden, wenn es plattformspezifisch nötig ist,
  z. B. `/home/pi/elder-berry/` für RPi5-Deploys.
- Halte Änderungen eng am bestehenden Stil und an vorhandenen Abstraktionen.

## Tests

- Runner unter Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

- Ausführen aus dem Projekt-Root.
- Pytest-Konfiguration: `pyproject.toml`, `[tool.pytest.ini_options]`,
  `asyncio_mode = "auto"`.
- Tests liegen flach in `tests/`.
- Namenskonvention: `test_{modulname}.py`.
- Neue Klasse oder neues Modul: eigener Testfile, nicht in bestehende Tests
  hineinquetschen.
- Nach Code-Änderungen: betroffene Tests ausführen und Ergebnis berichten.
- Mindestens testen: Happy Path, wichtigste Fehlerfälle und relevante Edge
  Cases.
- Mocks: `unittest.mock` bevorzugen, keine externen Mock-Libraries ohne
  Rückfrage.

## Dependencies

- Source of Truth: `pyproject.toml`.
- `requirements.txt` ist nur für Freeze-/Export-Zwecke.
- Optionale Gruppen: `windows`, `tts-neural`, `avatar`, `robot`, `agent`,
  `matrix`, `remote`, `memory`, `stt`, `tools`, `documents`, `computer-use`.
- Keine neuen Dependencies ohne Rückfrage. Begründe, warum sie nötig sind.
- Neue Dependencies in die passende optionale Gruppe eintragen.
- Nur in `[dependencies]` eintragen, wenn die Dependency auf Tower, Laptop und
  RPi5 gleichermaßen gebraucht wird.

## Error Handling

- Logging: `logging.getLogger(__name__)`.
- Kein `print()` für Fehler oder Warnungen.
- Kein bare `except:`. Fange spezifische Exceptions.
- Eigene Exceptions in der jeweiligen Modul-Datei definieren, wenn sinnvoll.
- Externe API-Aufrufe (Matrix, Ollama, FastAPI): Timeout und Retry-/Fehlerlogik
  einplanen.
- Fehler mit Format-Argumenten loggen, z. B.
  `logger.error("Kontext: %s", detail)`, nicht mit f-Strings im Log-Call.

## Remote-Commands (Matrix)

- Commands sind in domänenspezifische Handler aufgeteilt:
  `src/elder_berry/comms/commands/`.
- Wichtige Dateien:
  - `base.py`: `CommandHandler` ABC + `CommandResult` DTO.
  - `system_commands.py`, `calendar_commands.py`, `mail_commands.py`,
    `file_commands.py`, `process_commands.py`, `weather_commands.py`,
    `advanced_commands.py`.
- `remote_commands.py` ist nur der Orchestrator. Keine Command-Logik dort
  einbauen.
- Neuer Command: in passenden Handler einfügen oder neuen Handler erstellen.
- Neuer Handler:
  - Von `CommandHandler` erben.
  - `patterns`, `keywords` und `execute()` definieren.
  - In `RemoteCommandHandler._handlers` eintragen.
  - Reihenfolge in `_handlers` ist Priorität.
- Pattern-Tuple:
  `(compiled_pattern, command_name, use_original_text, use_search)`.
  - `use_original_text=True`, wenn Pfade erkannt werden und Case-Sensitivität
    wichtig ist.
  - `use_search=True` für `pattern.search()` statt `pattern.match()`.
- Hilfe-Text:
  - Neue Commands in `src/elder_berry/comms/commands/help_sections.py` in die
    passende Sektion von `HELP_SECTIONS` eintragen.
  - Neue Kategorie: Eintrag in `CATEGORY_LABELS` und `HELP_SECTIONS`.
- `KEYWORD_MAP` wird automatisch aus allen `Handler.keywords` aggregiert.

## E-Mail-Handling

- HTML-Mail-Bodies laufen immer durch `HtmlEmailSanitizer`
  (`src/elder_berry/tools/html_email_sanitizer.py`, Phase 85).
- Pfad: `IMAPEmailClient._decode_payload()` -> bei `text/html`
  `self._sanitizer.sanitize(text)`. Kein zweiter Code-Pfad.
- Naive HTML-Tag-Strip-Regex (`re.sub(r"<[^>]+>", " ", ...)`) ist verboten.
  Sie lässt Inhalte von `<script>`, `<style>`, `<noscript>` und Hidden-Text
  als Inject-Vektor durch.
- Konzept: `docs/concepts/phase-85-html-email-sanitizer.md`.
- Phase 86:
  - CSS-Style-Decls laufen über `css_decl_resolver`
    (`src/elder_berry/tools/css_decl_resolver.py`, tinycss2).
  - `_style_is_hidden` macht kein Regex-Pattern auf Style-Strings.
  - Hidden-Properties (`opacity`, `font-size`, `display`, `visibility`,
    `color`) laufen über den Cascade-Resolver.
  - Cascade-Regel: `!important` > non-important, sonst last-wins.
  - Konzept: `docs/concepts/phase-86-tinycss2-refactor.md`.
- Neue Property-Prüfer, z. B. `text-indent:-9999px`, gehören als reine
  Funktion in `css_decl_resolver.py`, nicht in den Sanitizer.
- Kein Zurück zur Style-String-Regex; diese war strukturell bypass-anfällig.
- Phase 87.B:
  - `color:white`-Hidden-Check ist kontextabhängig.
  - Der Sanitizer-Walker `_compute_effective_background_rgb` traversiert
    `[tag, *tag.parents]`, sammelt das nächste `background-color`/`bgcolor`
    und entscheidet per WCAG-Relative-Luminanz (< 0.179 = dunkel), ob
    `color:white` hidden oder sichtbar ist.
  - Default ohne erkennbaren Background im Walker-Pfad: weiß = hidden.
  - Konzept: `docs/concepts/phase-87-b-computed-background-heuristik.md`.
- Phase 87.B-3:
  - Hidden-Strip ist unwrap-fähig für color-hidden Tags.
  - `_strip_hidden_color_tag` extrahiert sichtbare Dark-bg-Islands per
    `.extract()` an die Eltern-Ebene, bevor der color-hidden Parent via
    `decompose()` fällt.
  - Hard-Hidden (`opacity:0`, `display:none`, `visibility:hidden`, sehr kleine
    `font-size`) bleibt bei direktem `decompose()`.
  - Neue Island-Quellen, z. B. CSS-Background-Image oder `background:`
    Shorthand, gehören in `_tag_own_background_rgb`.
- `MAX_BODY_CHARS` in `email_client.py` ist universeller Sicherheits-Cap
  für Plain + HTML.
- Source of Truth für HTML ist `HtmlEmailSanitizer.max_chars` (Default 8000
  plus 20-Zeichen Cap-Marker). Änderungen an einer Stelle erzwingen Abgleich
  mit der anderen.

## Architekturprinzipien

- OOP: jede Komponente als eigene Klasse, eine Klasse pro Datei
  (`snake_case`).
- Klassen kommunizieren über definierte Interfaces, nicht direkt über fremde
  Interna.
- Dependency Injection: Abhängigkeiten explizit über Konstruktor übergeben.
- Neue Komponenten als eigene Klasse modellieren, nicht als große Funktion in
  bestehende Dateien kippen.
- 3-Tier-Kontext:
  - Tower: Hirn/Server.
  - Laptop: Client/Entwicklung.
  - RPi5: Display/Sensoren.
- Details: `docs/architecture.md`.

## Umgebung

- Tower + Laptop (Windows): `C:\Dev\Elder-Berry\.venv`, Python 3.12.
- RPi 5 (Linux): `/home/pi/elder-berry/`, Python 3.13
  (System-Python Bookworm).
- Verwende `pathlib` statt hartcodierter Slashes, wenn Code
  plattformübergreifend ist.
- Weise aktiv darauf hin, wenn Code plattformspezifisch ist.
- Falls `.venv` fehlt: mit `py -3.12 -m venv .venv` erstellen.

## GitHub

- Zu Beginn jeder Phase einen neuen Branch erstellen:
  `feature/phase-X-Y-kurzbeschreibung`.
- Branch-Namen lowercase, Leerzeichen durch Bindestriche.
- Am Ende jeder Phase alle Änderungen committen.
- Keinen Pull Request erstellen; das macht der Nutzer selbst.
- Vor Commit: relevante Tests ausführen und Ergebnis im Abschluss nennen.

## Sessions Und Chat-Management

- Jede neue Phase soll nach Möglichkeit eine neue Session bekommen.
- Wenn der Client Session-Namen unterstützt, sprechende Namen nutzen, z. B.
  `phase-92-multi-stop-routing`.
- Für Architekturfragen vor Code-Umsetzung zuerst planen.
- Wenn Antworten unzuverlässiger werden oder Kontext fehlt: aktiv melden.

## Qualität

- Melde fehlende Tests, Sicherheitslücken, Logiklücken und technische Schulden
  aktiv.
- Wenn du eine riskante Abkürzung vorschlägst, benenne den Preis dafür.
- Lieber klein, nachvollziehbar und testbar arbeiten als große, unklare
  Umbauten starten.
