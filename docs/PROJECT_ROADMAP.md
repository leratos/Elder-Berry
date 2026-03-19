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

### ✅ Wetter (abgeschlossen)
- WeatherClient (Open-Meteo API, kostenlos, kein API-Key)
- Commands: "wetter", "wetter morgen", "wetter woche"
- Keywords: "regnet es", "brauche ich schirm", "wie warm"

### ✅ Timer & Erinnerungen (abgeschlossen)
- ReminderStore (SQLite, neustart-sicher, UTC)
- ReminderScheduler (Daemon-Thread, 15s Poll)
- Commands: "timer 20 min", "erinnere mich um 18 uhr: Wäsche", "erinnerungen"

### ✅ Daily Briefing (abgeschlossen)
- BriefingScheduler (Daemon-Thread, täglich 07:30)
- Wetter + Termine + Erinnerungen kombiniert
- Manuell: "briefing", Keywords: "guten morgen"

### OFFEN: Home Assistant Client
- HomeAssistantClient: REST API, Long-lived Token in SecretStore
- Harmony Hub über HA (kein direkter API-Zugriff nötig)
- Commands: "licht wohnzimmer an/aus", "heizung 21 grad", "szene film", "harmony tv an"
- HA-Whitelist für erlaubte Entities/Services (Sicherheit)
- Neue Klasse: `tools/home_assistant_client.py`
- Abhängigkeit: nur `httpx` (bereits vorhanden)

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

## Phase 10 – RPi5 Avatar-Display ✅ TEILWEISE ABGESCHLOSSEN

- ✅ Pepper's Ghost Display am RPi5 in Betrieb (720×1280, DSI, Fullscreen)
- ✅ RPi5AvatarDisplay: echte AvatarDisplay-Implementierung, Render-Thread
- ✅ Tower ↔ RPi5 verdrahtet (RobotClient, SecretStore: robot_host)
- ✅ Idle-Animationen (Glance, Smile, Soft-Close, Surprise)
- ✅ Lip-Sync Fix (show_speaking Reset-Bug)
- ✅ systemd-Autostart dokumentiert
- **Offen:** Drehteller (28BYJ-48 Stepper + Hall-Sensor Homing)
- **Offen:** Sensor-Integration (Kamera, BME280, APDS-9960)
- **Offen:** Gehäuse-Finish (Resin-Druck, Rinde, Moos)

## Phase 11 – Dokument-Zusammenfassung 📄 ✅ ABGESCHLOSSEN

Saleria kann PDF- und Textdateien zusammenfassen.

- ✅ Dateien via Matrix senden → Saleria extrahiert Text → LLM-Zusammenfassung
- ✅ Command: `zusammenfassung C:\...\datei.pdf` → LLM-Zusammenfassung
- ✅ PDF-Parsing: pymupdf (robustes Parsing)
- ✅ TXT: direkt lesen (UTF-8, Fallback Latin-1)
- ✅ Rohtext in Chat-History (Rückfragen möglich: "was steht auf Seite 3?")
- ✅ Audio immer an Matrix (nie lokal am Tower abspielen)
- Kein OCR in v1 (gescannte PDFs → Hinweis, kann später mit tesseract ergänzt werden)

## Phase 12 – Audio-Routing + Web-Interface ✅ ABGESCHLOSSEN

Einheitliches Audio-Routing: Audio wird immer an Matrix gesendet. Lokale PC-Ausgabe
ist optional und per Flag steuerbar.

- **Audio-Flag**: `AudioOutputMode` (matrix_only / matrix_and_local)
  - Default: `matrix_only` (sicher für unterwegs)
  - Alle Audio-Pfade (TTS, Timer, etc.) prüfen dieses Flag
- **Web-Interface**: FastAPI Endpoint zum Togglen des Flags
  - Minimales HTML-UI (kein Framework)
  - Toggle: "Audio am PC abspielen" an/aus
  - Status-Anzeige: aktuelle Einstellung
- **Später (Phase 10 Hardware)**: APDS-9960 Näherungssensor als automatischer Trigger
  - Nutzer am Schreibtisch → `matrix_and_local`
  - Nutzer weg → `matrix_only`
- Neue Klasse: `core/audio_router.py` (AudioRouter)
- Integration: Bridge + Assistant lesen Flag statt hardcoded Logik

