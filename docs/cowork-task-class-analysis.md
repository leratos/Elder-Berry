# Cowork Task: Klassen-Analyse Elder-Berry

## Anweisung

Analysiere die folgenden 3 Python-Klassen aus dem Elder-Berry Projekt und erstelle
eine strukturierte Dokumentation mit Schwachstellenanalyse.

### Zu analysierende Dateien
1. `C:\Dev\Elder-Berry\src\elder_berry\comms\bridge.py` (MatrixBridge, ~1420 Zeilen)
2. `C:\Dev\Elder-Berry\src\elder_berry\core\assistant.py` (Assistant, ~576 Zeilen)
3. `C:\Dev\Elder-Berry\src\elder_berry\comms\remote_commands.py` (RemoteCommandHandler, ~425 Zeilen)

### Kontext
- Lies zuerst `C:\Dev\Elder-Berry\docs\architecture.md` fuer die Gesamtarchitektur
- Lies `C:\Dev\Elder-Berry\CLAUDE.md` fuer die Coding-Konventionen
- Das Projekt ist ein 3-Tier-System: Tower (LLM) / Laptop (Client) / RPi5 (Display)

### Pro Klasse dokumentieren
1. **Zweck**: Was macht die Klasse (1-2 Saetze)
2. **Oeffentliche API**: Alle public Methoden mit Signatur und Kurzbeschreibung
3. **Dependencies**: Welche anderen Klassen/Module werden injiziert oder importiert
4. **Kontrollfluss**: Wie laeuft ein typischer Request durch die Klasse
5. **Threading/Async**: Welche Threads/Event-Loops werden genutzt, wo sind Race Conditions moeglich

### Schwachstellen-Analyse pro Klasse
- Verstoesse gegen die Konventionen aus CLAUDE.md (z.B. 400-Zeilen-Limit, bare except, print statt logging)
- Zu grosse Methoden (>50 Zeilen) – welche, und was koennten sie aufteilen
- Fehlende Error-Handling-Stellen (externe Calls ohne Timeout/Retry)
- Code-Duplikation innerhalb oder zwischen den Klassen
- Zu enge Kopplung (direkte Abhaengigkeiten statt Interfaces)
- Tote oder unerreichbare Code-Pfade

### Ausgabe
Erstelle die Dokumentation als: `C:\Dev\Elder-Berry\docs\class-analysis.md`
Format: Markdown mit klaren Ueberschriften pro Klasse, Tabellen fuer die API,
und eine priorisierte Liste der Schwachstellen am Ende (hoch/mittel/niedrig).
