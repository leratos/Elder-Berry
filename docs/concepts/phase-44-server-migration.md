# Phase 44 – Server-Migration & Audio-Router

## Übersicht

Saleria zieht vom Tower auf den Rootserver. Der Bot läuft 24/7
unabhängig davon ob Tower oder RPi5 erreichbar sind. Tower wird
zum optionalen Dienst für PC-Steuerung und Audio-Fallback.

### Ist-Zustand (aktuell)

```
Tower (Windows, on-demand)
├── Saleria Bot (start_saleria.py) ← BRAIN
├── Ollama LLM (phi4:14b, llava:7b)
├── Anthropic API Client
├── XTTS v2 TTS
├── FasterWhisper STT
├── WindowsActionController
├── Computer Use
├── SQLite DBs (Notes, Todos, Contacts, Reminders, Actions)
├── ChromaDB (RAG Memory)
├── SecretStore
└── Matrix Bot (matrix-nio)
       │
       ├── REST → RPi5 (192.168.50.220:8000)
       │         ├── Camera, Display, Turntable
       │         ├── HarmonyAdapter, Sensors
       │         └── Alexa Skill Handler
       │
       └── Matrix → Rootserver (matrix.last-strawberry.com)
                   ├── Synapse
                   ├── Nextcloud
                   ├── Stirling-PDF
                   └── Dashboard PWA
```

**Problem**: Tower aus → Saleria komplett offline. Keine Erinnerungen,
kein Briefing, keine Kalender-Alerts, keine Matrix-Antworten.

### Soll-Zustand (nach Migration)

```
Rootserver (Strato, 24/7) ← BRAIN
├── Saleria Bot (start_saleria.py)
├── Anthropic API (Sonnet, primäres LLM)
├── ElevenLabs TTS (primär)
├── Whisper API / Groq STT (primär, für Sprachnachrichten)
├── SQLite DBs (Notes, Todos, Contacts, Reminders, Actions)
├── ChromaDB (RAG Memory, sentence-transformers CPU)
├── SecretStore
├── Matrix Bot (matrix-nio)
├── DocumentClassifier (Anthropic Vision statt Ollama)
├── Stirling-PDF (OCR, bereits da)
├── Nextcloud (bereits da)
├── Dashboard PWA (bereits da)
│
├── SSH-Tunnel → RPi5
│   ├── Camera, Display, Turntable
│   ├── HarmonyAdapter, Sensors
│   └── Alexa Skill Handler
│
└── Heartbeat → Tower (optional, wenn online)
    ├── WindowsActionController
    ├── Computer Use
    ├── XTTS v2 TTS (Fallback)
    └── FasterWhisper STT (Fallback)
```

**Gewinn**: Saleria läuft 24/7. Tower-Ausfall = nur PC-Steuerung
und lokales Audio fallen weg. Alles andere funktioniert weiter.

---

## Architektur-Entscheidungen

### 1. LLM-Strategie (vereinfacht)

**Vorher**: Anthropic API (primär) + Ollama phi4:14b (Offline-Fallback)
**Nachher**: Anthropic API (einzig). Server hat stabiles Internet,
Offline-Fallback entfällt. Ollama auf Tower bleibt optional für
lokale Experimente, aber nicht mehr im Bot-Pfad.

**Konsequenz**: OllamaClient bleibt im Code (für Tower-Agent),
wird aber vom Server-Bot nicht mehr genutzt. LLMRouter-Logik
vereinfacht sich: kein Fallback-Switching mehr nötig.

### 2. TTS – ElevenLabs primär, XTTS v2 Fallback

Neue Klasse: `TTSRouter`

```python
class TTSRouter:
    """Wählt TTS-Engine basierend auf Verfügbarkeit."""
    
    def __init__(self, elevenlabs: ElevenLabsClient, tower_agent: TowerAgent):
        self._elevenlabs = elevenlabs
        self._tower = tower_agent
    
    async def synthesize(self, text: str, emotion: str = "neutral") -> bytes:
        """ElevenLabs primär, XTTS v2 via Tower als Fallback."""
        try:
            return await self._elevenlabs.synthesize(text)
        except ElevenLabsError:
            if self._tower.is_online:
                return await self._tower.tts(text, emotion)
            raise TTSUnavailableError("Kein TTS verfügbar")
```

