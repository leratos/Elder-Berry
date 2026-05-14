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
- **Offen:** Sensor-Integration (Kamera, BME280, APDS-9960)

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
- Drehteller: 200mm Alu Lazy-Susan Lager + 28BYJ-48 Stepper (Reaktionsantrieb)
- A3144 Hall-Sensoren für ±180° Begrenzung + Home-Position
- Stromversorgung: USB-C Netzteil (Dauerbetrieb) oder Akku – je nach Standort
- Pepper's Ghost Kammer fertigstellen + testen
- Ästhetik + Finish (Rinde bemalen, Moos-Details)
- **Offen:** Standort (Schreibtisch, Regal, Sideboard)

## Phase 5 – Software Advance ✅ GRÖSSTENTEILS ABGESCHLOSSEN

- AnthropicClient (Sonnet 4.6 primär, Ollama Offline-Fallback)
- RAG Memory: ChromaDB + OllamaEmbeddingClient (nomic-embed-text, 768-dim)
- STT: FasterWhisperEngine (GPU-beschleunigt, VAD-Filter, Lazy-Load)
- Startup-Script: start_saleria.py (Terminal/Matrix/Voice-Modus)
- **Offen:** Emotion-State-Machine (Persistente Stimmung über Konversation hinweg)
- **→ Phase 26:** ~~Multimodale Kamera-Eingabe~~ ✅ (RPi Camera + Anthropic Vision)
- **Offen:** Feinschliff Aktions-Logik (komplexe Verkettungen)

## Phase 6 – Matrix-Integration ✅ ABGESCHLOSSEN

- Synapse Matrix-Server auf Plesk-Server (matrix.example.com)
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

### ⏸️ ZURÜCKGESTELLT: Home Assistant Client

> Zurückgestellt wegen Umzug – HA-Setup wird am neuen Standort komplett neu aufgebaut.
> Nur Logitech Harmony Hub bleibt bestehen.

- HomeAssistantClient: REST API, Long-lived Token in SecretStore
- Harmony Hub über HA (kein direkter API-Zugriff nötig)
- Commands: "licht wohnzimmer an/aus", "heizung 21 grad", "szene film", "harmony tv an"
- HA-Whitelist für erlaubte Entities/Services (Sicherheit)
- Neue Klasse: `tools/home_assistant_client.py`
- Abhängigkeit: nur `httpx` (bereits vorhanden)

---

## Phase 9 – Multimodal + Autonomie 🔭 VISION

### ~~Kamera-Integration (Multimodal)~~ → Phase 26 ✅

- Umgesetzt als Phase 26 mit RPi Camera Module 3 + Anthropic Vision API

### Emotion Recognition (Voice)

- Audio-basierte Emotionserkennung → Saleria passt Antwortton an
- Analyse-Dokument: `docs/concepts/emotion-recognition-voice.md`
- Empfehlung: Hybrid-Ansatz (Audio-Features + LLM-Textanalyse, kein ML-Modell)
- Niedrige Priorität – erst wenn Sprachnachrichten regelmäßig genutzt werden

### ~~Multi-Channel~~ GESTRICHEN

> Eigener Matrix-Server = volle Kontrolle über eigene Daten.
> Discord/Telegram würde Daten an Dritte geben → widerspricht dem Projektprinzip.

---

## Phase 10 – RPi5 Avatar-Display ✅ TEILWEISE ABGESCHLOSSEN

- ✅ Pepper's Ghost Display am RPi5 in Betrieb (720×1280, DSI, Fullscreen)
- ✅ RPi5AvatarDisplay: echte AvatarDisplay-Implementierung, Render-Thread
- ✅ Tower ↔ RPi5 verdrahtet (RobotClient, SecretStore: robot_host)
- ✅ Idle-Animationen (Glance, Smile, Soft-Close, Surprise)
- ✅ Lip-Sync Fix (show_speaking Reset-Bug)
- ✅ systemd-Autostart dokumentiert
- **→ Phase 27:** Drehteller-Steuerung (28BYJ-48 + A3144 Hall-Sensor) ✅
- **→ Phase 26:** Kamera-Integration (RPi Camera Module 3) ✅
- **Offen:** Sensor-Integration (BME280, APDS-9960) – direkt ueber RPi5 GPIO/I2C
- **Offen:** Gehaeuse-Finish (Resin-Druck, Rinde, Moos)

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

## Phase 15 – Self-Update 🔄 ✅ ABGESCHLOSSEN

Saleria kann sich auf Befehl selbst aktualisieren (git pull + pip install + restart).
Enabler für alle folgenden Phasen: Code auf Laptop entwickeln, pushen, per Matrix live schalten.

- ✅ **Neuer Command**: `update` in ProcessCommandHandler
  - git fetch → Änderungen prüfen → git pull --ff-only → pip install (wenn pyproject.toml geändert) → restart
  - Kein Auto-Update – nur auf expliziten Befehl ("update dich", "neue Funktionen")
  - Sicherheit: --ff-only (kein Merge), Hash-Validierung, pip nur eigenes Projekt
  - Nutzt bestehenden Restart-Mechanismus (os.execv + Flag-Datei)
- ✅ **Tests**: `tests/test_self_update.py` (23 Tests)
- **Konzept**: `docs/concepts/phase-15-self-update.md`

## Phase 16 – Notizen & Wissensdatenbank 📝 ✅ ABGESCHLOSSEN

Expliziter Fakten- und Notizspeicher – getrennt von ChromaDB-RAG-Memory.

- ✅ **NoteStore**: SQLite + FTS5 Volltextsuche (`tools/note_store.py`)
  - Key-Value-Fakten: "merk dir: WLAN Büro ist xyz" → exakt abrufbar per "was ist WLAN Büro?"
  - Freitext-Notizen: "notiz: Vermieter heißt Müller, Kaution 1200€" → per Volltextsuche
  - Upsert bei existierenden Keys, FTS5-Trigger für automatische Index-Sync
- ✅ **NoteCommandHandler**: Neuer CommandHandler (`comms/commands/note_commands.py`)
  - Commands: merk dir, notiz, was ist, notizen suche, notizen, notiz löschen, vergiss
  - "was ist"-Miss → success=False → LLM-Fallthrough (keine Kollision mit allgemeinen Fragen)
- ✅ **Tests**: `tests/test_note_store.py` (27 Tests) + `tests/test_note_commands.py` (27 Tests)
- **Konzept**: `docs/concepts/phase-16-notizen-wissensdatenbank.md`

## Phase 17 – Kalender-Watcher (Proaktive Meeting-Erinnerungen) 📅 ✅ ABGESCHLOSSEN

Saleria erinnert proaktiv vor Terminen – ohne dass der Nutzer fragen muss.

- ✅ **CalendarWatcher**: Daemon-Thread, pollt GoogleCalendarClient alle 5 Min (`comms/calendar_watcher.py`)
  - Konfigurierbare Erinnerungszeiten: Default [15, 5] Minuten vor Termin
  - Deduplizierung: gleicher Reminder feuert nicht doppelt
  - Ganztags-Events werden übersprungen
  - Vergangene Events automatisch aus State entfernt (kein Memory-Leak)
- ✅ **GoogleCalendarClient**: `get_events_range(start, end)` hinzugefügt
- ✅ **MatrixBridge**: CalendarWatcher integriert (start/stop symmetrisch)
- ✅ **Abgrenzung**: BriefingScheduler = täglich 07:30, ReminderScheduler = explizite Timer,
  CalendarWatcher = automatisch vor jedem Termin
- ✅ **Tests**: `tests/test_calendar_watcher.py` (24 Tests)
- **Konzept**: `docs/concepts/phase-17-kalender-watcher.md`

## Phase 18 – Emotion-State-Machine 🧠 ✅ ABGESCHLOSSEN

Saleria bekommt ein emotionales Kurzzeitgedächtnis – die letzten Emotionen
fließen als Kontext in den System-Prompt, sodass das LLM die Stimmung natürlich
weiterentwickeln kann statt pro Turn bei Null zu starten.

- ✅ **EmotionTracker**: Ringbuffer (5 Einträge, deque), 30 Min Decay, Valenz-basierte Trend-Erkennung
- ✅ **CharacterEngine ABC**: `get_mood_context()` (nicht-abstrakt, Default None)
- ✅ **SaleriaEngine**: `extract_emotion()` füttert Tracker, `get_mood_context()` liefert Summary
- ✅ **Assistant**: mood_context wird vor LLM-Call in System-Prompt injiziert
- ✅ **Tests**: `tests/test_emotion_tracker.py` (32 Tests)
- **Prompt-Format**: `Emotionaler Kontext: angry → neutral | Dominante Stimmung: angry | Tendenz: aufhellend`

## Phase 19 – Wiederkehrende Erinnerungen 🔁 ✅ ABGESCHLOSSEN

Timer und Erinnerungen mit Wiederholungslogik: "Erinnere mich
jeden Montag um 9 an den Wochenbericht."

- ✅ ReminderStore: `recurrence`-Feld (daily, weekly:N, monthly:N, weekdays, biweekly:N)
- ✅ ReminderScheduler: Reschedule-Logik nach dem Feuern (nächstes Datum berechnen)
- ✅ WeatherCommandHandler: Neue Patterns für "jeden Montag", "täglich", "werktags"
- ✅ Verwaltung: Anzeige + Löschen wiederkehrender Erinnerungen
- **Konzept**: `docs/concepts/phase-19-wiederkehrende-erinnerungen.md`

## Phase 20 – Multi-Step Task Chaining ⛓️ ✅ ABGESCHLOSSEN

Saleria kann mehrstufige Aufgaben abarbeiten, bei denen das Ergebnis eines
Schritts als Input für den nächsten dient (ReAct-Pattern).

- ✅ **TaskChainRunner**: LLM-gesteuerter Loop (`core/task_chain.py`)
  - LLM → Remote-Command → Ergebnis als Kontext → nächster LLM-Call → ... → DONE
  - MAX_STEPS=5, Ergebnis-Trimming auf 2000 Zeichen (kein Token-Limit nötig)
  - Eigener CHAIN_SYSTEM_PROMPT mit verfügbaren Remote-Commands
  - on_step Callback für Zwischenstatus an Matrix
- ✅ **Assistant**: `multi_step` als neue Aktion im System-Prompt + Pass-through
- ✅ **MatrixBridge**: `_handle_multi_step()` – erkennt multi_step, führt Chain aus, sendet Schritte + Zusammenfassung
- ✅ **Tests**: `tests/test_task_chain.py` (16 Tests)
- **Konzept**: `docs/concepts/phase-20-multi-step-task-chaining.md`

## Phase 21 – Proaktive Kontext-Verknüpfung 🔗 ✅ ABGESCHLOSSEN

CalendarWatcher-Alerts werden kontextbewusst: relevante Notizen, Mails und
Wetter werden automatisch zum Termin-Reminder hinzugefügt.

- ✅ ContextEnricher: Sucht NoteStore, IMAP, Weather, MemoryStore zum Termin-Titel
- ✅ LLM formatiert gesammelten Kontext als natürliche Nachricht (Saleria-Stil)
- ✅ Integration in CalendarWatcher (nur beim ersten Reminder, z.B. 15 Min)
- ✅ Graceful Degradation: fehlende/fehlerhafte Quellen werden übersprungen (3s Timeout)
- ✅ Template-Fallback wenn LLM nicht verfügbar
- **Konzept**: `docs/concepts/phase-21-proaktive-kontext-verknuepfung.md`

## Phase 22 – Intent-Routing Verbesserung 🎯 ✅ ABGESCHLOSSEN

Die Erkennung, ob eine User-Nachricht ein direkter Command oder eine
LLM-Konversation ist, wurde verbessert.

- ✅ Keyword-Audit: fehlende Synonyme/Umgangssprache ergänzt (alle 9 Handler)
- ✅ Dynamischer Command-Prompt: `get_command_summary()` statt statischer Block
- ✅ Retry bei Parse-Fehler: LLM bekommt Feedback wenn Command nicht erkannt (max 1 Retry)
- ✅ **Tests**: `tests/test_intent_routing.py` (107 Tests)
- **Konzept**: `docs/concepts/phase-22-intent-routing.md`

## Phase 23 – Konversations-Zusammenfassung 📝 ✅ ABGESCHLOSSEN

ChatHistory vergisst den Gesprächsanfang nicht mehr – evicted Messages werden
zu einer Rolling Summary komprimiert.

- ✅ ChatHistory: Rolling Summary bei Eviction (LLM-basiert, max 3 Sätze)
- ✅ Batch-Eviction: alle 3 evicted Messages → 1 LLM-Call
- ✅ Summarizer-Callback als DI-Parameter (kein direkter LLM-Import)
- ✅ Summary wird im format_for_prompt() vor den letzten Nachrichten angezeigt
- ✅ Background-Thread: Summary blockiert nicht den Response
- ✅ **Tests**: `tests/test_chat_history.py` (34 Tests)
- **Konzept**: `docs/concepts/phase-23-konversations-zusammenfassung.md`

## Phase 24 – Avatar Asset Management & Animationssystem 🎨 ✅ ABGESCHLOSSEN

Salerias Avatar wird ausdrucksstärker und einfacher konfigurierbar.

- ✅ **Neue Assets**: 8 Bodies, 11 Augenpaare, 15 Münder (45 Assets gesamt)
- ✅ **EMOTION_MAP**: Jede Emotion visuell unterscheidbar (10 distinct Combos)
- ✅ **Breathing**: Subtile Atembewegung per Sinus-Offset (±2px, 1.2 Hz)
- ✅ **Verbesserte Lip-Sync**: Gewichtete Zufallsauswahl, 5 Stufen, ±30ms Jitter
- ✅ **YAML-Config**: EMOTION_MAP + Lip-Sync + Breathing externalisiert, Fallback auf Defaults
- ✅ **Web-Interface**: Avatar-Editor mit Canvas-Preview, Asset-Browser, Animation-Preview
- ✅ **Effekt-Layer**: Optionaler 4. Layer (effect/) pro Emotion, render_to_file() Support
- ✅ **Tests**: 54 Tests (Renderer + ConfigLoader) + 31 Tests (Avatar-Editor)
- **Konzept**: `docs/concepts/phase-24-avatar-asset-management.md`

## Phase 25 – Zentrales Logging & Error-Monitoring 📊 ✅ ABGESCHLOSSEN

Fehler aus allen Komponenten werden zuverlässig erfasst, persistent gespeichert,
und bei kritischen Problemen wird der Nutzer proaktiv über Matrix informiert.

- ✅ Zentrales Logging: `dictConfig()` mit RotatingFileHandler (5 MB, 3 Backups, UTF-8)
- ✅ ErrorCollector: Custom logging.Handler für ERROR+, Deduplizierung (5 Min Cooldown), Rate-Limiting (5/10 Min)
- ✅ Matrix-Alerting: ErrorCollectorHandler → asyncio Callback → Matrix-Room
- ✅ bridge._log_error() entfernt: alle 7 Stellen durch Standard-Logging ersetzt
- ✅ **Tests**: 13 Tests (ErrorCollector)
- **Konzept**: `docs/concepts/phase-25-zentrales-logging.md`

## Phase 26 – Kamera-Integration (RPi Camera Module 3) 📷 ✅ ABGESCHLOSSEN

RPi Camera Module 3 in die Projekt-Architektur integriert.

- ✅ **CameraController ABC + RPi5Camera**: picamera2, lazy-init
- ✅ **Server-Endpoints**: GET /camera/capture + /camera/status
- ✅ **RobotClient**: capture_image() + camera_status()
- ✅ **AnthropicClient**: describe_image() (Standard Vision API)
- ✅ **CameraCommandHandler**: foto + camera_describe Commands
- ✅ **SimulatedCamera**: 320x240 dunkelgrau Testbild
- ✅ **Tests**: 29 Tests (11 camera_controller + 18 camera_commands)
- **Konzept**: `docs/concepts/phase-26-kamera-integration.md`

## Phase 27 – Drehteller-Steuerung (28BYJ-48 + A3144 Hall-Sensor) ✅ ABGESCHLOSSEN

Software-Integration des Drehtellers in die Projekt-Architektur.
Hardware bereits getestet (test_stepper.py, test_hall.py).

