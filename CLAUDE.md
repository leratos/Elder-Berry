# Elder-Berry – Claude Code Instructions

Sei bei deinen Antworten ehrlich, schöne nichts, sei kritisch und weise auf
Logiklücken und Fehler hin.

## KONTEXT
- Lies zu Beginn jedes Chats: C:\Dev\Elder-Berry\docs\journal.txt (letzte 80 Zeilen)
- journal.txt ist die einzige Quelle für den aktuellen Stand
- PROJECT_ROADMAP.md ist reine Planung – nur anfassen wenn Scope oder Phasen sich ändern
- docs/concepts/ enthält Konzeptdokumente für geplante Phasen – lies das relevante Konzept bevor du eine Phase startest
- Falls journal.txt fehlt oder leer: frag nach, mach keine Annahmen

## DOKUMENTATION
- Schreibe BEVOR du anfängst zu arbeiten einen Draft-Eintrag in journal.txt:
  "## In Arbeit: [Phase] – nächster Schritt: [Datei] / [Funktion/Aufgabe]"
- Ergänze den Eintrag nach Abschluss: "## Abgeschlossen: [Phase]"
- Bei längeren Phasen: nach jedem abgeschlossenen Teilschritt Zwischenstand sichern
- journal.txt ist das einzige Dokument das laufend gepflegt wird

## PLANUNG VOR AUSFÜHRUNG
- Nach dem Lesen von journal.txt: erstelle einen kurzen Plan was du tun wirst
- Warte auf explizite Bestätigung bevor du mit der Arbeit beginnst
- Bei Änderungen an Dateien: nenne vorher welche Dateien du ändern wirst
- Fang NIE an Code zu schreiben oder Dateien zu bearbeiten ohne Bestätigung

## CHAT-MANAGEMENT
- Jede neue Phase = neuer Chat. Keine Phase über einen Chat-Wechsel hinweg fortführen
- Ich weise dich hin wenn der Context riskant lang wird (ab ~100k Token oder wenn Fehler zunehmen)
- Wenn du selbst merkst dass Antworten unzuverlässiger werden: sag es aktiv, warte nicht darauf dass ich es bemerke

## GITHUB
- Erstelle zu Beginn jeder Phase einen neuen Branch: feature/phase-X-Y-kurzbeschreibung
- Committe am Ende jeder Phase alle Änderungen
- Keinen Pull-Request erstellen – das macht der Nutzer selbst
- Branch-Namen immer lowercase, Leerzeichen durch Bindestriche

## CODE-GENERIERUNG
- Neue Code-Dateien (Python, JS): Chunks von maximal 400 Zeilen
- Templates (HTML, Jinja2 etc.): nie inline generieren – immer als separate Datei, in Chunks
- Bei langen Dateien: Zwischenstand in journal.txt sichern bevor der nächste Chunk beginnt
- Lies bestehende Dateien VOR dem Schreiben – immer, auch wenn du den Inhalt zu kennen glaubst
- Verwende immer absolute Pfade (C:\Dev\Elder-Berry\...)

## REMOTE-COMMANDS (Matrix)
- Commands sind in domänenspezifische Handler aufgeteilt: src/elder_berry/comms/commands/
  - base.py: CommandHandler ABC + CommandResult DTO
  - system_commands.py: Status, Screenshot, Media, Volume, Avatar, Restart
  - calendar_commands.py: Termine CRUD + Suche
  - mail_commands.py: Mails, Suche, Anhänge
  - file_commands.py: Clipboard, Send-File, Download
  - process_commands.py: Start/Kill, Git, Docker, WoL
  - weather_commands.py: Wetter, Timer, Erinnerungen, Briefing, Training
  - advanced_commands.py: ComputerUse, Web-Suche, Dokumente, Audio
- remote_commands.py ist NUR der Orchestrator (~310 Zeilen) – KEINE Command-Logik dort einfügen
- Neue Commands: in den passenden Handler einfügen, oder neuen Handler erstellen
- Neuer Handler: CommandHandler ABC erben, patterns/keywords/execute() definieren,
  in RemoteCommandHandler._handlers Liste eintragen (Reihenfolge = Priorität!)
- Pattern-Tuple: (compiled_pattern, command_name, use_original_text, use_search)
  - use_original_text=True wenn Pfade erkannt werden (case-sensitiv)
  - use_search=True für pattern.search() statt pattern.match()
- HELP_TEXT in remote_commands.py nachtragen – einzige Stelle die dem Nutzer Commands anzeigt
- KEYWORD_MAP wird automatisch aus allen Handler.keywords aggregiert
- Vergiss HELP_TEXT nicht – sonst weiß niemand dass das Feature existiert

## ARCHITEKTUR
- Verwende objektorientierte Programmierung (OOP) – jede Komponente als eigene Klasse
- Eine Klasse pro Datei, Dateiname = Klassenname (snake_case)
- Klassen kommunizieren über definierte Interfaces, nicht direkt
- 3-Tier-System:
  - Tower (Hirn): LLM + TTS-Generierung, Assistant-Orchestrator, immer an
  - Laptop (Client): PC-Steuerung + Audio-Empfänger, AgentServer (FastAPI)
  - RPi5 (Display-Einheit): Sensoren, Avatar-Display, Drehteller-Servo
