# Elder-Berry – Klassen-Analyse

Analyse der drei Kernklassen MatrixBridge, Assistant und RemoteCommandHandler.
Erstellt am 27.03.2026.

Referenzen: `docs/architecture.md` (Gesamtarchitektur), `CLAUDE.md` (Konventionen).

---

## 1. MatrixBridge

**Datei:** `src/elder_berry/comms/bridge.py` (1210 Zeilen)

### Zweck

Async-Bridge zwischen dem async MessageChannel (matrix-nio) und dem synchronen Assistant.
Löst das Async/Sync-Problem mit einem dedizierten Thread für den Event-Loop und `run_in_executor`
für blockierende Assistant-Aufrufe. Zusätzlich: Message-Router (Commands → Claude Agent → LLM),
Audio-Pipeline (WAV → OGG/Opus → Matrix), Chat-History und Scheduler-Verwaltung.

### Öffentliche API

| Methode / Property | Signatur | Beschreibung |
|---|---|---|
| `start()` | `() -> None` | Startet die Bridge in einem Hintergrund-Thread (nicht-blockierend) |
| `stop()` | `() -> None` | Stoppt Bridge, AlertMonitor, Scheduler und wartet auf Thread-Ende |
| `is_running` | `@property -> bool` | True wenn die Bridge aktiv ist |
| `send_restart_notification()` | `@staticmethod async (channel: MessageChannel) -> None` | Prüft Restart-Flag und sendet Begrüßung nach Neustart |

Modul-Level-Funktion:

| Funktion | Signatur | Beschreibung |
|---|---|---|| `extract_claude_message()` | `(text: str) -> str \| None` | Prüft ob Nachricht an ClaudeAgent gerichtet ist ("claude" + Anführungszeichen) |

### Dependencies

Direkt importiert:
- `ChatHistory`, `Summarizer` (comms.chat_history)
- `IncomingMessage`, `MessageChannel` (comms.message_channel)
- `asyncio`, `threading`, `tempfile`, `subprocess`, `re`, `os`, `sys`, `time`, `logging`

Per TYPE_CHECKING (DI via Konstruktor):
- `AlertMonitor`, `AudioConverter`, `CalendarWatcher`, `ClaudeAgent`
- `BriefingScheduler`, `ReminderScheduler`, `RemoteCommandHandler`
- `Assistant`, `AudioRouter`, `TaskChainRunner`
- `STTEngine`, `DocumentReader`

### Kontrollfluss

Ein typischer Request durchläuft:

1. `_async_main()` registriert `_handle_message` als Callback auf dem Channel
2. Nachricht kommt rein → `_handle_message(msg)`
3. Prüfung: alte Nachricht? → ignorieren. Unbekannter Sender? → ignorieren.
4. Audio-Nachricht? → `_handle_audio_message` (STT → Text → zurück zu Schritt 2)
5. Datei-Nachricht? → `_handle_file_message` (DocumentReader → LLM-Zusammenfassung)
6. Remote-Command? → `_handle_remote_command` (RemoteCommandHandler.parse_command/execute)
7. "claude" + "..."? → `_handle_claude_agent` (ClaudeAgent.process)
8. Sonst: → `_handle_assistant_message` (Assistant.process + Chat-History + Audio)9. LLM antwortet mit `remote_command` Aktion → `_handle_llm_remote_command` (Parse + Execute + ggf. Retry)
10. LLM antwortet mit `multi_step` → `_handle_multi_step` (TaskChainRunner)

### Threading/Async

- **Eigener Thread** (`matrix-bridge`, daemon): Erstellt eigenen `asyncio.EventLoop` in `_run_loop()`
- **`run_in_executor(None, ...)`** für alle blockierenden Calls: `Assistant.process()`, `RemoteCommandHandler.execute()`, `ClaudeAgent.process()`, `STTEngine.transcribe()`
- **Thread-safe Callbacks** für AlertMonitor, ReminderScheduler, BriefingScheduler, CalendarWatcher: nutzen `asyncio.run_coroutine_threadsafe()` um in den Bridge-Loop zu dispatchen
- **Race Condition – `_running` Flag**: Wird von main-Thread (stop) und bridge-Thread (run_loop finally) geschrieben. Kein Lock, aber unkritisch (bool-Assignment ist in CPython atomar).
- **Race Condition – `_loop`**: Wird in `_run_loop()` gesetzt und in `stop()` gelesen. Zeitfenster zwischen Thread-Start und Loop-Zuweisung, in dem `stop()` `_loop=None` sieht.

