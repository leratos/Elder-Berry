# Elder-Berry — Umfassende Analyse & Phase 31+ Vorschläge

Erstellt am 27.03.2026 auf Basis von: Quellcode-Analyse aller Module, Dokumentation,
class-analysis.md, Testreport, Architektur-Review.

---

## 1. Aktueller Stand: Was ist fertig, was fehlt, wo gibt es Lücken?

### Fertig und funktional (Phasen 1–30)

Das Projekt hat einen beeindruckenden Reifegrad erreicht. 30 Phasen sind abgeschlossen,
das System läuft produktiv als persönlicher Assistent via Matrix.

**Kern-Infrastruktur (solide):**
- LLM-Pipeline: Anthropic Sonnet (primär) + Ollama (Fallback) + OpenRouter
- Voice Cloning: Coqui XTTS v2 mit 10 Emotionen, pro Emotion ein Speaker-WAV
- STT: Faster Whisper (GPU-beschleunigt, VAD-Filter)
- Matrix-Bridge: Async/Sync Bridge mit Command-Router, Audio, Chat-History
- SecretStore: Fernet-verschlüsselt, File-Permissions 0o600 — gut implementiert
- 3-Tier-System: Tower / Laptop / RPi5 mit REST-Kommunikation

**Personal-Assistant-Tools (vollständig):**
- Google Calendar (CRUD, natürliche Sprache, OAuth2)
- E-Mail (IMAP/SMTP, Suche, Anhänge, Antwort-Workflow mit Draft + Bestätigung)
- Kontaktbuch (FTS5, E-Mail-Integration)
- Aufgabenliste (Prioritäten, Kategorien, Briefing-Integration)
- Notizen/Wissensdatenbank (KV-Fakten + Freitext, FTS5)- Wetter (Open-Meteo, kostenlos)
- Timer & Erinnerungen (einmalig + wiederkehrend, neustart-sicher)
- Briefing (07:30, Wetter + Termine + Erinnerungen + Todos)
- Web-Suche (Brave Search + LLM-Aufbereitung)
- Dokument-Zusammenfassung (PDF + TXT)

**Remote-Steuerung (umfangreich):**
- 50+ Commands ohne LLM, 14 Command-Handler
- Computer Use (Anthropic Vision), ClaudeAgent
- Self-Update (Tower + RPi5), Git, Docker, WoL
- Kamera (RPi Camera Module 3 + Vision-Beschreibung)
- Drehteller (28BYJ-48 + Hall-Sensor Homing)

**Avatar & Charakter:**
- LayeredSpriteRenderer mit Blink, Lip-Sync, Breathing, Idle-Animationen
- SaleriaEngine mit EmotionTracker (Ringbuffer, Decay, Trend-Erkennung)
- YAML-konfigurierbar, Web-basierter Avatar-Editor
- Pepper's Ghost Display auf RPi5

### Was fehlt / offen

| Bereich | Status | Kommentar |
|---|---|---|
| Phase 4: Gehäuse-Hardware | 🔧 In Arbeit | Resin-Druck, Finish — rein mechanisch |
| Phase 9: Emotion Recognition Voice | 📭 Vision | Niedrige Priorität, unklar ob nötig |
| Home Assistant Integration | ⏸️ Zurückgestellt | Wegen Umzug — könnte Phase 31+ werden |
| Sensor-Integration (BME280, APDS-9960) | ❌ Offen | Seit Phase 2/10 offen, nie angefasst |
| OCR für gescannte PDFs | ❌ Offen | Tesseract wäre trivial, aber selten gebraucht |
| Emotion State Machine (persistent) | ❌ Offen | Seit Phase 5 „offen", EmotionTracker deckt Kurzzeitgedächtnis ab |
### Lücken zwischen Anspruch und Realität

1. **MatrixBridge ist der Flaschenhals**: 1589 Zeilen, 4x über dem eigenen 400-Zeilen-Limit.
   Jede neue Funktion vergrößert diese Datei weiter. Das ist die größte technische Schuld.

2. **start_saleria.py ist ein zweiter Flaschenhals**: 1050+ Zeilen Initialisierung. Eine Änderung
   an irgendeiner Komponente erfordert Verständnis dieses gesamten Startup-Flows.

3. **Test-Lücken bei kritischen Modulen**: LLM-Clients (anthropic_client, ollama_client,
   openrouter_client) haben keine Tests. Die Bridge selbst hat minimale Coverage.
   6 von 14 Command-Handlern haben keine eigenen Testdateien.

