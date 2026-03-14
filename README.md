# Elder-Berry

> Virtual AI Assistant with V-Tuber character, voice cloning and robot control.
> Part of the Last-Strawberry project family.

## Overview
Elder-Berry is a modular AI assistant system built around a V-Tuber character named **Saleria Berry**.
It combines local LLM processing, voice cloning (XTTS v2), emotion-driven avatar rendering and PC control into a single cohesive assistant.

## Architecture

```text
User Input → LLM (Ollama phi4:14b) → [emotion] Tag + Response
                                          ↓
                              CharacterEngine (extract emotion)
                                          ↓
                          ┌───────────────┼───────────────┐
                          ↓               ↓               ↓
                    ActionController   CoquiTTSEngine   AvatarRenderer
                    (PC control)       (XTTS v2 voice)  (PyGame layered)
```

### Key Classes

| Class | Module | Description |
|---|---|---|
| `Assistant` | `core.assistant` | Orchestrator: LLM → Action → TTS → Avatar |
| `SaleriaEngine` | `character.saleria` | Character personality, emotion extraction |
| `CoquiTTSEngine` | `tts.coqui_engine` | XTTS v2 voice cloning with per-emotion samples |
| `LayeredSpriteRenderer` | `avatar.layered_renderer` | Component-based sprite compositing with blink + lip-sync |
| `WindowsActionController` | `actions.windows_controller` | PC control (keyboard, mouse, windows, volume) |
| `OllamaClient` | `llm.ollama_client` | Local LLM via Ollama |
| `ActionsDB` | `actions.db` | SQLite action registry with self-learning |

### Design Patterns

- **ABC + Implementation + DI** consistently across all components
- One class per file, snake_case naming
- Optional dependencies via `pyproject.toml` groups

## Hardware

| Component | Role |
|---|---|
| Tower PC (RTX 4070 Ti Super, 16GB VRAM) | LLM host, main processing |
| Laptop (RTX 4070, 8GB VRAM) | Development + testing |
| Raspberry Pi 5 (4GB) | I/O controller, avatar display (DSI) |
| RPi Touch Display 2 (5", 720x1280) | Pepper's Ghost hologram display |
| Mecanum 4WD Robot | Mobile carrier, autonomous charging |
| Pico 2W | Motor controller, battery monitoring |

## LLM Strategy

| Mode | Model | Use Case |
|---|---|---|
| Local | Ollama phi4:14b | Fast actions, PC control, sensors |
| Remote | OpenRouter | Multimodal, complex reasoning, fallback |

## Character: Saleria Berry

- Personality: "Charmant und melodisch mit einem Hauch spielerischer Gefahr"
- 10 emotions: neutral, cheerful, sarcastic, motivated, thoughtful, whisper, shy, depressed, sad, angry
- Voice: XTTS v2 voice cloning with per-emotion speaker WAVs
- Avatar: Layered sprite system (body + eyes + mouth), blink animation, lip-sync

## Installation

```bash
# Core
pip install -e .

# With Windows PC control
pip install -e ".[windows]"

# With neural TTS (XTTS v2)
pip install -e ".[tts-neural]"

# With avatar display
pip install -e ".[avatar]"

# With robot server/simulator
pip install -e ".[robot]"

# Everything
pip install -e ".[windows,tts-neural,avatar,robot]"
```

## Testing

```bash
pytest tests/ -q
```

287 tests, all passing.

## Project Structure

```text
src/elder_berry/
├── actions/          # PC control + action database
├── avatar/           # Avatar rendering (sprite + layered)
│   └── assets/       # Sprite components (body/, eye/, mouth/)
├── character/        # Character engine + Saleria personality
├── core/             # Assistant orchestrator
├── llm/              # LLM clients (Ollama, OpenRouter, Router)
├── robot/            # RPi5 communication (server, client, simulator)
├── system/           # System monitoring
└── tts/              # TTS engines (Windows SAPI, Coqui XTTS)
    └── voices/       # Voice samples per emotion

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
| 2 | RPi5 Integration (protocol, simulator) | Done (software) |
| 3 | Character / V-Tuber (Saleria, XTTS, Avatar) | Done |
| 4 | Body / Housing (enclosure, Pepper's Ghost) | Planned |
| 5 | Software Advance (emotion state machine, multimodal) | Planned |

## Project Family
- [last-strawberry.com](https://last-strawberry.com)
- last-strawberry-DnD
- Gym-Berry
- **Elder-Berry** ← you are here
