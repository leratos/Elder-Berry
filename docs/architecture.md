# Architektur

## Systemübersicht

```text
[Element / Matrix]              [Web Dashboard :8090]
       |                               |
       v                               v
[MatrixBridge] ── Command-Router    [AudioRouter]
       |
       ├─ Sprachnachricht?  ──> STT (Faster Whisper) ──> Text weiterleiten
       ├─ Direkter Command? ──> RemoteCommandHandler (Orchestrator)
       │                         ├─ SystemCommands     (Status, Screenshot, Medien)
       │                         ├─ CalendarCommands   (Termine CRUD + Suche)
       │                         ├─ MailCommands       (Mails, Suche, Antworten)
       │                         ├─ WeatherCommands    (Wetter, Timer, Erinnerungen)
       │                         ├─ NoteCommands       (Notizen + Wissensdatenbank)
       │                         ├─ ContactCommands    (Kontaktbuch)
       │                         ├─ TodoCommands       (Aufgabenliste)
       │                         ├─ FileCommands       (Clipboard, Dateien, Download)
       │                         ├─ ProcessCommands    (Start/Kill, Git, Docker, WoL)
       │                         ├─ CameraCommands     (Foto, Vision-Beschreibung)
       │                         ├─ TurntableCommands  (Drehteller-Steuerung)
       │                         └─ AdvancedCommands   (Computer Use, Web-Suche, Docs)
       ├─ "claude" + "..."? ──> ClaudeAgent (Anthropic API)
       └─ Alles andere      ──> Assistant (LLM + TTS + Avatar)
                                      |
                          ┌───────────┼───────────┐
                          v           v           v
                   ActionController  CoquiTTS   MemoryStore
                   (PC-Steuerung)    (XTTS v2)  (ChromaDB)
```

## 3-Tier-System

| Tier | Gerät | Rolle | Kommunikation |
|---|---|---|---|
| Tower | Windows-PC (RTX 4070 Ti Super) | LLM + TTS + Orchestrierung | Matrix-Bridge |
| Laptop | Windows-PC (RTX 4070) | PC-Steuerung + Audio-Empfänger | AgentServer (FastAPI) |
| RPi5 | Raspberry Pi 5 (4 GB) | Avatar-Display, Kamera, Servo | RobotServer (FastAPI, Port 8000) |

## Design-Patterns

- **ABC + Implementierung + DI**: Durchgehend für alle Komponenten
- **CommandHandler ABC**: Einheitliches Interface für alle Remote-Commands
  - `simple_commands`: Exakte Matches (z.B. "status", "todos")
  - `patterns`: Regex-Patterns mit Gruppen-Extraktion
  - `keywords`: Natürliche Sprache → Command-Mapping
  - `execute()` → `CommandResult` (success, text, file, pending_confirmation, fallthrough)
- **Graceful Degradation**: Fehlende Dependencies → Fehlertext, nie Crash
- **Constructor-based DI**: Alle Abhängigkeiten über Konstruktor, TYPE_CHECKING für zirkuläre Imports
- **SQLite + WAL-Modus**: Für alle lokalen Stores (Notes, Contacts, Todos, Reminders, Actions)
- **FTS5 Volltext**: Für NoteStore, ContactStore (automatische Trigger-basierte Index-Sync)

## Zentrale Klassen

### Kern

| Klasse | Modul | Beschreibung |
|---|---|---|
| `Assistant` | `core.assistant` | Orchestrator: LLM → Aktion → TTS → Avatar → Memory |
| `LLMRouter` | `llm.router` | Anthropic (primär) → Ollama (Fallback) |
| `AnthropicClient` | `llm.anthropic_client` | Sonnet 4.6, primäres LLM-Backend |
| `SecretStore` | `core.secret_store` | Fernet-verschlüsselter Credential-Speicher |
| `AudioRouter` | `core.audio_router` | Thread-safe Audio-Routing (matrix_only / matrix_and_local) |
| `TaskChainRunner` | `core.task_chain` | Multi-Step Command Chaining (ReAct, max 5 Schritte) |

### Kommunikation

| Klasse | Modul | Beschreibung |
|---|---|---|
| `MatrixChannel` | `comms.matrix_channel` | matrix-nio Async-Client |
| `MatrixBridge` | `comms.bridge` | Async/Sync Bridge mit Command-Router |
| `RemoteCommandHandler` | `comms.remote_commands` | Orchestrator: delegiert an Domain-Handler |
| `CommandHandler` (ABC) | `comms.commands.base` | Basisklasse für Command-Handler |
| `ClaudeAgent` | `comms.claude_agent` | Anthropic API für komplexe Aufgaben |
| `AlertMonitor` | `comms.alert_monitor` | Proaktive Alerts (Disk, Prozess-Crash) |
| `ChatHistory` | `comms.chat_history` | Sliding Window pro User + Rolling Summary |
| `ReminderScheduler` | `comms.reminder_scheduler` | Daemon-Thread, 15s Poll, Matrix-Callback |
| `BriefingScheduler` | `comms.briefing_scheduler` | Tägliches Briefing (Wetter + Kalender + Erinnerungen + Todos) |
| `CalendarWatcher` | `comms.calendar_watcher` | Proaktive Termin-Erinnerungen |
| `ContextEnricher` | `core.context_enricher` | Kontext-Anreicherung für Kalender-Alerts |

### Charakter & Ausgabe