4. **Proaktivität nur oberflächlich**: CalendarWatcher und AlertMonitor sind die einzigen
   proaktiven Komponenten. Für einen Assistenten, der „denkt", fehlt viel.

---

## 2. Code-Qualität & Sicherheit

### Zeilenüberschreitungen (CLAUDE.md: max 400 Zeilen)

| Datei | Zeilen | Faktor |
|---|---|---|
| comms/bridge.py | 1589 | **4.0x** |
| scripts/start_saleria.py | 1050+ | **2.6x** |
| comms/commands/process_commands.py | 1142 | **2.9x** |
| comms/claude_agent.py | 815 | **2.0x** |
| comms/commands/weather_commands.py | 706 | **1.8x** |
| comms/matrix_channel.py | 702 | **1.8x** |
| comms/commands/mail_commands.py | 624 | **1.6x** |
| comms/commands/calendar_commands.py | 555 | **1.4x** |
| core/assistant.py | 605 | **1.5x** |
| comms/remote_commands.py | 558 | **1.4x** |
**10 Dateien über dem Limit** — davon 3 massiv (>2x). Das 400-Zeilen-Limit in CLAUDE.md
wird systematisch ignoriert. Das ist nicht tragisch für ein Solo-Projekt, aber es macht
jede zukünftige Phase schwieriger.

### Sicherheit

**Gut gelöst:**
- SecretStore: Fernet-Verschlüsselung, File-Permissions 0o600 — solide
- Prozess-Whitelist für start/kill Commands
- Computer Use: User muss jeden Klick explizit bestätigen
- ClaudeAgent: Pfad-Validierung (darf nicht außerhalb Projektordner schreiben)
- E-Mail: Draft → Bestätigung → Senden (kein versehentliches Senden)

**Schwachstellen:**

| Schweregrad | Problem | Datei | Detail |
|---|---|---|---|
| **Hoch** | Kein Input-Length-Limit | assistant.py | `user_input.strip()` prüft auf leer, aber nicht auf Länge. Ein 100KB-String geht direkt ans LLM → Token-Kosten-Explosion |
| **Hoch** | Path Traversal Risiko | claude_agent.py | `_validate_path()` nutzt `lstrip("/")` — bei Windows-Pfaden mit `..\\` unzureichend |
| **Mittel** | Secrets im Speicher | secret_store.py | Nach dem Laden liegen alle Secrets als Plaintext-Dict im RAM. Unvermeidbar, aber kein Cleanup bei Session-Ende |
| **Mittel** | Keine E-Mail-Validierung | email_sender.py | `to`-Parameter akzeptiert beliebige Strings ohne RFC 5322-Check |
| **Mittel** | KEYWORD_MAP global mutable | remote_commands.py | `__init__` überschreibt globale Variable — bei theoretisch mehreren Instanzen Konflikt |
| **Niedrig** | Kein Rate-Limiting | email_sender.py | Kein Schutz gegen versehentliches Massen-Senden |
| **Niedrig** | Thread-Safety PendingConfirmation | pending_confirmation.py | Verlässt sich auf GIL statt explizite Locks — funktioniert, ist aber fragil |
### Error-Handling

**Gut:** Durchgängig `logging.getLogger(__name__)`, kein `print()`, spezifische Exceptions
in den meisten Modulen, Graceful Degradation bei fehlenden Dependencies.

**Probleme:**
- `bridge.py`: Jeder `_handle_*`-Handler hat identisches try/except mit send_text-Fallback —
  Copy-Paste-Pattern statt Decorator/Wrapper
- `assistant.py`: `_robot_set_emotion()` fängt Exceptions und ignoriert sie still
- `task_chain.py`: Fängt generisches `Exception` in `_execute_step()` — maskiert Programmfehler
- Kein Timeout für `run_in_executor`-Calls in bridge.py — LLM- oder TTS-Calls können
  unbegrenzt blockieren

### Potenzielle Bugs

1. **Race Condition `_loop` in bridge.py**: `stop()` liest `self._loop` während `_run_loop()`
   es noch setzt. Zeitfenster nach Thread-Start, in dem `stop()` `_loop=None` sieht.
   → Braucht `threading.Event` für Loop-Ready-Signalisierung.

2. **`parse_command()` mutiert State**: `self._command_handler_map[command] = handler` wird
   während Pattern-Match geschrieben — eine Query-Methode verändert den internen State.

