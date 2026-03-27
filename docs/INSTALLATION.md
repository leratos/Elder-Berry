# Installation

## Voraussetzungen

- **Python 3.12+**
- **Windows 10/11** (Tower) – Linux für RPi5
- **GPU empfohlen**: NVIDIA mit CUDA (für TTS + STT)
- **ffmpeg**: Für Audio-Konvertierung (`winget install ffmpeg`)

## 1. Repository klonen

```bash
git clone https://github.com/leratos/Elder-Berry.git
cd Elder-Berry
```

## 2. Virtuelle Umgebung erstellen

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS
```

**Wichtig**: Immer `python` statt `py` verwenden wenn die venv aktiv ist.
`py` ist der Python Launcher und ignoriert die virtuelle Umgebung.

## 3. Pakete installieren

Elder-Berry nutzt optionale Dependency-Gruppen. Für den Tower empfiehlt sich die Vollinstallation:

```bash
# Vollinstallation (Tower)
pip install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"
pip install chromadb faster-whisper
```

### Einzelne Gruppen

```bash
pip install -e "."                # Kern (LLM, Aktions-DB)
pip install -e ".[windows]"      # PC-Steuerung (pyautogui, pycaw)
pip install -e ".[tts-neural]"   # XTTS v2 Voice Cloning (coqui-tts, CUDA)
pip install -e ".[avatar]"       # Avatar-Display (pygame)
pip install -e ".[matrix]"       # Matrix-Integration (matrix-nio, pydub)
pip install -e ".[remote]"       # Remote-Features (anthropic, mss, pyperclip)
pip install -e ".[memory]"       # RAG-Gedächtnis (chromadb)
pip install -e ".[stt]"          # Spracherkennung (faster-whisper)
pip install -e ".[tools]"        # Assistent-Tools (google-api, oauthlib)
pip install -e ".[documents]"    # Dokument-Zusammenfassung (pymupdf)
pip install -e ".[computer-use]" # Computer Use Vision (Pillow, mss)
pip install -e ".[robot]"        # RPi5-Kommunikation (fastapi, uvicorn)
pip install -e ".[agent]"        # Laptop-Agent-Server (fastapi, audio)
```

## 4. Ollama (optionaler Offline-Fallback)

```bash
# Ollama installieren: https://ollama.ai
ollama serve
ollama pull phi4:14b           # LLM-Fallback
ollama pull nomic-embed-text   # Embedding-Modell für RAG-Memory
```

## 5. API-Keys & Accounts

| Dienst | Benötigt? | Registrierung | Kosten |
|---|---|---|---|
| **Anthropic** | Ja (primäres LLM) | [console.anthropic.com](https://console.anthropic.com) | Pay-per-use (~$3/MTok Sonnet) |
| **Matrix-Server** | Ja (Remote-Features) | Selbst-gehostet (Synapse) oder öffentlich | Kostenlos (self-hosted) |
| **Google Calendar** | Optional | [console.cloud.google.com](https://console.cloud.google.com) (OAuth2) | Kostenlos |
| **Brave Search** | Optional | [brave.com/search/api](https://brave.com/search/api/) | $5 monatliches Guthaben |
| **E-Mail (IMAP/SMTP)** | Optional | Beliebiger Anbieter (Strato, GMX, Gmail, ...) | Kostenlos |
| **Berry-Gym** | Optional | Interne REST API | Kostenlos |
| **Open-Meteo** | Optional (Wetter) | Keine Registrierung nötig | Kostenlos |
| **Ollama** | Optional (Offline) | Lokale Installation | Kostenlos |

## 6. Secrets konfigurieren

Alle Credentials werden verschlüsselt im SecretStore gespeichert (Fernet-Verschlüsselung).

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()

# ══════════════════════════════════════
# PFLICHT
# ══════════════════════════════════════

# Anthropic (primäres LLM-Backend)
store.set("anthropic_api_key", "sk-ant-...")

# Matrix (für Remote-Features)
store.set("matrix_homeserver", "https://matrix.example.com")
store.set("matrix_user_id", "@saleria:matrix.example.com")
store.set("matrix_access_token", "syt_...")  # via /_matrix/client/v3/login
store.set("matrix_room_id", "!roomid:matrix.example.com")
store.set("matrix_allowed_senders", "@dein-user:matrix.example.com")

# ══════════════════════════════════════
# OPTIONAL
# ══════════════════════════════════════

# Brave Search (Web-Suche)
store.set("brave_api_key", "BSA...")

# Wetter (Open-Meteo, kein API-Key – nur Koordinaten)
store.set("weather_latitude", "52.52")
store.set("weather_longitude", "13.41")
store.set("weather_city", "Berlin")

# E-Mail (IMAP – beliebiger Anbieter)
store.set("email_imap_host", "imap.strato.de")
store.set("email_user", "du@example.com")
store.set("email_password", "...")

# E-Mail (SMTP – für Antworten, Phase 28)
# Am einfachsten via Setup-Script:
#   python scripts/setup_email.py
# Oder manuell:
store.set("smtp_host", "smtp.strato.de")
store.set("smtp_port", "465")

# Google Calendar
# OAuth2-Setup via Script:
#   python scripts/setup_google_oauth.py
# Speichert Tokens automatisch im SecretStore.

# Berry-Gym (Fitness-API)
store.set("berry_gym_api_token", "<token>")

# Wake-on-LAN
store.set("tower_mac_address", "AA:BB:CC:DD:EE:FF")

# RPi5 Avatar-Display
store.set("robot_host", "http://192.168.50.220:8000")
```

## 7. Starten

```bash
# Matrix-Modus (Standard – empfohlen)
python scripts/start_saleria.py

# Terminal-Modus (lokales Testen, kein Matrix nötig)
python scripts/start_saleria.py --mode terminal

# Voice-Modus (Mikrofon-Eingabe)
python scripts/start_saleria.py --mode voice

# Optionen
python scripts/start_saleria.py --no-memory        # Ohne RAG-Gedächtnis
python scripts/start_saleria.py --no-tts            # Ohne Sprachausgabe
python scripts/start_saleria.py --no-avatar         # Ohne Avatar
python scripts/start_saleria.py --whisper-model large-v3  # Besseres STT
python scripts/start_saleria.py --debug             # Debug-Logging
```

## 8. Setup-Scripts

| Script | Zweck |
|---|---|
| `scripts/setup_email.py` | E-Mail (IMAP + SMTP) interaktiv konfigurieren |
| `scripts/setup_google_oauth.py` | Google Calendar OAuth2 einrichten |

## LLM-Strategie

| Modus | Modell | Einsatz |
|---|---|---|
| Primär | Anthropic Sonnet 4.6 | Gespräch, PC-Steuerung, alle Aufgaben |
| Fallback | Ollama phi4:14b | Offline-Modus, kein Internet nötig |
| Agent | Anthropic Sonnet 4.6 | Komplexe Aufgaben via Matrix (Journal, Docs, Tests) |