---

## 2. Assistant

**Datei:** `src/elder_berry/core/assistant.py` (576 Zeilen)

### Zweck

Zentraler Orchestrator: Nimmt User-Input entgegen, befragt das LLM, führt Aktionen aus (PC-Steuerung, Robot),
generiert TTS-Audio, aktualisiert den Avatar und speichert die Konversation im Memory.

### Öffentliche API

| Methode | Signatur | Beschreibung |
|---|---|---|
| `process()` | `(user_input: str, audio_output: Path \| None = None, chat_history: str = "") -> AssistantResult` | Hauptmethode: Input → LLM → Aktion → TTS → Avatar → Result |
| `new_session()` | `() -> None` | Startet neue Konversations-Session (setzt Session-ID zurück) |
Datenklasse:

| Klasse | Felder | Beschreibung |
|---|---|---|
| `AssistantResult` | `response`, `action_executed`, `action_success`, `emotion`, `audio_path`, `action_params` | Ergebnis einer `process()`-Anfrage |

### Dependencies

Direkt importiert:
- `ActionController` (actions.base)
- `ActionsDB` (actions.db)
- `LLMClient` (llm.base)
- `TTSEngine` (tts.base)
- `json`, `tempfile`, `logging`, `datetime`, `pathlib`

Per TYPE_CHECKING (DI via Konstruktor):
- `AgentClient`, `AvatarRenderer`, `CharacterEngine`
- `RemoteCommandHandler`, `MemoryStore`, `RobotClient`, `SystemMonitor`

### Kontrollfluss

1. `process(user_input)` → leere Eingabe abfangen
2. `_get_memory_context()` → RAG-Kontext aus MemoryStore
3. `_build_system_prompt()` → System-Prompt zusammenbauen (CharacterEngine oder Fallback-Template)
4. `_llm.generate()` → LLM-Antwort
5. `_parse_llm_response()` → JSON parsen (3 Fallback-Stufen)
6. Emotion extrahieren (CharacterEngine), Avatar aktualisieren (lokal + Robot)7. Aktion ausführen: `remote_command`/`multi_step` → pass-through; `system_status` → SystemMonitor; sonst → `_execute_action()` (Agent oder lokal)
8. TTS: `audio_output` gesetzt → Datei generieren; sonst → direkt abspielen (Agent oder lokal)
9. Memory speichern (`_save_to_memory`)
10. `AssistantResult` zurückgeben

### Threading/Async

- **Vollständig synchron**: Alle Methoden sind blocking. Wird von der Bridge via `run_in_executor` in einem Thread-Pool aufgerufen.
- **Kein eigener Threading-Code**: Keine Threads, keine Locks.
- **Potenzielle Blockierung**: `_llm.generate()` und `_tts.speak()` können lange dauern (Sekunden). Da pro Request ein Executor-Thread belegt wird, kann bei vielen gleichzeitigen Nachrichten der Default-ThreadPool erschöpft werden.

---

## 3. RemoteCommandHandler

**Datei:** `src/elder_berry/comms/remote_commands.py` (~425 Zeilen inkl. HELP_TEXT)

### Zweck

Orchestrator für direkte Befehle via Matrix. Parst Nachrichten in drei Stufen
(Simple-Match → Pattern-Match → Keyword-Suche) und delegiert die Ausführung
an domänenspezifische CommandHandler-Subklassen. Kein LLM nötig.

### Öffentliche API

| Methode | Signatur | Beschreibung |
|---|---|---|
| `parse_command()` | `(text: str) -> str \| None` | Prüft ob Text ein Command ist (3-stufig: exakt → Pattern → Keywords) |
| `execute()` | `(command: str, raw_text: str) -> CommandResult` | Führt erkannten Command aus, delegiert an den zuständigen Handler |
| `get_command_summary()` | `() -> str` | Kompakte Übersicht aller Commands für den System-Prompt |
Modul-Level:

| Name | Typ | Beschreibung |
|---|---|---|
| `HELP_TEXT` | `str` | Vollständiger Hilfe-Text aller Commands (~150 Zeilen) |
| `KEYWORD_MAP` | `dict[str, list[str]]` | Aggregierte Keywords aller Handler (global, wird in `__init__` befüllt) |
| `_build_keyword_map()` | `(handlers) -> dict` | Baut KEYWORD_MAP aus Handler-Keywords |

### Dependencies

Direkt importiert:
- `CommandHandler`, `CommandResult` (comms.commands.base)
- `SystemCommandHandler`, `CalendarCommandHandler`, `MailCommandHandler`
- `FileCommandHandler`, `ProcessCommandHandler`, `WeatherCommandHandler`
- `AdvancedCommandHandler`, `CameraCommandHandler`, `TurntableCommandHandler`
- `NoteCommandHandler`
- `logging`, `pathlib`

Per TYPE_CHECKING (alle optional, DI via Konstruktor):
- `ActionController`, `ComputerUseController`, `AvatarRenderer`
- `AudioRouter`, `SecretStore`, `AnthropicClient`, `RobotClient`
- `SystemMonitor`, `BraveSearchClient`, `DocumentReader`
- `IMAPEmailClient`, `GoogleCalendarClient`, `GymDataClient`
- `WeatherClient`, `BriefingScheduler`, `NoteStore`, `ReminderStore`

### Kontrollfluss

**parse_command(text):**
1. Normalisierung (strip + lower)
2. Stufe 1: "hilfe"/"help" → return3. Stufe 2: Exakter Match gegen `_simple_commands` Set
4. Stufe 3: Pattern-Match über alle Handler (Reihenfolge = Priorität)
5. Stufe 4: Keyword-Suche über alle Handler
6. Kein Match → `None`

**execute(command, raw_text):**
1. "hilfe"/"help" → HELP_TEXT zurückgeben
2. Handler-Lookup in `_command_handler_map`
3. `handler.execute(command, raw_text)` → `CommandResult`

### Threading/Async

- **Vollständig synchron**: Wird von der Bridge via `run_in_executor` aufgerufen.
- **Globaler Seiteneffekt in `__init__`**: Modifiziert die globale `KEYWORD_MAP` Variable. Bei mehreren Instanzen überschreibt die letzte die Map.
- **Kein Thread-Safety-Problem**: Nur eine Instanz wird erstellt, `parse_command` und `execute` sind read-only auf den internen Strukturen (mit Ausnahme der `_command_handler_map`-Mutation in `parse_command`, siehe Schwachstellen).

---

## Schwachstellen-Analyse (priorisiert)

### Hoch

| # | Klasse | Schwachstelle | Detail | Empfehlung |
|---|---|---|---|---|
| H1 | MatrixBridge | **Massiver Verstoß gegen 400-Zeilen-Limit** | 1210 Zeilen – 3× über dem Limit aus CLAUDE.md | Aufteilen in: `MatrixBridge` (Start/Stop/Loop), `MessageRouter` (Routing-Logik), `AudioPipeline` (Audio-Handling), `SchedulerManager` (Scheduler-Start/Stop) |
| H2 | MatrixBridge | **Kapselungsverletzung: direkte Zuweisung auf private Attribute** | `self._alert_monitor._send_alert = send_alert` und analog für `_reminder_scheduler`, `_briefing_scheduler`, `_calendar_watcher` | Callback über öffentliche Methode oder Konstruktor-Parameter übergeben |
| H3 | MatrixBridge | **Kapselungsverletzung: Zugriff auf Assistant-Interna** | `_play_audio_local` greift auf `self._assistant._agent` zu via `getattr` | AgentClient als eigene Dependency in MatrixBridge injizieren oder AudioRouter erweitern |
| H4 | MatrixBridge | **Kein Timeout für `run_in_executor`-Calls** | LLM- oder TTS-Calls können unbegrenzt blockieren; der Bridge-Thread wartet endlos | `asyncio.wait_for()` mit sinnvollem Timeout (z.B. 120s für LLM, 60s für TTS) |
| H5 | Assistant | **Verstoß gegen 400-Zeilen-Limit** | 576 Zeilen – 44% über dem Limit | `SYSTEM_PROMPT_TEMPLATE` (~60 Zeilen) in eigene Datei auslagern; Robot-Methoden in eigene Klasse `RobotProxy` extrahieren |
### Mittel

