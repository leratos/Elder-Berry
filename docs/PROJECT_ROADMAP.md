# Elder-Berry – Project Roadmap

---

## Phase 1 – Software Basic (Windows Tower) ✅ ABGESCHLOSSEN
- PC-Steuerung (Maus, Tastatur, Fenster, Lautstärke) – WindowsActionController
- Systemdaten auslesen (CPU, RAM, GPU, laufende Prozesse) – SystemMonitor
- LLM-Anbindung: Anthropic Sonnet 4.6 (primär) + Ollama phi4:14b (Offline-Fallback) – LLMRouter
- Aktions-DB (Befehl → Aktion, selbstlernend) – ActionsDB (SQLite)
- Basis-TTS (Text to Speech) – WindowsTTSEngine (pyttsx3/SAPI5)
- Assistant-Orchestrator (LLM → Aktion → TTS) – Assistant
- Konsistentes Pattern: ABC + plattformspezifische Implementierung + DI

## Phase 2 – RPi5 Anbindung ✅ SOFTWARE ABGESCHLOSSEN
- Kommunikationsprotokoll Tower ↔ RPi5: REST via FastAPI (Port 8000)
- Protocol DTOs, RobotServer (FastAPI), RobotClient (httpx)
- Simulator für lokale Entwicklung ohne Hardware
- Assistant-Integration: Emotion-Sync, Sensor-Status
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

## Phase 5 – Software Advance ✅ GRÖSSTENTEILS ABGESCHLOSSEN
- AnthropicClient (Sonnet 4.6 primär, Ollama Offline-Fallback)
- RAG Memory: ChromaDB + OllamaEmbeddingClient (nomic-embed-text, 768-dim)
- STT: FasterWhisperEngine (GPU-beschleunigt, VAD-Filter, Lazy-Load)
- Startup-Script: start_saleria.py (Terminal/Matrix/Voice-Modus)
- **Offen:** Emotion-State-Machine (Persistente Stimmung über Konversation hinweg)
- **Offen:** Multimodale Kamera-Eingabe (Webcam → OpenRouter Vision)
- **Offen:** Feinschliff Aktions-Logik (komplexe Verkettungen)

## Phase 6 – Matrix-Integration ✅ ABGESCHLOSSEN
- Synapse Matrix-Server auf Plesk-Server (matrix.last-strawberry.com)
- Element-Client auf Handy → Saleria erreichbar von unterwegs
- SecretStore (Fernet-verschlüsselte Credentials)
- MessageChannel (ABC) + MatrixChannel (matrix-nio, async)
- MatrixBridge (Async↔Sync Bridge: MessageChannel ↔ Assistant)
- AudioConverter (WAV → OGG/Opus) + Sprachnachrichten senden
- STT-Integration: m.audio empfangen → FasterWhisper → Assistant
- Live-getestet: Text + Sprachnachricht funktional

## Phase 7 – Remote-Features + ClaudeAgent ✅ ABGESCHLOSSEN
- RemoteCommandHandler: 20+ direkte Commands ohne LLM
  - Tier 1: status, screenshot, medien, lautstärke, avatar/selfie, hilfe
  - Tier 2: clipboard, send_file, start/kill prozess, WoL
  - Tier 3: git, docker, download
- ClaudeAgent: Anthropic API für komplexe Anfragen (Dateien, Tests, Journal)
- AlertMonitor: proaktive Benachrichtigungen (Disk, Prozess-Crash)
- Restart-Command: Bot startet sich nach git pull selbst neu

---

## Phase 8 – Personal Assistant Tools 🗓️ TEILWEISE ABGESCHLOSSEN

Saleria als echte Alltagsassistentin – Kalender, E-Mail, Fitness, Wetter, Smart Home.

### ✅ Google Calendar (abgeschlossen)
- GoogleCalendarClient: Termine lesen, erstellen, löschen, suchen
- OAuth2-Setup via Setup-Script
- Natürliche Sprache: "termine morgen", "erstelle termin Zahnarzt morgen 14:00",
  "lösche den 2. termin", "lösche alle termine"