3. **`_is_agent_online` ohne Cache**: Kommentar sagt „cached pro Request", aber es gibt
   keinen Cache. Jeder Aufruf macht einen Netzwerk-Check.

4. **Kapselungsverletzungen**: `self._alert_monitor._send_alert = send_alert` — direkte
   Zuweisung auf private Attribute anderer Objekte (3x in bridge.py).

---

## 3. Nutzen-Bewertung: Was bringt im Alltag am meisten?

### Täglich genutzt (hoher ROI)

| Feature | Warum wertvoll |
|---|---|
| **Matrix-Chat mit Saleria** | Immer erreichbar via Handy, natürliche Sprache |
| **Briefing (07:30)** | Morgenroutine: Wetter + Termine + Todos auf einen Blick |
| **Kalender-Watcher** | Proaktive Erinnerungen vor Terminen — das Wichtigste für Pünktlichkeit |
| **Timer & Erinnerungen** | „Erinnere mich in 20 min: Wäsche" — trivial aber unverzichtbar |
| **Todos** | Schnelles Erfassen via Chat, Prioritäten im Briefing |
| **Screenshot + Status** | Quick-Check auf den Tower von unterwegs |
| **Notizen/Merk dir** | „WLAN Büro ist xyz" — sofort abrufbar |
### Gelegentlich genutzt (mittlerer ROI)

| Feature | Warum |
|---|---|
| **E-Mail-Abruf + Zusammenfassung** | Praktisch, aber die meisten checken Mail direkt |
| **Web-Suche** | Nützlich, aber Browser ist schneller für komplexe Suchen |
| **Self-Update** | Enabler für alle anderen Features, aber nur bei Releases |
| **Computer Use** | Cool, aber 4-5 Cent pro Klick und langsam |
| **Sprachnachrichten** | Nett wenn Hände voll, aber selten der schnellste Weg |

### Wahrscheinlich selten/nie genutzt

| Feature | Warum |
|---|---|
| **Drehteller-Steuerung** | Gimmick — wie oft dreht man den Charakter manuell? |
| **Berry-Gym Integration** | Sehr nischig, nur relevant wenn Gym-Berry aktiv genutzt wird |
| **Docker-Commands** | Nur für Entwickler-Workflow, nicht für Alltags-Assistenz |
| **Git-Commands via Matrix** | Terminal ist bequemer für Git |
| **Emotion Recognition Voice (geplant)** | Technisch interessant, aber LLM-Textanalyse reicht |
| **Sensor-Integration BME280/APDS-9960** | Temperatur/Gestik — nett, aber kein Alltagsnutzen |
| **WoL** | Einmal eingerichtet, selten gebraucht (Tower läuft eh immer) |

### Unterschätztes Feature

**Chat-History + Rolling Summary**: Das ist der stille Held. Ohne das wäre jede Interaktion
kontextlos. Die Kombination aus Sliding Window + LLM-Summary ist elegant und unterschätzt.

---

## 4. Technische Schulden

### Kritisch (jetzt angehen, bevor es schlimmer wird)
**1. bridge.py aufteilen (1589 → 4 Dateien)**
Das ist die #1 technische Schuld. Jede neue Phase berührt diese Datei. Vorschlag:
- `MatrixBridge` (Start/Stop/Loop, ~200 Zeilen)
- `MessageRouter` (Routing-Logik, ~300 Zeilen)
- `AudioPipeline` (Audio-Handling, ~200 Zeilen)
- `SchedulerManager` → existiert bereits als `scheduler_manager.py`, aber bridge.py
  enthält immer noch Scheduler-Logik

**2. start_saleria.py refactoren (1050+ Zeilen)**
Startup ist eine 400-Zeilen-Funktion mit 30+ Komponenten-Initialisierungen. Vorschlag:
- `ComponentFactory` oder `ServiceContainer` Pattern
- Dependency-Gruppen: `create_core()`, `create_comms()`, `create_tools()`

**3. process_commands.py aufteilen (1142 Zeilen)**
Enthält Git, Docker, WoL, Update, Kill/Start — das sind 5 verschiedene Domänen.

### Hoch (nächste 3 Monate)

**4. LLM-Response-Parsing vereinheitlichen**
`assistant.py`, `task_chain.py` und `claude_agent.py` parsen JSON-Antworten
mit unterschiedlichen Fallback-Strategien. → Eigene `ResponseParser`-Klasse.

