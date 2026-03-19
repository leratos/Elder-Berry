# Elder-Berry – Projektanalyse

> Analyse aktualisiert: März 2026 (Stand nach Phase 14 + Konzeptphasen 15–17)
> Bereiche: Nutzen · Stand · Sicherheit · Funktionsumfang · Erweiterungsvorschläge

---

## Kontext: Kommunikationskanal

Der primäre Kommunikationspunkt ist ein **selbst gehosteter Matrix-Server**
(`matrix.last-strawberry.com`, Synapse). Besonderheiten:

- **Keine öffentliche Registrierung**: nur zwei Accounts – `@saleria` (Bot) und der Nutzer
- **Federation deaktiviert**: kein Datenabfluss nach außen
- **Kein E2EE** (Phase-6-Design-Entscheidung): der Server-Admin hat Zugang zu Klartext,
  was bei einem privaten Server kein Problem darstellt
- **Element** als Client auf Handy/Desktop: native Matrix-App, kein Custom-Client nötig

Diese Einschränkung (privater Ein-Nutzer-Server) macht das System deutlich sicherer
als öffentliche Chat-Dienste – gleichzeitig ist das der Angriffspunkt #1 (wer den
Matrix-Server kompromittiert, kann alle Commands absetzen).

---

## 1. Nutzen – Bewertung: 8 / 10

### Was das Projekt leistet

Elder-Berry ist ein modularer KI-Desk-Companion rund um die Figur **Saleria Berry**,
der lokale LLM-Verarbeitung (Ollama phi4:14b), XTTS v2 Voice Cloning, ein Pepper's Ghost
Hologramm und vollständige Fernsteuerung via Matrix kombiniert.

**Stärken:**

| Feature | Nutzen |
|---|---|
| Sprachausgabe mit 10 Emotionen (XTTS v2) | Sehr hoher Differenzierungsfaktor gegenüber einfachen TTS-Lösungen |
| Lokalem LLM + Cloud-Fallback (LLMRouter) | Datenschutz + Verfügbarkeit gleichzeitig gelöst |
| Matrix-Fernsteuerung | Praxisnah: Steuerung von unterwegs via Smartphone |
| PC-Steuerung (Maus, Tastatur, Lautstärke) | Echter Alltagsnutzen für Heimautomatisierung |
| ClaudeAgent (Datei lesen/schreiben, Tests laufen) | Starkes Feature für Entwickler-Workflow |
| Systemüberwachung (CPU/RAM/GPU) | Direkter Nützlichkeitswert |
| Pepper's Ghost Hologramm im Baumstamm-Gehäuse | Einzigartiger Wow-Faktor |

**Schwächen / Lücken:**

- Kein Multimodal-Input (Kamera → GPT-4o Vision), geplant in Phase 9
- Keine Emotion-State-Machine (geplant Phase 5), Emotionen sind rein textbasiert
- Kein Wake-Word / Always-Listening Modus – nur Text-Input via Matrix
- Kein expliziter Notizspeicher (geplant Phase 16)
- Keine proaktiven Kalender-Erinnerungen (geplant Phase 17)
- Kein Self-Update (geplant Phase 15) → Updates müssen manuell via SSH eingespielt werden

**Fazit:** Für ein persönliches Hobbyprojekt liegt der Nutzen weit über dem Durchschnitt.
Die Kombination aus Hologramm, Voice Cloning, LLM und Remote-Control ist funktional und
differenziert genug, um echten Alltagseinsatz zu rechtfertigen.

---

## 2. Stand – Bewertung: 8.5 / 10

| Phase | Name | Status |
|---|---|---|
| 1 | Software Basic (PC-Steuerung, TTS, LLM, Assistant) | ✅ Abgeschlossen |
| 2 | RPi5-Anbindung | ✅ Software abgeschlossen, Hardware offen |
| 3 | Charakter / V-Tuber (Saleria, XTTS, Avatar) | ✅ Abgeschlossen |
| 4 | Gehäuse + Drehteller | 🔧 In Arbeit (Hardware) |
| 5 | Software Advance (Emotion State Machine, Multimodal) | ⏳ Größtenteils abgeschlossen |
| 6 | Matrix-Integration | ✅ Abgeschlossen |
| 7 | Remote Features (ClaudeAgent, Commands) | ✅ Abgeschlossen |
| 8 | Personal Assistant Tools (Kalender, Mail, Wetter, Gym) | ✅ Größtenteils abgeschlossen |
| 9 | Multimodal + Autonomie | 🔭 Vision |
| 10 | RPi5 Avatar-Display | ✅ Teilweise abgeschlossen |
| 11 | Dokument-Zusammenfassung | ✅ Abgeschlossen |
| 12 | Audio-Routing + Web-Interface | ✅ Abgeschlossen |
| 13 | Computer Use (Anthropic Vision + PC-Steuerung) | ✅ Abgeschlossen |
| 14 | Web-Suche (Brave Search + LLM-Aufbereitung) | ✅ Abgeschlossen |
| 15 | Self-Update | 📋 Geplant (Konzept vorhanden) |
| 16 | Notizen & Wissensdatenbank | 📋 Geplant (Konzept vorhanden) |
| 17 | Kalender-Watcher (Proaktive Erinnerungen) | 📋 Geplant (Konzept vorhanden) |