- Event-IDs für kontextbasiertes Löschen nach Abfrage

### ✅ E-Mail / IMAP (abgeschlossen)
- IMAPEmailClient: Ungelesen, Suche, Anhänge senden
- IMAP UIDs, Body-Preview in Chat-History (LLM kann zusammenfassen)
- "mail suche Rechnung" → "fasse die mail zusammen" → "schick mir den anhang"

### ✅ Berry-Gym Fitness (abgeschlossen)
- GymDataClient: Training, Details, Woche, PRs

### ✅ Multi-Turn Chat-History (abgeschlossen)
- ChatHistory: Sliding Window pro User (10 Nachrichten)
- Ersetzt Quick-Fix (_last_command_result)
- Ermöglicht Rückfragen, Kontext-Bezug, "mach das nochmal"

### OFFEN: Wetter (Open-Meteo)
- WeatherClient (Open-Meteo API, kostenlos, kein API-Key)
- Standort einmalig in SecretStore: Koordinaten + Stadtname
- Commands: "wetter", "wetter morgen", "wetter diese woche"
- Integration: Wetter optional im System-Prompt (Saleria weiß wie das Wetter ist)
- Neue Klasse: `tools/weather_client.py`

### OFFEN: Timer & Erinnerungen
- ReminderStore: SQLite-basiert, neustart-sicher
- Asyncio-Scheduler im AlertMonitor-Stil
- Commands: "timer 20 minuten", "erinnere mich um 18 uhr: Wäsche"
- Matrix-Alert wenn Timer abläuft
- Neue Klasse: `tools/reminder_store.py`

### OFFEN: Home Assistant Client
- HomeAssistantClient: REST API, Long-lived Token in SecretStore
- Harmony Hub über HA (kein direkter API-Zugriff nötig)
- Commands: "licht wohnzimmer an/aus", "heizung 21 grad", "szene film", "harmony tv an"
- HA-Whitelist für erlaubte Entities/Services (Sicherheit)
- Neue Klasse: `tools/home_assistant_client.py`
- Abhängigkeit: nur `httpx` (bereits vorhanden)

### OFFEN: Daily Briefing
- CronJob (täglich 7:30 Uhr) → Matrix-Nachricht
- Inhalt: Wetter des Tages + heutige Termine + offene Erinnerungen
- Optional: kurze Saleria-Persönlichkeits-Note ("Heute wird ein langer Tag...")
- Erweiterung von AlertMonitor oder eigenem BriefingScheduler

---

## Phase 9 – Multimodal + Autonomie 🔭 VISION

### Kamera-Integration (Multimodal)
- Webcam oder RTSP-Feed → Bild → OpenRouter Vision (GPT-4o / Claude Vision)
- Commands: "was siehst du", "screenshot vom eingang"
- Anwendung: Paketlieferung erkennen, Haustier beobachten, Schreibtisch-Check
- Voraussetzung: Kamera physisch installiert

### Emotion Recognition (Voice)
- STT-Konfidenz + Sprechgeschwindigkeit + Tonhöhe → Stimmungsschätzung
- Saleria passt Antwortton an erkannte Stimmung an
- Keine externe API nötig (Whisper liefert bereits Konfidenz-Werte)

### Proaktive Autonomie
- Saleria initiiert Aktionen ohne User-Trigger
- Beispiele: "Dein Meeting beginnt in 10 Minuten" (Kalender-Watcher)
- "GPU-Auslastung 95% seit 2h – alles ok?" (SystemMonitor-Erweiterung)
- "Draußen regnet es, du hattest Fenster offen lassen" (HA + Wetter kombiniert)
- Technisch: erweiterter AlertMonitor mit Plugin-System