| Klasse | Modul | Beschreibung |
|---|---|---|
| `SaleriaEngine` | `character.saleria` | Persönlichkeit, Emotion-Extraktion |
| `EmotionTracker` | `character.emotion_tracker` | Stimmungs-Ringbuffer mit Decay |
| `CoquiTTSEngine` | `tts.coqui_engine` | XTTS v2 Voice Cloning, 10 Emotionen |
| `FasterWhisperEngine` | `stt.faster_whisper_engine` | Speech-to-Text, GPU, VAD-Filter |
| `LayeredSpriteRenderer` | `avatar.layered_renderer` | Sprite-Compositing, Blink + Lip-Sync |
| `WindowsActionController` | `actions.windows_controller` | PC-Steuerung (Tastatur, Maus, Lautstärke) |
| `ComputerUseController` | `actions.computer_use` | Vision-basierte PC-Steuerung (Anthropic) |

### Tools & Stores

| Klasse | Modul | Beschreibung |
|---|---|---|
| `GoogleCalendarClient` | `tools.google_calendar` | OAuth2, CRUD Events, natürliche Datumsangaben |
| `IMAPEmailClient` | `tools.email_client` | IMAP Suche, Anhänge, provider-agnostisch |
| `EmailSender` | `tools.email_sender` | SMTP Versand (Phase 28) |
| `NoteStore` | `tools.note_store` | SQLite + FTS5, KV-Fakten + Freitext-Notizen |
| `ContactStore` | `tools.contact_store` | SQLite + FTS5, Upsert per Name, E-Mail-Lookup |
| `TodoStore` | `tools.todo_store` | SQLite, Prioritäten, Kategorien, Briefing-Integration |
| `ReminderStore` | `tools.reminder_store` | SQLite, UTC, neustart-sichere Timer/Erinnerungen |
| `WeatherClient` | `tools.weather_client` | Open-Meteo API, Prognose, WMO-Codes |
| `BraveSearchClient` | `tools.brave_search_client` | Web-Suche via Brave Search API |
| `DocumentReader` | `tools.document_reader` | PDF (pymupdf) + TXT Parsing für LLM-Zusammenfassung |
| `GymDataClient` | `tools.gym_data` | Berry-Gym REST API Client |

### Hardware-Anbindung

| Klasse | Modul | Beschreibung |
|---|---|---|
| `RobotClient` / `RobotServer` | `robot.*` | Tower ↔ RPi5 Kommunikation (FastAPI) |
| `RPi5Camera` | `robot.camera_controller` | picamera2, RPi Camera Module 3 |
| `RPi5TurntableController` | `robot.turntable_controller` | 28BYJ-48, Hall-Sensor Homing |
| `RPi5AvatarDisplay` | `robot.avatar_display` | PyGame-CE, DSI-Fullscreen |
| `AudioDashboard` | `web.audio_dashboard` | FastAPI Web-UI (Port 8090) |

## Projektstruktur

```text
src/elder_berry/
├── actions/          # PC-Steuerung + Aktions-Datenbank
├── agent/            # Laptop Agent Server/Client
├── avatar/           # Avatar-Rendering (Sprite + Layered)
│   └── assets/       # Sprite-Komponenten (body/, eye/, mouth/)
├── character/        # Charakter-Engine + Saleria Persönlichkeit
├── comms/            # Matrix, Remote Commands, Claude Agent, Alerts
│   └── commands/     # Domain-spezifische Command-Handler
├── core/             # Assistant-Orchestrator, SecretStore, AudioRouter
├── llm/              # LLM-Clients (Anthropic, Ollama, OpenRouter, Router)
├── memory/           # RAG-Gedächtnis (ChromaDB + Embeddings)
├── robot/            # RPi5-Kommunikation (Server, Client, Simulator)
├── stt/              # Speech-to-Text (Faster Whisper)
├── system/           # System-Monitoring
├── tools/            # Assistent-Tools (Kalender, Mail, Wetter, Notizen, Kontakte, Todos, ...)
├── tts/              # TTS-Engines (Windows SAPI, Coqui XTTS)
│   └── voices/       # Voice Samples pro Emotion
└── web/              # Web Dashboard (Audio-Routing)
    └── templates/    # HTML Templates

docs/
├── concepts/         # Phase-Konzeptdokumente
├── journal.txt       # Projekt-Log
└── personal/         # Persönliche Notizen (gitignored)

hardware/
├── electronics/      # KiCad 9 Schaltpläne
├── enclosure/        # Gehäuse-CAD (Inventor)
│   └── iLogic/       # Parametrische Scripts (Rinde, Wurzeln)
└── bom/              # Stückliste

scripts/
├── start_saleria.py     # Haupteinstiegspunkt (Terminal/Matrix/Voice)
├── setup_email.py       # E-Mail-Konfiguration (IMAP + SMTP)
├── setup_google_oauth.py # Google Calendar OAuth2 Setup
└── demo_tts_live.py     # Interaktives TTS-Testing

tests/                # 1200+ Unit- + Integrationstests
```

## Hardware

| Komponente | Rolle |
|---|---|
| Tower-PC (RTX 4070 Ti Super, 16 GB VRAM) | LLM-Host, TTS-Generierung |
| Laptop (RTX 4070, 8 GB VRAM) | Entwicklung, Tests, mobiler Client |
| Raspberry Pi 5 (4 GB) | Avatar-Display (DSI), Sensoren, Servo |
| RPi Touch Display 2 (5", 720×1280) | Pepper's Ghost Hologramm-Display |
| 28BYJ-48 Stepper + ULN2003 + Drehteller | Rotation zum Benutzer (360°, Hall-Sensor Homing) |
| RPi Camera Module 3 | Vision-Beschreibung via Anthropic API |