- ✅ **TurntableController ABC + RPi5TurntableController**: lgpio, Background-Thread, Half-Step-Sequenz
- ✅ **Hall-Sensor Homing**: immer CCW, Sicherheitslimit 4200 Steps (~369 Grad)
- ✅ **Soft-Limits**: +/-180 Grad mit Clamp + Warnung (USB-C Kabel-Constraint)
- ✅ **Server-Endpoints**: /turntable/rotate, /turntable/home, /turntable/stop, /turntable/status
- ✅ **RobotClient**: rotate_turntable(), home_turntable(), stop_turntable(), turntable_status()
- ✅ **TurntableCommandHandler**: 7 Commands ("dreh dich", "schau nach links/rechts", "drehteller home/status")
- ✅ **SimulatedTurntable**: Synchroner Simulator fuer Tower-Tests
- ✅ **RPi5 Remote-Update**: `update rpi` / `update alles` via Matrix (git pull + pip + systemctl restart)
- ✅ **Server-Endpoint**: POST /system/update (git pull + pip install + systemctl restart)
- ✅ **Tests**: 47 Tests (Controller + Server + Client + Commands)
- **Konzept**: `docs/concepts/phase-27-drehteller-steuerung.md`

---

## Projektgrenzen (ehrliche Einschätzung)

### Was dieses Projekt ist

- **Persönlicher Single-User Assistent** – für eine Person, kein Multi-Tenant
- **Zunehmend proaktives System** – Saleria antwortet auf Eingaben und wird schrittweise proaktiver (Kalender-Watcher, Kontext-Verknüpfung)
- **Lokale KI-Pipeline** – Daten bleiben auf eigenem Server/Tower; kein Cloud-Zwang
- **Hobby-Projekt mit echtem Nutzen** – kein kommerzielles Produkt

### Technische Eigenschaften (keine Einschränkungen für den Use-Case)

| Bereich | Eigenschaft | Kontext |
|---|---|---|
| Antwortzeit | 3–8s pro Turn | Für einen Assistenten völlig akzeptabel – kein Gesprächsersatz, sondern Hilfe |
| LLM-Qualität | Abhängig von Anthropic/Ollama | Kein eigenes Fine-Tuning nötig – Sonnet 4.6 ist state-of-the-art |
| Offline-Fallback | phi4:14b lokal | Schlechter als Sonnet, aber funktional für einfache Anfragen |
| Gleichzeitige User | 1 (sequenziell) | Single-User by Design – kein Problem |
| Sprachqualität | ElevenLabs (primär) + XTTS v2 (Fallback) | Seit Phase 44 Cloud-TTS primär (~€22/Monat), lokales XTTS v2 als Fallback |
| Avatar-Display | Pepper's Ghost (5") | Klein, aber charmant – passt zum Holunder-Konzept |
| Kamera-Reasoning | Cloud-LLM nötig | Vision-Modelle lokal noch nicht ausgereift; OpenRouter ist sinnvoll |

### Was absichtlich nicht implementiert wird

- **Sicherheits-Infrastruktur für mehrere User** – nicht der Use-Case
- **Mobile App** – Element ist der Client, keine eigene App geplant
- **Emotionale Manipulation / Dark Patterns** – Saleria soll helfen, nicht abhängig machen
- **Autonome Code-Änderungen** – ClaudeAgent darf Docs schreiben, aber nicht `src/` ändern (Sicherheit)

### Realistisches Endprodukt

Ein physischer Assistent auf dem Schreibtisch (Holunder-Hologramm), erreichbar via Handy (Element) und Sprache, der:

- Fragen beantwortet und Gespräche führt (Saleria-Persönlichkeit)
- Kalender, Wetter, Erinnerungen managed
- Proaktiv vor Terminen erinnert (Kalender-Watcher)
- Fakten und Notizen speichert und abruft (Wissensdatenbank)
- Kontakte verwaltet und bei E-Mail-Antworten berücksichtigt (Kontaktbuch)
- Aufgaben mit Prioritäten und Kategorien verwaltet (To-Do-Liste)
- Auf E-Mails antwortet mit Draft-Generierung und Bestätigung
- Im Internet sucht und Ergebnisse aufbereitet (Brave Search)
- Den PC/Tower remote steuert (Screenshots, Medien, Prozesse, Computer Use)
- Sich physisch zum Nutzer dreht (Drehteller mit Hall-Sensor Homing)
- Sich selbst aktualisiert (Tower + RPi5 per Matrix-Command)
- Das Smart Home steuert (Lichter, Heizung via HA – nach Umzug)
- Sprachbefehle per Wake Word entgegennimmt ("Hey Saleria") oder Alexa als Proxy nutzt
- Sich an Gespräche erinnert (RAG-Memory)
- Proaktiv auf wichtige Events aufmerksam macht (Alerts)

Das ist ein vollständiges, nützliches Produkt – kein Prototyp mehr.

## Phase 28 – E-Mail-Antworten via Matrix ✅ ABGESCHLOSSEN

Saleria kann auf E-Mails antworten – mit Draft-Generierung, Bestätigungsfluss
und SMTP-Versand.

- ✅ **EmailSender**: SMTP-Versand (SSL/STARTTLS), `tools/email_sender.py`
- ✅ **PendingConfirmationStore**: Generischer Bestätigungsspeicher (1 pro User, 5 Min TTL)
- ✅ **MailCommandHandler erweitert**: `antworte auf #<ID> <Anweisung>` Command
  - LLM generiert Antwort-Entwurf basierend auf Original-Mail + Anweisung
  - Nutzer bestätigt ("ja") oder korrigiert ("nein, förmlicher")
- ✅ **MatrixBridge**: Bestätigungs-Logik für pending Drafts
- ✅ **setup_email.py erweitert**: SMTP-Konfiguration + Verbindungstest (9 Provider)
- ✅ **Tests**: 34 Tests (EmailSender + PendingStore + MailCommands)
- **Konzept**: `docs/concepts/phase-28-email-reply.md`

## Phase 29 – Kontaktbuch (ContactStore) ✅ ABGESCHLOSSEN

Persönliches Kontaktbuch mit Volltextsuche und E-Mail-Integration.

- ✅ **ContactStore**: SQLite + FTS5, Upsert per Name (case-insensitive), `tools/contact_store.py`
  - Felder: Name, Rolle, E-Mail, Formalität (förmlich/locker), Notizen
  - `find_by_email()` für automatischen Kontakt-Lookup bei E-Mail-Antworten
- ✅ **ContactCommandHandler**: `comms/commands/contact_commands.py`
  - Commands: kontakt:, wer ist, kontakte, kontakte suche, kontakt löschen
  - Automatische Feld-Erkennung: `@` → E-Mail, "förmlich"/"locker" → Anrede
  - `fallthrough=True` wenn Kontakt nicht gefunden → LLM beantwortet "wer ist Einstein?"
- ✅ **CommandResult.fallthrough**: Neues Feld in `base.py`, Bridge-Check vor LLM-Routing
- ✅ **Mail-Integration**: Kontaktkontext in LLM-Prompt bei E-Mail-Antworten (Phase 28)
- ✅ **Tests**: 51 Tests (ContactStore + ContactCommandHandler)
- **Konzept**: `docs/concepts/phase-29-kontaktbuch.md`

## Phase 30 – Aufgabenliste (TodoStore) ✅ ABGESCHLOSSEN

To-Do-Liste mit Prioritäten, Kategorien und Briefing-Integration.

- ✅ **TodoStore**: SQLite + WAL, Prioritäten (hoch/mittel/niedrig), Kategorien, `tools/todo_store.py`
  - `format_for_briefing()` für Morgen-Briefing Integration
  - 90-Tage Auto-Cleanup erledigter Todos
- ✅ **TodoCommandHandler**: `comms/commands/todo_commands.py`
  - Commands: todo:, todos, todo erledigt, todo wieder öffnen, todo priorität, todo löschen
  - Filter: todos hoch, todos Arbeit, todos erledigt, todos aufräumen
  - Flexible Feld-Erkennung: `todo: Dachdecker anrufen, hoch, Arbeit`
- ✅ **Briefing-Integration**: Offene Todos im BriefingScheduler
- ✅ **Tests**: 74 Tests (TodoStore + TodoCommandHandler)
- **Konzept**: `docs/concepts/phase-30-todo-liste.md`

## Phase 31 – Bridge Refactoring (Technische Schulden) ✅ ABGESCHLOSSEN

Große Dateien aufgeteilt und Verantwortlichkeiten sauber getrennt.

- ✅ **process_commands.py aufgeteilt**: 1142 → 200 Zeilen + 6 neue Handler-Dateien
  - git_commands.py, docker_commands.py, wol_commands.py, update_commands.py, selfcheck_commands.py, cmd_utils.py
- ✅ **bridge.py aufgeteilt**: 1589 → 417 Zeilen (74% Reduktion)
  - message_handlers.py (774 Zeilen), audio_pipeline.py (315 Zeilen), restart_manager.py (152 Zeilen)
  - Bridge delegiert via Komposition an Handler, AudioPipeline, RestartManager
- ✅ **start_saleria.py refactored**: run_matrix() in 3 Helper-Funktionen aufgeteilt
- ✅ **Tests**: 1866/1866 bestehende Tests grün, keine Regressionen

## Phase 32 – Test-Offensive ✅ ABGESCHLOSSEN

Umfassende Testabdeckung für alle bisher ungetesteten Module nachgeholt.

- ✅ **15 neue Testdateien** (410 Tests) für 6 Alt-Handler + 9 neue Module aus Phase 31
- ✅ **4 weitere Testdateien** (128 Tests): AnthropicClient, OllamaClient, OpenRouterClient, Bridge
- ✅ Erkenntnisse dokumentiert (RateLimitError toter Code, frozenset-Verhalten)
- ✅ Gesamt: 538 neue Tests, keine Regressionen

## Phase 33 – Smart Context Layer ✅ ABGESCHLOSSEN

Keyword-basierte Kontext-Injection: relevante Daten aus allen Stores werden
automatisch in den LLM-Prompt injiziert.

- ✅ **SmartContextProvider**: Keyword-basierte Input-Analyse, 6 Quellen (Calendar, Todos, Notes, Contacts, Reminders, Weather)
- ✅ 11 Meta-Phrasen ("was muss ich", "briefing", "tagesplan" etc.) → Multi-Source-Abfrage
- ✅ Parallele Abfrage via ThreadPoolExecutor, 3s Timeout pro Quelle, Graceful Degradation
- ✅ Assistant-Integration: smart_context Block wird vor memory_context in System-Prompt injiziert
- ✅ **Tests**: 52 Tests (Keyword-Erkennung, Query-Methoden, Integration, Timeout, Edge Cases)
- ✅ Gesamt: 2754 Tests grün

## Phase 34 – Briefing 2.0 ✅ ABGESCHLOSSEN

Personalisiertes Morgenbriefing mit Geburtstagen, offenen E-Mails,
"Vor einem Jahr"-Notizen und Wochenend-Variante.

- ✅ Geburtstage aus ContactStore (birthday-Feld: YYYY-MM-DD / 0000-MM-DD)
- ✅ Offene E-Mails (Anzahl ungelesener Mails als Einzeiler)
- ✅ Flashback-Notizen (≥330 Tage alte Notizen aus NoteStore)
- ✅ Wochenend-Variante (entspannter Ton, Todos/Erinnerungen ausgeblendet)
- ✅ Tests: 18 neue Tests, 2772 gesamt grün

## Phase 35 – Web-Zusammenfassung 🌐 ✅ ABGESCHLOSSEN

"Fasse https://... zusammen" als Command. Web-Inhalte via LLM zusammenfassen.

- ✅ **WebFetcher**: `httpx` + `trafilatura` (Primär) + BeautifulSoup (Fallback)
- ✅ **AdvancedCommandHandler**: Pattern `fasse <url> zusammen` / `zusammenfassung von <url>`
- ✅ **LLM-Pipeline**: gleiche Logik wie Dokument-Zusammenfassung (history_text → LLM)
- ✅ **Fallback**: Brave Search Snippet wenn URL nicht abrufbar (robots.txt, Paywall)

## Phase 36 – Nextcloud-Integration ☁️ ✅ ABGESCHLOSSEN

Self-Hosted Nextcloud als Backend für Dateien, Kalender und Kontakte.

### Unterphasen

- **36.1** ✅ Nextcloud Setup + WebDAV Files (NextcloudFilesClient)
  → Dateien hoch-/runterladen, Verzeichnisse listen, Share-Links
- **36.2** ✅ CalDAV Kalender (CalDAVCalendarClient → GoogleCalendarClient ersetzen)
  → Gleiche Methoden, DI-Austausch, Google Calendar nur noch Fallback
- **36.3** ✅ CardDAV Kontakte (bidirektionaler Sync)
  → Alle vCard-Felder gesynct, vcard_uid-Tracking gegen Duplikate

### Nicht migriert (by Design)

- NoteStore, TodoStore (SQLite + FTS5 ist schneller und offline-fähig)
- E-Mail (direktes IMAP ist besser als Nextcloud Mail)

- **Konzept**: `docs/concepts/phase-36-nextcloud-integration.md`

## Phase 37 – Smart Home Integration 🏠 TEILWEISE ABGESCHLOSSEN

Lokale Smart-Home-Steuerung über erweiterbare Adapter-Architektur.
Logitech-Cloud wurde abgelöst. Dashboard als modulare Kommandozentrale.

### Unterphasen

| Phase | Titel | Status |
|-------|-------|--------|
| 37.1 | Harmony Hub – vollständige Ablösung | ✅ abgeschlossen |
| 37.2 | Harmony Remote – Erweiterte Steuerung & Szenen | ✅ abgeschlossen |
| 37.3 | Dashboard 2.0 – Modulare Smart Home PWA | ✅ abgeschlossen |
| 37.4 | SmartHomeInterface + Plugin-Registry | offen |
| 37.5 | Home Assistant Adapter | offen (nach Umzug) |
| 37.6 | Alexa-Integration (Emulated Hue) | offen (nach Umzug + HA) |

### 37.1 ✅ Harmony Hub – Vollständige Logitech-Ablösung

- HarmonyAdapter auf RPi5 (WebSocket :8088, Backup-Config)
- Config-Mock-Server auf Rootserver (POST-Endpoints, SSL, DNS-Override)
- PWA Harmony Remote (Standalone, mobile-first)
- 5 Server-Endpoints, Matrix-Commands (fernsehen an, lauter, leiser etc.)

### 37.2 ✅ Harmony Remote – Erweiterte Steuerung & Szenen

- Layout-System (HarmonyLayoutManager, auto-generiert + kuratiert)
- PWA-Rewrite: Aktivitäts-Modus + Geräte-Modus + Szenen-Tab
- Szenen-Engine (HarmonySceneManager, CRUD + sequenzielle Ausführung)
- Saleria-Anbindung: "starte szene Gaming" → RPi5 → Szenen-Engine

### 37.3 ✅ Dashboard 2.0 – Modulare Smart Home PWA

Mobile-first PWA auf dem Rootserver als modulare Kommandozentrale (fern.example.com).

- ✅ PWA: installierbar, HTTPS, Service Worker, Offline-Cache
- ✅ Modul-Architektur: DashboardModule ABC, dynamischer Module-Loader
- ✅ System-Status, Harmony Remote, Saleria-Status als Module
- ✅ Nginx Reverse Proxy (HTTPS → HTTP RPi5/Tower)
- **Konzept**: `docs/concepts/phase-36-dashboard-2.0.md`

- **Konzept (Smart Home gesamt)**: `docs/concepts/phase-37-smart-home-integration.md`
- **Konzept (Harmony erweitert)**: `docs/concepts/harmony-remote-erweitert.md`
- **Abhängigkeit**: 37.5/37.6 nach Umzug; 37.1–37.4 sofort

## Phase 38 – Kontakte: Vollintegration Nextcloud + Saleria 📇 ✅ ABGESCHLOSSEN

Saleria kennt alle Informationen aus den Nextcloud-Kontakten und kann
natürliche Fragen über Personen beantworten.

- ✅ Contact-Datenmodell: 7 neue Felder, emails/phones als JSON-Arrays
- ✅ CardDAV-Sync: alle vCard-Properties, vcard_uid-Tracking, Push-Duplikat-Bug fix
- ✅ SmartContextProvider: 15+ Keywords, format_for_llm() Kontext-Injection
- ✅ Natürliche Feld-Abfragen: Geburtstag, Adresse, Telefon, Firma, Gruppen
- ✅ Briefing: Geburtstage morgen/Woche, Jahrestage, Auto-Sync vor Briefing
- ✅ Gruppen-Features: Listing, Filterung per CATEGORIES
- **Konzept**: `docs/concepts/phase-38-kontakte-vollintegration.md`

## Phase 39 – Nextcloud als Datei-Hub + Inhaltssuche ☁️ ✅ ABGESCHLOSSEN

Dateien werden über Nextcloud geteilt statt direkt per Matrix. Volltextsuche
in Dateiinhalten via NC Full text search Plugin.