**5. Fehlende Tests für LLM-Clients**
`anthropic_client.py`, `ollama_client.py`, `openrouter_client.py` — null Tests.
Bei einem Projekt, das zu 80% auf LLM-Calls basiert, ist das ein Risiko.

**6. Fehlende Tests für 6 Command-Handler**
advanced_commands, calendar_commands, file_commands, mail_commands,
process_commands, system_commands — nur über test_remote_commands.py indirekt getestet.
### Mittel (irgendwann)

**7. Konstruktor-Parameter reduzieren**
`RemoteCommandHandler` hat 23+ Parameter. `Assistant` hat 11.
→ Config-Dataclass oder Builder-Pattern.

**8. HELP_TEXT automatisch generieren**
~150 Zeilen manuell gepflegter Text, der bei jedem neuen Command vergessen werden kann.
→ Aus `handler.command_descriptions` + `handler.patterns` generieren.

**9. Dependency-Versionen pinnen**
`pyproject.toml` nutzt nur `>=` Constraints. Bei einem Hobby-Projekt akzeptabel,
aber ein `pip freeze` in einer Lock-Datei würde reproduzierbare Builds garantieren.

---

## 5. Ungenutztes Potential

### Schnelle Wins (wenig Aufwand, viel Nutzen)

**1. Morgenbriefing personalisieren**
Das Briefing ist statisch (Wetter + Termine + Erinnerungen + Todos). Mit wenig Aufwand:
- Pendler-Info (Bahnstörungen, Stau) via API
- „Heute vor einem Jahr"-Erinnerungen aus NoteStore
- Geburtstage aus ContactStore

**2. Quick-Replies für häufige Aktionen**
„Bin in 10 min da" → Timer 10 min + Nachricht an letzten Kontakt.
„Unterwegs" → Audio auf matrix_only, Status-Update.
Vorgefertigte Makros statt Multi-Step.

**3. Kontext-bewusste Antworten**
Wenn eine Frage NoteStore, Kalender UND Kontakte betrifft, werden die Quellen
einzeln abgefragt. Eine „Smart Query"-Schicht könnte automatisch relevante Quellen
identifizieren und dem LLM als Kontext mitgeben — ähnlich wie ContextEnricher,
aber für alle Anfragen.
**4. Clipboard-Integration erweitern**
Clipboard lesen/schreiben existiert. Fehlt: „Clip das" → letzten LLM-Output
in Clipboard. Oder: Links/Telefonnummern aus der letzten Nachricht extrahieren.

**5. Reminder-Snooze**
Erinnerung kommt → „snooze 10 min" oder „später" (verschiebt um 1h).
Trivial mit bestehendem ReminderStore.

### Mittlerer Aufwand, hoher Nutzen

**6. Saleria als Lern-Assistentin**
Karteikarten-System: „Lerne: Python GIL = Global Interpreter Lock" →
Spaced Repetition, Abfrage via Matrix. Nutzt bestehenden NoteStore als Backend.

**7. Zusammenfassungen von Webseiten**
„Fasse https://... zusammen" → Brave Search holt Text, LLM fasst zusammen.
Fast trivial mit bestehendem Code.

**8. Automatische Einkaufsliste**
Eigene Kategorie in TodoStore. „Kaufen: Milch" → spezielle Ansicht,
teilbar als Nachricht.

---

## 6. Vorgeschlagene Phasen 31+

### Phase 31 — Bridge Refactoring (Technische Schulden)

**Beschreibung:** MatrixBridge (1589 Zeilen) in 4 Module aufteilen: MatrixBridge
(Lifecycle), MessageRouter (Routing), AudioPipeline (Audio), plus die existierende
SchedulerManager-Integration vervollständigen. start_saleria.py in ServiceContainer
refactoren.
**Aufwand:** 2–3 Tage
**Begründung:** Jede zukünftige Phase wird einfacher. Die Bridge ist das Nadelöhr —
ohne dieses Refactoring wird jede neue Funktion riskanter. Außerdem werden dabei
die Kapselungsverletzungen (direkte Zuweisung auf private Attribute) und die
fehlenden Timeouts für run_in_executor behoben.

**Priorität:** ⭐⭐⭐⭐⭐ (Muss zuerst passieren)

---

### Phase 32 — Test-Offensive (Qualitätssicherung)

**Beschreibung:** Tests für die 6 ungetesteten Command-Handler schreiben
(advanced, calendar, file, mail, process, system), plus Tests für
anthropic_client, ollama_client, bridge.py (nach Refactoring). Ziel: 90%+ der
Module mit eigener Testdatei.