**ElevenLabsClient** (`tools/elevenlabs_client.py`):
- REST API: POST /v1/text-to-speech/{voice_id}
- Model: eleven_multilingual_v2 (Standard) oder eleven_flash_v2_5 (schnell)
- Voice-ID aus SecretStore (vorher in ElevenLabs UI konfiguriert)
- Rückgabe: MP3-Bytes → AudioConverter → OGG/Opus für Matrix
- SecretStore Keys: `elevenlabs_api_key`, `elevenlabs_voice_id`

**Tier**: Creator ($22/Monat), 100.000 Credits/Monat

### 3. STT – Cloud primär, lokal Fallback

Neue Klasse: `STTRouter`

```python
class STTRouter:
    """Wählt STT-Engine basierend auf Verfügbarkeit."""
    
    def __init__(self, cloud_stt: CloudSTTClient, tower_agent: TowerAgent):
        self._cloud = cloud_stt
        self._tower = tower_agent
    
    async def transcribe(self, audio_bytes: bytes) -> str:
        """Cloud-STT primär, lokales Whisper via Tower als Fallback."""
        try:
            return await self._cloud.transcribe(audio_bytes)
        except CloudSTTError:
            if self._tower.is_online:
                return await self._tower.stt(audio_bytes)
            raise STTUnavailableError("Kein STT verfügbar")
```

**CloudSTTClient** (`tools/cloud_stt_client.py`):
- Groq Whisper API (kostenlos im Free Tier, Whisper large-v3)
- Fallback: OpenAI Whisper API ($0.006/min)
- Input: OGG/Opus aus Matrix-Sprachnachricht
- SecretStore Keys: `groq_api_key` (optional: `openai_api_key`)

### 4. DocumentClassifier – Anthropic statt Ollama

**Vorher**: Ollama phi4:14b (Klassifikation) + Ollama llava:7b (Bild-Analyse)
**Nachher**: Anthropic API für beides (Sonnet 4.6 mit Vision)

Änderungen in `document_classifier.py`:
- `_classify_text()`: AnthropicClient.ask() statt OllamaClient.generate()
- `_analyze_image()`: AnthropicClient.describe_image() statt OllamaClient.generate_with_image()
- OllamaClient-Dependency entfällt komplett aus DocumentClassifier
- OCR bleibt Stirling-PDF (läuft auf demselben Server, noch schneller)

**Vorteil**: Bessere Klassifikations-Qualität (Sonnet > phi4:14b)
**Kosten**: ~1-2 Cent pro Dokument (Text ~500 Tokens, Bild ~2000 Tokens)
**Privatsphäre**: Vertretbar – Anthropic sieht ohnehin alle Konversationen

### 5. ChromaDB / RAG Memory – Embedding ohne Ollama

**Problem**: ChromaDB nutzt OllamaEmbeddingClient (nomic-embed-text, 768-dim).
Ollama gibt es auf dem Server nicht.

**Lösung**: `sentence-transformers` mit `all-MiniLM-L6-v2` (384-dim, CPU-only)
- ~80 MB Modell, braucht kein GPU
- Inference: <50ms pro Embedding auf Xeon
- Neuer EmbeddingClient der sentence-transformers nutzt statt Ollama
- **Einmaliger Aufwand**: ChromaDB Collection muss neu gebaut werden
  (alte 768-dim Embeddings inkompatibel mit neuen 384-dim)
- Bestehende Conversations bleiben erhalten, nur Embeddings werden neu berechnet

Alternative: `nomic-embed-text` via Ollama auf Server installieren (CPU, ~300ms/Embed).
Größerer Aufwand, gleiche Dimension (768), kein Rebuild nötig.