- ✅ File-Output: Upload nach /Saleria/YYYY-MM/ + Share-Link statt Matrix-Upload
- ✅ Fallback: direkter Matrix-Upload wenn NC nicht verfügbar
- ✅ Inhaltssuche: `cloud inhalt <query>` via NC Unified Search API
- ✅ NC Full text search + Workflow OCR serverseitig konfiguriert

## Phase 40 – Sprachsteuerung / Alexa-Ablösung 🎙️ TEILWEISE ABGESCHLOSSEN

Saleria erhält eine eigene Sprachschnittstelle — unabhängig von Amazon.
Zwei Modi werden parallel unterstützt, sodass zwischen Alexa und Saleria
gewechselt werden kann (Flexibilität, kein harter Cut).

### Unterphasen

| Phase | Titel                                | Status             |
|-------|--------------------------------------|--------------------|
| 40.1  | Alexa Skill "Saleria" (Proxy-Modus)  | ✅ abgeschlossen   |
| 40.2  | Natives Wake Word + Mic Array        | offen              |

### 40.1 ✅ Alexa Skill "Saleria" – Proxy-Modus

Echo macht Wake Word + STT, Text geht an Salerias API auf RPi5.

- ✅ **Infrastruktur**: SSH-Tunnel RPi5→Rootserver, Nginx Reverse Proxy (/alexa/)
- ✅ **AlexaSkillHandler**: Intent-basiertes Routing (TV/Musik/Gaming an, aus, lauter, leiser, stumm, status)
- ✅ **Alexa Skill**: Invocation "meine saleria", 8 Intents, HTTPS-Endpoint
- ✅ **Security**: AlexaRequestVerifier (Cert-URL, RSA-SHA256-Signatur, Timestamp ≤150s, ApplicationId)
- ✅ **Path-Traversal-Fix**: Download-Dateinamen sanitized (Path.name)
- ✅ **Tests**: 52 Tests (30 Handler + 22 Verifier)
- Live-Test: "Alexa, frag Saleria fernsehen an" → TV geht an ✓

### 40.2 – Natives Wake Word + Mic Array (offen)

- OpenWakeWord auf RPi5, faster-whisper auf Tower-GPU
- Hardware: ReSpeaker USB Array (~60€) oder Umbau vorhandener Hardware
- **Konzept**: `docs/concepts/phase-40-sprachsteuerung.md`
- **Abhängigkeit**: 40.2 nach 40.1 (Hardware-Entscheidung)

## Phase 41 – IR-Learning & Geräteverwaltung 📡 GEPLANT

Neue Geräte über die PWA anlernen, IR-Codes speichern, Geräte verwalten.
Setzt Phase 37.2 (Szenen-Engine) voraus und physischen Zugang zum Hub.

- **IR-Learning**: aioharmony learn_command(), Hub-Lernmodus via PWA
- **Lern-UI**: PWA-Wizard (Gerät → Name → Lernen → Fertig)
- **Geräteverwaltung**: Gerät anlegen/löschen, einzelne Commands entfernen
- **API**: POST /harmony/learn, GET /harmony/learn/status, POST /harmony/device/create, DELETE /harmony/device/{id}
- **Fallback**: IR-Codes aus LIRC/irdb manuell importieren
- **Einschränkung**: Physischer Zugang zum Hub nötig (IR-Signal muss Hub erreichen)
- **Konzept**: `docs/concepts/harmony-remote-erweitert.md` (Teil 2)
- **Abhängigkeit**: 37.2 ✅

## Phase 42 – Dokument-Ablage (Cloud Aufräumen) 📂 ✅ ABGESCHLOSSEN

Saleria analysiert Dokumente im `/Eingang/`-Ordner auf Nextcloud, schlägt
nach der Dateinamenskonvention (`YYYY-MM-DD_Kategorie_Beschreibung.ext`)
einen Namen und Zielordner vor, und verschiebt nach Bestätigung.

- ✅ **DocumentClassifier**: Textextraktion (pymupdf → Stirling-PDF OCR → Vision) + Ollama-Analyse
- ✅ **FilingCommandHandler**: "cloud aufräumen" mit Einzelbestätigung (ja / korrigieren / überspringen)
- ✅ **NextcloudFilesClient.move()**: WebDAV MOVE (Overwrite:F, Zielordner auto-erstellt)
- ✅ **OllamaClient.generate_with_image()**: Ollama Vision (llava:7b) für Bilder
- ✅ **Mail-Anhang-Ablage**: "anhang ablegen #<ID>" – PDF-Anhänge aus Mails direkt klassifizieren und ablegen
  - Nur PDF erlaubt (exe, docx, xlsx abgelehnt – Sicherheit), Bitdefender-Validierung
- ✅ **Tests**: 68 neue Tests (23 Classifier + 21 Filing + 8 Move + 5 Vision + 11 Mail-Anhang)
- **Konzept**: `docs/concepts/phase-42-dokument-ablage.md`

## Phase 43 – Routenplanung (Google Maps Directions) 🗺️ ✅ ABGESCHLOSSEN

"Plane meine Fahrt zu Lisa, muss morgen um 16 Uhr da sein" → Adresse aus
Kontakten, Fahrtdauer via Google Maps API, Abfahrtszeit, klickbarer Link.

- ✅ **RoutePlanner**: Google Maps Directions API, Fahrtdauer, Rückwärtsrechnung, Deep-Link (`tools/route_planner.py`)
  - RouteResult Dataclass, RouteError Exception, synchron (httpx.Client)
- ✅ **RouteCommandHandler**: Intent-Parsing ("plane fahrt zu Lisa", "fahrt von Mama zu Lisa", "wie komme ich zu")
  - parse_arrival_time(): "morgen um 16 uhr", "übermorgen", Wochentage
  - Kontakt-Lookup via ContactStore.search(), Home via find_by_group("home")
  - Abfahrtszeit-Berechnung mit konfigurierbarem Puffer (default 15 Min)
- ✅ **ContactStore**: `find_by_group()` als Alias für `find_by_category()`
- ✅ **Google Maps Link**: Deep-Link öffnet App auf Android (kompatibel mit Android Auto)
- ✅ **Tests**: 62 neue Tests (19 RoutePlanner + 43 RouteCommandHandler)
- **Konzept**: `docs/concepts/phase-43-routenplanung.md`

## Phase 44 – Server-Migration & Audio-Router 🚀 ✅ ABGESCHLOSSEN

Saleria zieht vom Tower auf den Rootserver. Bot läuft 24/7 unabhängig
vom Tower. ElevenLabs TTS primär, XTTS v2 Fallback. Cloud-STT primär,
lokales Whisper Fallback. Tower wird optionaler Agent für PC-Steuerung.

### Unterphasen

| Phase | Titel | Status |
|-------|-------|--------|
| 44.1 | ElevenLabsClient + TTSRouter | ✅ abgeschlossen |
| 44.2 | CloudSTTClient + STTRouter | ✅ abgeschlossen |
| 44.3 | DocumentClassifier Umbau (Ollama → Anthropic Vision) | ✅ abgeschlossen |
| 44.4 | TowerServer (FastAPI für Tower-PC) | ✅ abgeschlossen |
| 44.5 | Server-Deploy Vorbereitung | ✅ abgeschlossen |
| 44.6 | Integration + Cutover | ✅ abgeschlossen |

- ✅ **ElevenLabsClient**: REST API, MP3-Rückgabe, SecretStore Keys (elevenlabs_api_key, elevenlabs_voice_id)
- ✅ **TTSRouter**: ElevenLabs primär, Tower XTTS v2 Fallback (implementiert TTSEngine ABC)
- ✅ **CloudSTTClient**: Groq Whisper API (whisper-large-v3, Sprach-Hint)
- ✅ **STTRouter**: Groq primär, Tower FasterWhisper Fallback (implementiert STTEngine ABC)
- ✅ **TowerAgent**: Proxy für Tower-Dienste (TTS/STT/Actions/Screenshot via HTTP), Heartbeat
- ✅ **TowerServer**: FastAPI-Service, 5 Endpoints (/status, /tts, /stt, /action, /screenshot), Action-Dispatcher für 12 Aktionen
- ✅ **DocumentClassifier Umbau**: OllamaClient → AnthropicClient (kein separates Ollama mehr nötig)
- ✅ **Server-Deploy**: [server] Dependency-Gruppe, systemd Units (elder-berry.service + elder-berry-tower.service), ELDER_BERRY_HOME env-var, Security-Hardening
- ✅ **Integration**: Plattform-aware pip install, systemd-aware Restart, Screenshot-Fallback via TowerAgent
- ✅ **Tests**: 136+ neue Tests (43 TTS + 36 STT + 25 Classifier + 32 TowerServer + 25 Deploy + 12 Integration)
- **Kosten**: ~€20-25/Monat Mehrkosten (ElevenLabs Creator $22)
- **Konzept**: `docs/concepts/phase-44-server-migration.md`

## Phase 45 – Settings Dashboard Erweiterung ⚙️ ✅ ABGESCHLOSSEN

Bestehendes Dashboard (localhost:8090) um API-Verwaltung, LLM-Umschalter,
Grundeinstellungen und Sicherheitshärtung erweitert.

- ✅ **Rename**: AudioDashboard → SettingsDashboard (Klasse + Datei + alle Imports)
- ✅ **SECRET_REGISTRY**: 30 Keys in 8 Kategorien, SecretRegistryEntry TypedDict
  - Zentrale `_validate_secret()` mit Typ-Checks (int min/max, float, URL-Prefix)
  - asyncio.Lock für serialisierte Schreibzugriffe
- ✅ **Secrets-API**: GET /api/secrets/status, POST /api/secrets/set, POST /api/secrets/delete
  - Audit-Logging (Key + Client-IP, ohne Secret-Werte)
- ✅ **LLM-Endpoints**: GET /api/llm/status, POST /api/llm/mode
  - LLMRouter: mode Property/Setter, primary/fallback Info, Persistenz im SecretStore
- ✅ **Sicherheitshärtung**: CORS-Fix (allow_origins aus SecretStore), SecurityHeadersMiddleware
  (X-Content-Type-Options, X-Frame-Options, CSP), globaler Exception-Handler
- ✅ **Change-Callbacks**: on_change(key, callback) mit Fehler-Isolation
- ✅ **Metadaten**: updated_at Timestamp pro Key, Settings-Export-Endpoint
- ✅ **Frontend-UX**: Secrets-Tabelle mit Status pro Key, Suchfeld, Accordion-Kategorien,
  2-Stufen-Löschen, Direktlinks zu Anbieter-Dashboards, Inline-Editing, Restart-Badges
- ✅ **Tests**: 142 Tests (37 Dashboard + 26 Secrets + 22 LLM + 13 Security + 13 Stability + 31 Avatar-Editor)
- **Tier 2 (nicht in Phase 45)**: Memory-Browser, Service-Health, Log-Viewer
- **Konzept**: `docs/concepts/phase-45-settings-dashboard.md`

## Phase 46 – Setup-Wizard (Installationsassistent) 🧙 ✅ ABGESCHLOSSEN

Neuer Nutzer kann Elder-Berry von Null aufsetzen: Bootstrap-Script +
Web-Wizard der Schritt für Schritt alle Dienste konfiguriert und testet.

- ✅ **Bootstrap**: `scripts/install.ps1` (Windows) + `scripts/install.sh` (Linux/RPi5)
- ✅ **Web-Wizard**: 8-Schritt-Wizard auf localhost:8090/setup
  - Willkommen, LLM, Matrix, Nextcloud, E-Mail, Standort, Optionale Dienste, Zusammenfassung
  - Progress-Bar, Inline-Verbindungstests, Provider-Dropdown, Hilfe-Links
- ✅ **SetupTests** (`web/setup_tests.py`): Verbindungstest-Klasse (Anthropic, Matrix,
  Nextcloud WebDAV/CalDAV/CardDAV, IMAP/SMTP, Ollama, Brave, Groq, Google Maps)
- ✅ **First-Run-Detection**: `start_saleria.py` erkennt fehlende Matrix-Keys → Wizard starten
- ✅ **Dashboard-Integration**: GET / Redirect auf /setup wenn Setup nicht abgeschlossen,
  Re-Setup-Button im Dashboard für spätere Neukonfiguration
- ✅ **Geocoding**: Standort-Schritt mit Nominatim/OSM-Suche (Stadt → Lat/Lon, kein API-Key)
- ✅ **Standalone-Starter**: `scripts/setup_wizard.py` mit Browser-Auto-Open
- ✅ **FastAPI in Core-Dependencies**: Wizard funktioniert auf frischem System nach `pip install -e .`
- ✅ **Tests**: 50 Tests (19 SetupTests + 21 Wizard-API + 10 Install-Scripts)
- **Konzept**: `docs/concepts/phase-46-setup-wizard.md`

## Phase 47 – Befehlsmuster-Stabilisierung 🔧 ✅ ABGESCHLOSSEN

Alle Befehlspatterns analysiert, Lücken dokumentiert und kritische Fixes implementiert.

- ✅ **Pattern-Analyse**: 7 kritische (🔴), 6 mittlere (🟡), 3 niedrige (🟢) Lücken identifiziert
- ✅ **3 Risiko-Fixes**: VOLUME_PATTERN (.search→.match + Anker), NOTE_GET_FACT_PATTERN
  (Domain-Lookahead gegen Catch-All), START_PROCESS_PATTERN (Negative Lookahead)
- ✅ **Pattern-Erweiterungen**: 9 Handler-Dateien (system, mail, harmony, weather, process,
  contact, calendar, note, todo)
- ✅ **Tests**: 90 neue Pattern-Tests inkl. Cross-Handler-Konflikttests
- ✅ Alle 3.939 Tests grün
- **Konzept**: `docs/concepts/phase-47-befehlsmuster-stabilisierung.md`

### Phase 47b – UX-Polish ✅ ABGESCHLOSSEN

Fehlende Keywords, verbesserte Fehlermeldungen und universeller "bitte"-Prefix.

- ✅ **Keywords**: 5 Handler ergänzt (mail_search, termin_create/search, contact, weather, todo)
- ✅ **Fehlermeldungen**: Technische Hinweise entfernt, "Format:" → "Beispiel:" mit konkreten Eingaben
- ✅ **"bitte"-Prefix**: Universell in 4 Handlern ergänzt (mail, calendar, todo, note)
- ✅ Alle 3.939 Tests grün

## Phase 48 – Technische Schulden / Qualität 🔧 ✅ ABGESCHLOSSEN

Refactoring der zwei größten Dateien und Roadmap-Aktualisierung.

- ✅ **settings_dashboard.py aufgeteilt**: 1.259 → 825 Zeilen (35% Reduktion)
  - `web/secrets_api.py` (370 Zeilen): SECRET_REGISTRY, Validierung, Secrets-Endpoints + Export
  - `web/llm_api.py` (74 Zeilen): LLM-Status/Mode-Endpoints
  - `web/security_middleware.py` (73 Zeilen): CORS, Security-Headers, Exception-Handler
- ✅ **message_handlers.py aufgeteilt**: 1.158 → 752 Zeilen (35% Reduktion)
  - `comms/confirmation_handlers.py` (436 Zeilen): Mail-Senden, Filing, Restart, NC-Setup
- ✅ **Weitere 700+-Zeilen-Dateien geprüft**: Größe durch Pattern-Daten oder kohärente
  Domänenlogik begründet – kein Split nötig
- ✅ **Tests**: 206 betroffene Tests grün, keine Regressionen

## Phase 49 – Anhang-Aktionsmenü ✅ ABGESCHLOSSEN

Nach Mail-Anhang-Upload bietet Saleria ein Aktionsmenü an (nur PDFs).

- ✅ **Aktionsmenü**: Nach Upload bietet Saleria 4 Optionen an:
  - "zusammenfassen" – DocumentReader + LLM-Zusammenfassung
  - "ablegen" – DocumentClassifier → Filing-Flow (Vorschlag + Bestätigung)
  - "löschen" – Datei aus Nextcloud entfernen
  - "nichts" – so lassen
- ✅ **message_handlers.py**: `_handle_attachment_upload_with_menu()` –
  Upload zu NC, Temp-Dateien behalten bis User entschieden hat,
  PendingAction "attachment_menu" mit NC-Pfaden + lokalen Temp-Pfaden
- ✅ **bridge.py**: Routing für attachment_menu im pending-Block
- ✅ **confirmation_handlers.py**: `handle_attachment_menu()` mit 4 Aktionen
- ✅ **filing_commands.py**: `handle_confirm()` um source_type "nc_attachment" erweitert
  (MOVE statt Upload)
- ✅ **Tests**: 96 betroffene Tests grün

---

## UX-Verbesserungen (Phase 50–53)