- **1173+ Tests** (nach Phase 14 Refactoring), 53 skipped
- **Gute Dokumentation**: README, PROJECT_ROADMAP, Konzeptdokumente, journal.txt
- **Fehlende Hardware**: RPi5 Sensoren, Gehäuse-Finish, Drehteller
- **Phase 15–17**: Konzepte fertig, Implementierung steht noch aus

**Fazit:** Software-seitig ist das Projekt auf hohem Stand (14 von 17 geplanten Phasen).
Der größte offene Block ist Hardware. Phasen 15–17 sind klar spezifiziert und kurzfristig umsetzbar.

---

## 3. Sicherheit – Bewertung: 6.5 / 10 (nach bisherigen Fixes)

Dieses Kapitel listet gefundene Sicherheitsprobleme **und deren Status**.

### 3.1 Behoben durch diesen PR

#### 🔴 Kritisch: Path-Traversal in `ClaudeAgent._validate_path` (behoben)

```python
# VORHER – String-Präfix-Vergleich kann umgangen werden:
# Projekt-Root: /home/user/proj
# Angreifer: path = "../proj-evil/../../etc/passwd"
# resolved = /home/user/proj-evil/../../../etc/passwd → /etc/passwd
# str("/etc/passwd").startswith("/home/user/proj") → False ✓ (zufällig korrekt)
# Aber: /home/user/project resolves, wenn Root = /home/user/proj → /home/user/project startswith → True ✗
if not str(resolved).startswith(str(self._project_root)):

# NACHHER – semantisch korrekte Python-API (Python 3.9+):
if not resolved.is_relative_to(self._project_root):
```

Der String-Präfix-Check ist fehleranfällig: Ein `project_root` von
`/home/user/proj` würde `/home/user/proj-evil/datei` fälschlicherweise als
innerhalb des Projekts akzeptieren. `Path.is_relative_to()` prüft korrekt auf
Verzeichnis-Grenzen.

#### 🔴 Kritisch: `send_file` ohne Pfad-Einschränkung (behoben)

Der `schick mir <pfad>`-Command akzeptierte **jeden absoluten Pfad** auf dem System –
also auch `~/.elder-berry/secret.key`, `~/.ssh/id_rsa`, Passwort-Dateien etc.

**Fix:** Neuer Parameter `send_file_allowed_roots` in `RemoteCommandHandler`. Standard
sind `~/Documents`, `~/Downloads`, `~/Desktop`, `~/Pictures`. Zugriff außerhalb dieser
Verzeichnisse wird verweigert. Konfigurierbar für andere Anwendungsfälle.

#### 🟠 Hoch: `cmd` / `terminal` in `START_WHITELIST` (behoben)

Die Start-Whitelist enthielt `cmd` → `cmd.exe` und `terminal` → `wt` (Windows Terminal).
Wer über Matrix `starte cmd` schickt, bekommt eine Shell – je nach Desktop-Konfiguration
auch ohne sichtbare Interaktion. Beide Einträge wurden **entfernt**.

#### 🟡 Mittel: Keine Sender-Authentifizierung in `MatrixBridge` (behoben)

Jede Person in einem erlaubten Matrix-Raum konnte beliebige Commands ausführen
(Screenshot, Prozesse starten, Dateien senden, ClaudeAgent). Ein neuer Parameter
`allowed_senders: frozenset[str]` in `MatrixBridge` filtert Nachrichten nach
bekannten Matrix-User-IDs. Wenn nicht gesetzt, werden alle Sender akzeptiert
(Rückwärtskompatibilität).

### 3.2 Bekannte offene Punkte