**Empfehlung**: Ollama auf dem Server installieren, nur für Embeddings.
Kein GPU nötig, nomic-embed-text ist klein (274 MB). Gleiche Dimension,
kein ChromaDB-Rebuild, kein Code-Änderung am EmbeddingClient.

### 6. RPi5-Konnektivität

**Problem**: Tower erreicht RPi5 im LAN (192.168.50.220:8000).
Server steht im Rechenzentrum, kein LAN-Zugriff.

**Lösung**: SSH Reverse Tunnel (RPi5 → Server), autossh.
Bereits eingerichtet für Alexa (Port 12768 → RPi5:8000).

Prüfung ob der bestehende Tunnel für den Bot ausreicht:
- Aktuell: Nginx → localhost:12768 → RPi5:8000 (nur /alexa/ Pfad)
- Neu: Bot → localhost:12768 → RPi5:8000 (alle Endpoints)
- **Kein neuer Tunnel nötig** – der bestehende Tunnel ist port-basiert,
  nicht pfad-basiert. Der Bot kann direkt auf localhost:12768 zugreifen.

RobotClient-Anpassung:
```python
# Vorher (Tower → RPi5 direkt):
robot_host = "192.168.50.220:8000"

# Nachher (Server → RPi5 via Tunnel):
robot_host = "127.0.0.1:12768"
```

### 7. Tower als optionaler Agent

Neue Klasse: `TowerAgent` (ersetzt direkte WindowsActionController-Aufrufe)

Der Tower exponiert einen leichtgewichtigen FastAPI-Server (analog zum RPi5).
Der Bot auf dem Server ruft Tower-Dienste per HTTP auf – wenn verfügbar.

```python
class TowerAgent:
    """Proxy für Tower-Dienste (PC-Steuerung, Audio-Fallback)."""
    
    def __init__(self, tower_host: str, timeout: float = 3.0):
        self._host = tower_host  # z.B. 127.0.0.1:12769 via SSH-Tunnel
        self._timeout = timeout
        self._online = False
    
    @property
    def is_online(self) -> bool:
        return self._online
    
    async def heartbeat(self) -> bool:
        """Prüft ob Tower erreichbar ist. Wird periodisch aufgerufen."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(f"http://{self._host}/status")
                self._online = r.status_code == 200
        except Exception:
            self._online = False
        return self._online
    
    async def tts(self, text: str, emotion: str) -> bytes:
        """XTTS v2 auf Tower."""
        ...
    
    async def stt(self, audio: bytes) -> str:
        """FasterWhisper auf Tower."""
        ...
    
    async def execute_action(self, action: dict) -> dict:
        """WindowsActionController / Computer Use."""
        ...
    
    async def screenshot(self) -> bytes:
        """Screenshot vom Tower-Desktop."""
        ...
```

Tower-FastAPI-Endpoints (neuer Service auf Tower):
- GET /status → Heartbeat
- POST /tts → XTTS v2 Synthese
- POST /stt → FasterWhisper Transkription
- POST /action → WindowsActionController Befehl
- GET /screenshot → Desktop-Screenshot

**Konnektivität**: SSH Reverse Tunnel Tower → Server (analog RPi5).
Tower baut Tunnel auf wenn er startet, Server merkt via Heartbeat ob er da ist.

---

## Deployment-Strategie

### Server-Setup

**Pfad**: `/opt/elder-berry/` (analog zu `/opt/matrix/`)
**User**: `lera` (bestehend, sudo-fähig)
**Python**: 3.12 (bereits installiert)
**venv**: `/opt/elder-berry/.venv/`
**systemd**: `/etc/systemd/system/elder-berry.service`

```ini
[Unit]
Description=Elder-Berry Saleria Bot
After=network.target mariadb.service docker.service
Wants=network-online.target

[Service]
Type=simple
User=lera
Group=psacln
WorkingDirectory=/opt/elder-berry
Environment="PATH=/opt/elder-berry/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=/opt/elder-berry/.venv/bin/python -m elder_berry.scripts.start_saleria --mode matrix
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Git-basiertes Deployment

```bash
# Einmalig:
cd /opt
sudo git clone https://github.com/<user>/elder-berry.git
sudo chown -R lera:psacln elder-berry/
cd elder-berry
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[server]"  # neue optional-group ohne GPU-deps

