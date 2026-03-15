# Elder-Berry – Project Roadmap

## Phase 1 – Software Basic (Windows Tower) ✅ ABGESCHLOSSEN
- PC-Steuerung (Maus, Tastatur, Fenster, Lautstärke) – WindowsActionController
- Systemdaten auslesen (CPU, RAM, GPU, laufende Prozesse) – SystemMonitor
- LLM-Anbindung lokal via Ollama + OpenRouter Fallback – LLMRouter
- Aktions-DB (Befehl → Aktion, selbstlernend) – ActionsDB (SQLite)
- Basis-TTS (Text to Speech) – WindowsTTSEngine (pyttsx3/SAPI5)
- Assistant-Orchestrator (LLM → Aktion → TTS) – Assistant
- Konsistentes Pattern: ABC + plattformspezifische Implementierung + DI

## Phase 2 – RPi5 Anbindung ✅ SOFTWARE ABGESCHLOSSEN
- Kommunikationsprotokoll Tower ↔ RPi5: REST via FastAPI (Port 8000)
- Protocol DTOs, RobotServer (FastAPI), RobotClient (httpx)
- Simulator für lokale Entwicklung ohne Hardware
- Assistant-Integration: robot_drive, robot_stop, Emotion-Sync, Sensor-Status
- AgentServer für Laptop-Steuerung (Tower → Laptop Remote-Aktionen + Audio-Streaming)
- RPi5 Setup: Bookworm Lite, Python 3.13, IP 192.168.50.220
- **Offen:** Echte RPi5-Klassen (MotorController, SensorManager) wenn Hardware bereit
- **Offen:** Sensor-Integration (Kamera, IR, Temperatur)
- **Offen:** Kommunikation RPi5 ↔ Pico 2W

## Phase 3 – Charakter / V-Tuber ✅ ABGESCHLOSSEN
- Charakter: Saleria Berry – "Charmant und melodisch mit spielerischer Gefahr"
- CharacterEngine (ABC) + SaleriaEngine (10 Emotionen, YAML-Persönlichkeit)
- Coqui XTTS v2 Voice Cloning – CoquiTTSEngine (pro Emotion ein Speaker-WAV)
- Avatar: LayeredSpriteRenderer (PyGame, Component-basiert: Body/Eyes/Mouth)
- Blink-Animation, Lip-Sync, Pepper's Ghost optimiert (schwarzer Hintergrund)
- Display: Pepper's Ghost Hologramm (LCD horizontal + Acryl 45°)
- Display-Hardware: RPi Touch Display 2 (5", 720×1280, DSI, Portrait)

## Phase 4 – Gehäuse + Drehteller 🔧 IN ARBEIT (Hardware)
- Gehäuse: Holunder-Baumstamm (Resin-Druck, segmentiert)
  - Spec: docs/concepts/gehaeuse-baumstamm-spec.md
  - CAD: hardware/enclosure/ (Inventor)
  - Gewicht: 1.138g (stationär → kein Limit)
- ~~Mecanum 4WD~~ GESTRICHEN – stationär + drehbar statt mobil
- Drehteller: 1× Servo (SG90/MG996R) + Kugellager unter dem Stamm
- Stromversorgung: USB-C Netzteil (Dauerbetrieb) oder Akku – je nach Standort
- Pepper's Ghost Kammer fertigstellen + testen
- Ästhetik + Finish (Rinde bemalen, Moos-Details)
- **Offen:** Standort (Schreibtisch, Regal, Sideboard)
- **Offen:** Pico 2W Rolle (Sensoren ja, Motoren nein)

## Phase 5 – Software Advance
- Vollständige Aktions-Logik ausarbeiten
- Emotion-State-Machine
- Sensor-Kontext in LLM-Prompts integrieren
- OpenRouter Multimodal (Kamera → GPT-4o)
- Feinschliff, Stabilität, Performance

## Phase 6 – Matrix-Integration ✅ ABGESCHLOSSEN
- Synapse Matrix-Server auf Plesk-Server (matrix.last-strawberry.com)
- Element-Client auf Handy → Saleria erreichbar von unterwegs
- SecretStore (Fernet-verschlüsselte Credentials)
- MessageChannel (ABC) + MatrixChannel (matrix-nio, async)
- MatrixBridge (Async↔Sync Bridge: MessageChannel ↔ Assistant)
- AudioConverter (WAV → OGG/Opus) + Sprachnachrichten via Element
- Assistant-Integration: audio_output Parameter für TTS-to-File
- Live-getestet: Text + Sprachnachricht funktional
- Konzeptdokument: docs/concepts/phase-6-matrix-integration.md
