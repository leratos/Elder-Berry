# Architektur

## Systemübersicht

```text
[Element / Matrix]              [Web Dashboard :8090]
       |                               |
       v                               v
[MatrixBridge] ── Command-Router    [SettingsDashboard / SetupWizard]
       |
       ├─ Sprachnachricht?  ──> STTRouter (Groq Cloud / FasterWhisper lokal) ──> Text
       ├─ Direkter Command? ──> RemoteCommandHandler (Orchestrator)
       │                         ├─ SystemCommands     (Status, Screenshot, Medien)
       │                         ├─ CalendarCommands   (Termine CRUD + Suche)
       │                         ├─ MailCommands       (Mails, Suche, Antworten)
       │                         ├─ WeatherCommands    (Wetter, Timer, Erinnerungen)
       │                         ├─ NoteCommands       (Notizen + Wissensdatenbank)
       │                         ├─ ContactCommands    (Kontaktbuch + CardDAV)
       │                         ├─ TodoCommands       (Aufgabenliste)
       │                         ├─ FileCommands       (Clipboard, Dateien, Download)
       │                         ├─ CloudCommands      (Nextcloud + Ablage + PDF)
       │                         ├─ RouteCommands      (Routenplanung)
       │                         ├─ HarmonyCommands    (Smart Home, Szenen)
       │                         ├─ CameraCommands     (Foto, Vision-Beschreibung)
       │                         ├─ TurntableCommands  (Drehteller-Steuerung)
       │                         ├─ ProcessCommands    (Start/Kill, WoL)
       │                         ├─ GitCommands        (Status, Pull, Log)
       │                         ├─ DockerCommands     (PS, Restart, Logs)
       │                         ├─ UpdateCommands     (Self-Update Tower + RPi5)
       │                         ├─ SelfcheckCommands  (Gesundheitsprüfung)
       │                         ├─ LogCommands        (Remote Log-Zugriff)
       │                         └─ AdvancedCommands   (Computer Use, Web-Suche, Docs)
       ├─ Bestätigung?      ──> ConfirmationHandler (Mail, Filing, Restart, Cloud)
       ├─ "claude" + "..."? ──> ClaudeAgent (Anthropic API)
       └─ Alles andere      ──> Assistant (LLM + TTS + Avatar)
                                      |
                          ┌─────────┼─────────┐
                          v           v           v
                   TowerAgent    TTSRouter    MemoryStore
                   (PC via SSH)  (11Labs/XTTS) (ChromaDB)
```

## 4-Tier-System

| Tier | Gerät | Rolle | Kommunikation |
|---|---|---|---|
| Rootserver | Hetzner (Plesk, Ubuntu 24.04) | Synapse Matrix-Server, Alexa-Endpoint, Nginx-Proxy | Öffentliches Internet |
| Tower | Windows-PC (RTX 4070 Ti Super) | Haupthirn: LLM, TTS/STT, Orchestrierung, PC-Steuerung | Matrix-Bridge |
| Laptop | Windows-PC (RTX 4070) | Client: PC-Steuerung + Audio-Empfänger | AgentServer (FastAPI) |
| RPi5 | Raspberry Pi 5 (4 GB) | Körper: Avatar-Display, Kamera, Drehteller, Harmony Hub | RobotServer (FastAPI, Port 8000) |
## Design-Patterns

- **ABC + Implementierung + DI**: Durchgehend für alle Komponenten
- **CommandHandler ABC + Plugin-Registry (Phase 77)**: Einheitliches
  Interface für alle Remote-Commands. Handler werden als `CommandPlugin`-
  Manifest exportiert und via Registry aus drei Quellen geladen
  (Builtin / `~/.elder-berry/plugins/` / Entry-Points).
  - `simple_commands`: Exakte Matches (z.B. "status", "todos")
  - `patterns`: Regex-Patterns mit Gruppen-Extraktion
  - `keywords`: Natürliche Sprache → Command-Mapping
  - `execute()` → `CommandResult` (success, text, file, pending_confirmation, fallthrough)
  - Conflict-Detector als CI-Gate: kollidierende Patterns müssen explizit
    via `conflicts=("other_name",)` deklariert werden.
- **Graceful Degradation**: Fehlende Dependencies → Fehlertext, nie Crash
- **Constructor-based DI / HandlerContext**: Alle Abhängigkeiten über
  Konstruktor, TYPE_CHECKING für zirkuläre Imports. Phase 77 hat den
  Service-Container `HandlerContext` eingeführt, der allen Handlern
  einheitlich injiziert wird.