# Update (identisch zum bestehenden "update" Command):
cd /opt/elder-berry && git pull && pip install -e ".[server]"
sudo systemctl restart elder-berry
```

### pyproject.toml – neue Optional-Group `[server]`

Auf dem Server werden GPU-abhängige Pakete NICHT installiert:

```toml
[project.optional-dependencies]
# Bestehend (Tower):
gpu = ["faster-whisper", "TTS", "torch", "torchaudio"]

# Neu (Server – ohne GPU, ohne lokales TTS/STT):
server = [
    "anthropic",
    "httpx",
    "matrix-nio[e2e]",
    "aiosqlite",
    "chromadb",
    "sentence-transformers",  # falls Ollama nicht auf Server
    "pymupdf",
    "trafilatura",
    "beautifulsoup4",
    "pyyaml",
    "cryptography",           # SecretStore (Fernet)
    "caldav",
    "vdirsyncer",
    "icalendar",
    "webdav4",
    "Pillow",
    "pydub",                  # AudioConverter
]
```

### Daten-Migration

Folgende Dateien müssen vom Tower auf den Server kopiert werden:

| Datei | Tower-Pfad | Server-Pfad |
|-------|------------|-------------|
| SecretStore | `data/secrets.db` | `/opt/elder-berry/data/secrets.db` |
| NoteStore | `data/notes.db` | `/opt/elder-berry/data/notes.db` |
| TodoStore | `data/todos.db` | `/opt/elder-berry/data/todos.db` |
| ContactStore | `data/contacts.db` | `/opt/elder-berry/data/contacts.db` |
| ReminderStore | `data/reminders.db` | `/opt/elder-berry/data/reminders.db` |
| ActionsDB | `data/actions.db` | `/opt/elder-berry/data/actions.db` |
| ChromaDB | `data/chroma/` | `/opt/elder-berry/data/chroma/` |
| Character YAML | `config/saleria.yml` | `/opt/elder-berry/config/saleria.yml` |
| Speaker WAVs | `assets/speakers/` | nicht nötig (ElevenLabs) |

**SecretStore**: Schlüssel müssen auf dem Server neu gesetzt werden
(Fernet-Key ist maschinengebunden). Neue Keys:
- `elevenlabs_api_key`, `elevenlabs_voice_id`
- `groq_api_key`
- Bestehende Keys (anthropic, brave, nextcloud etc.) neu eingeben

**ChromaDB**: Wenn Embedding-Modell wechselt (768→384 dim),
muss Collection neu aufgebaut werden. Bei gleicher Dimension (Ollama
auf Server) → Verzeichnis 1:1 kopieren.

### Pfad-Handling

Der Code verwendet bereits `pathlib.Path` an den meisten Stellen.
Kritische Anpassungen:

1. **Basis-Pfad**: Neue Umgebungsvariable `ELDER_BERRY_HOME`
   - Tower: `C:\Dev\Elder-Berry`
   - Server: `/opt/elder-berry`
   - Alle relativen Pfade (`data/`, `config/`, `assets/`) werden
     relativ zu `ELDER_BERRY_HOME` aufgelöst

2. **SecretStore Pfade**: Einige gespeicherte Pfade enthalten
   Windows-Pfade (`C:\Dev\...`). Diese müssen plattformunabhängig
   oder relativ gespeichert werden.

3. **RobotClient**: Host wechselt von `192.168.50.220:8000` auf
   `127.0.0.1:<tunnel-port>`. Konfigurierbar via SecretStore
   (`robot_host`) – bereits so implementiert.

---

## Code-Änderungen (Übersicht)

### Neue Klassen

| Klasse | Datei | Beschreibung |
|--------|-------|--------------|
| ElevenLabsClient | `tools/elevenlabs_client.py` | ElevenLabs TTS API |
| CloudSTTClient | `tools/cloud_stt_client.py` | Groq/OpenAI Whisper API |
| TTSRouter | `core/tts_router.py` | ElevenLabs → XTTS v2 Fallback |
| STTRouter | `core/stt_router.py` | Cloud STT → lokales Whisper Fallback |
| TowerAgent | `core/tower_agent.py` | Proxy für Tower-Dienste |
| TowerServer | `tower/tower_server.py` | FastAPI auf Tower (TTS/STT/Actions) |

### Geänderte Klassen

| Klasse | Änderung |
|--------|----------|
| DocumentClassifier | OllamaClient → AnthropicClient für Klassifikation + Vision |
| AudioPipeline | CoquiTTSEngine → TTSRouter |
| MessageHandlers | FasterWhisperEngine → STTRouter |
| Assistant | LLMRouter vereinfachen (kein Ollama-Fallback) |
| start_saleria.py | Plattform-Erkennung, Server-Modus, DI-Anpassung |
| SelfcheckCommandHandler | Tower-Status als "optional" anzeigen |

### Entfallende Dependencies auf Server

- `TTS` (Coqui XTTS v2)
- `torch`, `torchaudio`
- `faster-whisper`
- `pyautogui` (WindowsActionController)
- `mss` (Screenshots)
- `pygame-ce` (Avatar)

---

## Unterphasen

| Phase | Titel | Beschreibung |
|-------|-------|--------------|
| 44.1 | ElevenLabsClient + TTSRouter | TTS-Abstraktion, ElevenLabs API, Fallback-Logik |
| 44.2 | CloudSTTClient + STTRouter | STT-Abstraktion, Groq API, Fallback-Logik |
| 44.3 | DocumentClassifier Umbau | Ollama → Anthropic Vision für Klassifikation + Bildanalyse |
| 44.4 | TowerAgent + TowerServer | Tower als optionaler Service, FastAPI, SSH-Tunnel |
| 44.5 | Server-Deploy | Git Clone, venv, systemd, Daten-Migration, SecretStore |
| 44.6 | Integration + Cutover | Server-Bot live, Tower-Bot deaktivieren, Monitoring |

### 44.1 – ElevenLabsClient + TTSRouter

**ElevenLabsClient** (`tools/elevenlabs_client.py`):
```python
class ElevenLabsClient:
    BASE_URL = "https://api.elevenlabs.io/v1"
    
    def __init__(self, api_key: str, voice_id: str,
                 model: str = "eleven_multilingual_v2"):
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
    
    async def synthesize(self, text: str) -> bytes:
        """Text → MP3 Bytes."""
        url = f"{self.BASE_URL}/text-to-speech/{self._voice_id}"
        headers = {"xi-api-key": self._api_key}
        payload = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.content  # MP3 Bytes
    
    async def get_usage(self) -> dict:
        """Verbleibende Credits abfragen."""
        ...