## Phase 13 – Computer Use (Anthropic Vision + PC-Steuerung) ✅ ABGESCHLOSSEN

Saleria kann auf Anweisung des Nutzers auf Bildschirmelemente klicken –
gesteuert über Anthropic Computer Use (Sonnet 4.6 Vision).

### Flow
1. Nutzer: "schick mir einen screenshot"
2. Saleria: Screenshot via mss → Matrix
3. Nutzer: "klick auf [Element]"
4. Saleria: Screenshot → Anthropic Computer Use API (Bild + Tool-Def)
5. Sonnet: strukturierte Antwort `{"action": "click", "coordinate": [x, y]}`
6. Saleria: `WindowsActionController.click(x, y)`
7. Saleria: 3s warten → neuer Screenshot → Matrix (Verification)

### Technisch
- **Anthropic Computer Use Tool**: `computer_20250124` Tool-Typ im API-Call
  - Strukturierte Ausgabe (click, type, key, scroll) statt freies Koordinaten-Raten
  - Kalibriert auf exakte Pixel-Koordinaten
- **AnthropicClient erweitern**: Vision-Input (Base64-Bild) + Computer-Use-Tool-Definition
- **Neuer Command**: `klick auf <Element>` → Screenshot → Vision → Klick → Verification
- **Mapping**: Computer Use Actions → bestehende WindowsActionController-Methoden
  - `click(x, y)` → `pyautogui.click(x, y)`
  - `type(text)` → `pyautogui.typewrite(text)`
  - `key(name)` → `pyautogui.press(name)`
  - `scroll(direction, amount)` → `pyautogui.scroll(amount)`
- **DPI-Kompensation**: Windows-Skalierung (125%/150%) muss berücksichtigt werden

### Kosten
- ~4-5 Cent pro Klick-Aktion (Screenshot-Bild ~6.000 Tokens + Koordinaten-Antwort)
- Bei gelegentlicher Nutzung (5-10x/Tag) vernachlässigbar

### Entscheidungen (gelöst)
- Multi-Monitor: Monitor-Index konfigurierbar (Setter + Web-Dashboard http://localhost:8090)
- Loop-Modus: Nein – jeder Schritt einzeln per Befehl (User bestätigt)
- Sicherheit: Keine Whitelist nötig – User muss jeden Klick explizit anweisen

## Phase 14 – Web-Suche (Brave Search + LLM-Aufbereitung) ✅ ABGESCHLOSSEN

Saleria kann auf Anfrage im Internet suchen und die Ergebnisse aufbereitet zurückgeben.

### Flow
1. Nutzer: "Suche Dachdecker in der Nähe von Plattenburg"
2. Saleria → Claude: extrahiert Suchbegriff + Ort ("Dachdecker Plattenburg Brandenburg")
3. Saleria → Brave Search API: REST-Query
4. API → Saleria: Rohe Suchergebnisse (JSON)
5. Saleria → Claude: "Bereite diese Ergebnisse auf"
6. Claude → Saleria: Formatierte Zusammenfassung (Name, Adresse, Bewertung, Link)
7. Saleria → Matrix: Aufbereitete Antwort

### Technisch
- **Brave Search API**: 2000 Queries/Monat kostenlos, einfache REST-API, kein Google-Account
- **Claude als Doppelrolle**: Intent-Erkennung ("was will der User suchen") + Aufbereitung ("mach JSON lesbar")
- **Neue Klasse**: `tools/brave_search_client.py` (BraveSearchClient)
- **SecretStore**: `brave_api_key` für API-Key
- **Neuer Command**: `suche <query>` oder natürliche Sprache ("suche mir...", "finde...")
- **Abhängigkeit**: nur `httpx` (bereits vorhanden)

### Kosten
- Brave API: $5/1000 Req, aber $5 monatliches Guthaben → effektiv kostenlos unter 1000 Req/Monat
- Claude Intent + Aufbereitung: ~500 Input + ~300 Output Tokens → ~0.5 Cent pro Suche

### Entscheidungen (gelöst)
- Auto-Erkennung: Nein – explizit ("suche ...") + LLM-Fallback über Saleria-Prompt reicht
- Lokale Ergebnisse: Nein – Standard-Web-Suche, Brave liefert beides implizit
- Ergebnis-Caching: Nein – bei effektiv kostenlosem Free-Tier nicht nötig

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