- **mypy --strict (Phasen 76, 76b, 76c)**: `core/`, `comms/`, `tools/`
  und `web/` werden im CI strict typgeprüft. Tier-Whitelist im
  `pyproject.toml` macht die Erweiterung sichtbar.
- **SQLite + WAL-Modus**: Für alle lokalen Stores (Notes, Contacts,
  Todos, Reminders, Actions, Proposals).
- **FTS5 Volltext**: Für `NoteStore`, `ContactStore`, `ProposalStore`
  (Dedupe-Suche, automatische Trigger-basierte Index-Sync).

## Zentrale Klassen

### Kern

| Klasse | Modul | Beschreibung |
|---|---|---|
| `Assistant` | `core.assistant` | Orchestrator: LLM → Aktion → TTS → Avatar → Memory |
| `LLMRouter` | `llm.router` | Anthropic (primär) → Ollama (Fallback) |
| `AnthropicClient` | `llm.anthropic_client` | Claude Sonnet 4.6, primäres LLM-Backend |
| `SecretStore` | `core.secret_store` | Fernet-verschlüsselter Credential-Speicher |
| `AudioRouter` | `core.audio_router` | Thread-safe Audio-Routing (matrix_only / matrix_and_local) |
| `TTSRouter` | `core.tts_router` | ElevenLabs (primär) → CoquiTTS → WindowsTTS (Notfall) |
| `STTRouter` | `core.stt_router` | Groq Whisper API (primär) → FasterWhisper lokal (Fallback) |
| `TaskChainRunner` | `core.task_chain` | Multi-Step Command Chaining (ReAct, max 5 Schritte) |

### Kommunikation

| Klasse | Modul | Beschreibung |
|---|---|---|
| `MatrixChannel` | `comms.matrix_channel` | matrix-nio Async-Client |
| `MatrixBridge` | `comms.bridge` | Async/Sync Bridge mit Command-Router |
| `RemoteCommandHandler` | `comms.remote_commands` | Orchestrator: delegiert an Domain-Handler |
| `CommandHandler` (ABC) + `CommandPlugin` | `comms.commands.base` | Basisklasse + Plugin-Manifest (Phase 77) |
| `PluginRegistry` | `comms.commands.registry` | Discovery aus Builtin / User-Dir / Entry-Points (Phase 77) |
| `ProposalNotifier` | `comms.proposal_notifier` | Erkennt LLM-Fallback-Lücken → speichert Plugin-Vorschläge (Phase 78) |
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
| `ElevenLabsClient` | `tools.elevenlabs_client` | Cloud-TTS (primär), Voice Cloning via API |
| `CoquiTTSEngine` | `tts.coqui_engine` | XTTS v2 Voice Cloning lokal, 10 Emotionen |
| `CloudSTTClient` | `tools.cloud_stt_client` | Groq Whisper API (primäre STT) |
| `FasterWhisperEngine` | `stt.faster_whisper_engine` | Lokales Speech-to-Text, GPU, VAD-Filter |
| `LayeredSpriteRenderer` | `avatar.layered_renderer` | Sprite-Compositing, Blink + Lip-Sync |
| `WindowsActionController` | `actions.windows_controller` | PC-Steuerung (Tastatur, Maus, Lautstärke) |
| `ComputerUseController` | `actions.computer_use` | Vision-basierte PC-Steuerung (Anthropic) |

### Tools & Stores

