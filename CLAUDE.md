# Elder-Berry – Claude Code Instructions

Sei bei deinen Antworten ehrlich, schöne nichts, sei kritisch und weise auf
Logiklücken und Fehler hin.

## KONTEXT
- Lies zu Beginn jedes Chats: `docs/journal.txt` (letzte 80 Zeilen, relativ vom
  Projekt-Root). Die Datei ist gitignored (siehe `.gitignore` – Phase 67) und
  wird nur lokal auf Tower/Laptop gepflegt.
- journal.txt ist die primäre Quelle für den aktuellen Stand
- Falls journal.txt fehlt (z.B. frischer Clone, Public-Fork, Codespace ohne
  lokale Pflege): nicht raten. Nutze stattdessen als Fallback in dieser
  Reihenfolge: `CHANGELOG.md` → `git log --oneline -30` → letzte gemergte
  PR-Beschreibungen. Der Stand ist dann zwangsläufig grobkörniger – sag das
  ehrlich, mach keine Annahmen.
- PROJECT_ROADMAP.md ist reine Planung – nur anfassen wenn Scope oder Phasen sich ändern
- docs/concepts/ enthält Konzeptdokumente – lies das relevante Konzept bevor du eine Phase startest
- Für Architektur, Hardware und Klassenübersicht siehe docs/architecture.md

## PLANUNG VOR AUSFÜHRUNG
- Nach dem Lesen von journal.txt: erstelle einen kurzen Plan was du tun wirst
- Warte auf explizite Bestätigung bevor du mit der Arbeit beginnst
- Bei Änderungen an Dateien: nenne vorher welche Dateien du ändern wirst
- Fang NIE an Code zu schreiben oder Dateien zu bearbeiten ohne Bestätigung

## DOKUMENTATION
- Schreibe BEVOR du anfängst einen Draft-Eintrag in journal.txt:
  "## In Arbeit: [Phase] – nächster Schritt: [Datei] / [Funktion/Aufgabe]"
- Ergänze den Eintrag nach Abschluss: "## Abgeschlossen: [Phase]"
- Bei längeren Phasen: nach jedem abgeschlossenen Teilschritt Zwischenstand sichern
- journal.txt ist das einzige Dokument das laufend gepflegt wird

## CODE-GENERIERUNG
- Neue Code-Dateien: Chunks von maximal 400 Zeilen
- Templates (HTML, Jinja2): nie inline – immer als separate Datei, in Chunks
- Bei langen Dateien: Zwischenstand in journal.txt sichern bevor der nächste Chunk beginnt
- Lies bestehende Dateien VOR dem Schreiben – immer, auch wenn du den Inhalt zu kennen glaubst
- Verwende relative Pfade vom Projekt-Root (`src/elder_berry/...`, `tests/...`).
  Vollqualifizierte Pfade nur wenn plattform-spezifisch nötig (z.B.
  `/home/pi/elder-berry/` für RPi5-Deploys).

## TESTS
- Runner: `.venv\Scripts\python.exe -m pytest` aus dem Projekt-Root
- Config: pyproject.toml ([tool.pytest.ini_options], asyncio_mode = "auto")
- Verzeichnis: tests/, flache Struktur (kein Unterordner-Nesting)
- Namenskonvention: test_{modulname}.py – eine Testdatei pro Klasse/Modul
- Neue Klasse = neuer Testfile, nicht in bestehende Tests reinquetschen
- Nach Code-Änderungen: betroffene Tests ausführen und Ergebnis berichten
- Mindestens: Happy Path + wichtigste Fehlerfälle + Edge Cases testen
- Mocks: unittest.mock bevorzugen, keine externen Mock-Libraries

## DEPENDENCIES
- Quelle: pyproject.toml (NICHT requirements.txt – die ist nur für pip freeze)
- Optionale Gruppen: windows, tts-neural, avatar, robot, agent, matrix, remote,
  memory, stt, tools, documents, computer-use