- Kernklassen:
  - Assistant         → Orchestrator: LLM → Action → TTS → Avatar → Robot → Matrix
  - SaleriaEngine     → Charakter-Persönlichkeit, Emotion-Extraktion
  - CoquiTTSEngine    → XTTS v2 Voice Cloning (pro Emotion ein Speaker-WAV)
  - LayeredSpriteRenderer → Component-basiertes Avatar-Rendering (PyGame)
  - WindowsActionController → PC-Steuerung (Tastatur, Maus, Fenster, Lautstärke)
  - RobotClient/Server → Tower ↔ RPi5 Kommunikation (REST, Port 8000)
  - AgentClient/Server → Tower ↔ Laptop Kommunikation (REST + Audio-Streaming)
  - LLMRouter         → entscheidet lokal (Ollama) oder remote (OpenRouter)
    - Unterwegs: Auto-Erkennung localhost → Mesh-IP → Fallback
    - Tower benötigt: OLLAMA_HOST=0.0.0.0 + Firewall nur Mesh-IP auf 11434
  - ActionsDB         → SQLite Aktions-Registry mit Self-Learning
  - SecretStore       → Fernet-verschlüsselter Credential-Store (~/.elder-berry/)
  - MessageChannel    → ABC für bidirektionale Nachrichtenkanäle
  - MatrixChannel     → matrix-nio Implementierung (async, Auto-Join, Room-Whitelist)
  - MatrixBridge      → Async↔Sync Bridge (MessageChannel ↔ Assistant, Thread+EventLoop)
  - AudioConverter    → WAV/MP3 → OGG/Opus (pydub + ffmpeg)
  - RemoteCommandHandler → Orchestrator, delegiert an CommandHandler-Subklassen
  - CommandHandler (ABC) → Interface für domänenspezifische Command-Handler (comms/commands/)
- Neue Komponenten immer als eigene Klasse, nie als Funktion in bestehende Datei kippen
- Abhängigkeiten zwischen Klassen explizit über Konstruktor übergeben (Dependency Injection)

## UMGEBUNG
- Tower (Windows, 16GB VRAM): C:\Dev\Elder-Berry\.venv, Python 3.12
  - LLM: phi4:14b – läuft vollständig in VRAM
  - Rolle: Hirn (LLM + TTS-Generierung), immer an
  - Aktuell: noch nicht scharfgeschaltet, Entwicklung läuft auf Laptop
- Laptop (Windows, 8GB VRAM): C:\Dev\Elder-Berry\.venv, Python 3.12
  - LLM: phi4:14b – läuft mit leichter RAM-Auslagerung, akzeptable Geschwindigkeit
  - Rolle: Client (empfängt PC-Befehle + Audio vom Tower, wenn User auf Couch)
  - Unterwegs: kann Tower als LLM-Backend über NordVPN Meshnet nutzen
  - Fallback: eigenes Ollama lokal wenn Tower nicht erreichbar
- RPi 5 (Linux): /home/pi/elder-berry/, Python 3.13 (System-Python Bookworm), absolute Linux-Pfade
- Gleiches Modell auf Tower und Laptop → identisches Verhalten beim Testen
- Verwende pathlib statt hartcodierte Slashes wo plattformübergreifend
- Weise aktiv darauf hin wenn Code plattformspezifisch ist
- Falls .venv nicht vorhanden: erstelle es mit py -3.12 -m venv .venv
- Führe nach Code-Änderungen die betroffenen Tests aus und berichte das Ergebnis

## HARDWARE
### Tower
- RTX 4070 Ti Super (16GB VRAM)
- Ollama lokal (phi4:14b)
- Hauptrechner für LLM, Aktionslogik, PC-Steuerung

### Laptop (Testplattform)
- RTX 4070 Laptop (8GB VRAM)
- Ollama lokal (phi4:14b)

### RPi 5 (I/O-Hub + Sensor-Hub)
- Sensor-Integration: BME280 (I2C), APDS-9960 (I2C), Kamera (CSI)
- Drehteller: 28BYJ-48 Stepper + ULN2003 (GPIO) + A3144 Hall-Sensoren (GPIO)
- Kommunikation Tower ↔ RPi 5: REST via FastAPI (Port 8000, WLAN)
- Kein LLM

### Roboter-Chassis → GESTRICHEN (stationär + drehbar)
- Mecanum-Antrieb gestrichen – Mehrwert zu gering
- Stattdessen: Drehteller mit 200mm Alu Lazy-Susan Lager (60-70kg Tragkraft)
- 1× 28BYJ-48 Stepper + ULN2003 über RPi5 GPIO (Reaktionsantrieb)
- A3144 Hall-Sensoren für ±180° Begrenzung + Home-Position
- Akku: optional (USB-C Netzteil für Dauerbetrieb möglich)
- Kamera: fest im Gehäuse

## LLM-STRATEGIE
- Lokal (Ollama): schnelle Aktionen, Sensor-Auswertung, PC-Steuerung, Dauerbetrieb
- OpenRouter: Multimodal (Kamera-Input), komplexes Reasoning, Fallback
- Modell-Wechsel nur mit expliziter Begründung vorschlagen

## CHARAKTER
- Saleria Berry – "Charmant und melodisch mit einem Hauch spielerischer Gefahr"
- 10 Emotionen: neutral, cheerful, sarcastic, motivated, thoughtful, whisper, shy, depressed, sad, angry
- Voice: Coqui XTTS v2 Voice Cloning, pro Emotion ein Speaker-WAV
- Avatar: Layered Sprite System (Body + Eyes L/R + Mouth), Blink-Animation, Lip-Sync
- Pepper's Ghost Hologramm: LCD horizontal + Acryl 45°, schwarzer Hintergrund (0,0,0)
- Persönlichkeit definiert in: src/elder_berry/character/saleria.yaml

## QUALITÄT
- Weise aktiv auf fehlende Tests, Sicherheitslücken oder technische Schulden hin
- Wenn etwas unklar ist: frag nach, statt Annahmen zu machen