**Aufwand:** 3–4 Tage
**Begründung:** 1539 Tests klingt viel, aber die kritischsten Pfade (LLM-Clients,
Command-Handler, Bridge) haben minimale Coverage. Ohne Tests ist jedes Refactoring
ein Glücksspiel. Muss direkt nach Phase 31 kommen.

**Priorität:** ⭐⭐⭐⭐⭐ (Absicherung für alles Weitere)

---

### Phase 33 — Smart Context Layer (Nutzen)

**Beschreibung:** Automatische Kontext-Anreicherung für alle LLM-Anfragen. Wenn der
User fragt „Was muss ich heute noch machen?", werden automatisch Todos, Kalender,
offene Erinnerungen und relevante Notizen als Kontext injiziert. Erweitert den
bestehenden ContextEnricher von CalendarWatcher-only auf alle Anfragen.
**Aufwand:** 2–3 Tage
**Begründung:** Das größte ungenutzte Potential. Alle Datenquellen existieren bereits
(Calendar, Todos, Notes, Contacts, Reminders, Weather). Aktuell nutzt das LLM nur
Memory (RAG) + Chat-History als Kontext. Die strukturierten Stores werden nur über
explizite Commands abgefragt. Ein Smart Context Layer würde Saleria spürbar
intelligenter machen, ohne neue Features zu bauen.

**Priorität:** ⭐⭐⭐⭐ (Höchster Nutzen bei geringem Aufwand)

---

### Phase 34 — Briefing 2.0 (Nutzen)

**Beschreibung:** Personalisiertes Morgenbriefing mit:
- Geburtstage aus ContactStore (Notizen-Feld parsen oder eigenes Datum-Feld)
- Pendler-Info (Deutsche Bahn API oder Google Maps Directions)
- Offene E-Mails (Anzahl ungelesener Mails als Einzeiler)
- „Vor einem Jahr"-Notizen aus NoteStore
- Wochenend-Variante (entspannter Ton, andere Prioritäten)

**Aufwand:** 2 Tage
**Begründung:** Das Briefing ist das Feature mit dem höchsten täglichen Touchpoint.
Jede Verbesserung hier hat sofortige Auswirkung auf den Alltag. Die Datenquellen
existieren größtenteils bereits.

**Priorität:** ⭐⭐⭐⭐ (Täglicher Mehrwert)

---

### Phase 35 — Web-Zusammenfassung (Nutzen)

**Beschreibung:** „Fasse https://... zusammen" als neuer Command. Nutzt httpx
(bereits vorhanden) zum Abrufen von Webseiten, extrahiert Text (readability/trafilatura),
fasst via LLM zusammen. Optional: Brave Search Snippet als Fallback wenn URL
nicht abrufbar.
**Aufwand:** 1–2 Tage
**Begründung:** Natürliche Erweiterung von DocumentReader (PDF/TXT → Web). Geringer
Aufwand weil die LLM-Zusammenfassungs-Pipeline bereits steht. Praktisch für
Newsletter, Artikel, Dokumentation.

**Priorität:** ⭐⭐⭐⭐ (Wenig Aufwand, sofort nützlich)

---

### Phase 36 — Home Assistant Integration (Nutzen)

**Beschreibung:** Smart-Home-Steuerung via Home Assistant REST API. Bereits in
Phase 8 konzipiert und zurückgestellt (Umzug). Umfasst: Licht an/aus, Heizung,
Szenen, Harmony Hub über HA. Entity-Whitelist für Sicherheit.

**Aufwand:** 2–3 Tage
**Begründung:** Wurde explizit zurückgestellt, nicht gestrichen. Am neuen Standort
mit frischem HA-Setup ist das der logische nächste Schritt für physische
Schreibtisch-Präsenz. Saleria wird vom Chat-Bot zum tatsächlichen
Raum-Kontrolleur.

**Priorität:** ⭐⭐⭐ (Abhängig vom Umzugsstatus)

---

### Phase 37 — Reminder-Snooze + Quick-Actions (Nutzen)

**Beschreibung:** Snooze-Funktion für Erinnerungen („snooze 10", „später" = +1h).
Plus: Quick-Action-Makros als konfigurierbare Shortcuts. Beispiel:
„unterwegs" → Audio auf matrix_only + „Bin unterwegs" an letzten Chat-Partner.

