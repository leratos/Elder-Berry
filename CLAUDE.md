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
- Wenn du selbst merkst dass Antworten unzuverlässiger werden: sag es aktiv

## GITHUB
- Erstelle zu Beginn jeder Phase einen neuen Branch: feature/phase-X-Y-kurzbeschreibung
- Committe am Ende jeder Phase alle Änderungen
- Keinen Pull-Request erstellen – das macht der Nutzer selbst
- Branch-Namen immer lowercase, Leerzeichen durch Bindestriche

## CODE-GENERIERUNG
- Neue Code-Dateien (Python, JS): Chunks von maximal 400 Zeilen
- Templates (HTML, Jinja2 etc.): nie inline – immer als separate Datei, in Chunks
- Bei langen Dateien: Zwischenstand in journal.txt sichern bevor nächster Chunk beginnt
- Lies bestehende Dateien VOR dem Schreiben – immer
- Verwende immer absolute Pfade (C:\Dev\Elder-Berry\...)

## UMGEBUNG
- Tower (Windows): C:\Dev\Elder-Berry\.venv, Python 3.12, absolute Windows-Pfade
- RPi5 (Linux): /home/pi/elder-berry/, absolute Linux-Pfade
- Verwende pathlib statt hartcodierte Slashes wo plattformübergreifend
- Weise aktiv darauf hin wenn Code plattformspezifisch ist
- Falls .venv nicht vorhanden: erstelle es mit py -3.12 -m venv .venv
- Führe nach Code-Änderungen die betroffenen Tests aus und berichte das Ergebnis

## HARDWARE
- Tower: RTX 4070 Ti Super (16GB VRAM), Ollama läuft lokal (bevorzugt 14B Modell)
- RPi5: I/O-Controller (Sensoren, Motoren) – kein LLM
- Kommunikation Tower ↔ RPi5: noch zu definieren (WLAN oder USB)
- Roboter: Mecanum-Antrieb, 2x 18650 Akku, eigene Platine

## LLM-STRATEGIE
- Lokal (Ollama): schnelle Aktionen, Sensor-Auswertung, PC-Steuerung, Dauerbetrieb
- OpenRouter: Multimodal (Kamera-Input), komplexes Reasoning, Fallback
- Modell-Wechsel nur mit expliziter Begründung vorschlagen

## QUALITÄT
- Weise aktiv auf fehlende Tests, Sicherheitslücken oder technische Schulden hin
- Wenn etwas unklar ist: frag nach, statt Annahmen zu machen
