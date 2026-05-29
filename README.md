# Elder-Berry

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![codecov](https://codecov.io/gh/leratos/Elder-Berry/branch/main/graph/badge.svg)](https://codecov.io/gh/leratos/Elder-Berry)

> Virtueller KI-Assistent mit V-Tuber-Charakter, Voice Cloning und Fernsteuerung.
> Teil der [Last-Strawberry](https://last-strawberry.com) Projektfamilie.

> **Personal project.** Aktiv entwickelt fuer mein eigenes Setup. Forks und
> Issues sind willkommen, aber ich rekrutiere nicht aktiv und kann keine
> Garantien fuer Bug-Fixes auf fremder Hardware geben.

## Was ist Elder-Berry?

Elder-Berry ist ein modularer KI-Assistent rund um den V-Tuber-Charakter **Saleria Berry**.
Sie kombiniert LLM-Verarbeitung (Anthropic + Ollama), Cloud-TTS (ElevenLabs + XTTS v2 Fallback),
emotionsgesteuerte Avatar-Darstellung, PC-Steuerung, Spracherkennung und Fernzugriff via Matrix
zu einem vollständigen persönlichen Assistenten.

Saleria ist als stationäre Schreibtisch-Begleiterin konzipiert – mit einem Pepper's Ghost
Hologramm-Display in einem 3D-gedruckten Holunder-Baumstamm-Gehäuse.

## Funktionsübersicht

### Gespräch & Persönlichkeit
- Konversation mit eigenem Charakter, Emotion-Tagging und Sarkasmus
- Sprachausgabe: ElevenLabs Cloud-TTS (primär) + Coqui XTTS v2 Voice Cloning (Fallback)
- Spracheingabe: Groq Whisper API (primär) + Faster Whisper STT lokal (Fallback)
- RAG-Gedächtnis: ChromaDB + Ollama Embeddings
- Emotionaler Kontext: Stimmungs-Tracking über mehrere Nachrichten

### Persönlicher Assistent
- **Kalender**: Termine anzeigen, erstellen, löschen, suchen (Nextcloud CalDAV, Google Calendar Fallback)
- **E-Mail**: Mails abrufen, suchen, Anhänge senden, Antworten generieren (IMAP/SMTP)
- **Kontaktbuch**: Kontakte anlegen, suchen, bidirektionaler Nextcloud-CardDAV-Sync
- **Aufgabenliste**: Todos mit Prioritäten und Kategorien, im Morgen-Briefing integriert
- **Wetter**: Aktuell, Morgen, Woche (Open-Meteo, kostenlos)
- **Timer & Erinnerungen**: Einmalig und wiederkehrend (täglich, wöchentlich, monatlich)
- **Briefing**: Tagesübersicht um 07:30 (Wetter + Termine + Erinnerungen + Todos + Geburtstage)
- **Notizen & Fakten**: Fakten lokal im `FactStore` (SQLite), Freitext-Notizen über Nextcloud Notes (inkl. Suche/Kategorien)
- **Web-Suche**: Brave Search API + LLM-Aufbereitung der Ergebnisse
- **Dokumente**: PDF/TXT zusammenfassen, Dokument-Ablage mit Auto-Klassifikation (Nextcloud)
- **Routenplanung**: Google Maps Directions API, Kontakt-Adressen, Abfahrtszeit-Berechnung
- **Nextcloud**: Datei-Hub (Upload + Share-Links), CalDAV, CardDAV, Inhaltssuche

### Fernsteuerung (via Matrix / Element)
- 50+ direkte Commands ohne LLM, aufgeteilt in 24 Plugin-Handler (Status, Screenshot, Medien, Clipboard, Dateien, ...)
- PC-Steuerung via Anthropic Vision (Computer Use)
- Git, Docker, Wake-on-LAN, Self-Update (Tower + RPi5)
- Sprachnachrichten: Whisper transkribiert, Saleria antwortet mit Text + Sprache
- Claude Agent: komplexe Aufgaben via Anthropic API
- Plugin-System (Phase 77): eigene Handler in `~/.elder-berry/plugins/`
  ablegen oder via `pip install` als Entry-Point. Self-Suggestion
  (Phase 78) erkennt fehlende Capabilities und sammelt Vorschläge im
  Dashboard.

### Sprachsteuerung (via Alexa)
- Alexa Custom Skill "Meine Saleria" als Sprach-Proxy
- "Alexa, frag meine Saleria fernsehen an" → Harmony Hub → TV
- Befehle: Aktivitäten (TV, Musik, Gaming), Lautstärke, Stumm, Alles aus, Status
- Kette: Echo → Amazon → Rootserver → SSH-Tunnel → RPi5 → Harmony Hub

### Hardware
- **Avatar**: Pepper's Ghost Hologramm (RPi5 + 5" DSI Display)
- **Drehteller**: 360° Rotation mit Hall-Sensor Homing
- **Kamera**: RPi Camera Module 3 + Anthropic Vision

## 4-Tier-System

| Tier | Gerät | Rolle | Verbindung |
|---|---|---|---|
| Rootserver | Cloud-Server (Linux, 24/7) | Matrix-Server (Synapse), Alexa-Endpoint, Nginx-Proxy | Öffentliches Internet |
| Tower | Windows-PC (RTX 4070 Ti Super, 16 GB VRAM) | Haupthirn: LLM, TTS/STT, Orchestrierung, PC-Steuerung | Matrix → SecretStore |
| Laptop | Windows-PC (RTX 4070, 8 GB VRAM) | Client: AgentServer, PC-Steuerung, Audio-Empfänger | AgentServer (FastAPI) |
| RPi5 | Raspberry Pi 5 (4 GB) | Körper: Avatar-Display, Kamera, Drehteller, Harmony Hub | RobotServer (FastAPI :8000) |

## Schnellstart

```bash
# Repository klonen
git clone https://github.com/leratos/Elder-Berry.git
cd Elder-Berry

# Virtuelle Umgebung erstellen
py -3.12 -m venv .venv
.venv\Scripts\activate  # Windows

# Vollinstallation (empfohlen für Tower)
pip install -e ".[tower]"   # Tower (Windows-Extras + TTS/STT + Matrix, Vollinstallation)

# Andere Plattformen via Metapaketen:
pip install -e ".[server]"  # Rootserver (Matrix + Cloud-Tools ohne Windows-Extras)
# RPi5: System-Python 3.13, siehe docs/rpi5_setup.md
```

Mindestens benötigt: ein Anthropic API-Key und Matrix-Zugangsdaten.

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()
store.set("anthropic_api_key", "sk-ant-...")
store.set("matrix_homeserver", "https://matrix.example.com")
store.set("matrix_user_id", "@saleria:matrix.example.com")
store.set("matrix_access_token", "syt_...")
store.set("matrix_room_id", "!roomid:matrix.example.com")
```

```bash
# Starten
python scripts/start_saleria.py                  # Matrix-Modus (Standard, Server)
python scripts/start_saleria.py --mode terminal  # Terminal-Modus (lokal, ohne Matrix)
python scripts/start_saleria.py --mode agent     # Tower-Agent (nur TTS/STT/Actions)
```

Für die vollständige Installations-Anleitung, alle API-Keys und optionale Dienste
siehe **[docs/INSTALLATION.md](docs/INSTALLATION.md)**.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| **[INSTALLATION.md](docs/INSTALLATION.md)** | Installation, API-Keys, Secrets, Voraussetzungen |
| **[USAGE.md](docs/USAGE.md)** | Alle Commands, Workflows, Beispiele |
| **[architecture.md](docs/architecture.md)** | System-Design, Klassen, Patterns, Projektstruktur |
| **[rpi5_setup.md](docs/rpi5_setup.md)** | RPi5-spezifische Einrichtung (Avatar, Drehteller, Kamera) |
| **[matrix_setup.md](docs/matrix_setup.md)** | Synapse Matrix-Server Setup (Plesk/Docker) |
| **[ssh-tunnel.md](docs/ssh-tunnel.md)** | SSH Reverse Tunnels (Tower + RPi5 → Rootserver) |
| **[PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md)** | Vollständige Roadmap (aktuelle Phasen inkl. Konzept-/ON-HOLD-Stränge) |

## Architektur (Kurzfassung)

```text
[Element / Matrix]    [Web Dashboard :8090]    [Alexa Echo]
       |                      |                      |
       v                      v                      v
[MatrixBridge]        [SettingsDashboard]   [RPi5: /saleria Endpoint]
       |               [SetupWizard]              |
       ├── Command-Router                   └─> HarmonyAdapter ─> Hub ─> IR
       |
       ├─ Sprachnachricht?  ──> STTRouter (Groq / FasterWhisper) ──> Text
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
                          ┌───────────┼───────────┐
                          v           v           v
                   TowerAgent    TTSRouter    MemoryStore
                   (PC via SSH)  (11Labs/XTTS) (ChromaDB)
```

Detaillierte Architektur mit allen Klassen und Patterns: **[architecture.md](docs/architecture.md)**

## Charakter: Saleria Berry

- **Persönlichkeit**: Direkt, entspannt, schlagfertig. Wie eine clevere Freundin, die hilft und locker bleibt.
- **10 Emotionen**: neutral, cheerful, sarcastic, motivated, thoughtful, whisper, shy, depressed, sad, angry
- **Stimme**: ElevenLabs Cloud-TTS (primär) + XTTS v2 Voice Cloning (Fallback)
- **Avatar**: Layered Sprite System (Body + Augen + Mund), Blink-Animation, Lip-Sync
- **Display**: Pepper's Ghost Hologramm (LCD horizontal + Acryl 45°, schwarzer Hintergrund)

## Tests

```bash
pytest tests/ -q
```

Aktuell >170 Testdateien im `tests/`-Verzeichnis. CI läuft mit vier
Gates: `test` (Ubuntu+Windows, inkl. Coverage), `lint` (ruff), `typecheck`
(`mypy --strict` für `core/`, `comms/`, `tools/`, `web`) und `security`
(`pip-audit`).

## Roadmap (Auszug)

| Phase | Name | Status |
|---|---|---|
| 1–3 | Basis-Software, RPi5, Charakter/V-Tuber | ✅ Fertig |
| 4 | Gehäuse + Drehteller (Hardware) | 🔧 In Arbeit |
| 5–8 | Fortgeschrittene Software, Matrix, Remote, Assistent-Tools | ✅ Fertig |
| 9 | Multimodal + Autonomie | 🔭 Vision |
| 10–14 | Avatar-Display, Dokumente, Audio, Computer Use, Web-Suche | ✅ Fertig |
| 15–20 | Self-Update, Notizen, Kalender-Watcher, Emotion, Erinnerungen, Task Chains | ✅ Fertig |
| 21–25 | Kontext-Verknüpfung, Intent-Routing, Chat-Summary, Avatar-Assets, Logging | ✅ Fertig |
| 26–30 | Kamera, Drehteller, E-Mail-Reply, Kontaktbuch, Aufgabenliste | ✅ Fertig |
| 31–35 | Bridge-Refactoring, Test-Offensive, Smart Context, Briefing 2.0, Web-Summary | ✅ Fertig |
| 36–39 | Nextcloud (CalDAV, CardDAV, Datei-Hub), Kontakte Vollintegration | ✅ Fertig |
| 40.1 | Sprachsteuerung via Alexa Custom Skill | ✅ Fertig |
| 41 | IR-Learning & Geräteverwaltung | 📡 Geplant |
| 42–43 | Dokument-Ablage (Cloud Aufräumen), Routenplanung (Google Maps) | ✅ Fertig |
| 44–48 | Server-Migration, Settings Dashboard, Setup-Wizard, UX-Polish, Refactoring | ✅ Fertig |
| 49–51 | Anhang-Aktionsmenü, Fehler-UX, Kontextsensitive Hilfe | ✅ Fertig |
| 52–53 | Unified Settings, Install-Script Härtung, Avatar-Editor UX | ✅ Fertig |
| 55 | pydub/audioop Migration (Python 3.13-Kompatibilität) | ✅ Fertig |
| 56 | Nextcloud Tasks als Todo-Backend | ✅ Fertig |
| 57–60 | Security-Härtung (CORS, CSP, Dashboard-Login, Rate-Limiting, IMAP-Sent) | ✅ Fertig |
| 61 | Remote Log-Zugriff via Matrix | ✅ Fertig |
| 63–66 | CSP-Härtung, CSRF/SSRF/Robot-Token, mittlere Security-Fixes, Robot-Reverse-Proxy | ✅ Fertig |
| 67 | Public-Readiness Audit + Sanitization | ✅ Fertig |
| 68 + 68 B1 | Public-Release-Vorbereitung, Asset-Licensing + NOTICE | ✅ Fertig |
| 69–72 | Path-Traversal-Schutz, Session-Hardening, Hygiene Runde 2, Auth-Hardening (PW-Min 12, bcrypt 14) | ✅ Fertig |
| 73 | CodeQL-Triage + PR-A/B/C (SSRF, stack-trace, log-injection) | ✅ Fertig |
| 74 | Codecov-Integration | ✅ Fertig |
| 75 + 75b | Repo-Hygiene, ruff-format Massen-Sweep (~300 Dateien) | ✅ Fertig |
| 76 + 76b + 76c | mypy-Strict-Rollout (`core/`, `comms/`, `tools/`+`web/`), CI-Gate hart | ✅ Fertig |
| 77 + 77.5 | Commands-Plugin-Registry (24 Builtin-Plugins, Discovery, Wizard) + Plugin-Inspector | ✅ Fertig |
| 78 | Plugin-Self-Suggestion (ProposalStore + Trigger-Pipeline + Dashboard) | ✅ Fertig |
| 79 | Richer Pseudocode für Vorschläge | ⏸️ ON HOLD |
| 80 | ConversationListStore + list_pick (web_search/mail_inbox/note_search) | ✅ Fertig |
| 81 + 81b | Command-Fallback-UX + Plugin-Vorschlag aus Fallback-Pfad | ✅ Fertig |
| 82 + 82.1 | Multi-Action-Sequencing + Multi-Line-in-Step | ✅ Fertig |
| 83 | Reactive AvatarEngine | 🔬 Konzept |
| 85 + 86 + 87.1 + 87.B + 87.C | HTML-Mail-Sanitizer, tinycss2-Resolver, Iteration-Crash-Fix, Background-Heuristik (WCAG), Doku-Migration | ✅ Fertig |
| 89 | Saleria-Initiativ-Followup | 🔬 Konzept |
| 90 | Multi-Line-Notiz-Pattern + Halluzinations-Vermeidung (90-C nach Smoketest nicht nötig) | ✅ Fertig |
| 91 | FactStore-Extraktion + Note-Flow-Refactor | ✅ Fertig |
| 92 | Multi-Stop-Routing | ✅ Fertig |
| 93 | Nextcloud Cookbook-Integration (Rezepte, API-Matching, Kategorie-Suche) | ✅ Fertig |
| 94 | LibreSign-Integration (PDF-Signierung via Nextcloud) | 🔬 Konzept |
| 95 | Comms-Pattern-Stabilisierung (PatternSpec, Routing-Confidence, Handler-Gates) | ✅ Fertig |

Vollständige Roadmap mit Details: **[PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md)**
Phasenchronik mit Beschreibungen: **[CHANGELOG.md](docs/CHANGELOG.md)**

## Lizenz & Drittanbieter

Elder-Berry steht unter der **MIT-Lizenz** ([LICENSE](LICENSE)). Eigene Assets
(Saleria Voice-Samples, Avatar-Sprites) stehen ebenfalls unter MIT.

Wichtig für Forks: **XTTS v2** (Coqui TTS) ist nur **non-commercial** lizenziert
(CPML). Wer Elder-Berry kommerziell einsetzen will, muss XTTS v2 ersetzen.

Vollständige Übersicht über eigene Assets, eingebundene Modelle und genutzte
Cloud-APIs: **[NOTICE.md](NOTICE.md)**.

## Projektfamilie

- [last-strawberry.com](https://last-strawberry.com)
- last-strawberry-DnD
- Gym-Berry
- **Elder-Berry** ← du bist hier