```

**TTSRouter** (`core/tts_router.py`):
- ElevenLabs primär
- XTTS v2 via TowerAgent als Fallback
- Logging: welcher Pfad genutzt wird
- Monitoring: Credits-Stand bei jedem Aufruf loggen

**AudioPipeline Anpassung**:
- `_synthesize()` ruft TTSRouter statt CoquiTTSEngine
- MP3→OGG Konvertierung via pydub (ElevenLabs liefert MP3)
- Speaker-WAVs für Emotionen entfallen (ElevenLabs hat eigene Voice)

**Tests**: ~20 (ElevenLabsClient Mock + TTSRouter Fallback-Logik)

### 44.2 – CloudSTTClient + STTRouter

**CloudSTTClient** (`tools/cloud_stt_client.py`):
```python
class CloudSTTClient:
    """Groq Whisper API (primär), OpenAI Whisper (Fallback)."""
    
    GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    
    async def transcribe(self, audio_bytes: bytes,
                         language: str = "de") -> str:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {"file": ("audio.ogg", audio_bytes, "audio/ogg")}
        data = {"model": "whisper-large-v3", "language": language}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(self.GROQ_URL, headers=headers,
                                  files=files, data=data)
            r.raise_for_status()
            return r.json()["text"]
```

**STTRouter** (`core/stt_router.py`):
- Cloud-STT primär (Groq → OpenAI Fallback)
- Lokales Whisper via TowerAgent als letzter Fallback
- Spracherkennung: Groq erkennt Sprache automatisch

**MessageHandlers Anpassung**:
- `_handle_audio()` ruft STTRouter statt FasterWhisperEngine
- FasterWhisperEngine wird nicht mehr direkt importiert

**Tests**: ~15 (CloudSTTClient Mock + STTRouter Fallback-Logik)

### 44.3 – DocumentClassifier Umbau

Änderungen in `document_classifier.py`:

```python
# Vorher:
class DocumentClassifier:
    def __init__(self, ollama: OllamaClient, reader: DocumentReader,
                 stirling: StirlingPDFClient | None = None):