Aus einer systematischen UX-Analyse (2026-04-10) abgeleitet. Ziel: Benutzererfahrung
über alle Touchpoints (Matrix, Web-Dashboard, Setup, Startup) konsistent und
hilfreich machen.

---

## Phase 50 – Fehler-UX & Bestätigungsdialoge 🛡️ ✅ ABGESCHLOSSEN

Fehlermeldungen humanisieren und destruktive Commands absichern.

### 50.1 – Fehler-Wrapper für Command-Handler

- **Problem**: 30+ `except Exception as e` geben Raw-Exceptions an Matrix weiter
  ("ConnectionRefusedError", "401 Unauthorized") – nicht hilfreich für den Nutzer
- **Lösung**: `user_friendly_error(e)` Utility in `comms/commands/base.py`
  - Mapping bekannter Exceptions → nutzerfreundliche Texte mit Handlungsempfehlung
  - ConnectionError → "Server nicht erreichbar. Prüfe ob der Dienst läuft."
  - 401/403 → "Zugangsdaten ungültig oder abgelaufen. Neu konfigurieren: /setup"
  - Timeout → "Zeitüberschreitung. Versuch es gleich nochmal."
  - Fallback: kurze Fehlerbeschreibung ohne Stacktrace
- **Scope**: Alle 18 Command-Handler in `comms/commands/` refactoren
- **Tests**: Wrapper-Unit-Tests + Stichproben-Tests pro Handler

### 50.2 – "Nicht konfiguriert"-Meldungen mit Setup-Link

- **Problem**: "E-Mail nicht konfiguriert." sagt nicht WAS der Nutzer tun soll
- **Lösung**: Jede "nicht konfiguriert"-Meldung ergänzen:
  "E-Mail nicht konfiguriert. Einrichten unter http://localhost:8090/setup (Schritt 5)."
- **Scope**: Alle Handler die optionale Dienste nutzen (Mail, Cloud, Brave, Gym, Kamera, Harmony)

### 50.3 – Bestätigungsdialoge für destruktive Commands

- **Problem**: `restart`, `lösche alle termine`, `lösche alle erinnerungen`,
  `todos aufräumen`, `update` führen sofort aus ohne Rückfrage
- **Lösung**: `pending_confirmation` nutzen (Mechanismus existiert bereits)
  - "Alle 4 Erinnerungen löschen? Bestätige mit 'ja'."
  - "Bot wird neugestartet. Sicher? Bestätige mit 'ja'."
- **Scope**: 5 Commands in 3 Handlern (weather, calendar, process/update)

### 50.4 – Konsistentes Fehlerformat

- **Problem**: Manche Handler sagen "nicht konfiguriert", andere "Fehler: ...",
  andere "Exception: ..."
- **Lösung**: Einheitliches Format für alle Fehler-Rückgaben:
  - Feature fehlt: "⚠ [Feature] nicht konfiguriert. → [Link/Anleitung]"
  - Aktion fehlgeschlagen: "❌ [Was schiefging]. [Was der Nutzer tun kann]."
  - Teilerfolg: "⚠ [Was geklappt hat], aber [was fehlgeschlagen ist]."

## Phase 51 – Kontextsensitive Hilfe & Command-Discovery 📖 ✅ ABGESCHLOSSEN

Hilfesystem überarbeiten: vom monolithischen Textblock zu kategorisierter,
durchsuchbarer Hilfe.

### 51.1 – Kategorisierte Hilfe

- **Problem**: `hilfe` gibt ~190 Zeilen auf einmal aus – in Matrix unlesbar
- **Lösung**: `hilfe` zeigt nur Kategorien-Übersicht (10 Zeilen):
  ```
  Verfügbare Hilfe-Kategorien:
  hilfe basis – Status, Screenshot, Restart
  hilfe kalender – Termine, Suche, Erstellen
  hilfe mail – Mails, Suche, Antworten
  hilfe wetter – Wetter, Timer, Erinnerungen
  hilfe notizen – Notizen, Fakten, Wissen
  hilfe kontakte – Kontaktbuch
  hilfe todos – Aufgabenliste
  hilfe cloud – Nextcloud Dateien
  hilfe medien – Audio, Mediensteuerung
  hilfe system – Prozesse, Git, Docker, Update
  hilfe alles – Vollständige Hilfe
  ```
- **Technisch**: HELP_TEXT aufteilen in Dict `HELP_SECTIONS`, Abfrage per Kategorie
- **Scope**: `remote_commands.py` (HELP_TEXT + parse_command/execute)

### 51.2 – Tippfehler-Erkennung (Did-you-mean)

- **Problem**: "volumen 50", "statsu", "screnshot" → keine Erkennung, geht ans LLM
- **Lösung**: Levenshtein-Distanz auf `simple_commands` aller Handler
  - Distanz ≤ 2 → "Meintest du 'volume'? Versuche: volume 50"
  - Keine neue Dependency (difflib.get_close_matches aus stdlib)
- **Scope**: `remote_commands.py` (nach fehlgeschlagenem parse_command)

### 51.3 – Keyword-Erweiterung für natürliche Sprache

- **Problem**: "Zeig mir meine Termine" oder "Kannst du den Status checken" werden
  nicht erkannt, weil Keywords zu eng definiert sind
- **Lösung**: Systematische Erweiterung der Keyword-Listen um Varianten mit
  Füllwörtern ("zeig mir", "sag mir", "kannst du", "bitte", "check mal")
- **Scope**: Alle 18 Handler in `comms/commands/`, aufbauend auf Phase 47b
- **Risiko**: Mehr Keywords = mehr Kollisionen → Cross-Handler-Konflikttests erweitern

## Phase 52 – Unified Settings & Startup-Feedback ⚙️ ✅ ABGESCHLOSSEN

Konfiguration an einem Ort statt über 3 Oberflächen verteilt.
Startup gibt klares Feedback was funktioniert und was fehlt.

### 52.1 – Unified Settings-Panel

- **Problem**: Secrets in Setup-Wizard, 4 Settings im Dashboard, Rest nur per API
  oder Terminal → fragmentiert und verwirrend
- **Lösung**: Settings-Dashboard (`/settings`) als zentrale Konfigurations-Oberfläche
  - Tab 1: Dienste & API-Keys (alle aus SECRET_REGISTRY, gruppiert nach Kategorie)
  - Tab 2: Verhalten (Timezone, LLM-Modus, STT-Timeout, etc.)
  - Tab 3: Sicherheit (Allowed Senders, CORS)
  - Jedes Feld: Inline-Edit, Verbindungstest-Button, Hilfe-Link, "Restart nötig"-Badge
  - Setup-Wizard bleibt nur für Erst-Einrichtung (First-Run), wird nicht mehr für
    Re-Konfiguration angeboten
- **Scope**: `web/settings_dashboard.py`, neues Template `settings_panel.html`

### 52.2 – Startup-Summary

- **Problem**: `start_saleria.py` loggt einzelne Komponenten, aber zeigt nie eine
  Gesamtübersicht. Nutzer sieht nicht was fehlt.
- **Lösung**: Nach dem Startup eine Summary ausgeben + optional an Matrix senden:
  ```
  ╔═══════════════════════════════════════╗
  ║        Saleria – Startup Summary      ║
  ╠═══════════════════════════════════════╣
  ║ ✓ LLM: Anthropic (Sonnet 4.6)        ║
  ║ ✓ Matrix: @saleria:matrix.example.com ║
  ║ ✓ Kalender: Nextcloud CalDAV          ║
  ║ ✓ Wetter: Open-Meteo (Berlin)         ║
  ║ ⚠ E-Mail: nicht konfiguriert          ║
  ║ ⚠ Nextcloud: nicht konfiguriert       ║
  ║ ✗ Tower: nicht erreichbar             ║
  ║ ✗ RPi5: nicht erreichbar              ║
  ╚═══════════════════════════════════════╝
  ```
- **Scope**: `scripts/start_saleria.py` (neue Funktion `_print_startup_summary()`)

### 52.3 – Setup-Wizard → Settings-Migration

- **Problem**: Re-Setup-Button im Dashboard öffnet den 8-Schritte-Wizard –
  Wizard-Metapher ist unpassend wenn man nur einen API-Key ändern will
- **Lösung**: Re-Setup-Button entfernen, stattdessen Link zu `/settings`
  mit Deep-Link zur richtigen Kategorie (z.B. `/settings#llm`)
- **Scope**: `web/templates/audio_dashboard.html`, `settings_dashboard.py`

## Phase 53 – Install-Script Härtung & Avatar-Editor UX 🔧 ✅ ABGESCHLOSSEN

Kleinere UX-Verbesserungen für Installation und Avatar-Konfiguration.

### 53.1 – Install-Script Fehlerhandling

- **Problem**: `pip install --quiet` verschluckt Fehler, Nutzer sieht erst
  beim Start dass Dependencies fehlen
- **Lösung**:
  - `--quiet` entfernen, stattdessen Output nach stderr filtern
  - Exit-Code prüfen und explizit warnen wenn pip fehlschlägt
  - Ollama-Check mit Erklärung: "Ohne Ollama nur Anthropic API (kostenpflichtig)"
  - Post-Install-Validierung: `python -c "import elder_berry"` als Smoke-Test
- **Scope**: `scripts/install.ps1`, `scripts/install.sh`

### 53.2 – Avatar-Editor Onboarding

- **Problem**: Avatar-Editor hat kein Onboarding, Nutzer versteht nicht was
  Assets, Layers und Emotion-Maps bedeuten
- **Lösung**: Intro-Modal beim ersten Aufruf:
  - "Salerias Avatar besteht aus 3 Layern: Körper, Augen, Mund"
  - "Jede Emotion hat eine eigene Kombination"
  - "Wähle links ein Asset, sieh rechts die Vorschau"
  - "Zurücksetzen auf Standard" Button
- **Scope**: `web/templates/avatar_editor.html`

### 53.3 – Settings aus Config-Datei statt Hardcode ✅ ERLEDIGT DURCH 52.0

- **Status**: Phase 52.0 hat `SECRET_REGISTRY` in `secrets_api.py` zur Single
  Source of Truth ausgebaut (inkl. `behavior`, `risk_level`, `placeholder`,
  `select_options`). `_setting_definitions()` wird via
  `_registry_to_setting_definition()` daraus abgeleitet. Neue Settings
  brauchen nur noch einen Registry-Eintrag, kein Code-Change in
  settings_dashboard.py. YAML-Auslagerung würde das Problem nochmal lösen
  ohne Mehrwert.


## Phase 55 – pydub/audioop Migration 🐍 ✅ ABGESCHLOSSEN

Python 3.13 entfernt das `audioop`-Stdlib-Modul (PEP 594). `pydub`
importiert es unconditional → ImportError beim RPi5-Upgrade auf
Bookworm/Python 3.13.

Konzept: `docs/concepts/phase-55-audioop-migration.md`

### 55.1 – audio_converter.py auf direkten ffmpeg-Subprozess umgestellt

- `to_ogg_opus()` ruft jetzt `subprocess.run(['ffmpeg', -c:a, libopus, ...])`
  mit Exit-Code-Check und Timeout direkt auf
- `get_duration_ms()` nutzt `ffprobe -show_entries format=duration -of json`
- pydub aus `[matrix]` und `[server]` in `pyproject.toml` entfernt
- 32 Tests grün, Laufzeit von ~30s auf 1s (kein echter ffmpeg-Call mehr
  in Mocks)

### 55.2 – Screenshot-Hänger + pytest-timeout

- `system_commands._wake_monitor()` nutzt jetzt `SendMessageTimeoutW` mit
  `SMTO_ABORTIFHUNG`, statt des blockierenden `SendMessageW`-Broadcasts.
  Echtes Prod-Bugfix: ein Broadcast zu HWND_BROADCAST hing, sobald ein
  beliebiges System-Fenster einen kaputten Message-Loop hatte.
- `TestCmdScreenshot`: mss + `_wake_monitor` in den beiden Live-Tests
  gemockt, keine deselect-Liste mehr nötig
- `pytest-timeout>=2.3` als neue `[dev]`-Gruppe in `pyproject.toml`
- Globales `timeout = 60` in `[tool.pytest.ini_options]`, damit
  zukünftige Hänger nach 60s zwangsweise abgebrochen werden

## Phase 56 – Nextcloud Tasks als Todo-Backend 📋 ✅ ABGESCHLOSSEN

Nextcloud Tasks (CalDAV VTODO) ersetzt den lokalen SQLite-TodoStore.
Aufgaben werden über DAVx5 aufs Handy synchronisiert. Fälligkeitsdaten
werden unterstützt ("aufgaben morgen", "todo: Arzt, morgen").

Konzept: `docs/concepts/phase-56-nextcloud-tasks.md`

- ✅ **56.1 CalDAVTaskClient** (`src/elder_berry/tools/caldav_tasks.py`):
  TaskItem-Dataclass + CalDAVTaskClient, lazy-init, retry, graceful
  degradation, VTODO-Lesen/Schreiben via `caldav` + `icalendar`.
- ✅ **56.2 TodoCommandHandler umverdrahtet**: `task_client: CalDAVTaskClient`
  per Konstruktor, IDs als UUID-Strings + Session-Index für Chat-Usability.
- ✅ **56.3 Due-Date-Support**: Patterns "todo: X, morgen", "aufgaben
  morgen/heute/überfällig", Datum-Parsing für Wochentage + DD.MM(.YYYY).
- ✅ **56.4 BriefingScheduler umgestellt**:
  `briefing_scheduler.py:402` ruft `task_client.format_for_briefing()`.
- ✅ **56.5 Migration & Deprecation**: `scripts/migrate_todos_to_nextcloud.py`
  (einmalige SQLite→CalDAV-Migration), `tools/todo_store.py` mit
  `.. deprecated:: Phase 56` markiert, Imports aus aktivem Code entfernt.
- ✅ **Tests**: `tests/test_caldav_tasks.py`, `tests/test_todo_commands.py`
  auf den neuen Client umgestellt.

### 56.1 – CalDAVTaskClient

- **Neue Klasse** `tools/caldav_tasks.py`: TaskItem-Dataclass + CalDAVTaskClient
- Gleicher Pattern wie CalDAVCalendarClient: Lazy-Init, retry, graceful degradation
- Liest/schreibt VTODOs via `caldav` + `icalendar` Library
- Fälligkeitsdatum (DUE), Priorität, Kategorie

### 56.2 – TodoCommandHandler umverdrahten

- TodoStore-Referenzen durch CalDAVTaskClient ersetzen
- user_id-Parameter entfernen (CalDAV hat keine User-ID)
- ID-Typ von int auf str (UUID), mit Session-Index für Chat-Usability

### 56.3 – Due-Date-Support in Commands

- Neue Patterns: "todo: X, morgen", "aufgaben morgen/heute/überfällig"
- Date-Parsing: heute, morgen, Wochentage, DD.MM(.YYYY)
- Filter-Erweiterung in _cmd_filter

### 56.4 – SmartContext + BriefingScheduler umstellen

- smart_context._query_todos → task_client.format_for_briefing()
- briefing_scheduler._build_todo_section → task_client
- Constructor-Parameter und Imports anpassen

### 56.5 – Migration & Deprecation

- Migrations-Script: SQLite-Todos → Nextcloud Tasks (einmalig)
- TodoStore aus allen Imports entfernen, Datei deprecaten


## Phase 57 – Security-Härtung: Loopback, First-Run-Gate, Tower-Auth 🛡️ ✅ ABGESCHLOSSEN

Schließt 4 Sicherheitslücken, die ein Code-Review nach Phase 52 aufgedeckt
hat. Phase 52 hat die Basis gelegt (Loopback + Token fürs Settings-Panel),
57 zieht das gleiche Muster durch für Setup-Wizard, TowerServer und die
Wizard-Exemption der Middleware.

Konzept: `docs/concepts/phase-57-security-haertung.md`

- ✅ **57.1** Loopback-Default + Grace-Period: `ELDER_BERRY_SETUP_BIND` /
  `ELDER_BERRY_TOWER_BIND`, Default `127.0.0.1`. Einmaliger LAN-Bind beim
  Upgrade-Start (Marker-Datei). Stellen: `scripts/start_saleria.py`
  (Z. 605, 1413), `src/elder_berry/web/setup_wizard.py:651`.
- ✅ **57.2** First-Run-Gate für Wizard-Exemption:
  `SettingsTokenMiddleware` wertet `setup_wizard_completed` aus.
- ✅ **57.3** Tower-Token + Host-Discovery: Header
  `X-Saleria-Tower-Token` (`tower/tower_server.py:149`,
  `src/elder_berry/core/tower_agent.py:35`), neue Secrets
  `tower_auth_token` + `tower_advertised_host` (auto-generiert beim
  ersten Start), RobotClient zieht beides aus dem SecretStore.