### Notizen & Wissensdatenbank
- Explizit gespeicherte Fakten (getrennt von RAG-Memory)
- "Merk dir: WLAN-Passwort Büro ist xyz"
- "Was ist das WLAN-Passwort vom Büro?"
- SQLite-basiert, Key-Value + Volltextsuche
- Unterschied zu ChromaDB-Memory: direkt abrufbar, kein Embedding nötig

### Multi-Channel
- Discord als zweiter Kanal (DiscordChannel implementiert MessageChannel ABC)
- Telegram (optionale Alternative zu Matrix)
- Web-Interface (einfaches FastAPI + HTML, kein Framework)

---

## Phase 10 – Hardware-Abschluss 🤖 WARTEND AUF LIEFERUNG

- Pepper's Ghost Display am RPi5 in Betrieb nehmen (LayeredSpriteRenderer live)
- Drehteller-Servo: Servo-Controller via RPi5 GPIO, Befehle über RobotServer
- Pico 2W: Sensor-Anbindung (Näherungssensor, Temperatur)
- Gehäuse-Finish: Resin-Druck, Rinde bemalen, Moos-Details
- Gesamtintegration: Tower (Hirn) ↔ Laptop (PC) ↔ RPi5 (Display+Servo) ↔ Pico 2W (Sensoren)

---

## Projektgrenzen (ehrliche Einschätzung)

### Was dieses Projekt ist
- **Persönlicher Single-User Assistent** – für eine Person, kein Multi-Tenant
- **Reaktives System** – Saleria antwortet auf Eingaben; proaktive Autonomie ist Erweiterung, kein Kern
- **Lokale KI-Pipeline** – Daten bleiben auf eigenem Server/Tower; kein Cloud-Zwang
- **Hobby-Projekt mit echtem Nutzen** – kein kommerzielles Produkt

### Technische Eigenschaften (keine Einschränkungen für den Use-Case)
| Bereich | Eigenschaft | Kontext |
|---|---|---|
| Antwortzeit | 3–8s pro Turn | Für einen Assistenten völlig akzeptabel – kein Gesprächsersatz, sondern Hilfe |
| LLM-Qualität | Abhängig von Anthropic/Ollama | Kein eigenes Fine-Tuning nötig – Sonnet 4.6 ist state-of-the-art |
| Offline-Fallback | phi4:14b lokal | Schlechter als Sonnet, aber funktional für einfache Anfragen |
| Gleichzeitige User | 1 (sequenziell) | Single-User by Design – kein Problem |
| Sprachqualität | XTTS v2 | Gut genug für Alltagsnutzung; ElevenLabs wäre besser, kostet aber |
| Avatar-Display | Pepper's Ghost (5") | Klein, aber charmant – passt zum Holunder-Konzept |
| Kamera-Reasoning | Cloud-LLM nötig | Vision-Modelle lokal noch nicht ausgereift; OpenRouter ist sinnvoll |

### Was absichtlich nicht implementiert wird
- **Sicherheits-Infrastruktur für mehrere User** – nicht der Use-Case
- **Mobile App** – Element ist der Client, keine eigene App geplant
- **Wake-Word** ("Hey Saleria") – würde ständig laufenden STT-Prozess brauchen; zu viel Ressourcen
- **Emotionale Manipulation / Dark Patterns** – Saleria soll helfen, nicht abhängig machen
- **Autonome Code-Änderungen** – ClaudeAgent darf Docs schreiben, aber nicht `src/` ändern (Sicherheit)

### Realistisches Endprodukt
Ein physischer Assistent auf dem Schreibtisch (Holunder-Hologramm), erreichbar via Handy (Element) und Sprache, der:
- Fragen beantwortet und Gespräche führt (Saleria-Persönlichkeit)
- Kalender, Wetter, Erinnerungen managed
- Den PC/Tower remote steuert (Screenshots, Medien, Prozesse)
- Das Smart Home steuert (Lichter, Heizung via HA)
- Sich an Gespräche erinnert (RAG-Memory)
- Proaktiv auf wichtige Events aufmerksam macht (Alerts)

Das ist ein vollständiges, nützliches Produkt – kein Prototyp mehr.
