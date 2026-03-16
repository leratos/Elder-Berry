# Elder-Berry – Projektanalyse

> Analyse erstellt: März 2026  
> Bereiche: Nutzen · Stand · Sicherheit · Umsetzung/Codequalität

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

- Kein Multimodal-Input (Kamera → GPT-4o, geplant in Phase 5)
- Keine Emotion-State-Machine (geplant), Emotionen sind rein textbasiert
- Kein Wake-Word / Always-Listening Modus – nur Text-Input via Matrix

**Fazit:** Für ein persönliches Hobbyprojekt liegt der Nutzen weit über dem Durchschnitt.
Die Kombination aus Hologramm, Voice Cloning, LLM und Remote-Control ist funktional und
differenziert genug um echten Alltagseinsatz zu rechtfertigen.

---

## 2. Stand – Bewertung: 7.5 / 10

| Phase | Name | Status |
|---|---|---|
| 1 | Software Basic (PC-Steuerung, TTS, LLM, Assistant) | ✅ Abgeschlossen |
| 2 | RPi5-Anbindung | ✅ Software abgeschlossen, Hardware offen |
| 3 | Charakter / V-Tuber (Saleria, XTTS, Avatar) | ✅ Abgeschlossen |
| 4 | Gehäuse + Drehteller | 🔧 In Arbeit (Hardware) |
| 5 | Software Advance (Emotion State Machine, Multimodal) | 📋 Geplant |
| 6 | Matrix-Integration | ✅ Abgeschlossen |
| 7 | Remote Features (ClaudeAgent, Commands) | ✅ Abgeschlossen |

- **520+ Tests**, alle bestehend laut README (25 Test-Dateien)
- **Gute Dokumentation**: README, PROJECT_ROADMAP, Konzeptdokumente, journal.txt
- **Fehlende Hardware**: RPi5 noch nicht vollständig integriert (MotorController,
  SensorManager als Platzhalter), Pico 2W-Rolle unklar, Gehäuse in Arbeit

**Fazit:** 6 von 7 Softwarephasen sind abgeschlossen. Der größte offene Block ist
Hardware (Gehäuse, Drehteller, echte RPi5-Sensorklassen). Die Codebasis ist reif
für die verbleibenden Phasen.

---

## 3. Sicherheit – Bewertung: 5.5 / 10 (vor Fixes: 4.5 / 10)

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
| 🟡 Mittel | `git pull` in `GIT_WHITELIST`: kann schädlichen Code ziehen | Entfernen oder separaten Flag erfordern |
| 🟡 Mittel | `download <url>` lädt von beliebigen URLs herunter | URL-Whitelist oder Domain-Filter |
| 🟡 Mittel | `SecretStore` Key-Datei chmod 600 greift auf Windows nicht | Windows DACL setzen (optional) |
| 🟡 Mittel | Kein Rate-Limiting für ClaudeAgent → unkontrollierte API-Kosten | Request-Throttling (z.B. 10 req/min) |
| 🟢 Niedrig | Matrix ohne E2EE (Phase 1 Design-Entscheidung) | E2EE für Phase 5 einplanen |
| 🟢 Niedrig | `docker restart <name>` ohne Container-Whitelist | Container-Namen-Whitelist analog zu Docker-Commands |
| 🟢 Niedrig | Fehlende Security-Logging von abgelehnten Nachrichten | Zentrales Security-Log |

---

## 4. Umsetzung / Codequalität – Bewertung: 7.5 / 10

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

#### Dateigröße

| Datei | Zeilen | Problem |
|---|---|---|
| `remote_commands.py` | 1 207 | Sollte in `commands/` aufgeteilt werden (Tier 1/2/3 je Datei) |
| `claude_agent.py` | 815 | `_exec_*`-Handler könnten in eigene Klasse ausgelagert werden |

#### Async-Konsistenz in `ActionsDB`

`ActionsDB` nutzt synchrones `sqlite3` direkt in async-fähigen Kontexten. Bei hohem
Durchsatz (z.B. mehrere parallele Matrix-Nachrichten) blockiert das den Event-Loop.
Empfehlung: `aiosqlite` oder Ausführung in `loop.run_in_executor()`.

#### Hardcodierte Pfade

`claude_agent.py` Zeile 17 zeigt `project_root=Path("C:/Dev/Elder-Berry")` im
Docstring-Beispiel – das ist ein Windows-absoluter Pfad. Im Produktivcode sollte
dieser Pfad immer dynamisch ermittelt werden (z.B. `Path(__file__).parents[N]`).

#### Fehlende Input-Sanitierung bei `clip_write`

`clip: <beliebiger Text>` schreibt direkt in die Windows-Zwischenablage. Wenn die
Zwischenablage anschließend in ein Programm eingefügt wird, könnte ein Angreifer
Tastenkombinationen oder Shell-Injection-Payloads einschleusen. Längenbegrenzung
und Whitespace-Normalisierung würden das Risiko reduzieren.

#### `LLMRouter._select_client()` doppelt `is_available()` aufgerufen

```python
def generate(self, prompt: str, system: str = "") -> str:
    client = self._select_client()   # ruft is_available() auf
    return client.generate(...)
```

`_select_client()` ruft `is_available()` intern zweimal auf (einmal für Ollama,
einmal für OpenRouter). Da `is_available()` einen HTTP-Check macht, sind das zwei
Netzwerkaufrufe pro LLM-Request. Ein kurzes Caching (z.B. 30 Sekunden) würde die
Latenz reduzieren.

#### Fehlende `__all__`-Deklarationen

Keines der Module definiert `__all__`. Für eine Bibliothek (auch interne) ist das
empfohlen, um die öffentliche API explizit zu machen.

---

## Gesamtbewertung

| Bereich | Note | Begründung |
|---|---|---|
| **Nutzen** | **8 / 10** | Klarer, differenzierter Einsatzzweck; Phase 5 fehlt noch |
| **Stand** | **7.5 / 10** | 6 von 7 Phasen erledigt; Hardware-Block ist der Flaschenhals |
| **Sicherheit** | **5.5 / 10** | Nach Fixes solider Kern; offene Punkte (Rate Limiting, E2EE) bleiben |
| **Codequalität** | **7.5 / 10** | Saubere Architektur; große Dateien und Async-DB sind die Hauptbaustellen |
| **Gesamt** | **7.1 / 10** | Über dem Durchschnitt für ein Hobbyprojekt dieser Komplexität |

---

## Top-5-Sofortmaßnahmen (nach Priorität)

1. **Rate-Limiting für ClaudeAgent** – ein einfacher Token-Bucket (z.B. 10 Anfragen/Minute)
   verhindert unkontrollierte API-Kosten bei Angriffen oder Bugs.
2. **`git pull` aus `GIT_WHITELIST` entfernen** – oder hinter einen separaten
   `allow_git_pull: bool`-Flag stellen.
3. **`allowed_senders` befüllen** – beim Starten der `MatrixBridge` die eigene Matrix-ID
   in `allowed_senders` übergeben. Ohne diesen Schritt ist der neue Parameter wirkungslos.
4. **`remote_commands.py` aufteilen** – Tier-1/2/3 in separate Module, erleichtert Tests
   und Navigation erheblich.
5. **`ActionsDB` auf `aiosqlite` migrieren** – löst potenzielle Event-Loop-Blockierungen
   wenn mehrere Matrix-Nachrichten parallel ankommen.