| Klasse | Modul | Beschreibung |
|---|---|---|
| `GoogleCalendarClient` | `tools.google_calendar` | OAuth2, CRUD Events, natürliche Datumsangaben |
| `CalDAVCalendar` | `tools.caldav_calendar` | Nextcloud CalDAV-Kalender (primär, Phase 36) |
| `CalDAVTasks` | `tools.caldav_tasks` | Nextcloud Tasks / Aufgaben via CalDAV |
| `CardDAVSync` | `tools.carddav_sync` | Bidirektionaler Nextcloud CardDAV-Sync |
| `NextcloudFiles` | `tools.nextcloud_files` | WebDAV Datei-Hub, Share-Links, Volltextsuche |
| `IMAPEmailClient` | `tools.email_client` | IMAP Suche, Anhänge, provider-agnostisch |
| `EmailSender` | `tools.email_sender` | SMTP Versand |
| `NoteStore` | `tools.note_store` | SQLite + FTS5, KV-Fakten + Freitext-Notizen |
| `ContactStore` | `tools.contact_store` | SQLite + FTS5, Upsert per Name, E-Mail-Lookup |
| `TodoStore` | `tools.todo_store` | SQLite, Prioritäten, Kategorien, Briefing-Integration |
| `ReminderStore` | `tools.reminder_store` | SQLite, UTC, neustart-sichere Timer/Erinnerungen |
| `ProposalStore` | `tools.proposal_store` | SQLite + FTS5, Plugin-Vorschläge mit Status-Workflow (Phase 78) |
| `ConversationListStore` | `tools.conversation_list_store` | In-Memory-Listen-Disambiguation, TTL=1h, gegen LLM-ID/URL-Halluzinationen (Phase 80) |
| `WeatherClient` | `tools.weather_client` | Open-Meteo API, Prognose, WMO-Codes |
| `BraveSearchClient` | `tools.brave_search_client` | Web-Suche via Brave Search API |
| `WebFetcher` | `tools.web_fetcher` | Webseiten abrufen + LLM-Zusammenfassung |
| `DocumentReader` | `tools.document_reader` | PDF (pymupdf) + TXT Parsing für LLM-Zusammenfassung |
| `DocumentClassifier` | `tools.document_classifier` | Auto-Klassifikation für Ablage (LLM-basiert) |
| `StirlingPDF` | `tools.stirling_pdf` | Stirling-PDF API: Merge, Split, OCR, Convert |
| `RoutePlanner` | `tools.route_planner` | Google Maps Directions API, Kontakt-Adressen |
| `GymDataClient` | `tools.gym_data` | Berry-Gym REST API Client |

### Hardware-Anbindung

| Klasse | Modul | Beschreibung |
|---|---|---|
| `RobotClient` / `RobotServer` | `robot.*` | Tower ↔ RPi5 Kommunikation (FastAPI, Port 8000) |
| `RPi5Camera` | `robot.camera_controller` | picamera2, RPi Camera Module 3 |
| `RPi5TurntableController` | `robot.turntable_controller` | 28BYJ-48, Hall-Sensor Homing |
| `RPi5AvatarDisplay` | `robot.avatar_display` | PyGame-CE, DSI-Fullscreen |
| `HarmonyAdapter` | `robot.harmony_adapter` | Harmony Hub via aioharmony (WebSocket, kein Cloud) |
| `AlexaSkillHandler` | `robot.alexa_skill_handler` | Alexa Custom Skill Endpoint + Request-Verifikation |

### Web & Security

| Klasse | Modul | Beschreibung |
|---|---|---|
| `SettingsDashboard` | `web.settings_dashboard` | FastAPI Web-UI (Port 8090), Secret-Verwaltung |
| `SetupWizard` | `web.setup_wizard` | Browser-basierter Ersteinrichtungsassistent |
| `SecurityMiddleware` | `web.security_middleware` | CSP, X-Frame-Options, Permissions-Policy |
| `OriginCheckMiddleware` | `web.origin_check_middleware` | CSRF-Schutz: Origin/Referer-Check für state-changing Routes (Phase 64) |
| `DashboardAuth` | `web.dashboard_auth` | Passwort-Schutz für Dashboard (bcrypt rounds=14, PW-Min 12, Phase 72) |
| `SessionRevocationList` | `web.session_revocation_list` | Server-side Logout-Invalidation (Phase 70 H1) |
| `RateLimiter` | `web.rate_limiter` | IP-basiertes Rate-Limiting für API-Endpunkte |
| `SettingsTokenManager` | `web.settings_token` | Single-Use Token für Dashboard-Autorisierung |
| `ProposalsAPI` | `web.proposals_api` | Dashboard-API für Plugin-Vorschläge (Phase 78) |
| `PluginsAPI` | `web.plugins_api` | Dashboard-API für Plugin-Inspector (Phase 77.5) |
| `WebFetcher` | `tools.web_fetcher` | SSRF-Schutz (private/loopback/metadata-IPs geblockt), 5 MB Stream-Cap (Phase 65 + 70 H3) |

## Projektstruktur