**Aufwand:** 1–2 Tage
**Begründung:** Kleine Quality-of-Life-Features, die den Alltag spürbar angenehmer
machen. Snooze ist das meistgewünschte Feature bei jedem Erinnerungssystem.
Quick-Actions reduzieren Tipp-Aufwand für Routine-Abläufe.

**Priorität:** ⭐⭐⭐ (Klein aber fein)
---

### Phase 38 — Input-Validierung & Security Hardening

**Beschreibung:** Systematische Absicherung aller Eingabepfade:
- Input-Length-Limit (z.B. 10.000 Zeichen) in assistant.py und bridge.py
- E-Mail-Validierung (RFC 5322) in email_sender.py
- Path-Traversal-Fix in claude_agent.py (pathlib.is_relative_to)
- Rate-Limiting für E-Mail-Versand
- Timeouts für alle run_in_executor Calls (120s LLM, 60s TTS)
- Threading.Lock für PendingConfirmationStore

**Aufwand:** 1–2 Tage
**Begründung:** Keine der Schwachstellen ist akut kritisch (Single-User-System),
aber als Hygiene-Maßnahme wichtig. Besonders das Input-Length-Limit schützt
vor versehentlichen Token-Kosten-Explosionen.

**Priorität:** ⭐⭐⭐ (Hygiene, kann parallel zu anderen Phasen)

---

### Phase 39 — Spaced Repetition / Lern-Modus

**Beschreibung:** Karteikarten-System auf Basis von NoteStore. „Lerne: X = Y" speichert
Lernkarte. Saleria fragt in konfigurierbaren Intervallen ab (SM-2 Algorithmus).
Statistik über Lernfortschritt.

**Aufwand:** 3–4 Tage
**Begründung:** Nutzt bestehende Infrastruktur (NoteStore + ReminderScheduler).
Originell und nützlich — kein anderer persönlicher Assistent bietet das.
Differenzierungs-Feature.

**Priorität:** ⭐⭐ (Nice-to-have, aber einzigartig)
---

### Phase 40 — Dashboard 2.0 (Übersicht)

**Beschreibung:** Erweiterung des Web-Dashboards (Port 8090) zu einer echten
Übersichtsseite: Status aller Komponenten, letzte Nachrichten, Todos,
nächste Termine, Erinnerungen, System-Health. Kein Framework — weiterhin
minimales HTML + HTMX oder Alpine.js für Reaktivität.

**Aufwand:** 3–4 Tage
**Begründung:** Aktuell gibt es nur Audio-Toggle und Avatar-Editor. Ein Dashboard
wäre die einzige Stelle, an der man den gesamten System-Status auf einen Blick sieht.
Nützlich für Debugging und Daily-Check.

**Priorität:** ⭐⭐ (Komfort, nicht kritisch)

---

## Zusammenfassung: Empfohlene Reihenfolge

| Phase | Name | Aufwand | Typ |
|---|---|---|---|
| **31** | Bridge Refactoring | 2–3 Tage | Technische Schulden |
| **32** | Test-Offensive | 3–4 Tage | Qualitätssicherung |
| **33** | Smart Context Layer | 2–3 Tage | Feature (hoher Nutzen) |
| **34** | Briefing 2.0 | 2 Tage | Feature (täglicher Nutzen) |
| **35** | Web-Zusammenfassung | 1–2 Tage | Feature (Quick Win) |
| **36** | Home Assistant | 2–3 Tage | Feature (abhängig von Umzug) |
| **37** | Snooze + Quick-Actions | 1–2 Tage | Quality of Life |
| **38** | Security Hardening | 1–2 Tage | Sicherheit |
| **39** | Spaced Repetition | 3–4 Tage | Feature (Differenzierung) |
| **40** | Dashboard 2.0 | 3–4 Tage | Komfort |

**Gesamtaufwand Phase 31–40:** ~20–30 Tage

**Kernaussage:** Die Basis ist hervorragend. 30 Phasen in ~2 Wochen Entwicklungszeit
sind beeindruckend. Die größten Hebel jetzt: (1) Technische Schulden in bridge.py
abbauen, (2) Test-Coverage erhöhen, (3) den Smart Context Layer bauen — das macht
Saleria spürbar klüger ohne neue Features zu erfinden.

---

*Analyse erstellt mit Claude Opus 4.6 auf Basis von: 86+ Source-Dateien,
65 Test-Dateien (1539 Tests), 5 Dokumentationsdateien, class-analysis.md.*