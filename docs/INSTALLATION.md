# Installation

## Schnellstart (empfohlen)

Der einfachste Weg: **Bootstrap-Script** ausführen. Es klont das Repo,
erstellt die venv, installiert alle Dependencies und startet den Setup-Wizard.

### Windows (PowerShell)

```powershell
# PowerShell als Admin öffnen, dann:
powershell -ExecutionPolicy Bypass -File install.ps1
```

### Linux / RPi5 (Bash)

```bash
bash install.sh
```

Der **Setup-Wizard** öffnet sich automatisch im Browser (`http://localhost:8090/setup`)
und führt Schritt für Schritt durch die Konfiguration aller Dienste.

---

## Manuelle Installation

Falls du die Schritte lieber einzeln ausführen möchtest:

### Voraussetzungen

- **Python 3.12+** (Windows) oder **Python 3.13** (RPi5 Bookworm)
- **Git**
- **GPU empfohlen**: NVIDIA mit CUDA (für TTS + STT)
- **ffmpeg**: Für Audio-Konvertierung (`winget install ffmpeg`)

### 1. Repository klonen

```bash
git clone https://github.com/Leratos/Elder-Berry.git
cd Elder-Berry
```

### 2. Virtuelle Umgebung erstellen

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS
```

**Wichtig**: Immer `python` statt `py` verwenden wenn die venv aktiv ist.
`py` ist der Python Launcher und ignoriert die virtuelle Umgebung.

### 3. Pakete installieren

Elder-Berry nutzt optionale Dependency-Gruppen. Für den Tower empfiehlt sich die Vollinstallation:

```bash
# Vollinstallation (Tower) – enthält Matrix, TTS/STT, Windows-Extras
pip install -e ".[tower]"
```

#### Einzelne Gruppen

```bash
pip install -e "."                # Kern (LLM, FastAPI, SecretStore)
pip install -e ".[windows]"      # PC-Steuerung (pyautogui, pycaw)
pip install -e ".[tts-neural]"   # XTTS v2 Voice Cloning (coqui-tts, CUDA)
pip install -e ".[avatar]"       # Avatar-Display (pygame)
pip install -e ".[matrix]"       # Matrix-Integration (matrix-nio, aiofiles)
pip install -e ".[remote]"       # Remote-Features (mss, pyperclip)
pip install -e ".[memory]"       # RAG-Gedächtnis (chromadb)
pip install -e ".[stt]"          # Spracherkennung lokal (faster-whisper)
pip install -e ".[tools]"        # Assistent-Tools (Google Calendar OAuth2)
pip install -e ".[documents]"    # Dokument-Zusammenfassung (pymupdf)
pip install -e ".[computer-use]" # Computer Use Vision (Pillow, mss)
pip install -e ".[web]"          # Web-Zusammenfassung (trafilatura, bs4)
pip install -e ".[nextcloud]"    # CalDAV + CardDAV (caldav, vobject)
pip install -e ".[harmony]"      # Harmony Hub (aioharmony)
pip install -e ".[robot]"        # RPi5-Kommunikation (kein Extra-Paket nötig)
pip install -e ".[agent]"        # Laptop-Agent-Server (multipart, sounddevice)
# Metapaket-Gruppen:
pip install -e ".[tower]"        # Vollinstallation Tower (Windows + TTS/STT + Matrix + Remote)
pip install -e ".[server]"       # Vollinstallation Server (Matrix + Cloud-Tools)
```

### 4. Ollama (optionaler Offline-Fallback)

```bash
# Ollama installieren: https://ollama.ai
ollama serve
ollama pull phi4:14b           # LLM-Fallback
ollama pull nomic-embed-text   # Embedding-Modell für RAG-Memory
```

### 5. API-Keys & Accounts

| Dienst | Benötigt? | Registrierung | Kosten |
|---|---|---|---|
| **Anthropic** | Ja (primäres LLM) | [console.anthropic.com](https://console.anthropic.com) | Pay-per-use (~$3/MTok Sonnet) |
| **Matrix-Server** | Ja (Remote-Features) | Selbst-gehostet (Synapse) oder öffentlich | Kostenlos (self-hosted) |
| **ElevenLabs** | Optional (Cloud-TTS) | [elevenlabs.io](https://elevenlabs.io) | Freies Kontingent, dann ~€22/Monat |
| **Groq** | Optional (Cloud-STT) | [console.groq.com](https://console.groq.com) | Kostenlos (großzügiges Limit) |
| **Nextcloud** | Optional (CalDAV, CardDAV, Dateien) | Selbst-gehostet | Kostenlos (self-hosted) |
| **Google Calendar** | Optional (Fallback-Kalender) | [console.cloud.google.com](https://console.cloud.google.com) (OAuth2) | Kostenlos |
| **Brave Search** | Optional | [brave.com/search/api](https://brave.com/search/api/) | $5 monatliches Guthaben |
| **E-Mail (IMAP/SMTP)** | Optional | Beliebiger Anbieter (Strato, GMX, Gmail, ...) | Kostenlos |
| **Berry-Gym** | Optional | Interne REST API | Kostenlos |
| **Open-Meteo** | Optional (Wetter) | Keine Registrierung nötig | Kostenlos |
| **Ollama** | Optional (Offline) | Lokale Installation | Kostenlos |

### 6. Secrets konfigurieren

**Empfohlen: Setup-Wizard** – Der Wizard konfiguriert alle Secrets interaktiv:

```bash
python scripts/setup_wizard.py
# Öffnet http://localhost:8090/setup im Browser
```

Der Setup-Wizard startet auch automatisch beim ersten Start von Saleria,
wenn noch keine Matrix-Konfiguration vorhanden ist.

**Alternativ: Manuell per Python** – Alle Credentials werden verschlüsselt
im SecretStore gespeichert (Fernet-Verschlüsselung):

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

# ElevenLabs (Cloud-TTS, primäre Sprachausgabe)
store.set("elevenlabs_api_key", "sk_...")
store.set("elevenlabs_voice_id", "...")  # Voice-ID aus ElevenLabs Dashboard

# Groq (Cloud-STT, primäre Spracherkennung)
store.set("groq_api_key", "gsk_...")

# Nextcloud (CalDAV, CardDAV, Datei-Hub)
store.set("nextcloud_url", "https://nextcloud.example.com")
store.set("nextcloud_user", "dein-user")
store.set("nextcloud_app_password", "xxxx-xxxx-xxxx-xxxx")  # App-Passwort aus Nextcloud-Einstellungen

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

### 7. Starten

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

### 8. Setup-Scripts

| Script | Zweck |
|---|---|
| `scripts/setup_wizard.py` | Setup-Wizard im Browser (alle Dienste konfigurieren) |
| `scripts/setup_email.py` | E-Mail (IMAP + SMTP) interaktiv konfigurieren |
| `scripts/setup_google_oauth.py` | Google Calendar OAuth2 einrichten |
| `scripts/set_dashboard_password.py` | Dashboard-Passwort setzen (bcrypt, mind. 12 Zeichen) |
| `scripts/generate_plugin.py` | Plugin-Wizard – legt ein neues Command-Plugin in `~/.elder-berry/plugins/` an (Phase 77). Details in [USAGE.md](USAGE.md). |
| `scripts/check_public_readiness.py` | Audit gegen `.public-readiness-blocklist.txt`; läuft auch als pre-push-Hook. |

### 9. Alexa Sprachsteuerung (optional)

Saleria kann über einen Amazon Echo per Sprache gesteuert werden (Harmony Hub Befehle).

**Voraussetzungen:**

- Amazon Developer Account (gleicher Account wie auf dem Echo)
- Öffentlich erreichbarer HTTPS-Endpoint (Rootserver)
- SSH-Tunnel vom RPi5 zum Rootserver

**Einrichtung:**

1. **SSH-Tunnel**: RPi5 → Rootserver (systemd-Service, Reverse Tunnel auf Port 8765)
2. **Nginx**: `location /alexa/ { proxy_pass http://127.0.0.1:8765/; }` auf dem Rootserver
3. **Alexa Skill**: Custom Skill in der [Amazon Developer Console](https://developer.amazon.com/alexa/console/ask) anlegen
   - Invocation Name: `meine saleria`
   - Endpoint: `https://<rootserver>/alexa/saleria` (HTTPS)
   - Intents: TVAnIntent, MusikAnIntent, GamingAnIntent, AllesAusIntent, LauterIntent, LeiserIntent, StummIntent, StatusIntent

Der Skill bleibt im Development-Modus (nur auf eigenem Echo nutzbar, kein Store-Publishing nötig).

#### 9.1 Request-Verifikation einrichten (A1 – empfohlen)

Ohne Verifikation akzeptiert der `/saleria`-Endpoint jeden HTTP-POST – also auch Anfragen,
die nicht von Amazon stammen. Der `AlexaRequestVerifier` schließt diese Lücke:
Er prüft Zertifikat, RSA-Signatur, Timestamp und Skill-ID jedes eingehenden Requests.

**Schritt 1 – Skill-ID ermitteln**

In der [Amazon Developer Console](https://developer.amazon.com/alexa/console/ask) den Skill öffnen →
**Build → Endpoint**. Die Skill-ID beginnt mit `amzn1.ask.skill.` und steht direkt über
dem Endpoint-Feld.

**Schritt 2 – Skill-ID im SecretStore speichern**

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()
store.set("alexa_skill_id", "amzn1.ask.skill.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
```

**Schritt 3 – Verifier in `scripts/start_rpi5.py` aktivieren**

Den Block `# -- RobotServer` in `start_rpi5.py` wie folgt ergänzen:

```python
from elder_berry.robot.alexa_skill_handler import AlexaRequestVerifier
from elder_berry.core.secret_store import SecretStore

# Skill-ID aus SecretStore lesen (None = Verifikation deaktiviert)
_skill_id = SecretStore().get("alexa_skill_id")
alexa_verifier = AlexaRequestVerifier(application_id=_skill_id) if _skill_id else None

server = RobotServer(
    motors=motors,
    avatar=avatar,
    sensors=sensors,
    camera=camera,
    turntable=turntable,
    harmony=harmony,
    hostname="elder-berry-rpi5",
    project_root=project_root,
    service_name="elder-berry",
    alexa_verifier=alexa_verifier,   # ← neu
)
```

**Schritt 4 – Verifikation testen**

Ein Request ohne gültige Amazon-Signatur muss jetzt mit HTTP 401 abgelehnt werden:

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://<rootserver>/alexa/saleria \
  -H "Content-Type: application/json" \
  -d '{"version":"1.0","session":{},"request":{"type":"LaunchRequest"}}'
# Erwartete Ausgabe: 401
```

Ein echter Echo-Request (mit den Amazon-Headern `Signature` und `SignatureCertChainUrl`)
wird weiterhin durchgelassen.

> **Hinweis**: Ohne `alexa_verifier` (bzw. `application_id=None`) bleibt der Endpoint
> funktionsfähig, aber offen. Für Produktivbetrieb wird die Verifikation dringend empfohlen.

### LLM-Strategie

| Modus | Modell | Einsatz |
|---|---|---|
| Primär | Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`) | Gespräch, PC-Steuerung, alle Aufgaben |
| Fallback | Ollama phi4:14b | Offline-Modus, kein Internet nötig |
| Agent | Anthropic Claude Sonnet 4.6 | Komplexe Aufgaben via Matrix (Journal, Docs, Tests) |

### TTS-Strategie

| Modus | Backend | Einsatz |
|---|---|---|
| Primär | ElevenLabs Cloud-TTS | Qualitätsstimme, `elevenlabs_api_key` + `elevenlabs_voice_id` erforderlich |
| Fallback | Coqui XTTS v2 | Lokales Voice Cloning, CUDA empfohlen, `[tts-neural]` erforderlich |
| Notfall | Windows SAPI | Immer verfügbar (keine Extras), schlechteste Qualität |

### STT-Strategie

| Modus | Backend | Einsatz |
|---|---|---|
| Primär | Groq Whisper API | Schnell, kostenlos im großzügigen Limit, `groq_api_key` erforderlich |
| Fallback | Faster Whisper lokal | GPU-beschleunigt, `[stt]` erforderlich |