```text
src/elder_berry/
├── actions/          # PC-Steuerung + Aktions-Datenbank
├── agent/            # Laptop Agent Server/Client
├── avatar/           # Avatar-Rendering (Sprite + Layered)
│   └── assets/       # Sprite-Komponenten (body/, eye/, mouth/)
├── character/        # Charakter-Engine + Saleria Persönlichkeit
├── comms/            # Matrix, Remote Commands, Claude Agent, Alerts
│   └── commands/     # Domain-spezifische Command-Plugins (24 Handler + Registry, Phase 77)
├── core/             # Assistant-Orchestrator, SecretStore, TTSRouter, STTRouter
├── llm/              # LLM-Clients (Anthropic, Ollama, OpenRouter, Router)
├── memory/           # RAG-Gedächtnis (ChromaDB + Embeddings)
├── robot/            # RPi5-Kommunikation (Server, Client, Simulator, Alexa)
├── server/           # Test-/Mock-Server (z.B. Harmony Mock)
├── stt/              # Speech-to-Text (Faster Whisper Engine)
├── system/           # System-Monitoring
├── tools/            # Assistent-Tools (Kalender, Mail, Cloud, Nextcloud, Kontakte, Stores, ...)
├── tts/              # TTS-Engines (Windows SAPI, Coqui XTTS, ElevenLabs)
│   └── voices/       # Voice Samples pro Emotion
├── web/              # FastAPI Dashboard, Setup-Wizard, Security/CSRF Middleware,
│                     #   Session-Revocation, Plugin- + Proposal-APIs
│   └── templates/    # Jinja2 HTML Templates
└── webapp/           # Progressive Web App (Dashboard-Frontend, Module, Icons)

docs/
├── README.md             # Repo-Einstieg (im Root)
├── CHANGELOG.md          # Phasenchronik (kompakt)
├── PROJECT_ROADMAP.md    # Vollständige Roadmap (Planungsdokument)
├── INSTALLATION.md       # Installation + API-Keys + Secrets
├── USAGE.md              # Commands + Workflows + Plugin-System
├── architecture.md       # Dieses Dokument
├── matrix_setup.md       # Synapse-Setup (Plesk/Docker)
├── rpi5_setup.md         # Raspberry Pi 5 Setup
├── ssh-tunnel.md         # SSH Reverse Tunnels (Tower + RPi5 → Rootserver)
├── EINKAUFSLISTE.md      # Hardware-Stückliste mit Status
├── public-readiness-audit.md # Generierter Audit-Bericht (read-only)
├── concepts/             # Phase-Konzeptdokumente (historisch + ON HOLD)
├── deploy/               # Beispiel-Configs (z.B. nginx-fern.conf)
├── prompts/              # LLM-Prompt-Snippets
├── templates/            # Plugin-Templates (z.B. plugin_template.py)
├── journal.txt           # Projekt-Log (laufend gepflegt, gitignored)
└── personal/             # Persönliche Notizen (gitignored)

hardware/
├── electronics/      # KiCad 9 Schaltpläne
├── enclosure/        # Gehäuse-CAD (Inventor)
│   └── iLogic/       # Parametrische Scripts (Rinde, Wurzeln)
└── bom/              # Stückliste

scripts/
├── start_saleria.py         # Haupteinstiegspunkt (Terminal/Matrix/Voice)
├── start_rpi5.py            # RPi5-Start (Avatar + RobotServer)
├── setup_wizard.py          # Browser-Wizard starten
├── setup_email.py           # E-Mail-Konfiguration (IMAP + SMTP)
├── setup_google_oauth.py    # Google Calendar OAuth2 Setup
├── set_dashboard_password.py # Dashboard-Passwort setzen
├── generate_plugin.py       # Plugin-Wizard (Phase 77)
├── check_public_readiness.py # Public-Repo-Audit (pre-push-Hook)
└── demo_tts_live.py         # Interaktives TTS-Testing

tests/                # 5418 Unit- + Integrationstests (~160 Testdateien, Stand Phase 81),
                      # mypy --strict-Gate im CI für core/, comms/, tools/, web/
```

## Hardware

| Komponente | Rolle |
|---|---|
| Tower-PC (RTX 4070 Ti Super, 16 GB VRAM) | LLM-Host, TTS/STT-Generierung, PC-Steuerung |
| Laptop (RTX 4070, 8 GB VRAM) | AgentServer, Entwicklung, Tests, mobiler Client |
| Raspberry Pi 5 (4 GB) | Avatar-Display (DSI), Kamera, Drehteller, Harmony Hub |
| RPi Touch Display 2 (5", 720×1280, DSI) | Pepper's Ghost Hologramm-Display |
| 28BYJ-48 Stepper + ULN2003 + Drehteller | Rotation zum Benutzer (360°, A3144 Hall-Sensor Homing) |
| RPi Camera Module 3 | Foto + Vision-Beschreibung via Anthropic API |
| Logitech Harmony Hub | IR-Steuerung aller AV-Geräte (TV, Receiver, ...) |
