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

## ARCHITEKTUR
- Verwende objektorientierte Programmierung (OOP) – jede Komponente als eigene Klasse
- Eine Klasse pro Datei, Dateiname = Klassenname (snake_case)
- Klassen kommunizieren über definierte Interfaces, nicht direkt
- 3-Tier-System:
  - Tower (Hirn): LLM + TTS-Generierung, Assistant-Orchestrator, immer an
  - Laptop (Client): PC-Steuerung + Audio-Empfänger, AgentServer (FastAPI)
  - RPi5 (Robot-Körper): Motoren, Sensoren, Avatar-Display, RobotServer (FastAPI)
- Kernklassen:
  - Assistant         → Orchestrator: LLM → Action → TTS → Avatar → Robot
  - SaleriaEngine     → Charakter-Persönlichkeit, Emotion-Extraktion
  - CoquiTTSEngine    → XTTS v2 Voice Cloning (pro Emotion ein Speaker-WAV)
  - LayeredSpriteRenderer → Component-basiertes Avatar-Rendering (PyGame)
  - WindowsActionController → PC-Steuerung (Tastatur, Maus, Fenster, Lautstärke)
  - RobotClient/Server → Tower ↔ RPi5 Kommunikation (REST)
  - LLMRouter         → entscheidet lokal (Ollama) oder remote (OpenRouter)
    - Unterwegs: Auto-Erkennung localhost → Mesh-IP → Fallback
    - Tower benötigt: OLLAMA_HOST=0.0.0.0 + Firewall nur Mesh-IP auf 11434
  - ActionsDB         → SQLite Aktions-Registry mit Self-Learning
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
- Pico 2W: MicroPython, zuständig für Motorsteuerung und Akku-Monitoring
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

### RPi 5 (I/O-Hub)
- Sensor-Integration: Kamera, IR, Temperatur
- Kommunikation Tower ↔ RPi 5: WLAN (noch zu definieren)
- Kommunikation RPi 5 ↔ Pico 2W: WLAN oder USB (noch zu definieren)
- Kein LLM

### Pico 2W (Motor-Controller)
- Echtzeit-Motorsteuerung (kein OS-Latenz Problem)
- Akku-Monitoring (2× 18650, 2S BMS)
- Autonomes Laden: erkennt niedrigen Akkustand → fährt selbst zur Ladestation
- Sicherheit: stoppt Motoren wenn RPi 5 nicht antwortet
- MicroPython

### Roboter-Chassis
- Mecanum 4WD, eigene Platine
- Adafruit DC Motor HAT (I²C) – aktuell auf RPi 5
- Platinen-Redesign in Phase 4: RPi 5 + Pico 2W Integration prüfen
- Akku: 2× 18650, 2S BMS mit Schutzschaltung und Ladefunktion
- Kamera: aktuell fest montiert (Mecanum-Rotation als Kompensation)
  → Pan/Tilt Servo Entscheidung offen – wird bei Platinen-Definition Phase 4 geklärt

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