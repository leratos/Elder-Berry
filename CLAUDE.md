# Elder-Berry – Claude Code Instructions

Sei bei deinen Antworten ehrlich, schöne nichts, sei kritisch und weise auf
Logiklücken und Fehler hin.

## KONTEXT
- Lies zu Beginn jedes Chats: C:\Dev\Elder-Berry\docs\journal.txt (letzte 80 Zeilen)
- journal.txt ist die einzige Quelle für den aktuellen Stand
- PROJECT_ROADMAP.md ist reine Planung – nur anfassen wenn Scope oder Phasen sich ändern
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
- Kernklassen:
  - SensorManager    → verwaltet alle Sensor-Inputs (RPi 5)
  - ActionController → verwaltet PC-Aktionen und Aktions-DB (Tower)
  - LLMRouter        → entscheidet lokal (Ollama) oder remote (OpenRouter)
  - CharacterEngine  → steuert V-Tuber Charakter / Emotionen
  - RobotController  → Kommunikation Tower → RPi 5 → Pico 2W
- Neue Komponenten immer als eigene Klasse, nie als Funktion in bestehende Datei kippen
- Abhängigkeiten zwischen Klassen explizit über Konstruktor übergeben (Dependency Injection)

## UMGEBUNG
- Tower (Windows, 16GB VRAM): C:\Dev\Elder-Berry\.venv, Python 3.12
  - LLM: phi4:14b – läuft vollständig in VRAM
- Laptop (Windows, 8GB VRAM): C:\Dev\Elder-Berry\.venv, Python 3.12
  - LLM: phi4:14b – läuft mit leichter RAM-Auslagerung, akzeptable Geschwindigkeit
- RPi 5 (Linux): /home/pi/elder-berry/, Python 3.12, absolute Linux-Pfade
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
- Elder-Berry ist eine virtuelle Assistentin mit eigenem Charakter (noch zu definieren)
- Persönlichkeit, Name der Figur, Stimme und visueller Stil werden in Phase 3 festgelegt
- Bis dahin: keine Annahmen über Charakter treffen, keine Namen oder Eigenschaften erfinden

## QUALITÄT
- Weise aktiv auf fehlende Tests, Sicherheitslücken oder technische Schulden hin
- Wenn etwas unklar ist: frag nach, statt Annahmen zu machen