- ✅ **57.4** `matrix_allowed_senders` Fail-Closed-Audit:
  `src/elder_berry/comms/bridge.py:340` – leere/None-Senderliste lehnt
  Nachrichten ab, Regression-Test `tests/test_allowed_senders_fail_closed.py`.

### 57.1 – Loopback-Default + Grace-Period für Setup-Wizard und TowerAgent

- **Problem**: `setup_wizard.py:470` und `start_saleria.py:538` binden
  standalone auf `0.0.0.0`. Secrets (API-Keys, Matrix-Tokens) sind
  während des First-Run im LAN mitlesbar, Tower-Steuerung ist direkt
  exponiert.
- **Lösung**: Default-Bind `127.0.0.1`. Zwei neue Env-Variablen
  `ELDER_BERRY_SETUP_BIND` und `ELDER_BERRY_TOWER_BIND` (konsistent zu
  `ELDER_BERRY_SETTINGS_BIND` aus Phase 52). Bei LAN-Bind Warn-Log.
- **Grace-Period (57.1a)**: Beim ersten Upgrade-Start bindet der
  Wizard einmalig auf `0.0.0.0`, damit headless Installationen nicht
  ausgesperrt werden. Marker-Datei `~/.elder-berry/.phase57_migration_done`
  + gelbes Banner im Wizard-UI. Ab dem zweiten Start (oder wenn der
  Marker existiert) gilt Loopback-Default.
- **Scope**: `scripts/start_saleria.py`, `src/elder_berry/web/setup_wizard.py`
- **Breaking Change**: Dauerhaft-headless-Installationen müssen die
  Env-Variable explizit setzen. Grace-Period fängt den einmaligen
  Upgrade-Fall ab.
- **Abhängigkeit**: Muss **nach 57.2** gemerged werden, sonst ist das
  Grace-Period-Fenster doppelt riskant (LAN + offene Middleware-
  Exemption).

### 57.2 – First-Run-Gate für Wizard-Exemption

- **Problem**: `SettingsTokenMiddleware` exempted `/api/setup` dauerhaft.
  Der First-Run-Marker `setup_wizard_completed` existiert, wird aber
  nicht ausgewertet. Phase 52.3 war genau diese Arbeit, wurde irrtümlich
  gestrichen.
- **Lösung**: Middleware bekommt `SecretStore`-Dependency, prüft
  `setup_wizard_completed`. Nach Abschluss entfällt die Exemption und
  `/api/setup` verlangt den Settings-Token. Cache-Invalidation im
  Finish-Endpoint.
- **Scope**: `src/elder_berry/web/settings_token_middleware.py`,
  Cache-Invalidation in `setup_wizard.py`

### 57.3 – Tower-Token + Host-Discovery

- **Problem**: `tower/tower_server.py` hat keinerlei Auth. `/action`
  erlaubt beliebige PC-Steuerung, sobald der Server direkt im LAN
  erreichbar ist.
- **Lösung**: Header `X-Saleria-Tower-Token`, Quelle (Priorität):
  Env `ELDER_BERRY_TOWER_TOKEN` → `SecretStore.get("tower_auth_token")`.
  Fail-closed beim Start (kein Token → Server verweigert Start).
- **Auto-Migration (Token + Host)**: `start_saleria.py` generiert beim
  ersten Upgrade einen neuen Token (`secrets.token_hex(32)`) **und**
  ermittelt den lokalen `tower_advertised_host` über eine Fallback-
  Kette (Env `ELDER_BERRY_TOWER_ADVERTISED_HOST` → UDP-Route-
  Heuristik → `gethostbyname` → `127.0.0.1`). Beide Werte werden im
  `SecretStore` abgelegt und einmalig geloggt.
- **RobotClient zieht beides gemeinsam** aus dem `SecretStore` – ein
  Eintrag weniger im Dashboard, keine doppelte Pflege von Host und
  Token.
- **Scope**: `tower/tower_server.py`, `scripts/start_saleria.py`,
  `src/elder_berry/robot/client.py` (Header + Host-Lookup),
  `SECRET_REGISTRY` (zwei neue Einträge `tower_auth_token` +
  `tower_advertised_host`, Kategorie "Tower & Agent")
- **Breaking Change**: Bestehende Installationen erhalten automatisch
  Token und Host beim ersten Upgrade-Start, User muss im Normalfall
  nichts manuell eintragen.

### 57.4 – `matrix_allowed_senders` Fail-Closed-Audit

- **Problem**: Unklar, wie Bridge und MessageHandler auf leere
  `allowed_senders`-Liste reagieren (fail-closed vs. fail-open).
- **Lösung**: Audit zuerst (vor 57.1–57.3). Fall A (fail-closed): neuer
  Regression-Test. Fall B (fail-open): Phase 57 pausiert, Hotfix auf
  separatem Branch, danach 57 wieder aufnehmen.
- **Scope**: `src/elder_berry/comms/bridge.py`,
  `src/elder_berry/comms/message_handlers.py`,
  `tests/test_allowed_senders_fail_closed.py` (neu)

### Reihenfolge

1. **57.4 Audit** (Go/No-Go für die Phase)
2. **57.2 First-Run-Gate** – **muss vor 57.1** gemerged sein, sonst
   ist das Grace-Period-Fenster in 57.1 doppelt riskant (LAN-Bind
   plus offene Middleware-Exemption gleichzeitig). Nicht verhandelbar.
3. **57.1 Loopback-Default + Grace-Period** (Einmal-BC für Upgrade-User,
   dauerhafter BC nur für LAN-Dauer-Nutzer)
4. **57.3 Tower-Token + Host-Discovery** (größter BC, Auto-Migration
   für Token **und** Host)

## Phase 54 – Bull-Berry: Autonomes Investment-Experiment 📊 KONZEPT

Eigenständiges Projekt mit geplanter Schnittstelle zu Saleria. Eigenes
Repository, separate Codebase. **Kein** Code-Bestandteil von Elder-Berry.

- Konzept: `docs/concepts/phase-54-investment-experiment.md`
- Status: Konzept-Phase, kein Elder-Berry-Code-Impact.

## Phase 58 – Dashboard-Login + Avatar-Tab 🔐🎭 ✅ ABGESCHLOSSEN

Folge-Phase nach 57. Login-Flow für das Dashboard (`fern.example.com`)
plus eigener Avatar-Tab im Settings-Panel.

- Konzept: `docs/concepts/phase-58-dashboard-login-avatar.md`
- PR: #99 (`feature/phase-58-dashboard-login-avatar`)

## Phase 59 – Rate-Limiting & Brute-Force-Schutz 🚦 ✅ ABGESCHLOSSEN

Auth-Endpoints (Dashboard-Login, Setup-Wizard, Tower) bekommen
IP-basiertes Rate-Limiting + Brute-Force-Erkennung. Security-Events
landen in `logs/security.log`.

- `RateLimiter` Klasse, `start_rpi5` Robot-Token-Handling als Teil-Scope.
- PRs: #103 (`feature/phase-59-rate-limiting`), Robot-Token-Regressions
  in `start_saleria` / `start_rpi5`.

## Phase 60 – IMAP-Gesendet-Ordner ✉️ ✅ ABGESCHLOSSEN

Gesendete E-Mails (Saleria-Antworten via Matrix) werden jetzt zusätzlich
in den IMAP-`Gesendet`-Ordner kopiert, damit sie im Mail-Client sichtbar
bleiben. Provider-agnostisch (Gmail "Sent", IMAP "Sent", deutsche
"Gesendet"-Ordner).

- PR: #104 (`feature/phase-60-sent-folder-copy`)

## Phase 61 – Remote Log-Zugriff via Matrix 📜 ✅ ABGESCHLOSSEN

Neuer Matrix-Command `log` – holt die letzten N Zeilen aus den
Tower-Logs aufs Handy. Nützlich für Remote-Debugging.

- Neuer `LogCommandHandler` in `src/elder_berry/comms/commands/`.
- PR: #105 (`feature/phase-61-remote-log-access`)

> **Phase 62**: Nummer übersprungen – kein zugehöriger PR/Branch.

## Phase 63 – CSP-Härtung: `unsafe-inline` raus 🛡️ ✅ ABGESCHLOSSEN

Alle Jinja2-Templates des Web-Stacks auf externe `/static/`-Assets
migriert; CSP-Header verzichtet auf `unsafe-inline`.

- Konzept: `docs/concepts/security-h2-csp-unsafe-inline.md`
- Schritte 1+2: StaticFiles-Mount + CSP-Negativtests.
- Schritt 3: `settings_panel.html` (Pilot).
- Schritt 4: `audio_dashboard.html`.
- Schritt 5: `avatar_editor.html`.
- Schritt 6a: `/api/setup/geocode` als Nominatim-Proxy.
- Schritt 6b: `setup_wizard.html` (großer Brocken, 27 Inline-Treffer).
- Schritt 7: CSP verschärft, `'unsafe-inline'` entfernt.
- Nachtrag: Standalone-Wizard liefert `/static/`-Assets korrekt aus.

## Phase 64 – CSRF/SSRF/Robot-Token Hard-Fail 🛡️ ✅ ABGESCHLOSSEN

Drei "Hoch"-Findings aus dem Security-Review:

- **H-1** Robot-Token Hard-Fail: kein Fallback-Mode mehr, fehlender
  Token → Server-Start verweigert.
- **H-2** CSRF-Schutz: SameSite=strict + Origin-Check für
  state-changing Endpoints.
- **H-3** SSRF-Schutz: Whitelist für ausgehende Web-Fetches.
- PR: #112 (`feature/phase-64-security-fixes`)

## Phase 65 – Mittlere Security-Fixes (M-1…M-4) 🔐 ✅ ABGESCHLOSSEN

- **M-1 SecretStore → OS-Keyring**: Fernet-Masterkey wandert aus der
  Plaintext-Datei in den OS-Keyring (Windows DPAPI, macOS Keychain,
  Linux Secret Service). Auto-Migration mit Verify-before-Delete.
  Fallback auf File-Verhalten wenn kein Keyring-Backend verfügbar.
- **M-2 Git-Command-Whitelist**: `extra_args` für `git log` / `git diff`
  via Matrix gegen enge Regex-Whitelist validiert (max 10 Tokens).
  Schützt gegen `--output`, `-o`, `--exec`, `-c core.pager=…`.
- **M-3 Lockfiles + Dependabot**: `pip-tools>=7.0`, zwei Lockfiles
  (`requirements-tower.lock`, `requirements-dev.lock`),
  `scripts/update-lockfiles.{ps1,sh}`. Dependabot weekly mit
  Security-/Non-Security-Gruppen.
- **M-4 Globales Logout**: `POST /api/dashboard/logout-all` rotiert
  das Session-Secret → alle bestehenden Cookies sofort ungültig,
  aufrufender Client bekommt frisches Cookie.
- PR: #113 (`feature/phase-65-medium-security`)

## Phase 66 – Robot-Reverse-Proxy 🔁 ✅ ABGESCHLOSSEN

`/api/robot/*` als authentifizierter Reverse-Proxy zum RPi5. Damit
muss der RPi5 nicht direkt aus dem LAN/VPN erreichbar sein – Tower
ist der einzige Eintrittspunkt.

- PR: #123 (`feature/phase-66-robot-proxy`)

## Phase 67 – Public-Readiness Audit + Sanitization 🌍 ✅ ABGESCHLOSSEN

Audit-Welle vor dem Public-Release. Mehrere Tranchen:

- Public-Readiness Audit-Tooling (`scripts/check_public_readiness.py`).
- README-Polish, CHANGELOG für die Public-Story.
- Deployment-spezifische Setup-Docs entfernt.
- Matrix-IDs und PII in Tests sanitisiert.
- Service-Files + Deploy-Script als Templates.
- **`docs/journal.txt` aus dem Public-Repo entfernt** (lebt nur noch
  lokal als Workflow-Tool, gitignored).
- Final cleanup nach Audit.
- PR: #124 (`feature/phase-67-public-readiness`)

## Phase 73 – Code-Hygiene-Sweep 🧹 ✅ ABGESCHLOSSEN

PR-E der Public-Release-Hygiene-Serie. Reanimation des
`test_secrets_api`, kleinere Aufräumarbeiten.

- PR: #142

## Phase 74 – Codecov-Integration 📊 ✅ ABGESCHLOSSEN

Coverage-Reporting nach Codecov, getriggert vom Linux-CI-Lauf.
`codecov.yml` mit zurückhaltenden Schwellen (`target: auto`,
`threshold: 1%`, Patch-Coverage 70%) – Baseline wird nach 1–2
Mergewochen angezogen. Frontend-Bundle (`webapp/`) und Entry-Points
(`scripts/start_*`) aus dem Coverage-Report ausgeschlossen.

- PR: #144

## Phase 75 – Repo-Hygiene 🧹 ✅ ABGESCHLOSSEN

Sediment-Cleanup vor den Modernisierungs-Phasen 76–78. Lokale Branch-Liste
von 28 auf 2 reduziert (`main` + aktiver Phase-Branch), 14 verwaiste
Worktrees entfernt, Phase-33-Stash gedroppt, korrupte
`.git/config`-Tail-Whitespace-Zeile repariert. Versionsbump
`0.1.0 → 1.0.0-rc1` als Public-Release-Kandidat. `pre-commit`-Setup mit
`ruff` (Lint), Standard-Checks (EOL, trailing-whitespace, YAML/TOML,
merge-conflict, large-files) und `check_public_readiness.py` als
pre-push-Hook. `ruff-format` bewusst auf `manual` stage – Massen-Reformat
(300 Dateien) gehört in eine eigene Folgephase. 8 EOL/whitespace-Fixes in
alten Konzept-/Skript-Dateien als Beiprodukt mitgenommen. Zusätzlich
Konzepte für Phase 76 (mypy), 77 (Plugin-Registry) und 78 (Plugin
Self-Suggestion) angelegt – Roadmap der nächsten Modernisierungs-Reihe.

- Konzept: `docs/concepts/phase-75-repo-hygiene.md`

## Phase 75b – Format-Sweep mit ruff-format 🎨 ✅ ABGESCHLOSSEN

Folge-Quick-Win nach Phase 75: einmalige Reformatierung der gesamten
Python-Codebase mit `ruff format`, damit der Stand konsistent ist und
nicht weiter driftet. `pre-commit`-Hook von `stages: [manual]` zurück
auf default gestellt – ab jetzt prüft jeder Commit auf Format-Konsistenz.
Tests vor/nach identisch (5016 passed, 3 skipped). Reine Format-Phase
ohne Code-Verhalten – Commit-SHA Kandidat für `.git-blame-ignore-revs`
(optionale Folge).

- Konzept: `docs/concepts/phase-75b-format-sweep.md`

## Phase 68 – Public-Release-Vorbereitung (laufend)

Vorbereitung des Repos für Public-Release. In kleinen Tranchen, parallel
zu den laufenden Sicherheits-Fixes (Phase 69, Path-Traversal). Jede
Tranche ist scharf abgegrenzt und kommt als eigener PR.

### Tranche C – Trivial-Cleanup ✅ ABGESCHLOSSEN
- **B2**: `--author=marcus` aus `git_commands.py` Hilfetext + Tests durch
  generisches `--author=user` ersetzt.
- **B3**: `last-strawberry.com` aus `webapp/dashboard/index.html`
  entfernt; jetzt parametrisiert über `<meta name="elderberry-server-host">`
  + JS-Override `window.ELDERBERRY_SERVER_HOST`. Default `example.com`,
  d.h. LAN-Modus ist im öffentlichen Source der Default.
- **E5**: `pyproject.toml` `[project]` um `license = "MIT"` und
  `license-files = ["LICENSE"]` ergänzt (PEP 639, kompatibel mit
  setuptools>=82, sdist-PKG-INFO bekommt `License-Expression: MIT`).
- **Branch**: `chore/public-release-cleanup`.
- **Tests**: 4848 passed, 28 skipped, keine Architektur-Änderungen.

## Phase 69 – Path-Traversal-Schutz für Matrix-Commands 🛡️ ✅ ABGESCHLOSSEN

- **Trigger**: Security-Review vor Public-Release identifizierte zwei
  kritische Path-Traversal-Findings:
  - **K1**: `advanced_commands.py::_cmd_document_summary` reicht den
    Pfad aus der Matrix-Nachricht direkt an `Path()` weiter — ohne
    `resolve()` / `is_relative_to`-Check. Matrix-Sender (auch
    allowlisted) konnten via `zusammenfassung <pfad>` beliebige
    Dateien lesen (`id_rsa`, `.env`, SecretStore-Backups).
  - **K2**: `pdf_commands.py::_is_local_path` akzeptiert jeden
    absoluten Pfad; `_resolve_file` öffnet ihn ungeprüft für
    `pdf zusammenfügen`, `pdf split`, `pdf ocr`, `pdf komprimieren`,
    `pdf zu word`, `zu pdf`, `pdf bilder`.