# Nachher:
class DocumentClassifier:
    def __init__(self, anthropic: AnthropicClient, reader: DocumentReader,
                 stirling: StirlingPDFClient | None = None):
```

- `_classify_text()`: `self._anthropic.ask(prompt)` statt `self._ollama.generate(prompt)`
- `_analyze_image()`: `self._anthropic.describe_image(base64_img, prompt)` statt
  `self._ollama.generate_with_image(base64_img, prompt)`
- Prompt bleibt identisch (Kategorie + Datum + Beschreibung extrahieren)
- AnthropicClient.describe_image() existiert bereits (Phase 26)

**Tests**: Bestehende 23 Tests anpassen (Mock OllamaClient → Mock AnthropicClient)

### 44.4 – TowerAgent + TowerServer

**TowerServer** (`tower/tower_server.py`) – neuer FastAPI-Service auf dem Tower:

```python
app = FastAPI(title="Elder-Berry Tower Agent")

@app.get("/status")
async def status():
    return {"online": True, "hostname": socket.gethostname()}

@app.post("/tts")
async def tts(request: TTSRequest):
    audio = coqui_engine.synthesize(request.text, request.emotion)
    return Response(content=audio, media_type="audio/wav")

@app.post("/stt")
async def stt(file: UploadFile):
    text = whisper_engine.transcribe(await file.read())
    return {"text": text}

@app.post("/action")
async def action(request: ActionRequest):
    result = action_controller.execute(request.action, request.params)
    return result

@app.get("/screenshot")
async def screenshot():
    img_bytes = screenshot_service.capture()
    return Response(content=img_bytes, media_type="image/png")
```

**SSH Reverse Tunnel (Tower → Server)**:
```bash
# Auf Tower (autossh, systemd oder Task Scheduler):
ssh -N -R 12769:localhost:8090 lera@last-strawberry.com
```
→ Server erreicht Tower unter `127.0.0.1:12769`

**Tests**: ~25 (TowerAgent Heartbeat, Fallback bei Offline, TowerServer Endpoints)

### 44.5 – Server-Deploy

Schritt-für-Schritt (als root / sudo):

1. **Repository klonen**:
   ```bash
   cd /opt && git clone <repo-url> elder-berry
   chown -R lera:psacln elder-berry/
   ```

2. **venv + Dependencies**:
   ```bash
   cd /opt/elder-berry
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[server]"
   ```

3. **Ollama für Embeddings** (falls gewählt):
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull nomic-embed-text
   # Läuft auf CPU, braucht ~500 MB RAM
   ```

4. **Daten migrieren** (von Tower via SCP):
   ```bash
   scp -r lera@<tower-ip>:/path/to/data/* /opt/elder-berry/data/
   ```

5. **SecretStore neu initialisieren**:
   ```bash
   cd /opt/elder-berry
   python -m elder_berry.tools.setup_secrets
   # Alle Keys neu eingeben (Fernet-Key ist maschinengebunden)
   ```

