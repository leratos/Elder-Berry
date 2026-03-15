# Elder-Berry

> Virtual AI Assistant with V-Tuber character, voice cloning and remote control.
> Part of the Last-Strawberry project family.

## Overview

Elder-Berry is a modular AI assistant built around a V-Tuber character named **Saleria Berry**.
She combines local LLM processing, voice cloning (XTTS v2), emotion-driven avatar rendering,
PC control and remote access via Matrix into a single cohesive system.

Saleria is designed as a stationary desk companion with a Pepper's Ghost hologram display
inside a 3D-printed elderberry tree trunk enclosure.

## What Saleria Can Do

### Local (PC)

- **Conversation** with personality, emotion tagging and sarcasm
- **Voice output** via Coqui XTTS v2 voice cloning (10 emotions, German)
- **PC control**: keyboard, mouse, window management, volume
- **System monitoring**: CPU, RAM, GPU, top processes
- **Avatar display**: layered sprite rendering with blink + lip-sync (Pepper's Ghost optimized)

### Remote (via Matrix / Element)

- **Direct commands**: `status`, `screenshot`, `pause`, `play`, `skip`, `volume 50`
- **Natural language commands**: "schick mir ein screenshot", "nächster song"
- **Claude Agent**: complex project tasks via Anthropic API (Sonnet 4.6)
  - Read/write files in `docs/`, append to journal, run tests, git status
  - Trigger: `claude "Dokumentiere X im Journal"`
- **Voice messages**: TTS generates WAV, converts to OGG/Opus, sends via Matrix
- **Text responses**: Saleria personality via local LLM (Ollama phi4:14b)

## Quick Start

### 1. Install

```bash
# Clone
git clone https://github.com/leratos/Elder-Berry.git
cd Elder-Berry

# Create venv
py -3.12 -m venv .venv
.venv\Scripts\activate  # Windows

# Core only
pip install -e .

# Full installation (recommended)
pip install -e ".[windows,tts-neural,avatar,matrix,remote]"
```

### 2. Set Up Secrets

```python
from elder_berry.core.secret_store import SecretStore
store = SecretStore()

# Matrix (required for remote features)
store.set("matrix_homeserver", "https://matrix.example.com")
store.set("matrix_user_id", "@saleria:matrix.example.com")
store.set("matrix_password", "your-bot-password")
store.set("matrix_room_id", "!roomid:matrix.example.com")

# Claude Agent (optional, for complex remote tasks)
store.set("anthropic_api_key", "sk-ant-...")
```

### 3. Run

```bash
# Echo bot (test Matrix connection)
python scripts/demo_matrix_bot.py

# Remote commands only (no LLM needed)
python scripts/demo_matrix_bot.py --remote

# Full pipeline: LLM + TTS + voice messages
python scripts/demo_matrix_bot.py --llm

# Everything: LLM + remote commands + Claude agent
python scripts/demo_matrix_bot.py --llm --remote --agent
```

**Prerequisite**: Ollama must be running locally with `phi4:14b` for `--llm` mode.

### 4. Usage via Element (Matrix Client)

| You type in Element | What happens |
|---|---|
| `status` | System status (CPU, RAM, GPU, disk) |
| `screenshot` | Screenshot sent as image |
| `pause` / `play` / `skip` | Media control |
| `volume 50` | Set volume to 50% |
| `claude "Was war der letzte Arbeitsschritt?"` | Claude API reads journal.txt and answers |
| `claude "Dokumentiere X im Journal"` | Claude API appends to journal.txt |
| `Wie geht's dir?` | Saleria answers with personality + voice message |

## Architecture

```text
[Element / Matrix]
       |
       v
[MatrixBridge] ── Command-Router:
       |
       ├─ Direct command?  ──> RemoteCommandHandler (status, screenshot, media)
       ├─ "claude" + "..."? ──> ClaudeAgent (Anthropic API, Sonnet 4.6)
       └─ Everything else   ──> Assistant (local LLM + TTS + Avatar)
                                      |
                          ┌───────────┼───────────┐
                          v           v           v
                   ActionController  CoquiTTS   AvatarRenderer
                   (PC control)      (XTTS v2)  (PyGame layered)
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
| `Assistant` | `core.assistant` | Orchestrator: LLM -> Action -> TTS -> Avatar |
| `SaleriaEngine` | `character.saleria` | Character personality, emotion extraction |
| `CoquiTTSEngine` | `tts.coqui_engine` | XTTS v2 voice cloning, 10 emotion samples |
| `LayeredSpriteRenderer` | `avatar.layered_renderer` | Sprite compositing, blink + lip-sync |
| `WindowsActionController` | `actions.windows_controller` | PC control (keyboard, mouse, volume) |
| `LLMRouter` | `llm.router` | Ollama (local) -> OpenRouter (fallback) |
| `SecretStore` | `core.secret_store` | Fernet-encrypted credential store |
| `MatrixChannel` | `comms.matrix_channel` | matrix-nio async client |
| `MatrixBridge` | `comms.bridge` | Async/sync bridge with command router |
| `RemoteCommandHandler` | `comms.remote_commands` | Direct commands (no LLM) |
| `ClaudeAgent` | `comms.claude_agent` | Anthropic API for complex tasks |
| `AudioConverter` | `comms.audio_converter` | WAV -> OGG/Opus for Matrix voice messages |
| `RobotClient/Server` | `robot.*` | Tower <-> RPi5 communication (FastAPI) |
| `ActionsDB` | `actions.db` | SQLite action registry with self-learning |
| `SystemMonitor` | `system.info` | CPU, RAM, GPU, process monitoring |

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
pip install -e ".[windows]"      # PC control (pyautogui, pycaw)
pip install -e ".[tts-neural]"   # XTTS v2 voice cloning (coqui-tts, CUDA)
pip install -e ".[avatar]"       # Avatar display (pygame)
pip install -e ".[robot]"        # RPi5 communication (fastapi, uvicorn)
pip install -e ".[agent]"        # Laptop agent server (fastapi, audio)
pip install -e ".[matrix]"       # Matrix integration (matrix-nio, pydub)
pip install -e ".[remote]"       # Remote features (anthropic, mss)
```

## Testing

```bash
pytest tests/ -q
```

520+ tests, all passing.

## Project Structure

```text
src/elder_berry/
├── actions/          # PC control + action database
├── agent/            # Laptop agent server/client
├── avatar/           # Avatar rendering (sprite + layered)
│   └── assets/       # Sprite components (body/, eye/, mouth/)
├── character/        # Character engine + Saleria personality
├── comms/            # Matrix, remote commands, Claude agent
├── core/             # Assistant orchestrator + secret store
├── llm/              # LLM clients (Ollama, OpenRouter, Router)
├── robot/            # RPi5 communication (server, client, simulator)
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
└── bom/              # Bill of materials

scripts/              # Demo and utility scripts
tests/                # Unit + integration tests
```

## Roadmap

| Phase | Name | Status |
|---|---|---|
| 1 | Software Basic (PC control, TTS, LLM, Assistant) | Done |
| 2 | RPi5 Integration (protocol, simulator, agent server) | Done (software) |
| 3 | Character / V-Tuber (Saleria, XTTS, Avatar) | Done |
| 4 | Enclosure + Turntable (tree trunk, Pepper's Ghost) | In progress (hardware) |
| 5 | Software Advance (emotion state machine, multimodal) | Planned |
| 6 | Matrix Integration (remote messaging, voice messages) | Done |
| 7 | Remote Features (commands, Claude agent) | Done |

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
| Local | Ollama phi4:14b | Conversation, PC control, fast actions |
| Remote | OpenRouter | Multimodal, complex reasoning, fallback |
| Agent | Anthropic Sonnet 4.6 | Project tasks via Matrix (journal, docs, tests) |

## Project Family

- [last-strawberry.com](https://last-strawberry.com)
- last-strawberry-DnD
- Gym-Berry
- **Elder-Berry** ← you are here