| Schweregrad | Problem | Empfehlung |
|---|---|---|
| 🟡 Mittel | `git pull` in `GIT_WHITELIST`: kann schädlichen Code ziehen | Phase-15-Update-Command (`--ff-only`) ist sicherer; direktes `git pull` aus Whitelist entfernen oder separaten Flag erfordern |
| 🟡 Mittel | `download <url>` lädt von beliebigen URLs herunter | URL-Whitelist oder Domain-Filter |
| 🟡 Mittel | `SecretStore` Key-Datei chmod 600 greift auf Windows nicht | Windows DACL setzen (optional) |
| 🟡 Mittel | Kein Rate-Limiting für ClaudeAgent → unkontrollierte API-Kosten | Request-Throttling (z.B. 10 req/min) |
| 🟡 Mittel | `docker restart <name>` ohne Container-Whitelist | Container-Namen-Whitelist analog zu Docker-Commands |
| 🟢 Niedrig | Matrix ohne E2EE (Phase 1 Design-Entscheidung) | E2EE für Phase 5 einplanen – auf privatem Server niedriger Priorität |
| 🟢 Niedrig | Fehlende Security-Logging von abgelehnten Nachrichten | Zentrales Security-Log |
| 🟢 Niedrig | `clip: <beliebiger Text>` ohne Längenbegrenzung | Maximallänge (z.B. 10 000 Zeichen) und Whitespace-Normalisierung |
| 🟢 Niedrig | Matrix-Server selbst ist Angriffspunkt #1 | Synapse regelmäßig aktualisieren, SSH-Key-Only auf Server |

**Matrix-spezifische Sicherheit:**
- `allowed_senders` in `MatrixBridge` sollte **immer** mit der eigenen User-ID befüllt sein
- Ohne diesen Schritt kann jeder in einem erlaubten Raum Commands absetzen
- Bei einem privaten Server mit nur zwei Konten ist das Risiko gering, aber die Härtung kostet nichts

---

## 4. Funktionsumfang – Bewertung: 8.5 / 10

### Vorhandene Kernfunktionen (via Matrix steuerbar)

| Kategorie | Commands | Status |
|---|---|---|
| System | status, screenshot, restart | ✅ |
| Medien | pause/play, volume, skip | ✅ |
| Clipboard | clipboard, clip: | ✅ |
| Dateien | schick mir, download | ✅ |
| Kalender | termine, termin erstellen/löschen | ✅ |
| E-Mail | mails, mail suche, anhang | ✅ |
| Wetter | wetter, wetter morgen | ✅ |
| Timer/Erinnerungen | timer 20 min, erinnere mich | ✅ |
| Briefing | briefing, guten morgen | ✅ |
| Fitness | training, gym | ✅ |
| Dokumente | zusammenfassung <pdf> | ✅ |
| Web-Suche | suche <query> | ✅ |
| Computer Use | klick auf <element> | ✅ |
| Git/Docker | git status, docker ps | ✅ |
| ClaudeAgent | Claude "..." | ✅ |
| Proaktive Alerts | Disk, Crash-Monitor | ✅ |

### Geplante Erweiterungen (Phase 15–17)

| Phase | Feature | Status | Wert |
|---|---|---|---|
| 15 | Self-Update (update dich) | 📋 Konzept fertig | Hoch – Deployment-Vereinfachung |
| 16 | Notizen & Wissensdatenbank | 📋 Konzept fertig | Hoch – persistentes Gedächtnis |
| 17 | Proaktive Kalender-Erinnerungen | 📋 Konzept fertig | Mittel – Komfort |

---

## 5. Umsetzung / Codequalität – Bewertung: 8 / 10

### Was gut ist

- **Konsequentes OOP**: Jede Komponente als eigene Klasse, ABC + Implementierung,
  Dependency Injection überall – sauber und testbar.
- **Graceful Degradation**: Fehlende optionale Bibliotheken führen zu Fehlertext, nie
  zu Crashes. (`try: import pygame; except ImportError: ...`)
- **Testabdeckung**: 520+ Tests in 25 Dateien decken alle Kernmodule ab.
- **Dokumentation**: Jede Klasse und Methode hat einen Docstring; `docs/` ist
  aktuell gehalten.
- **`pyproject.toml` mit optionalen Groups**: `[windows]`, `[tts-neural]`, `[avatar]`
  etc. erlauben selektive Installation.
- **`SecretStore`**: Fernet-Verschlüsselung für Credentials ist eine deutlich bessere
  Lösung als `.env`-Dateien.

### Was verbessert werden sollte

#### Dateigröße (teilweise behoben durch Phase-7-Refactoring)

| Datei | Zeilen | Status |
|---|---|---|
| `remote_commands.py` | ~310 | ✅ Refactored zu Orchestrator (Phase 7) |
| `claude_agent.py` | 815 | ⚠️ `_exec_*`-Handler könnten in eigene Klasse ausgelagert werden |

#### Async-Konsistenz in `ActionsDB`

`ActionsDB` nutzt synchrones `sqlite3` direkt in async-fähigen Kontexten. Bei hohem
Durchsatz blockiert das den Event-Loop.
Empfehlung: `aiosqlite` oder `loop.run_in_executor()`.