- REGEL: Keine neuen Dependencies ohne Rückfrage – begründe warum nötig
- Neue Dependency: in die passende optionale Gruppe eintragen, nie in [dependencies]
  außer sie wird von allen Plattformen (Tower, Laptop, RPi5) gebraucht

## ERROR HANDLING
- Logging: logging.getLogger(__name__) – kein print() für Fehler oder Warnungen
- Kein bare `except:` – immer spezifische Exceptions fangen
- Eigene Exceptions in der jeweiligen Modul-Datei definieren wenn sinnvoll
- Externe API-Aufrufe (Matrix, Ollama, FastAPI): immer mit Timeout + Retry-Logik
- Fehler loggen mit logger.error("Kontext: %s", detail) – nicht logger.error(f"...")

## REMOTE-COMMANDS (Matrix)
- Commands in domänenspezifische Handler aufgeteilt: src/elder_berry/comms/commands/
  - base.py: CommandHandler ABC + CommandResult DTO
  - system_commands.py, calendar_commands.py, mail_commands.py, file_commands.py,
    process_commands.py, weather_commands.py, advanced_commands.py
- remote_commands.py ist NUR der Orchestrator – KEINE Command-Logik dort
- Neuer Command: in passenden Handler einfügen oder neuen Handler erstellen
- Neuer Handler: CommandHandler ABC erben, patterns/keywords/execute() definieren,
  in RemoteCommandHandler._handlers Liste eintragen (Reihenfolge = Priorität!)
- Pattern-Tuple: (compiled_pattern, command_name, use_original_text, use_search)
  - use_original_text=True wenn Pfade erkannt werden (case-sensitiv)
  - use_search=True für pattern.search() statt pattern.match()
- Hilfe-Text: neue Commands müssen in die passende Sektion in
  src/elder_berry/comms/commands/help_sections.py (HELP_SECTIONS dict) –
  sonst weiß niemand, dass das Feature existiert. Neue Kategorie? Eintrag
  in CATEGORY_LABELS + HELP_SECTIONS (beide in derselben Datei).
- KEYWORD_MAP wird automatisch aus allen Handler.keywords aggregiert

## E-MAIL-HANDLING
- HTML-Mail-Bodies laufen IMMER durch `HtmlEmailSanitizer`
  (`src/elder_berry/tools/html_email_sanitizer.py`, Phase 85).
  Pfad: `IMAPEmailClient._decode_payload()` → bei `text/html`
  `self._sanitizer.sanitize(text)`. Kein zweiter Code-Pfad.
- Naive HTML-Tag-Strip-Regex (`re.sub(r"<[^>]+>", " ", ...)`) ist verboten –
  laesst Inhalte von `<script>/<style>/<noscript>` und Hidden-Text
  (`display:none`, weisse Schrift, Mini-Font) als Inject-Vektor durch.
  Konzept: `docs/concepts/phase-85-html-email-sanitizer.md`.
- Phase 86: CSS-Style-Decls werden ueber `css_decl_resolver`
  (`src/elder_berry/tools/css_decl_resolver.py`, tinycss2) spec-konform
  geparst. `_style_is_hidden` macht KEIN Regex-Pattern auf Style-Strings
  mehr; alle 5 Hidden-Properties (`opacity`, `font-size`, `display`,
  `visibility`, `color`) laufen ueber den Cascade-Resolver
  (`!important` > non-important, sonst last-wins). Konzept:
  `docs/concepts/phase-86-tinycss2-refactor.md`.
- Neue Property-Pruefer (z.B. `text-indent:-9999px`-Hidden-Detection)
  gehoeren als reine Funktion in `css_decl_resolver.py`, nicht in den
  Sanitizer. Kein Zurueck zur Style-String-Regex -- das war Phase 85.x
  und hat sich strukturell als bypass-anfaellig erwiesen (5 Codex-
  Findings in 4 PR-Iterations).