6. **systemd Service**:
   ```bash
   cp server/elder-berry.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable elder-berry
   systemctl start elder-berry
   journalctl -u elder-berry -f  # Logs prüfen
   ```

7. **SSH-Tunnel für RPi5 verifizieren**:
   ```bash
   curl http://127.0.0.1:12768/status  # RPi5 erreichbar?
   ```

### 44.6 – Integration + Cutover

1. **Parallelbetrieb** (1-2 Tage):
   - Server-Bot läuft in separatem Matrix-Room (Test)
   - Tower-Bot bleibt aktiv im Haupt-Room
   - Vergleich: gleiche Befehle, gleiche Ergebnisse?

2. **Cutover**:
   - Tower-Bot stoppen
   - Server-Bot auf Haupt-Room umschalten
   - `update` Command anpassen: `git pull` auf Server statt Tower

3. **Tower-Bot → Tower-Agent**:
   - `start_saleria.py --mode agent` startet nur TowerServer
   - Kein Matrix-Bot, kein LLM, nur FastAPI für TTS/STT/Actions
   - Autostart via Task Scheduler (bei Windows-Login)

4. **Monitoring**:
   - SelfcheckCommandHandler: Tower-Status als optional (✅/➖)
   - ElevenLabs Credits-Verbrauch im Briefing
   - `journalctl -u elder-berry` für Server-Logs

---

## Risiken und Gegenmaßnahmen

| Risiko | Schwere | Gegenmaßnahme |
|--------|---------|----------------|
| Server-Ausfall (Strato) | Hoch | BorgBackup (bereits aktiv), Strato-SLA 99.9% |
| ElevenLabs API down | Mittel | TTSRouter → XTTS v2 Fallback via Tower |
| Groq API down | Mittel | STTRouter → OpenAI → Tower Whisper Fallback |
| Anthropic API down | Hoch | Kein Fallback für LLM (bewusste Entscheidung) |
| SSH-Tunnel bricht ab | Mittel | autossh mit Auto-Reconnect, Heartbeat-Check |
| ElevenLabs Credits aufgebraucht | Niedrig | TTSRouter → XTTS v2 Fallback, Monitoring im Briefing |
| ChromaDB Embedding-Inkompatibilität | Einmalig | Rebuild bei Modellwechsel, oder Ollama auf Server |
| SecretStore Migration | Einmalig | Alle Keys manuell neu eingeben |

## Kosten (monatlich)

| Posten | Kosten | Anmerkung |
|--------|--------|-----------|
| Strato Rootserver | bereits vorhanden | Keine Mehrkosten |
| Hetzner Storage Box | €3,81 | Bereits aktiv (Backup) |
| ElevenLabs Creator | $22 (~€20) | 100.000 Credits/Monat |
| Groq Whisper | kostenlos | Free Tier |
| Anthropic API | ~€5-15 | Bereits vorhanden, leicht höher durch DocumentClassifier |
| **Gesamt Mehrkosten** | **~€20-25/Monat** | Nur ElevenLabs + minimal mehr API |

## Offene Fragen (vor Start klären)

- [ ] ElevenLabs Account erstellen, Voice-ID für Saleria festlegen
- [ ] Groq API Key besorgen (kostenlos)
- [ ] ChromaDB: Ollama auf Server (einfacher) oder sentence-transformers (kein Ollama)?
- [ ] Tower SSH-Tunnel: Port festlegen (Vorschlag: 12769)
- [ ] Repo-Zugriff auf Server: Deploy Key oder bestehender SSH-Key?
- [ ] BorgBackup erweitern: `/opt/elder-berry/data/` in Backup-Pfade aufnehmen

## Abgrenzung (nicht in dieser Phase)

- Emotion-basierte Voice-Varianten in ElevenLabs (spätere Phase)
- Wake Word auf Server (bleibt RPi5/Tower)
- Home Assistant Integration (nach Umzug)
- Multi-User Support (nicht geplant)