| # | Klasse | Schwachstelle | Detail | Empfehlung |
|---|---|---|---|---|
| M1 | MatrixBridge | **Code-Duplikation: Scheduler-Start-Methoden** | `_start_alert_monitor`, `_start_reminder_scheduler`, `_start_briefing_scheduler`, `_start_calendar_watcher` sind nahezu identisch | Generische `_start_scheduler(scheduler, attr_name, prefix)` Methode |
| M2 | MatrixBridge | **Code-Duplikation: Handler-Methoden** | `_handle_document_summary` und `_handle_mail_summary` folgen exakt demselben Muster | Gemeinsame `_handle_llm_enrichment(msg, result, prompt_template)` extrahieren |
| M3 | MatrixBridge | **Code-Duplikation: Error-Handling in Handlern** | Jeder `_handle_*`-Handler hat identisches try/except mit send_text-Fallback | Decorator oder Wrapper-Methode für einheitliches Error-Handling |
| M4 | RemoteCommandHandler | **Mutable State in parse_command()** | `self._command_handler_map[command] = handler` wird während des Pattern-Match geschrieben – eine Query-Methode mutiert State | Handler-Mapping vollständig in `__init__` aufbauen (Patterns sind statisch) |
| M5 | RemoteCommandHandler | **HELP_TEXT manuell gepflegt** | ~150 Zeilen müssen bei jedem neuen Command manuell nachgetragen werden | HELP_TEXT automatisch aus `handler.command_descriptions` generieren (analog zu `get_command_summary`) |
| M6 | RemoteCommandHandler | **Globaler Seiteneffekt in `__init__`** | `KEYWORD_MAP.clear()` + `KEYWORD_MAP.update()` modifiziert globale Variable | KEYWORD_MAP als Instanz-Attribut statt global; oder als `@property` berechnen |
| M7 | Assistant | **`_is_agent_online` ohne Cache** | Kommentar sagt "cached pro Request", aber es gibt keinen Cache | Einfacher Request-scoped Cache (z.B. `_agent_online_cache` zu Beginn von `process()` setzen) |
| M8 | MatrixBridge | **`_handle_message` hat zu viele Verantwortlichkeiten** | Routing für 5+ Message-Typen in einer Methode | In eigene Router-Klasse extrahieren (Strategy/Chain of Responsibility Pattern) |

### Niedrig

| # | Klasse | Schwachstelle | Detail | Empfehlung |
|---|---|---|---|---|
| N1 | Assistant | **`_parse_llm_response` ohne JSON-Validierung** | Geparstes JSON wird nicht gegen erwartete Keys validiert | Schema-Validierung oder `.get()` mit Defaults (teilweise schon vorhanden) |
| N2 | Assistant | **`process()` Methode zu lang** | ~80 Zeilen – über dem 50-Zeilen-Richtwert | Aktion-Ausführung und TTS-Block in eigene Methoden extrahieren |
| N3 | RemoteCommandHandler | **Konstruktor mit 20+ Parametern** | Hohe Komplexität, schwer testbar | Config-Dataclass oder Builder-Pattern; oder Dependencies pro Handler-Gruppe bündeln |
| N4 | MatrixBridge | **`extract_claude_message` als Modul-Level-Funktion** | Gehört logisch zur Bridge, ist aber frei im Modul | Als `@staticmethod` in MatrixBridge verschieben |
| N5 | MatrixBridge | **Restart via `os._exit(0)` auf Windows** | Kein sauberes Cleanup, atexit-Handler werden nicht aufgerufen | Subprocess starten und dann sauber über `sys.exit()` beenden |
| N6 | MatrixBridge | **Enge Kopplung an `ErrorCollectorHandler`** | `_setup_error_alerting` durchsucht Root-Logger-Handlers nach spezifischem Typ | ErrorCollectorHandler als Konstruktor-Parameter übergeben |
| N7 | MatrixBridge | **Race Condition bei `_loop`-Zugriff** | `stop()` liest `self._loop` während `_run_loop()` es noch setzt | `threading.Event` für Loop-Ready-Signalisierung verwenden |