- Phase 87.B: `color:white`-Hidden-Check ist KONTEXTABHAENGIG. Der
  Sanitizer-Walker `_compute_effective_background_rgb` traversiert
  `[tag, *tag.parents]`, sammelt das naechste `background-color`/
  `bgcolor` und entscheidet ueber WCAG-Relative-Luminanz (< 0.179 =
  dunkel), ob `color:white` als hidden oder visible einzustufen ist.
  Default ohne erkennbaren bg im Walker-Pfad = weiss = hidden
  (Status-Quo, schuetzt vor Spam-Bypass). Konzept:
  `docs/concepts/phase-87-b-computed-background-heuristik.md`.
- Phase 87.B-3: Hidden-Strip ist UNWRAP-FAEHIG fuer color-hidden
  Tags. `_strip_hidden_color_tag` extrahiert visible Dark-bg-Islands
  (Tags mit eigenem dunklen bg) per `.extract()` an die Eltern-Ebene,
  bevor der color-hidden Eltern via `decompose()` faellt. Reine
  Text-Nodes ohne Island-Wrapper fallen mit (Anti-Spam-Bypass).
  Hard-Hidden (opacity:0, display:none, visibility:hidden, font-size
  unter Schwelle) bleibt bei direktem `decompose()` ohne Unwrap --
  das ist semantisch korrekt, weil der Mail-Client diese Pfade gar
  nicht rendert. Neue Island-Quellen (z.B. CSS-Background-Image,
  `background:` Shorthand) gehoeren in `_tag_own_background_rgb`,
  nicht in den Walker.
- `MAX_BODY_CHARS` in `email_client.py` ist universeller Sicherheits-Cap
  (Plain + HTML); Source of Truth fuer HTML ist `HtmlEmailSanitizer.max_chars`
  (Default 8000 + 20-Zeichen Cap-Marker). Aenderung an einer Stelle erzwingt
  Abgleich mit der anderen.

## ARCHITEKTUR (Prinzipien)
- OOP: jede Komponente als eigene Klasse, eine Klasse pro Datei (snake_case)
- Klassen kommunizieren über definierte Interfaces, nicht direkt
- Dependency Injection: Abhängigkeiten explizit über Konstruktor übergeben
- Neue Komponenten immer als eigene Klasse, nie als Funktion in bestehende Datei kippen
- 3-Tier: Tower (Hirn) / Laptop (Client) / RPi5 (Display+Sensoren)
- Details zu Klassen, Hardware und Charakter: docs/architecture.md

## UMGEBUNG
- Tower + Laptop (Windows): C:\Dev\Elder-Berry\.venv, Python 3.12
- RPi 5 (Linux): /home/pi/elder-berry/, Python 3.13 (System-Python Bookworm)
- Verwende pathlib statt hartcodierte Slashes wo plattformübergreifend
- Weise aktiv darauf hin wenn Code plattformspezifisch ist
- Falls .venv nicht vorhanden: erstelle es mit py -3.12 -m venv .venv

## GITHUB
- Erstelle zu Beginn jeder Phase einen neuen Branch: feature/phase-X-Y-kurzbeschreibung
- Committe am Ende jeder Phase alle Änderungen
- Keinen Pull-Request erstellen – das macht der Nutzer selbst
- Branch-Namen immer lowercase, Leerzeichen durch Bindestriche

## SESSIONS & CHAT-MANAGEMENT
- Jede neue Phase = neuer Chat / neue Session
- Sessions benennen mit /rename (z.B. "phase-28-email-reply")
- /plan nutzen für Architektur-Fragen bevor Code geschrieben wird
- /resume statt Kontext manuell neu aufbauen
- Wenn Antworten unzuverlässiger werden: aktiv melden, nicht abwarten

## QUALITÄT
- Weise aktiv auf fehlende Tests, Sicherheitslücken oder technische Schulden hin
- Wenn etwas unklar ist: frag nach, statt Annahmen zu machen
