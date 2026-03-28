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
| Sprachqualität | XTTS v2 | Gut genug für Alltagsnutzung; ElevenLabs wäre besser, kostet aber |
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


## Phase 34 – Briefing 2.0 ✅ ABGESCHLOSSEN

Personalisiertes Morgenbriefing mit Geburtstagen, offenen E-Mails,
"Vor einem Jahr"-Notizen und Wochenend-Variante.

- ✅ Geburtstage aus ContactStore (birthday-Feld: YYYY-MM-DD / 0000-MM-DD)
- ✅ Offene E-Mails (Anzahl ungelesener Mails als Einzeiler)
- ✅ Flashback-Notizen (≥330 Tage alte Notizen aus NoteStore)
- ✅ Wochenend-Variante (entspannter Ton, Todos/Erinnerungen ausgeblendet)
- ✅ Tests: 18 neue Tests, 2772 gesamt grün

## Phase 35 – Web-Zusammenfassung 🌐 GEPLANT

"Fasse https://... zusammen" als neuer Command. Natürliche Erweiterung von
DocumentReader (Phase 16) auf Web-Inhalte.

- **WebFetcher**: `httpx` (bereits vorhanden) + `trafilatura` für Text-Extraktion
- **WebSummaryCommandHandler**: Pattern `fasse .* zusammen` / `zusammenfassung von .*`
- **LLM-Pipeline**: bereits vorhanden (gleiche Logik wie Dokument-Zusammenfassung)
- **Fallback**: Brave Search Snippet wenn URL nicht abrufbar (robots.txt, Paywall)
- **Aufwand**: 1–2 Tage
- **Konzept**: `docs/concepts/phase-35-web-zusammenfassung.md`

## Phase 36 – Dashboard 2.0 (Modulare Smart Home PWA) 📱 GEPLANT

Mobile-first PWA auf dem Rootserver als modulare UI-Grundlage für Phase 37+.
Ersetzt keine bestehenden Tools — das AudioDashboard (Tower :8090) bleibt als Dev-Settings.

- **PWA**: installierbar auf Handy, HTTPS, Rootserver
- **Modul-Architektur**: jedes Modul eigenständige JS-Klasse, ein-/ausblendbar
- **Modul 1**: Harmony Remote (Phase 37.1 — RPi5 :8001/harmony/*)
- **Modul 2**: System-Status (RPi5 + Tower Health, immer sichtbar)
- **Modul 3**: Saleria-Status (Tower-abhängig, graceful offline)
- **Modul 4**: Home Assistant (Platzhalter, Phase 37.3)
- **Service Worker**: Offline-Cache für statische Assets
- **Design**: Weiterführung der bestehenden Ästhetik (#1a1a2e, Saleria-Lila)
- **Konzept**: `docs/concepts/phase-36-dashboard-2.0.md`
- **Abhängigkeit**: wird parallel zu Phase 37.1 implementiert

## Phase 37 – Smart Home Integration 🏠 GEPLANT

Vollständige lokale Smart-Home-Steuerung über eine erweiterbare Adapter-Architektur.
Logitech-Cloud wird sofort abgelöst (nicht erst bei Server-Shutdown).

### Unterphasen
- **37.1** Harmony Hub vollständige Ablösung (HarmonyAdapter auf RPi5, Config-Mock-Server, PWA)
- **37.2** SmartHomeInterface ABC + SmartHomeRegistry (Plugin-Architektur, Tower)
- **37.3** Home Assistant Adapter (REST API, lokal, nach Umzug)
- **37.4** Alexa-Integration via Emulated Hue (RPi5, nach Umzug + HA stabil)

- **Konzept**: `docs/concepts/phase-37-smart-home-integration.md`
- **Abhängigkeit**: 37.3/37.4 nach Umzug; 37.1+37.2 sofort

## Phase 38 – Sprachsteuerung / Alexa-Ablösung 🎙️ GEPLANT

Saleria erhält eine eigene Sprachschnittstelle — unabhängig von Amazon.
Zwei Modi werden parallel unterstützt, sodass zwischen Alexa und Saleria
gewechselt werden kann (Flexibilität, kein harter Cut).

### Unterphasen
- **38.1** Alexa Skill "Saleria" (Proxy-Modus, keine neue Hardware)
  → Echo macht Wake Word + STT, Text geht an Salerias API
- **38.2** Natives Wake Word + Mic Array (vollständige Unabhängigkeit)
  → OpenWakeWord auf RPi5, faster-whisper auf Tower-GPU
  → Hardware: ReSpeaker USB Array (~60€) oder Umbau vorhandener Hardware

- **Konzept**: `docs/concepts/phase-38-sprachsteuerung.md`
- **Abhängigkeit**: 38.1 nach 37.4; 38.2 nach 38.1 (Hardware-Entscheidung)