#### Fehlende Input-Sanitierung bei `clip_write`

`clip: <beliebiger Text>` schreibt direkt in die Windows-Zwischenablage ohne Längenbegrenzung.
Längenbegrenzung und Whitespace-Normalisierung würden das Risiko reduzieren.

#### `LLMRouter._select_client()` doppelter `is_available()` Aufruf

`is_available()` macht HTTP-Checks und wird zweimal aufgerufen. Kurzzeit-Caching
(30 Sekunden) würde die Latenz reduzieren.

---

## 6. Erweiterungsvorschläge

### Kurzfristig (nächste 3 Phasen – Konzepte vorhanden)

1. **Phase 15: Self-Update** – `update dich` startet git pull + pip install + restart.
   Enabler für alle weiteren Phasen: Code auf Laptop entwickeln, per Matrix live schalten.
   *Priorität: Hoch. Konzept: `docs/concepts/phase-15-self-update.md`*

2. **Phase 16: Notizen & Wissensdatenbank** – Expliziter KV-Fakten-Speicher und Freitext-Notizen,
   getrennt vom unscharfen ChromaDB-RAG. "merk dir: WLAN Büro ist xyz123" → abrufbar per "was ist WLAN Büro?"
   *Priorität: Hoch. Konzept: `docs/concepts/phase-16-notizen-wissensdatenbank.md`*

3. **Phase 17: Kalender-Watcher** – Daemon-Thread prüft alle 5 Min den Kalender und erinnert
   proaktiv 15 + 5 Minuten vor Terminen. Kein User-Eingriff nötig.
   *Priorität: Mittel. Konzept: `docs/concepts/phase-17-kalender-watcher.md`*

### Mittelfristig (nach Phase 17)

4. **Rate-Limiting für ClaudeAgent** – Token-Bucket (z.B. 10 Anfragen/Minute) verhindert
   unkontrollierte API-Kosten bei Bugs oder Angriffen.

5. **Docker-Container-Whitelist** – `docker restart <name>` nur für vordefinierte Container
   (z.B. `synapse`, `postgres`), um unbeabsichtigtes Restarten kritischer Container zu verhindern.

6. **`allowed_senders` in Startskript setzen** – Matrix-User-ID des Nutzers in
   `MatrixBridge(allowed_senders=frozenset(["@nutzer:domain.com"]))` eintragen.
   Ohne das ist die Absender-Authentifizierung wirkungslos.

7. **Security-Logging** – Abgelehnte Nachrichten (`allowed_senders`-Filter, Whitelist-Verletzungen)
   in eine separate Log-Datei oder ein Matrix-Admin-Raum schreiben.

### Langfristig (Phase 9+)

8. **E2EE für Matrix** – Auf einem privaten Server niedrige Priorität, aber für ein rundes
   Sicherheitsbild wünschenswert. Umsetzung: matrix-nio E2E-Extension.

9. **Emotion-State-Machine** – Persistente Stimmung über Konversation hinweg statt nur
   textbasierter Emotion-Extraktion.

10. **Kamera-Integration** – RPi Camera Module 3 → Vision-Modell → Saleria sieht was vor ihr ist.

---

## Gesamtbewertung (aktualisiert)

| Bereich | Note | Begründung |
|---|---|---|
| **Nutzen** | **8 / 10** | Klarer Alltagsnutzen; Phase 15–17 fehlen noch |
| **Stand** | **8.5 / 10** | 14 von 17 Phasen erledigt; Konzepte für Rest vorhanden |
| **Sicherheit** | **6.5 / 10** | Kernprobleme behoben; Rate-Limiting und Container-Whitelist offen |
| **Codequalität** | **8 / 10** | Saubere Architektur nach Refactoring; ActionsDB-Async noch offen |
| **Gesamt** | **7.75 / 10** | Deutlich über Durchschnitt für ein Hobbyprojekt dieser Komplexität |

---

## Top-5-Sofortmaßnahmen (nach Priorität)

1. **Phase 15 implementieren (Self-Update)** – Enabler für alle Folge-Deployments. Kosten: ~2h.
2. **`allowed_senders` befüllen** – in `start_saleria.py` die eigene Matrix-User-ID eintragen.
   Ohne das ist die Sender-Prüfung wirkungslos.
3. **Phase 16 implementieren (Notizen)** – Hochgenutztes Feature: "merk dir X" ist der häufigste
   Assistent-Use-Case. Kosten: ~4h.
4. **Rate-Limiting für ClaudeAgent** – Token-Bucket verhindert API-Kostenfallen.
5. **Phase 17 implementieren (Kalender-Watcher)** – Proaktive Erinnerungen ohne User-Eingriff.
