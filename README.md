# Elder-Berry

> Virtual AI Assistant with V-Tuber character, voice cloning and remote control.
> Part of the Last-Strawberry project family.

## Overview

Elder-Berry is a modular AI assistant built around a V-Tuber character named **Saleria Berry**.
She combines LLM processing (Anthropic + Ollama), voice cloning (XTTS v2), emotion-driven
avatar rendering, PC control, speech recognition and remote access via Matrix into a single
cohesive system.

Saleria is designed as a stationary desk companion with a Pepper's Ghost hologram display
inside a 3D-printed elderberry tree trunk enclosure.

## What Saleria Can Do

### Local (PC)

- **Conversation** with personality, emotion tagging and sarcasm
- **Voice output** via Coqui XTTS v2 voice cloning (10 emotions, German)
- **Speech input** via Faster Whisper STT (GPU-accelerated, VAD filter)
- **PC control**: keyboard, mouse, window management, volume
- **System monitoring**: CPU, RAM, GPU, disk, top processes
- **Avatar display**: layered sprite rendering with blink + lip-sync (Pepper's Ghost optimized)
- **RAG memory**: ChromaDB + Ollama embeddings (remembers past conversations)

### Remote (via Matrix / Element)

- **Direct commands**: `status`, `screenshot`, `pause`, `play`, `skip`, `volume 50`
- **Clipboard**: `clipboard` (read), `clip: text` (write)
- **Files**: `schick mir C:\...\datei.pdf`, `download https://...`
- **Processes**: `starte chrome`, `kill blender` (whitelisted)
- **System**: `wol` (Wake-on-LAN), `restart` (bot self-restart after git pull)
- **Dev tools**: `git status`, `git pull`, `docker ps`, `docker restart synapse`
- **Avatar**: `selfie`, `selfie angry` (sends rendered avatar image)
- **Natural language**: "schick mir ein screenshot", "nächster song", "was kannst du"
- **Claude Agent**: complex project tasks via Anthropic API (Sonnet 4.6)
  - Read/write files in `docs/`, append to journal, run tests, git status
  - Trigger: `claude "Dokumentiere X im Journal"`
- **Voice messages**: send a voice note in Element, Whisper transcribes it, Saleria responds with text + voice
- **Text responses**: Saleria personality via Anthropic Sonnet 4.6 (Ollama fallback)

## Quick Start

### 1. Install

```bash
# Clone
git clone https://github.com/leratos/Elder-Berry.git
cd Elder-Berry

# Create venv
py -3.12 -m venv .venv
.venv\Scripts\activate  # Windows

# Full installation (recommended for Tower)
pip install -e ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"
pip install chromadb faster-whisper
```

### 2. Set Up Secrets

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()

# Anthropic (primary LLM backend)
store.set("anthropic_api_key", "sk-ant-...")

# Matrix (required for remote features)
store.set("matrix_homeserver", "https://matrix.example.com")
store.set("matrix_user_id", "@saleria:matrix.example.com")
store.set("matrix_access_token", "syt_...")  # from /_matrix/client/v3/login
store.set("matrix_room_id", "!roomid:matrix.example.com")

# Wake-on-LAN (optional)
store.set("tower_mac_address", "AA:BB:CC:DD:EE:FF")
```

### 3. Prerequisites

- **Ollama** running locally with `phi4:14b` (offline fallback): `ollama serve`
- **Embedding model**: `ollama pull nomic-embed-text`
- **ffmpeg** installed (for audio conversion): `winget install ffmpeg`

### 4. Run

```bash
# Full Matrix mode (recommended)
python scripts/start_saleria.py

# Terminal mode (local testing, no Matrix needed)
python scripts/start_saleria.py --mode terminal

# With options
python scripts/start_saleria.py --no-memory      # Without RAG memory
python scripts/start_saleria.py --no-tts          # Without voice output
python scripts/start_saleria.py --whisper-model large-v3  # Better STT
python scripts/start_saleria.py --debug           # Debug logging
```

### 5. Usage via Element (Matrix Client)

| You type in Element | What happens |
|---|---|
| `status` | System status (CPU, RAM, GPU, disk) |
| `screenshot` | Screenshot sent as image |
| `pause` / `play` / `skip` | Media control |
| `volume 50` | Set volume to 50% |
| `clipboard` | Read clipboard content |
| `clip: some text` | Write to clipboard |
| `selfie` / `selfie angry` | Saleria sends avatar image |
| `hilfe` | Show all available commands |
| `schick mir C:\...\file.pdf` | Send file via Matrix |
| `starte chrome` / `kill blender` | Process control (whitelisted) |
| `git status` / `git pull` | Git commands (whitelisted) |
| `restart` | Bot self-restart (after git pull) |
| `claude "Was war der letzte Schritt?"` | Claude API reads journal and answers |
| `Wie geht's dir?` | Saleria answers with personality + voice message |
| Voice message | Whisper transcribes, routes through commands/LLM |

## Architecture

```text
[Element / Matrix]
       |
       v
[MatrixBridge] ── Command-Router:
       |
       ├─ Audio message?   ──> STT (Faster Whisper) ──> re-route as text
       ├─ Direct command?   ──> RemoteCommandHandler (status, screenshot, etc.)
       ├─ "claude" + "..."? ──> ClaudeAgent (Anthropic API, Sonnet 4.6)
       └─ Everything else   ──> Assistant (LLM + TTS + Avatar)
                                      |
                          ┌───────────┼───────────┐
                          v           v           v
                   ActionController  CoquiTTS   MemoryStore
                   (PC control)      (XTTS v2)  (ChromaDB)
```

### 3-Tier System

| Tier | Device | Role |
|---|---|---|
| Tower | Windows PC (RTX 4070 Ti Super, 16GB VRAM) | Brain: LLM + TTS generation, always on |
| Laptop | Windows PC (RTX 4070, 8GB VRAM) | Client: PC control + audio receiver |
| RPi5 | Raspberry Pi 5 (4GB) | Body: avatar display, sensors, servo |

### Key Classes

| Class | Module | Description |
|---|---|---|
| `Assistant` | `core.assistant` | Orchestrator: LLM -> Action -> TTS -> Avatar -> Memory |
| `SaleriaEngine` | `character.saleria` | Character personality, emotion extraction |
| `CoquiTTSEngine` | `tts.coqui_engine` | XTTS v2 voice cloning, 10 emotion samples |
| `FasterWhisperEngine` | `stt.faster_whisper_engine` | Speech-to-text, GPU, VAD filter |
| `LayeredSpriteRenderer` | `avatar.layered_renderer` | Sprite compositing, blink + lip-sync |
| `WindowsActionController` | `actions.windows_controller` | PC control (keyboard, mouse, volume) |
| `LLMRouter` | `llm.router` | Anthropic (primary) -> Ollama (fallback) |
| `AnthropicClient` | `llm.anthropic_client` | Sonnet 4.6, primary LLM backend |
| `ChromaMemoryStore` | `memory.chroma_memory` | RAG memory with Ollama embeddings |
| `SecretStore` | `core.secret_store` | Fernet-encrypted credential store |
| `MatrixChannel` | `comms.matrix_channel` | matrix-nio async client |
| `MatrixBridge` | `comms.bridge` | Async/sync bridge with command router |
| `RemoteCommandHandler` | `comms.remote_commands` | 20+ direct commands (no LLM) |
| `ClaudeAgent` | `comms.claude_agent` | Anthropic API for complex tasks |
| `AlertMonitor` | `comms.alert_monitor` | Proactive alerts (disk, process crash) |
| `AudioConverter` | `comms.audio_converter` | WAV -> OGG/Opus for Matrix voice messages |
| `RobotClient/Server` | `robot.*` | Tower <-> RPi5 communication (FastAPI) |
| `ActionsDB` | `actions.db` | SQLite action registry with self-learning |
| `SystemMonitor` | `system.info` | CPU, RAM, GPU, disk, process monitoring |

### Design Patterns

- **ABC + Implementation + DI** consistently across all components
- One class per file, snake_case naming
- Optional dependencies via `pyproject.toml` groups
- Graceful degradation: missing dependencies produce error text, never crash

## Character: Saleria Berry

- **Personality**: Direct, relaxed, witty. Like a clever friend who helps and stays chill.
- **10 emotions**: neutral, cheerful, sarcastic, motivated, thoughtful, whisper, shy, depressed, sad, angry
- **Voice**: XTTS v2 voice cloning with per-emotion speaker WAVs
- **Avatar**: Layered sprite system (body + eyes L/R + mouth), blink animation, lip-sync
- **Display**: Pepper's Ghost hologram (LCD horizontal + acrylic 45deg, black background)

## Installation Options

```bash
pip install -e "."                # Core only (LLM, actions DB)
pip install -e ".[windows]"      # PC control (pyautogui, pycaw)
pip install -e ".[tts-neural]"   # XTTS v2 voice cloning (coqui-tts, CUDA)
pip install -e ".[avatar]"       # Avatar display (pygame)
pip install -e ".[matrix]"       # Matrix integration (matrix-nio, pydub)
pip install -e ".[remote]"       # Remote features (anthropic, mss, pyperclip)
pip install -e ".[memory]"       # RAG memory (chromadb)
pip install -e ".[stt]"          # Speech-to-text (faster-whisper)
pip install -e ".[robot]"        # RPi5 communication (fastapi, uvicorn)
pip install -e ".[agent]"        # Laptop agent server (fastapi, audio)
```

## Testing

```bash
pytest tests/ -q
```

815+ tests, all passing.

## Project Structure

```text
src/elder_berry/
├── actions/          # PC control + action database
├── agent/            # Laptop agent server/client
├── avatar/           # Avatar rendering (sprite + layered)
│   └── assets/       # Sprite components (body/, eye/, mouth/)
├── character/        # Character engine + Saleria personality
├── comms/            # Matrix, remote commands, Claude agent, alerts
├── core/             # Assistant orchestrator + secret store
├── llm/              # LLM clients (Anthropic, Ollama, OpenRouter, Router)
├── memory/           # RAG memory (ChromaDB + embeddings)
├── robot/            # RPi5 communication (server, client, simulator)
├── stt/              # Speech-to-text (Faster Whisper)
├── system/           # System monitoring
└── tts/              # TTS engines (Windows SAPI, Coqui XTTS)
    └── voices/       # Voice samples per emotion

docs/
├── concepts/         # Phase concept documents
├── journal.txt       # Living project log (single source of truth)
└── personal/         # Personal notes (gitignored)

hardware/
├── electronics/      # KiCad 9 schematics
├── enclosure/        # Enclosure CAD (Inventor)
│   └── iLogic/       # Parametric scripts (bark, roots)
└── bom/              # Bill of materials

scripts/
├── start_saleria.py     # Main entry point (Terminal/Matrix/Voice mode)
├── demo_tts_live.py     # Interactive TTS testing (emotion + text)
└── demo_integration.py  # Robot simulator integration test

tests/                # 815+ unit + integration tests
```

## Roadmap

| Phase | Name | Status |
|---|---|---|
| 1 | Software Basic (PC control, TTS, LLM, Assistant) | Done |
| 2 | RPi5 Integration (protocol, simulator, agent server) | Done (software) |
| 3 | Character / V-Tuber (Saleria, XTTS, Avatar) | Done |
| 4 | Enclosure + Turntable (tree trunk, Pepper's Ghost) | In progress (hardware) |
| 5 | Software Advance (Anthropic, Memory, STT, Startup) | Mostly done |
| 6 | Matrix Integration (remote messaging, voice messages) | Done |
| 7 | Remote Features (commands, Claude agent, alerts) | Done |
| 8 | Personal Assistant Tools (calendar, email, gym, weather, timer, briefing) | Done |
| 9 | Multimodal + Autonomie (camera, emotion recognition) | Vision |
| 10 | RPi5 Avatar-Display (Pepper's Ghost live) | Mostly done |
| 11 | Document Summarization (PDF/TXT via LLM) | Planned |

## Hardware

| Component | Role |
|---|---|
| Tower PC (RTX 4070 Ti Super, 16GB VRAM) | LLM host, TTS generation |
| Laptop (RTX 4070, 8GB VRAM) | Development, testing, mobile client |
| Raspberry Pi 5 (4GB) | Avatar display (DSI), sensors, servo |
| RPi Touch Display 2 (5", 720x1280) | Pepper's Ghost hologram display |
| Servo (SG90/MG996R) + turntable | Rotation towards user |

## LLM Strategy

| Mode | Model | Use Case |
| --- | --- | --- |
| Primary | Anthropic Sonnet 4.6 | Conversation, PC control, all tasks |
| Fallback | Ollama phi4:14b | Offline mode, no internet required |
| Agent | Anthropic Sonnet 4.6 | Project tasks via Matrix (journal, docs, tests) |

## RPi5 Setup (Avatar Display)

The RPi5 runs the avatar display (Pepper's Ghost hologram) and the Robot API.

### Install

```bash
cd /home/pi/elder-berry
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[robot,avatar]"
pip install pygame-ce
```

### Manual Start

```bash
SDL_VIDEODRIVER=kmsdrm python scripts/start_rpi5.py              # Fullscreen (DSI)
SDL_VIDEODRIVER=kmsdrm python scripts/start_rpi5.py --windowed   # Debug
```

### Autostart (systemd)

```bash
sudo nano /etc/systemd/system/elder-berry.service
```

```ini
[Unit]
Description=Elder-Berry Avatar Display
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/elder-berry
ExecStart=/home/pi/elder-berry/.venv/bin/python scripts/start_rpi5.py
Restart=on-failure
RestartSec=5
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=DISPLAY=:0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable elder-berry    # Autostart on boot
sudo systemctl start elder-berry     # Start now
sudo systemctl status elder-berry    # Check status
sudo journalctl -u elder-berry -f    # Live logs
```

### Tower Connection

On the Tower, set the RPi5 IP in SecretStore:

```python
from elder_berry.core.secret_store import SecretStore
SecretStore().set("robot_host", "http://192.168.50.220:8000")
```

The Tower then controls the avatar automatically via `RobotClient`:

- LLM emotion → `POST /avatar/emotion` → display changes
- TTS speaking → lip-sync on display
- Health check → `GET /health`

## Project Family

- [last-strawberry.com](https://last-strawberry.com)
- last-strawberry-DnD
- Gym-Berry
- **Elder-Berry** ← you are here
