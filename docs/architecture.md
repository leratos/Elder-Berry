# Elder-Berry – Architektur & Referenz

Dieses Dokument enthält Referenzinformationen zu Architektur, Klassen, Hardware und
Charakter. Für Workflow-Regeln und Arbeitsanweisungen siehe `CLAUDE.md` im Projekt-Root.

## 3-Tier-System

- **Tower (Hirn)**: LLM + TTS-Generierung, Assistant-Orchestrator, immer an
- **Laptop (Client)**: PC-Steuerung + Audio-Empfänger, AgentServer (FastAPI)
- **RPi5 (Display-Einheit)**: Sensoren, Avatar-Display, Drehteller-Servo

## Kernklassen

| Klasse | Modul | Verantwortung |
|--------|-------|---------------|
| Assistant | core | Orchestrator: LLM → Action → TTS → Avatar → Robot → Matrix |
| SaleriaEngine | character | Charakter-Persönlichkeit, Emotion-Extraktion |
| CoquiTTSEngine | tts | XTTS v2 Voice Cloning (pro Emotion ein Speaker-WAV) |
| LayeredSpriteRenderer | avatar | Component-basiertes Avatar-Rendering (PyGame) |
| WindowsActionController | actions | PC-Steuerung (Tastatur, Maus, Fenster, Lautstärke) |
| RobotClient / RobotServer | robot | Tower ↔ RPi5 Kommunikation (REST, Port 8000) |
| AgentClient / AgentServer | agent | Tower ↔ Laptop Kommunikation (REST + Audio-Streaming) |
| LLMRouter | llm | Lokal (Ollama) oder remote (OpenRouter), Auto-Erkennung |
| ActionsDB | actions | SQLite Aktions-Registry mit Self-Learning |
| SecretStore | core | Fernet-verschlüsselter Credential-Store (~/.elder-berry/) |
| MessageChannel | comms | ABC für bidirektionale Nachrichtenkanäle |
| MatrixChannel | comms | matrix-nio Implementierung (async, Auto-Join, Room-Whitelist) |
| MatrixBridge | comms | Async↔Sync Bridge (MessageChannel ↔ Assistant) |
| AudioConverter | tts | WAV/MP3 → OGG/Opus (pydub + ffmpeg) |
| RemoteCommandHandler | comms | Orchestrator, delegiert an CommandHandler-Subklassen |
| CommandHandler (ABC) | comms/commands | Interface für domänenspezifische Command-Handler |

## LLM-Strategie

- **Lokal (Ollama)**: phi4:14b – schnelle Aktionen, Sensor-Auswertung, PC-Steuerung, Dauerbetrieb
- **OpenRouter**: Multimodal (Kamera-Input), komplexes Reasoning, Fallback
- LLMRouter: Auto-Erkennung localhost → Mesh-IP → Fallback
- Tower benötigt: OLLAMA_HOST=0.0.0.0 + Firewall nur Mesh-IP auf 11434
- Modell-Wechsel nur mit expliziter Begründung

## Charakter – Saleria Berry

- Motto: "Charmant und melodisch mit einem Hauch spielerischer Gefahr"
- 10 Emotionen: neutral, cheerful, sarcastic, motivated, thoughtful, whisper, shy, depressed, sad, angry
- Voice: Coqui XTTS v2 Voice Cloning, pro Emotion ein Speaker-WAV
- Avatar: Layered Sprite System (Body + Eyes L/R + Mouth), Blink-Animation, Lip-Sync
- Pepper's Ghost Hologramm: LCD horizontal + Acryl 45°, schwarzer Hintergrund (0,0,0)
- Persönlichkeit definiert in: src/elder_berry/character/saleria.yaml

## Hardware

### Tower
- RTX 4070 Ti Super (16GB VRAM), Ollama lokal (phi4:14b)
- Rolle: Hirn (LLM + TTS-Generierung), immer an
- Aktuell: noch nicht scharfgeschaltet, Entwicklung läuft auf Laptop

### Laptop (Testplattform)
- RTX 4070 Laptop (8GB VRAM), Ollama lokal (phi4:14b)
- Rolle: Client (empfängt PC-Befehle + Audio vom Tower)
- Unterwegs: Tower als LLM-Backend über NordVPN Meshnet, Fallback lokales Ollama

### RPi 5 (I/O-Hub + Sensor-Hub)
- Sensoren: BME280 (I2C), APDS-9960 (I2C), Kamera (CSI, IMX708)
- Drehteller: 28BYJ-48 Stepper + ULN2003 (GPIO) + A3144 Hall-Sensoren (GPIO)
- Kommunikation: REST via FastAPI (Port 8000, WLAN)
- Kein LLM

### Stationärer Drehteller (ehem. Roboter-Chassis)
- Mecanum-Antrieb gestrichen – Mehrwert zu gering
- 200mm Alu Lazy-Susan Lager (60-70kg Tragkraft)
- 1× 28BYJ-48 Stepper + ULN2003 über RPi5 GPIO (Reaktionsantrieb)
- A3144 Hall-Sensoren für ±180° Begrenzung + Home-Position
- USB-C Netzteil für Dauerbetrieb, Kamera fest im Gehäuse

## Projektstruktur

```
src/elder_berry/
├── actions/      # PC-Steuerung, ActionsDB
├── agent/        # Tower ↔ Laptop Kommunikation
├── avatar/       # Sprite-Renderer, Editor
├── character/    # SaleriaEngine, saleria.yaml
├── comms/        # Matrix, Bridge, RemoteCommands, commands/
├── core/         # Assistant, SecretStore
├── llm/          # LLMRouter, Ollama/OpenRouter
├── memory/       # MemoryStore, ChatHistory
├── robot/        # RobotClient/Server, Turntable, Simulator
├── stt/          # Faster-Whisper STT
├── system/       # SystemInfo, ErrorCollector
├── tools/        # EmailClient, Calendar, Weather, BraveSearch
├── tts/          # CoquiTTS, AudioConverter
└── web/          # Audio-Dashboard
```
