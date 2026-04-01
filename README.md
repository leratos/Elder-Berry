# Elder-Berry

> Virtueller KI-Assistent mit V-Tuber-Charakter, Voice Cloning und Fernsteuerung.
> Teil der [Last-Strawberry](https://last-strawberry.com) Projektfamilie.

## Was ist Elder-Berry?

Elder-Berry ist ein modularer KI-Assistent rund um den V-Tuber-Charakter **Saleria Berry**.
Sie kombiniert LLM-Verarbeitung (Anthropic + Ollama), Voice Cloning (XTTS v2), emotionsgesteuerte
Avatar-Darstellung, PC-Steuerung, Spracherkennung und Fernzugriff via Matrix zu einem
vollständigen persönlichen Assistenten.

Saleria ist als stationäre Schreibtisch-Begleiterin konzipiert – mit einem Pepper's Ghost
Hologramm-Display in einem 3D-gedruckten Holunder-Baumstamm-Gehäuse.

## Funktionsübersicht

### Gespräch & Persönlichkeit
- Konversation mit eigenem Charakter, Emotion-Tagging und Sarkasmus
- Sprachausgabe via Coqui XTTS v2 Voice Cloning (10 Emotionen, Deutsch)
- Spracheingabe via Faster Whisper STT (GPU-beschleunigt)
- RAG-Gedächtnis: ChromaDB + Ollama Embeddings
- Emotionaler Kontext: Stimmungs-Tracking über mehrere Nachrichten

### Persönlicher Assistent
- **Kalender**: Termine anzeigen, erstellen, löschen, suchen (Google Calendar)
- **E-Mail**: Mails abrufen, suchen, Anhänge senden, Antworten generieren (IMAP/SMTP)
- **Kontaktbuch**: Kontakte anlegen, suchen, bei E-Mail-Antworten als Kontext nutzen
- **Aufgabenliste**: Todos mit Prioritäten und Kategorien, im Morgen-Briefing integriert
- **Wetter**: Aktuell, Morgen, Woche (Open-Meteo, kostenlos)
- **Timer & Erinnerungen**: Einmalig und wiederkehrend (täglich, wöchentlich, monatlich)
- **Briefing**: Tagesübersicht um 07:30 (Wetter + Termine + Erinnerungen + Todos)
- **Notizen**: Fakten-Speicher + Freitext mit Volltextsuche (SQLite + FTS5)
- **Web-Suche**: Brave Search API + LLM-Aufbereitung der Ergebnisse
- **Dokumente**: PDF/TXT zusammenfassen via LLM

### Fernsteuerung (via Matrix / Element)
- 50+ direkte Commands ohne LLM (Status, Screenshot, Medien, Clipboard, Dateien, ...)
- PC-Steuerung via Anthropic Vision (Computer Use)
- Git, Docker, Wake-on-LAN, Self-Update (Tower + RPi5)
- Sprachnachrichten: Whisper transkribiert, Saleria antwortet mit Text + Sprache
- Claude Agent: komplexe Aufgaben via Anthropic API

### Sprachsteuerung (via Alexa)
- Alexa Custom Skill "Meine Saleria" als Sprach-Proxy
- "Alexa, frag meine Saleria fernsehen an" → Harmony Hub → TV
- Befehle: Aktivitäten (TV, Musik, Gaming), Lautstärke, Stumm, Alles aus, Status
- Kette: Echo → Amazon → Rootserver → SSH-Tunnel → RPi5 → Harmony Hub

### Hardware
- **Avatar**: Pepper's Ghost Hologramm (RPi5 + 5" DSI Display)
- **Drehteller**: 360° Rotation mit Hall-Sensor Homing
- **Kamera**: RPi Camera Module 3 + Anthropic Vision

## 3-Tier-System

| Tier | Gerät | Rolle |
|---|---|---|
| Tower | Windows-PC (RTX 4070 Ti Super, 16 GB VRAM) | Gehirn: LLM + TTS, Dauerbetrieb |
| Laptop | Windows-PC (RTX 4070, 8 GB VRAM) | Client: PC-Steuerung + Audio |
| RPi5 | Raspberry Pi 5 (4 GB) | Körper: Avatar-Display, Sensoren, Servo |

## Schnellstart

```bash
# Repository klonen
git clone https://github.com/leratos/Elder-Berry.git
cd Elder-Berry

# Virtuelle Umgebung erstellen
py -3.12 -m venv .venv
.venv\Scripts\activate  # Windows

# Vollinstallation (empfohlen für Tower)
pip install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"
pip install chromadb faster-whisper
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
python scripts/start_saleria.py                  # Matrix-Modus (Standard)
python scripts/start_saleria.py --mode terminal  # Terminal-Modus (lokal, ohne Matrix)
```

Für die vollständige Installations-Anleitung, alle API-Keys und optionale Dienste
siehe **[docs/INSTALLATION.md](docs/INSTALLATION.md)**.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| **[INSTALLATION.md](docs/INSTALLATION.md)** | Installation, API-Keys, Secrets, Voraussetzungen |
| **[USAGE.md](docs/USAGE.md)** | Alle Commands, Workflows, Beispiele |
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | System-Design, Klassen, Patterns, Projektstruktur |
| **[RPI5_SETUP.md](docs/RPI5_SETUP.md)** | RPi5-spezifische Einrichtung (Avatar, Drehteller, Kamera) |
| **[PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md)** | Vollständige Roadmap (Phase 1–30) |

## Architektur (Kurzfassung)

```text
[Element / Matrix]    [Web Dashboard :8090]    [Alexa Echo]
       |                      |                      |
       v                      v                      v
[MatrixBridge]           [AudioRouter]    [RPi5: /saleria Endpoint]
       |                                         |
       ├── Command-Router                        └─> HarmonyAdapter ─> Hub ─> IR
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

Detaillierte Architektur mit allen Klassen und Patterns: **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**

## Charakter: Saleria Berry

- **Persönlichkeit**: Direkt, entspannt, schlagfertig. Wie eine clevere Freundin, die hilft und locker bleibt.
- **10 Emotionen**: neutral, cheerful, sarcastic, motivated, thoughtful, whisper, shy, depressed, sad, angry
- **Stimme**: XTTS v2 Voice Cloning mit pro-Emotion Speaker-WAVs
- **Avatar**: Layered Sprite System (Body + Augen + Mund), Blink-Animation, Lip-Sync
- **Display**: Pepper's Ghost Hologramm (LCD horizontal + Acryl 45°, schwarzer Hintergrund)

## Tests

```bash
pytest tests/ -q
```

3200+ Tests.

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
| 26–27 | Kamera-Integration, Drehteller-Steuerung | ✅ Fertig |
| 28 | E-Mail-Antworten via Matrix | ✅ Fertig |
| 29 | Kontaktbuch (ContactStore) | ✅ Fertig |
| 30 | Aufgabenliste (TodoStore) | ✅ Fertig |
| 31–35 | Morgen-Briefing, PWA-Dashboard, Harmony-Szenen, Musik-Streaming, Audio-Router | ✅ Fertig |
| 36–37 | Dashboard v2, Nextcloud-Integration | ✅ Fertig |
| 38 | Kontakte Vollintegration (Nextcloud CardDAV) | ✅ Fertig |
| 39 | Nextcloud als Datei-Hub | ✅ Fertig |
| 40.1 | Sprachsteuerung via Alexa Custom Skill | ✅ Fertig |

Vollständige Roadmap mit Details: **[PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md)**

## Projektfamilie

- [last-strawberry.com](https://last-strawberry.com)
- last-strawberry-DnD
- Gym-Berry
- **Elder-Berry** ← du bist hier