- **Lösung**: Neue Klasse `PathGuard` in
  `src/elder_berry/core/path_guard.py` mit `validate(path)`-Methode:
  - `resolve(strict=True)` — Symlinks aufgelöst, `FileNotFoundError`
    bei nicht-existenten Dateien (Caller darf NC-Fallback versuchen).
  - `is_relative_to(base)`-Check gegen Allow-Liste — Verstöße werfen
    `PermissionError`.
  - Defaults via `PathGuard.default()`: `~/Documents`, `~/Downloads`,
    `~/Desktop`, `tempfile.gettempdir()` (NC-Cache lebt dort), CWD.
  - Override per Env-Var `EB_ALLOWED_PATHS` (`os.pathsep`-getrennt).
  - Audit-Log via `getLogger("elder_berry.security")` →
    `logs/security.log` (Konvention aus Phase 59 Rate-Limit-Events).
- **Integration**:
  - `advanced_commands.py::_cmd_document_summary`: `validate()` vor
    Suffix-Check; `PermissionError` → Abbruch ohne Pfad-Echo;
    `FileNotFoundError` → bestehender NC-Fallback bleibt erhalten.
  - `pdf_commands.py::_resolve_file`: `validate()` bei lokalen
    Pfaden; NC-Pfade gehen unverändert durch.
- **Kein Pfad-Echo**: Fehlermeldungen an Matrix-Sender sind generisch
  ("Zugriff verweigert. Datei liegt ausserhalb erlaubter
  Verzeichnisse."). Der konkrete Pfad landet nur im Security-Log.
- **Tests**: `tests/test_path_guard.py` (neu, 18 Tests inkl.
  Symlink-Escape, dotdot-Traversal, Env-Override, Logging-Routing).
  Regression-Tests in `tests/test_advanced_commands.py` (3) und
  `tests/test_pdf_commands.py` (4). Suite: 4872 passed, 29 skipped.
- **Branch**: `fix/path-traversal-document-pdf-commands`.

## Phase 71 – Public-Release-Hygiene Runde 2 🧹 ✅ ABGESCHLOSSEN

Vier unabhängige Public-Release-Verbesserungen in einem PR. Parallel
zu Phase 70 (Session-Härtung), berührt keine Auth-/Web-Dateien — nur
Repo-Hygiene, Audit-Tools und Doku.

- **E2 — Hardware-OldVersions explizit ausgeschlossen**: `.gitignore`
  bekommt einen expliziten Eintrag `hardware/enclosure/OldVersions/`
  (zusätzlich zum bereits vorhandenen generischen `OldVersions/`-
  Pattern). Inventor-Backup-Versionen (.0001.ipt, .0002.iam, ~129 MB
  lokal) sollen niemals ins Public-Repo. Doppelt gehalten als Schutz,
  falls jemand das generische Pattern später entfernt. Kein
  `git rm --cached` nötig — die Dateien waren nie im Tracking.
  Zusätzlich: `.claude/settings.local.json` zu `.gitignore` ergänzt
  (war ein Loch — harness-spezifische Permissions sollen nicht ins
  Repo).
- **E3 — Issue-/PR-Templates**:
  - `.github/ISSUE_TEMPLATE/bug_report.md` (Plattform-Auswahl Tower /
    Laptop / RPi5, Stack-Trace-Block, Sicherheits-Hinweis).
  - `.github/ISSUE_TEMPLATE/feature_request.md` (Use-Case + Alternativen
    + "selbst bauen?"-Checkbox).
  - `.github/ISSUE_TEMPLATE/config.yml` mit `contact_links` auf
    Security-Advisory + Issue-mit-Label-question (Discussions sind
    deaktiviert).
  - `.github/PULL_REQUEST_TEMPLATE.md` (Was/Warum, Test-Plan,
    Plattform-Impact, Checkliste inkl. Journal/Roadmap).
- **E6 — `scripts/check_public_readiness.py` konfigurierbar**:
  - Maintainer-spezifische Patterns (last-strawberry.com, marcus,
    sfi-kohtz, lera, h2724315, /home/lera, /opt/Elder-Berry, ...)
    raus aus dem hardcoded `CATEGORIES`-Tupel.
  - Neue Funktion `_load_blocklist_patterns()` lädt Patterns aus
    optionaler `.public-readiness-blocklist.txt` (gitignored, ein
    Regex pro Zeile, `#`-Kommentare).
  - Default-Fallback: `example.com`, `your-domain.tld` — Forks
    bekommen "alles ok" und sehen das Tool als Skeleton.
  - `.public-readiness-blocklist.example.txt` (getrackt) zeigt
    den Stil mit allen Original-Patterns + Kommentaren.
  - Generische Kategorien (`lan_ip`, `matrix_id`) bleiben als
    konstantes `_CATEGORY_*`.
  - Tests: `tests/test_check_public_readiness.py` (neu, 21 Tests:
    Loader-Logik, Default-Fallback, Compile-Robustheit für ungültige
    Regex, End-to-End-Scan).
- **SECURITY.md — Bekannte Einschränkungen / Known Limitations**:
  Neuer Abschnitt mit M1-M5 aus dem internen Security-Review:
  - **M1** `allowed_rooms` fail-open ohne explizite Konfiguration.
  - **M2** Setup-Wizard unauthenticated (by design, mitigation: VPN-only).
  - **M3** Robot-/Settings-Token ohne Auto-Rotation (manuell via
    Dashboard / SecretStore).
  - **M4** LLM-Provider-Sichtbarkeit (Matrix-Inhalte gehen 1:1 an
    Anthropic/OpenRouter; Mitigation: lokales Ollama).
  - **M5** CSRF: SameSite=strict + Origin-Check, kein expliziter
    CSRF-Token (Real-Risk in modernen Browsern minimal).
- **Branch**: `chore/public-release-hygiene-round-2`.
## Phase 70 – Session- + Web-Hardening 🛡️ ✅ ABGESCHLOSSEN

- **Trigger**: Security-Review hat vier "Hoch"-Findings ergeben, die
  alle in derselben Auth-/Tooling-Surface leben und gemeinsam in
  einem Branch + PR gemerged werden.
- **H1 — Server-side Logout-Invalidation**:
  `delete_cookie()` loescht den Cookie nur im Browser; der HMAC-
  signierte Token bleibt bis ``exp`` valide und kann nach Diebstahl
  repliziert werden. Neue Klasse
  `src/elder_berry/web/session_revocation_list.py`
  (`SessionRevocationList`) -- in-memory Set mit lazy Cleanup +
  optionaler JSON-Persistenz neben `secrets.enc`. Eintraege halten
  nur den SHA-256 des Cookies (kein Klartext-Echo).
  `verify_session()` prueft die Liste nach Signatur + exp + Cap.
  `/api/dashboard/logout` ruft `revoke_session()` zusaetzlich zu
  `delete_cookie()`. Trade-off im Code dokumentiert: Single-Session
  (Default) vs. `logout-all` (Secret-Rotation).
- **H2 — `tempfile.mktemp()` Abloesung**:
  Vier TOCTOU-anfaellige Stellen
  (`audio_pipeline.py` 200/230, `message_handlers.py` 383/599) auf
  `tempfile.NamedTemporaryFile(delete=False)` umgestellt. Symlink-
  Race-Vektor in `$TMP` ist damit zu.
- **H3 — WebFetcher Stream-Cap**:
  `httpx.get()` -> `httpx.stream()` mit chunk-weisem Lesen + Hard-Cap
  (`DEFAULT_MAX_RESPONSE_BYTES = 5 MB`, konfigurierbar). Vor dem Read
  Content-Length-Check, danach laufender Byte-Counter.
  Neue Exception `ResponseTooLargeError(RuntimeError)`. Verhindert
  Speicher-DoS via beliebig grosser Antwort.
- **H4 — Absoluter Session-Cap**:
  `DashboardAuthManager.issue_session()` schreibt jetzt
  `iat_original` ins Payload. `verify_session()` und
  `extend_session()` pruefen `now - iat_original` gegen
  `DEFAULT_MAX_ABSOLUTE_LIFETIME_HOURS = 24`. Sliding-Renewal
  verlaengert das Cookie, rollt den Cap aber nicht zurueck.
  Legacy-Cookies ohne `iat_original` -> Fallback auf `iat`
  (graceful Migration nach Deploy). Middleware ruft jetzt
  `extend_session()` statt `issue_session()`, damit
  `iat_original` ueber alle Renewals erhalten bleibt.
- **Tests**: `tests/test_session_revocation_list.py` (neu, 14 Tests),
  `tests/test_dashboard_auth.py` (+18 fuer Cap + Revocation +
  Legacy-Fallback), `tests/test_dashboard_auth_routes.py` (+4 fuer
  Logout-Replay), `tests/test_web_fetcher.py` (+8 fuer Size-Limit).
  Suite: **4913 passed, 29 skipped** (vorher 4872 → +41 neue Tests).
- **Branch**: `fix/session-and-web-hardening`.

## Phase 72 – Auth-Hardening (PW-Min + bcrypt rounds) 🔒 ✅ ABGESCHLOSSEN

- **Trigger**: Letzte Hardening-Schicht vor Public-Release. Zwei
  kleine Stellschrauben in derselben Auth-Surface, gemeinsam in
  einem PR.
- **N1 — Mindest-Passwortlaenge 8 → 12**:
  Neue Konstante `MIN_PASSWORD_LENGTH = 12` in
  `src/elder_berry/web/dashboard_auth.py`. `set_password()` haengt
  die Fehlermeldung per f-string an die Konstante. CLI
  (`scripts/set_dashboard_password.py`) importiert die Konstante
  und nutzt sie identisch. Setup-Wizard-Label
  (`templates/setup_wizard.html`) und Client-Validierung
  (`static/js/setup_wizard.js`) auf 12 Zeichen.
- **N2 — bcrypt rounds 12 → 14**:
  `BCRYPT_ROUNDS = 14`. ~250 ms/Hash auf moderner CPU; unkritisch
  im Login-Pfad, GPU-Resistenz fuer kurze 8–12 Zeichen-PWs steigt
  um Faktor 4. MIN_PASSWORD_LENGTH = 12 mitigiert den eigentlichen
  Vektor schon, gehoert aber zusammen.
- **Migration**: Bestehende rounds=12-Hashes funktionieren weiter
  -- bcrypt liest den Cost-Faktor aus dem Hash-Prefix. Neue Hashes
  nutzen rounds=14.
- **Tests**: `tests/test_dashboard_auth.py::test_overwriting_password_works`
  nutzt 13/13-Zeichen-PWs (vorher 11/10). Suite:
  **4916 passed, 29 skipped**.
- **Branch**: `chore/auth-hardening-pw-bcrypt`.

## Phase 76 – mypy --strict für `core/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Erster Tier-Rollout aus dem mypy-Konzept (Phase 75).
  `core/` als Tier 1 ist das kleinste Paket mit den meisten
  Querverbindungen → schmerzhafte Typ-Drift früh fangen.
- **Etappen 1-4** (2026-05-01): Tier-1 strict (Setup + 3 Module),
  Tier-2 strict (3 Module), Out-of-Scope-Pakete silencen, Tier-3
  strict (6 Module), Tier-4 strict (4 Module) + Gate hart. 14 Module
  insgesamt. CI-Workflow `.github/workflows/mypy-strict.yml` ergänzt.
- **Tests**: keine Suite-Änderung — mypy ist statische Prüfung.
- **Branch**: `feature/phase-76-mypy-strict-core` (Etappen einzeln gemergt).

## Phase 76b – mypy --strict für `comms/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Zweiter Tier-Rollout nach 76 + 76c. `comms/` mit den
  Plugin-Handlern ist am komplexesten (TYPE_CHECKING-Pattern, viele
  zirkuläre Imports).
- **Etappen 0-5** (2026-05-04 bis -05): Setup, Tier 1 (Stores +
  Schedulers), Tier 2 (Helper), Tier 3 (Bridge-Infra), Tier 4a (alle
  24 Command-Handler), Tier 4b (Infrastruktur: `bridge.py`,
  `claude_agent.py`, ...), Tier 5 + CI-Gate.
- **Hotfix Etappe 5** (2026-05-05): Plattform-Differenz Linux/Windows
  in `multiprocessing`-Typing. Fix per `if sys.platform == "win32"`-Guards.
- **Branch**: `feature/phase-76b-mypy-strict-comms`.

## Phase 76c – mypy --strict für `tools/` + `web/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Parallel zu 76b — `tools/` (47 Module) und `web/` als
  größte Pakete.
- **Etappen 0-5** (2026-05-02 bis -04): Setup, Tier 1-3 stufenweise,
  Tier 4 plus Sonderbehandlung für große Module (Etappe 4b), Tier 5
  + CI-Gate.
- **Branch**: `feature/phase-76c-mypy-strict-tools-web`.

## Phase 77 – Commands-Plugin-Registry 🧩 ✅ ABGESCHLOSSEN

- **Trigger**: Konzept aus Phase 75 — Command-Handler als Plugins
  ladbar (Builtin / User-Dir / Entry-Points), damit Selbst-Erweiterung
  ohne Repo-Edit möglich ist.
- **Etappe 1** (2026-05-04): `CommandPlugin`-Manifest +
  `HandlerContext`-Service-Container in `base.py`. 3 Pilot-Handler
  (weather, todo, note).
- **Etappe 2** (2026-05-04): Migration der 20 verbleibenden Handler.
- **Etappe 3** (2026-05-04): `PluginRegistry` mit Discovery aus 3
  Quellen, Conflict-Detector als CI-Gate
  (`tests/test_plugin_pattern_conflicts.py`), Generator-Wizard
  (`scripts/generate_plugin.py`).
- **Voraussetzung**: Phase 76 + 76c.
- **Branch**: `feature/phase-77-plugin-registry`.

## Phase 77.5 – Plugin-Inspector 🔬 ✅ ABGESCHLOSSEN

- **Trigger**: Vorbedingung für Phase 78 (Self-Suggestion soll wissen,
  welche Plugins von welcher Quelle aktiv sind).
- **Maßnahme** (2026-05-05): Registry-Loader liefern intern
  `LoadedPlugin`-Wrapper mit Quellen-Information. Neues `plugins`-
  Builtin-Plugin (24. Builtin) und Dashboard-Modul für Plugin-Inspector
  (`web.plugins_api`).
- **Branch**: `feature/phase-77-5-plugin-inspector`.

## Phase 78 – Plugin-Self-Suggestion 💡 ✅ ABGESCHLOSSEN

- **Trigger**: Saleria soll Capability-Lücken systematisch sammeln,
  statt dass Lera sie aus Chat-Verläufen herausklauben muss.
- **R1-Guard** (Konzept §6 R1): kein `.py`-Drop, kein
  Filesystem-Schreiben, kein Sandbox-Lint. Manuelle Implementierung
  durch Maintainer.
- **Etappe 1** (2026-05-07): `tools.proposal_store.ProposalStore` —
  SQLite + FTS5, Dedupe-Suche, persistent.
- **Etappe 2** (2026-05-07): `comms.proposal_notifier` +
  `tools.intent_aggregator` — Trigger-Pipeline aus dem LLM-Fallback,
  Smalltalk-Filter, confidence≥0.7.
- **Etappe 3** (2026-05-08): Dashboard-Modul + `web.proposals_api`.
  Status-Workflow `new` → `reviewed` → `implemented`/`rejected`.
- **Hotfixes** (2026-05-08): CI-Fail bleach/markdown-it-Versionen,
  `deploy_dashboard.sh` mit Auto-Substitution.
- **Branch**: `feature/phase-78-plugin-self-suggestion`.

## Phase 79 – Richer Pseudocode für Vorschläge ⏸️ ON HOLD

- **Auftrag (2026-05-10)**: Bewertung "Phase 79 jetzt nicht gebraucht"
  als Konzept-Datei festhalten — als ON HOLD mit hartem Trigger.
- **Trigger** (Konzept §2.2): 5 Vorschläge in DB, 3 davon
  implementiert, pro Vorschlag dokumentierte Spec-Lücke.
- **Selbst-Verpflichtung** (Konzept §2.3): nach 6 Monaten ohne
  erfüllten Trigger → Phase VERWORFEN. Schutz gegen ewiges Offenhalten.
- **Konzept**: `docs/concepts/phase-79-richer-pseudocode.md`.

## Phase 80 – ConversationListStore + list_pick 🧷 ✅ ABGESCHLOSSEN

- **Trigger**: LLM halluzinierte URLs und Mail-IDs in Folge-Befehlen.
  Lösung: Listen serverseitig vorhalten, LLM bekommt nur den Index.
- **Etappe 1** (2026-05-08): `tools.conversation_list_store.
  ConversationListStore` — in-memory, TTL=1h, eine aktive Liste pro
  `(user_id, list_type)`. Lazy Eviction. Thread-safe.
- **Etappe 2** (2026-05-08): `web_search`-Integration + erstes
  `list_pick`-Tool im LLM-Schema.
- **Etappe 3** (2026-05-09): List-Types `mail_inbox`, `note_search`.
  Codex-Reviewer-Findings ausgeräumt (`mail_by_id`-Reroute).
- **Tests**: `tests/test_conversation_list_store.py` + Integrations-
  Tests pro List-Type.
- **Merge**: 3 PRs sequenziell auf main.
- **Branch**: `feature/phase-80-conversation-list-store-*`.

## Phase 81 + 81b – Command-Fallback-UX + Self-Suggestion-Hook 🔁 ✅ ABGESCHLOSSEN

- **Trigger**: Zwei UX-Härtungen während Phase 80.
- **Phase 81 (Punkt 7)**: Wenn das LLM auch nach Retry kein Command
  findet, bekommt der User eine kurze Erklärung statt Schweigen
  ("Ich habe das als Befehl verstanden, konnte ihn aber keinem
  Command zuordnen — Tipp `hilfe`.").
- **Phase 81b**: Der Fallback-Pfad legt zusätzlich einen
  Plugin-Vorschlag über die Phase-78-Pipeline an. `is_rejected`-Check
  vorab, damit der User nicht über bereits abgelehnte Features
  informiert wird. Bei Erfolg: "Ich habe Marcus eine Notiz
  hinterlassen — wenn das öfter vorkommt, kümmert er sich darum."
- **Files**: `src/elder_berry/comms/message_handlers.py` (Z. ~1362,
  ~1572), `src/elder_berry/tools/intent_aggregator.py` (`is_rejected`).
- **Tests**: `tests/test_message_handlers.py` (3 neue Tests) +
  `is_rejected`-Helper-Tests in `tests/test_intent_aggregator.py`.
- **Suite**: 5418 Tests collected (Stand 2026-05-10).

## Phase 76 – mypy --strict für `core/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Erster Tier-Rollout aus dem mypy-Konzept (Phase 75).
  `core/` als Tier 1 ist das kleinste Paket mit den meisten
  Querverbindungen → schmerzhafte Typ-Drift früh fangen.
- **Etappen 1-4** (2026-05-01): Tier-1 strict (Setup + 3 Module),
  Tier-2 strict (3 Module), Out-of-Scope-Pakete silencen, Tier-3
  strict (6 Module), Tier-4 strict (4 Module) + Gate hart. 14 Module
  insgesamt. CI-Workflow `.github/workflows/mypy-strict.yml` ergänzt;
  bei Tier-Drift bricht CI.
- **Tests**: keine Suite-Änderung — mypy ist statische Prüfung.
- **Branch**: `feature/phase-76-mypy-strict-core` (Etappen einzeln gemergt).

## Phase 76b – mypy --strict für `comms/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Zweiter Tier-Rollout nach 76 + 76c. `comms/` mit den
  Plugin-Handlern ist am komplexesten (TYPE_CHECKING-Pattern, viele
  zirkuläre Imports).
- **Etappen 0-5** (2026-05-04 bis -05): Setup, Tier 1 (Stores +
  Schedulers), Tier 2 (Helper), Tier 3 (Bridge-Infra), Tier 4a (alle
  24 Command-Handler), Tier 4b (Infrastruktur: `bridge.py`,
  `claude_agent.py`, ...), Tier 5 + CI-Gate. Plugin-Registry-Awareness:
  `base.py` + `registry.py` sind durch Phase 77 ohnehin bereits strict.
- **Hotfix Etappe 5** (2026-05-05): CI auf Linux durch, lokal Windows
  nicht — Plattform-Differenz in `multiprocessing`-Typing. Fix per
  `if sys.platform == "win32"`-Guards.
- **Branch**: `feature/phase-76b-mypy-strict-comms`.

## Phase 76c – mypy --strict für `tools/` + `web/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Parallel zu 76b — `tools/` (47 Module) und `web/` als
  größte Pakete. Konzept §8 hatte das als 76b/c separiert; sequenziell
  wie Phase 76 abgearbeitet.
- **Etappen 0-5** (2026-05-02 bis -04): Setup, Tier 1-3 stufenweise,
  Tier 4 plus Sonderbehandlung für große Module (Etappe 4b), Tier 5
  + CI-Gate. Pattern aus Phase 76 (`stt_router/_run_async`-Workaround)
  mehrfach wiederverwendet.
- **Branch**: `feature/phase-76c-mypy-strict-tools-web`.

## Phase 77 – Commands-Plugin-Registry 🧩 ✅ ABGESCHLOSSEN

- **Trigger**: Konzept aus Phase 75 — Command-Handler sollen als
  Plugins ladbar sein (Builtin / User-Dir / Entry-Points), damit
  Selbst-Erweiterung ohne Repo-Edit möglich ist.
- **Etappe 1** (2026-05-04): `CommandPlugin`-Manifest +
  `HandlerContext`-Service-Container in `base.py`. 3 Pilot-Handler
  migriert (weather, todo, note).
- **Etappe 2** (2026-05-04): Migration der 20 verbleibenden Handler.
- **Etappe 3** (2026-05-04): `PluginRegistry` mit Discovery aus 3
  Quellen, Conflict-Detector als CI-Gate
  (`tests/test_plugin_pattern_conflicts.py`), Generator-Wizard
  (`scripts/generate_plugin.py`).
- **Voraussetzung**: Phase 76 + 76c (strict in `core/`, `tools/`, `web/`).
- **Branch**: `feature/phase-77-plugin-registry`.

## Phase 77.5 – Plugin-Inspector 🔬 ✅ ABGESCHLOSSEN

- **Trigger**: Vorbedingung für Phase 78 (Self-Suggestion soll wissen,
  welche Plugins von welcher Quelle aktiv sind).
- **Maßnahme** (2026-05-05): Registry-Loader liefern intern
  `LoadedPlugin`-Wrapper mit Quellen-Information. Neues `plugins`-
  Builtin-Plugin (24. Builtin) und Dashboard-Modul für Plugin-Inspector
  (`web.plugins_api`). `load_plugins()` bleibt rückwärtskompatibel.
- **Tests**: API-Tests in `tests/test_plugins_api.py`.
- **Branch**: `feature/phase-77-5-plugin-inspector`.

## Phase 78 – Plugin-Self-Suggestion 💡 ✅ ABGESCHLOSSEN

- **Trigger**: Saleria soll Capability-Lücken systematisch sammeln,
  statt dass Lera sie aus Chat-Verläufen herausklauben muss.
- **Konzept-Nachschärfung** (2026-05-07): R1-Guard zwingend (kein
  `.py`-Drop, kein Filesystem-Schreiben, kein Sandbox-Lint). Speicher
  zentral, Trigger reaktiv, Status-Workflow im Dashboard.
- **Etappe 1** (2026-05-07): `tools.proposal_store.ProposalStore` —
  SQLite + FTS5, Dedupe-Suche, persistent. Pattern wie `NoteStore`.
- **Etappe 2** (2026-05-07): `comms.proposal_notifier` +
  `tools.intent_aggregator` — Trigger-Pipeline aus dem LLM-Fallback,
  Smalltalk-Filter, confidence≥0.7.
- **Etappe 3** (2026-05-08): Dashboard-Modul + `web.proposals_api`.
  Status-Workflow `new` → `reviewed` → `implemented`/`rejected`.
- **Hotfixes** (2026-05-08): CI-Fail `bleach`/`markdown-it`-Versionen
  korrigiert. `deploy_dashboard.sh` mit Auto-Substitution.
- **Tests**: `tests/test_proposal_store.py`,
  `tests/test_proposal_notifier.py`, `tests/test_intent_aggregator.py`,
  `tests/test_proposals_api.py`.
- **Branch**: `feature/phase-78-plugin-self-suggestion`.

## Phase 79 – Richer Pseudocode für Vorschläge ⏸️ ON HOLD

- **Auftrag (2026-05-10)**: Bewertung "Phase 79 jetzt nicht gebraucht"
  als Konzept-Datei festhalten — nicht als offen-unter-Vorbehalt,
  sondern als ON HOLD mit hartem Trigger.
- **Trigger-Bedingung** (Konzept §2.2): 5 Vorschläge in der DB, 3 davon
  durch den Implementierungs-Prozess gelaufen, pro Vorschlag
  dokumentierte Spec-Lücke (nicht Bauchgefühl).
- **Selbst-Verpflichtung** (Konzept §2.3): wenn der Trigger nach
  6 Monaten nicht erfüllt ist, Phase wird VERWORFEN. Schutz gegen
  ewiges Offenhalten.
- **Wenn aktiviert**: Pseudocode-Cap 25 Zeilen, Test-Bullets-Cap 5,
  oranger Banner im Dashboard ("LLM-generiert, nicht 1:1 kopieren").
  R1-Guard aus Phase 78 bleibt zwingend in Kraft.
- **Konzept**: `docs/concepts/phase-79-richer-pseudocode.md`.

## Phase 80 – ConversationListStore + list_pick 🧷 ✅ ABGESCHLOSSEN

- **Trigger**: LLM halluzinierte URLs und Mail-IDs in Folge-Befehlen
  ("fasse die zweite Suche zusammen" → Random-URL). Lösung: Listen
  serverseitig vorhalten, LLM bekommt nur den Index.
- **Etappe 1** (2026-05-08): `tools.conversation_list_store.
  ConversationListStore` — in-memory, TTL=1h, eine aktive Liste pro
  `(user_id, list_type)`. Lazy Eviction. Thread-safe.
- **Etappe 2** (2026-05-08): `web_search`-Integration + erstes
  `list_pick`-Tool im LLM-Schema.
- **Etappe 3** (2026-05-09): Zusätzliche List-Types `mail_inbox`,
  `note_search`. Codex-Reviewer-Findings ausgeräumt
  (`mail_by_id`-Reroute).
- **Tests**: `tests/test_conversation_list_store.py` + Integrations-
  Tests pro List-Type. CodeQL-Findings aus Etappe 2 nachgezogen.
- **Merge**: 3 PRs (Etappen 1-3) sequenziell auf main.
- **Branch**: `feature/phase-80-conversation-list-store-*`.

## Phase 81 + 81b – Command-Fallback-UX + Self-Suggestion-Hook 🔁 ✅ ABGESCHLOSSEN

- **Trigger**: Zwei UX-Härtungen, die während Phase 80 aufgefallen
  sind und zusammen sauber in den Command-Router passen.
- **Phase 81 (Punkt 7)**: Wenn das LLM auch nach Retry kein Command
  aus dem User-Text findet, bekommt der User eine kurze Erklärung
  statt Schweigen ("Ich habe das als Befehl verstanden, konnte ihn
  aber keinem meiner Commands zuordnen — Tipp `hilfe` für die
  Übersicht.").
- **Phase 81b**: Der Fallback-Pfad ruft zusätzlich die Phase-78-
  Pipeline (`IntentAggregator`) auf, um einen Plugin-Vorschlag anzulegen.
  Aggregator filtert selbst (Smalltalk, confidence<0.7, abgelehnt nur
  Trigger-Zähler). Zusätzlicher `is_rejected`-Check vorab, damit der
  User nicht über bereits abgelehnte Features informiert wird. Bei
  erfolgreichem Vorschlag ergänzt Saleria im User-Feedback "Ich habe
  Marcus eine Notiz hinterlassen — wenn das öfter vorkommt, kümmert
  er sich darum."
- **Tests**: `tests/test_message_handlers.py` (3 neue Tests:
  User-Feedback-Pfad, Aggregator-Trigger, Notiz-Hinweis-Bedingung) +
  `tests/test_intent_aggregator.py::is_rejected`-Helper-Tests.
- **Files**: `src/elder_berry/comms/message_handlers.py` (Z. ~1362,
  ~1572), `src/elder_berry/tools/intent_aggregator.py` (`is_rejected`).
- **Suite**: 5418 Tests collected (Stand 2026-05-10).

## Phase 76 – mypy --strict für `core/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Erster Tier-Rollout aus dem mypy-Konzept (Phase 75
  Konzept). `core/` ist als Tier 1 das kleinste Paket mit den meisten
  Querverbindungen → schmerzhafte Typ-Drift früh fangen.
- **Etappen 1-4** (2026-05-01): Tier-1 strict (Setup + 3 Module),
  Tier-2 strict (3 Module), Out-of-Scope-Pakete silencen, Tier-3
  strict (6 Module), Tier-4 strict (4 Module) + Gate hart. 14 Module
  insgesamt. CI-Workflow `.github/workflows/mypy-strict.yml` ergänzt;
  bei Tier-Drift bricht CI.
- **Tests**: keine Suite-Änderung — mypy ist statische Prüfung.
- **Branch**: `feature/phase-76-mypy-strict-core` (Etappen einzeln
  gemergt).

## Phase 76b – mypy --strict für `comms/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Zweiter Tier-Rollout nach 76 + 76c. `comms/` mit den
  Plugin-Handlern ist am komplexesten (TYPE_CHECKING-Pattern, viele
  zirkuläre Imports).
- **Etappen 0-5** (2026-05-04 bis -05): Setup, Tier 1 (Stores +
  Schedulers), Tier 2 (kleine Helper), Tier 3 (Bridge-Infra),
  Tier 4a (alle 24 Command-Handler), Tier 4b (Infrastruktur:
  `bridge.py`, `claude_agent.py`, ...), Tier 5 + CI-Gate.
  Plugin-Registry-Awareness: `base.py` + `registry.py` sind durch
  Phase 77 ohnehin bereits strict.
- **Hotfix Etappe 5** (2026-05-05): CI lief auf Linux durch, lokal
  auf Windows nicht — Plattform-Differenz in `multiprocessing`-
  Typing. Fix per `if sys.platform == "win32"`-Guards.
- **Tests**: keine Suite-Änderung.
- **Branch**: `feature/phase-76b-mypy-strict-comms`.

## Phase 76c – mypy --strict für `tools/` + `web/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Parallel zu 76b — `tools/` (47 Module) und `web/` als
  größte Pakete. Konzept §8 hatte das als 76b/c separiert; wegen
  ähnlicher Strukturen sequenziell wie Phase 76.
- **Etappen 0-5** (2026-05-02 bis -04): Setup, Tier 1-3 stufenweise,
  Tier 4 plus Sonderbehandlung für große Module (Etappe 4b), Tier 5
  + CI-Gate. Pattern aus Phase 76 (`stt_router/_run_async`-Workaround)
  mehrfach wiederverwendet.
- **Tests**: keine Suite-Änderung.
- **Branch**: `feature/phase-76c-mypy-strict-tools-web`.

## Phase 77 – Commands-Plugin-Registry 🧩 ✅ ABGESCHLOSSEN

- **Trigger**: Konzept aus Phase 75 — Command-Handler sollen als
  Plugins ladbar sein (Builtin / User-Dir / Entry-Points), damit
  Selbst-Erweiterung ohne Repo-Edit möglich ist.
- **Etappe 1** (2026-05-04): `CommandPlugin`-Manifest +
  `HandlerContext`-Service-Container in `base.py`. 3 Pilot-Handler
  migriert (weather, todo, note).
- **Etappe 2** (2026-05-04): Migration der 20 verbleibenden Handler.
- **Etappe 3** (2026-05-04): `PluginRegistry` mit Discovery aus 3
  Quellen, Conflict-Detector als CI-Gate
  (`tests/test_plugin_pattern_conflicts.py`), Generator-Wizard
  (`scripts/generate_plugin.py`).
- **Tests**: Conflict-Detector als pflichtiger Test; pro Handler
  je 1 Integrations-Test, dass das Plugin korrekt geladen wird.
- **Voraussetzung**: Phase 76 + 76c (strict in `core/`, `tools/`,
  `web/`).
- **Branch**: `feature/phase-77-plugin-registry`.

## Phase 77.5 – Plugin-Inspector 🔬 ✅ ABGESCHLOSSEN

- **Trigger**: Vorbedingung für Phase 78 (Self-Suggestion soll wissen,
  welche Plugins von welcher Quelle aktiv sind).
- **Maßnahme** (2026-05-05): Registry-Loader liefern intern
  `LoadedPlugin`-Wrapper mit Quellen-Information. Neues `plugins`-
  Builtin-Plugin (24. Builtin) und Dashboard-Modul für Plugin-Inspector
  (`web.plugins_api`). `load_plugins()` bleibt rückwärtskompatibel.
- **Tests**: Plugin-Inspector-Tests + API-Tests in
  `tests/test_plugins_api.py`.
- **Branch**: `feature/phase-77-5-plugin-inspector`.

## Phase 78 – Plugin-Self-Suggestion 💡 ✅ ABGESCHLOSSEN

- **Trigger**: Saleria soll Capability-Lücken systematisch sammeln,
  statt dass Lera sie aus Chat-Verläufen herausklauben muss.
- **Konzept-Nachschärfung** (2026-05-07): R1-Guard zwingend
  (kein `.py`-Drop, kein Filesystem-Schreiben, kein Sandbox-Lint).
  Speicher zentral, Trigger reaktiv, Status-Workflow im Dashboard.
- **Etappe 1** (2026-05-07): `tools.proposal_store.ProposalStore` —
  SQLite + FTS5, Dedupe-Suche, persistent. Pattern wie `NoteStore`.
- **Etappe 2** (2026-05-07): `comms.proposal_notifier` +
  `tools.intent_aggregator` — Trigger-Pipeline aus dem LLM-Fallback,
  Smalltalk-Filter, confidence≥0.7.
- **Etappe 3** (2026-05-08): Dashboard-Modul (`webapp/dashboard/
  modules/proposals.js`) + `web.proposals_api`. Status-Workflow
  `new` → `reviewed` → `implemented`/`rejected`.
- **Hotfixes** (2026-05-08): CI-Fail `bleach`/`markdown-it`-Versionen
  korrigiert. `deploy_dashboard.sh` mit Auto-Substitution.
- **Tests**: `tests/test_proposal_store.py`,
  `tests/test_proposal_notifier.py`, `tests/test_intent_aggregator.py`,
  `tests/test_proposals_api.py`.
- **Branch**: `feature/phase-78-plugin-self-suggestion`.

## Phase 79 – Richer Pseudocode für Vorschläge ⏸️ ON HOLD

- **Auftrag (2026-05-10)**: Lera will Bewertung "Phase 79 jetzt nicht
  gebraucht" als Konzept-Datei festhalten — nicht als
  offen-unter-Vorbehalt, sondern als ON HOLD mit hartem Trigger.
- **Trigger-Bedingung** (Konzept §2.2): 5 Vorschläge in der DB, 3 davon
  durch den Implementierungs-Prozess gelaufen, pro Vorschlag
  dokumentierte Spec-Lücke (nicht Bauchgefühl).
- **Selbst-Verpflichtung** (Konzept §2.3): wenn der Trigger nach
  6 Monaten nicht erfüllt ist, Phase wird VERWORFEN. Schutz gegen
  ewiges Offenhalten.
- **Wenn aktiviert**: Pseudocode-Cap 25 Zeilen, Test-Bullets-Cap 5,
  oranger Banner im Dashboard ("LLM-generiert, nicht 1:1 kopieren").
  R1-Guard aus Phase 78 bleibt zwingend in Kraft.
- **Konzept**: `docs/concepts/phase-79-richer-pseudocode.md`.

## Phase 80 – ConversationListStore + list_pick 🧷 ✅ ABGESCHLOSSEN

- **Trigger**: LLM halluzinierte URLs und Mail-IDs in Folge-Befehlen
  ("fasse die zweite Suche zusammen" → Random-URL). Lösung: Listen
  serverseitig vorhalten, LLM bekommt nur den Index.
- **Etappe 1** (2026-05-08): `tools.conversation_list_store.
  ConversationListStore` — in-memory, TTL=1h, eine aktive Liste pro
  `(user_id, list_type)`. Lazy Eviction. Thread-safe.
- **Etappe 2** (2026-05-08): `web_search`-Integration + erstes
  `list_pick`-Tool im LLM-Schema.
- **Etappe 3** (2026-05-09): Zusätzliche List-Types `mail_inbox`,
  `note_search`. Codex-Reviewer-Findings ausgeräumt
  (`mail_by_id`-Reroute).
- **Tests**: `tests/test_conversation_list_store.py` + Integrations-
  Tests pro List-Type. CodeQL-Findings aus Etappe 2 nachgezogen.
- **Merge**: 3 PRs (Etappen 1-3) sequenziell auf main.
- **Branch**: `feature/phase-80-conversation-list-store-*`.

## Phase 81 + 81b – Command-Fallback-UX + Self-Suggestion-Hook 🔁 ✅ ABGESCHLOSSEN

- **Trigger**: Zwei UX-Härtungen, die während Phase 80 aufgefallen
  sind und zusammen sauber in den Command-Router passen.
- **Phase 81 (Punkt 7)**: Wenn das LLM auch nach Retry kein Command
  aus dem User-Text findet, bekommt der User eine kurze Erklärung
  statt Schweigen ("Ich habe das als Befehl verstanden, konnte ihn
  aber keinem meiner Commands zuordnen — Tipp `hilfe` für die
  Übersicht."). Ohne diesen Hook landete der User in einer stillen
  Sackgasse.
- **Phase 81b**: Der Fallback-Pfad ruft zusätzlich die Phase-78-Pipeline
  (`IntentAggregator`) auf, um einen Plugin-Vorschlag anzulegen.
  Aggregator filtert selbst (Smalltalk, confidence<0.7, abgelehnt nur
  Trigger-Zähler). Zusätzlicher `is_rejected`-Check vorab, damit der
  User nicht über bereits abgelehnte Features informiert wird. Bei
  erfolgreichem Vorschlag ergänzt Saleria im User-Feedback "Ich habe
  Marcus eine Notiz hinterlassen — wenn das öfter vorkommt, kümmert
  er sich darum."
- **Tests**: `tests/test_message_handlers.py` (3 neue Tests:
  User-Feedback-Pfad, Aggregator-Trigger, Notiz-Hinweis-Bedingung) +
  `tests/test_intent_aggregator.py::is_rejected`-Helper-Tests.
- **Files**: `src/elder_berry/comms/message_handlers.py` (Z. ~1362,
  ~1572), `src/elder_berry/tools/intent_aggregator.py` (`is_rejected`).
- **Suite**: 5418 Tests collected (Stand 2026-05-10).

## Phase 76 – mypy --strict für `core/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Erster Tier-Rollout aus dem mypy-Konzept (Phase 75).
  `core/` als Tier 1 ist das kleinste Paket mit den meisten
  Querverbindungen → schmerzhafte Typ-Drift früh fangen.
- **Etappen 1-4** (2026-05-01): Tier-1 strict (Setup + 3 Module),
  Tier-2 strict (3 Module), Out-of-Scope-Pakete silencen, Tier-3
  strict (6 Module), Tier-4 strict (4 Module) + Gate hart. 14 Module
  insgesamt. CI-Workflow `.github/workflows/mypy-strict.yml` ergänzt.
- **Tests**: keine Suite-Änderung — mypy ist statische Prüfung.
- **Branch**: `feature/phase-76-mypy-strict-core` (Etappen einzeln gemergt).

## Phase 76b – mypy --strict für `comms/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Zweiter Tier-Rollout nach 76 + 76c. `comms/` mit den
  Plugin-Handlern ist am komplexesten (TYPE_CHECKING-Pattern, viele
  zirkuläre Imports).
- **Etappen 0-5** (2026-05-04 bis -05): Setup, Tier 1 (Stores +
  Schedulers), Tier 2 (Helper), Tier 3 (Bridge-Infra), Tier 4a (alle
  24 Command-Handler), Tier 4b (Infrastruktur: `bridge.py`,
  `claude_agent.py`, ...), Tier 5 + CI-Gate.
- **Hotfix Etappe 5** (2026-05-05): Plattform-Differenz Linux/Windows
  in `multiprocessing`-Typing. Fix per `if sys.platform == "win32"`-Guards.
- **Branch**: `feature/phase-76b-mypy-strict-comms`.

## Phase 76c – mypy --strict für `tools/` + `web/` 🔍 ✅ ABGESCHLOSSEN

- **Trigger**: Parallel zu 76b — `tools/` (47 Module) und `web/` als
  größte Pakete.
- **Etappen 0-5** (2026-05-02 bis -04): Setup, Tier 1-3 stufenweise,
  Tier 4 plus Sonderbehandlung für große Module (Etappe 4b), Tier 5
  + CI-Gate.
- **Branch**: `feature/phase-76c-mypy-strict-tools-web`.

## Phase 77 – Commands-Plugin-Registry 🧩 ✅ ABGESCHLOSSEN

- **Trigger**: Konzept aus Phase 75 — Command-Handler als Plugins
  ladbar (Builtin / User-Dir / Entry-Points), damit Selbst-Erweiterung
  ohne Repo-Edit möglich ist.
- **Etappe 1** (2026-05-04): `CommandPlugin`-Manifest +
  `HandlerContext`-Service-Container in `base.py`. 3 Pilot-Handler
  (weather, todo, note).
- **Etappe 2** (2026-05-04): Migration der 20 verbleibenden Handler.
- **Etappe 3** (2026-05-04): `PluginRegistry` mit Discovery aus 3
  Quellen, Conflict-Detector als CI-Gate
  (`tests/test_plugin_pattern_conflicts.py`), Generator-Wizard
  (`scripts/generate_plugin.py`).
- **Voraussetzung**: Phase 76 + 76c.
- **Branch**: `feature/phase-77-plugin-registry`.

## Phase 77.5 – Plugin-Inspector 🔬 ✅ ABGESCHLOSSEN

- **Trigger**: Vorbedingung für Phase 78 (Self-Suggestion soll wissen,
  welche Plugins von welcher Quelle aktiv sind).
- **Maßnahme** (2026-05-05): Registry-Loader liefern intern
  `LoadedPlugin`-Wrapper mit Quellen-Information. Neues `plugins`-
  Builtin-Plugin (24. Builtin) und Dashboard-Modul für Plugin-Inspector
  (`web.plugins_api`).
- **Branch**: `feature/phase-77-5-plugin-inspector`.

## Phase 78 – Plugin-Self-Suggestion 💡 ✅ ABGESCHLOSSEN

- **Trigger**: Saleria soll Capability-Lücken systematisch sammeln,
  statt dass Lera sie aus Chat-Verläufen herausklauben muss.
- **R1-Guard** (Konzept §6 R1): kein `.py`-Drop, kein
  Filesystem-Schreiben, kein Sandbox-Lint. Manuelle Implementierung
  durch Maintainer.
- **Etappe 1** (2026-05-07): `tools.proposal_store.ProposalStore` —
  SQLite + FTS5, Dedupe-Suche, persistent.
- **Etappe 2** (2026-05-07): `comms.proposal_notifier` +
  `tools.intent_aggregator` — Trigger-Pipeline aus dem LLM-Fallback,
  Smalltalk-Filter, confidence>=0.7.
- **Etappe 3** (2026-05-08): Dashboard-Modul + `web.proposals_api`.
  Status-Workflow `new` -> `reviewed` -> `implemented`/`rejected`.
- **Hotfixes** (2026-05-08): CI-Fail bleach/markdown-it-Versionen,
  `deploy_dashboard.sh` mit Auto-Substitution.
- **Branch**: `feature/phase-78-plugin-self-suggestion`.

## Phase 79 – Richer Pseudocode für Vorschläge ⏸️ ON HOLD

- **Auftrag (2026-05-10)**: Bewertung "Phase 79 jetzt nicht gebraucht"
  als Konzept-Datei festhalten — als ON HOLD mit hartem Trigger.
- **Trigger** (Konzept §2.2): 5 Vorschläge in DB, 3 davon
  implementiert, pro Vorschlag dokumentierte Spec-Lücke.
- **Selbst-Verpflichtung** (Konzept §2.3): nach 6 Monaten ohne
  erfüllten Trigger -> Phase VERWORFEN. Schutz gegen ewiges Offenhalten.
- **Konzept**: `docs/concepts/phase-79-richer-pseudocode.md`.

## Phase 80 – ConversationListStore + list_pick 🧷 ✅ ABGESCHLOSSEN

- **Trigger**: LLM halluzinierte URLs und Mail-IDs in Folge-Befehlen.
  Lösung: Listen serverseitig vorhalten, LLM bekommt nur den Index.
- **Etappe 1** (2026-05-08): `tools.conversation_list_store.
  ConversationListStore` — in-memory, TTL=1h, eine aktive Liste pro
  `(user_id, list_type)`. Lazy Eviction. Thread-safe.
- **Etappe 2** (2026-05-08): `web_search`-Integration + erstes
  `list_pick`-Tool im LLM-Schema.
- **Etappe 3** (2026-05-09): List-Types `mail_inbox`, `note_search`.
  Codex-Reviewer-Findings ausgeräumt (`mail_by_id`-Reroute).
- **Tests**: `tests/test_conversation_list_store.py` + Integrations-
  Tests pro List-Type.
- **Merge**: 3 PRs sequenziell auf main.
- **Branch**: `feature/phase-80-conversation-list-store-*`.

## Phase 81 + 81b – Command-Fallback-UX + Self-Suggestion-Hook 🔁 ✅ ABGESCHLOSSEN

- **Trigger**: Zwei UX-Härtungen während Phase 80.
- **Phase 81 (Punkt 7)**: Wenn das LLM auch nach Retry kein Command
  findet, bekommt der User eine kurze Erklärung statt Schweigen
  ("Ich habe das als Befehl verstanden, konnte ihn aber keinem
  Command zuordnen — Tipp `hilfe`.").
- **Phase 81b**: Der Fallback-Pfad legt zusätzlich einen
  Plugin-Vorschlag über die Phase-78-Pipeline an. `is_rejected`-Check
  vorab, damit der User nicht über bereits abgelehnte Features
  informiert wird. Bei Erfolg: "Ich habe Marcus eine Notiz
  hinterlassen — wenn das öfter vorkommt, kümmert er sich darum."
- **Files**: `src/elder_berry/comms/message_handlers.py` (Z. ~1362,
  ~1572), `src/elder_berry/tools/intent_aggregator.py` (`is_rejected`).
- **Tests**: `tests/test_message_handlers.py` (3 neue Tests) +
  `is_rejected`-Helper-Tests in `tests/test_intent_aggregator.py`.
- **Suite**: 5418 Tests collected (Stand 2026-05-10).

## Phase 92 – Multi-Stop-Routing 🗺️ KONZEPT

- **Trigger**: User-Request – Routen mit mehreren Stops planen, Reihenfolge
  optimieren, POIs entlang der Route finden (z.B. "nach Leipzig Hbf,
  vorher Lisa und Andrea abholen, auf dem Weg bei Kaufland einkaufen").
- **Architektur**: `GoogleMapsRoutePlanner` (konkrete Klasse, Google
  Directions + Places API v1 "Search Along Route"), `MapsLinkBuilder`
  (provider-unabhängige Util für Google-Maps-Deep-Link), `RouteIntentParser`
  (Pattern-Vorfilter + Claude-Sonnet-Tool-Call mit JSON-Schema),
  `MultiStopRouteCommandHandler` mit Plugin-Pattern (priority=80,
  fallthrough zu Single-Stop bei priority=76).
- **Kein RouteProvider-Interface (bewusst)**: Datenschutz-Gewinn durch
  OSM = null wegen Google-Maps-Deep-Link am Ende, Kosten ~$1/Jahr
  amortisieren keinen Aufwand, Self-Hosting-Stack wäre Sicherheitsrisiko.
  YAGNI bis konkreter Trigger (Phase 92.3).
- **Disambiguierung**: Sequenziell mit nummerierten Listen, Zustand in
  `PendingConfirmationStore` (`action_type="route_disambig"`).
  Handler-eigener Zahl-Antwort-Vorcheck — `PendingConfirmationStore` selbst
  bleibt unverändert.
- **Phase 43-Single-Stop bleibt unangetastet**. Existierender Bug im
  `RouteCommandHandler._resolve_address()` (immer `results[0]` ohne
  Mehrdeutigkeits-Check) explizit aus Phase 92 ausgeschlossen –
  separater Bugfix-Branch.
- **Konzept**: `docs/concepts/phase-92-multi-stop-routing.md`.
- **Etappen**: E1 (Konzept) abgeschlossen 2026-05-13.
  E2–E5 (Implementierung) in eigenen Folge-Chats.
- **Branches**: `feature/phase-92-multi-stop-routing-concept` (initial,
  gemerged via PR #231), `feature/phase-92-concept-refactor-drop-osm-abstraction`
  (Refactor nach Datenschutz-/Kosten-/Sicherheits-Analyse).
