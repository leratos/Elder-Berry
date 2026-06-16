# Elder-Berry – Gesamtanalyse Sicherheit & Codequalität

**Stand:** 2026-06-09 · **Branch:** `main` (`3b4b057`) · **Version:** `1.0.0-rc1`
**Umfang:** 188 Python-Module / ~59.700 LOC in `src/`, 201 Testdateien.
**Methode:** Automatisierte Scans (bandit, ruff) + manuelles Tiefen-Review der
sicherheitskritischen Module (Auth, Secrets, Subprocess, Netzwerk, XML, SQL).

> Hinweis: `pip-audit` konnte in der Analyse-Umgebung nicht aufgelöst werden
> (gepinnte Versionen sind zukunftsdatiert, kein PyPI-Match). Die CVE-Prüfung
> der Dependencies muss in der echten CI-Umgebung erfolgen – dort ist
> `pip-audit --desc on` bereits als Pipeline-Schritt vorhanden.

---

## 1. Gesamteinschätzung

Elder-Berry ist für ein Projekt dieser Größe **überdurchschnittlich reif**.
Die sicherheitskritischen Pfade sind durchdacht gebaut: keine offensichtlichen
Injection-Flächen, sauberes Secret-Management, gehärtete Web-/Session-Schicht,
und eine CI mit Lint + Typcheck + Tests + SAST (CodeQL) + Dependency-Audit.

Die größten offenen Punkte sind **nicht akute Lücken**, sondern (a) ein
bewusst „fail-open" gestaltetes Auth-Default bei den Agent-/Robot-Servern,
(b) ungehärtetes XML-Parsing externer Server-Antworten, und (c)
Codequalitäts-/Wartbarkeitsschulden (sehr große Dateien, breite
Exception-Behandlung, teilweise untypisierte Paket-Tiers).

| Bereich | Bewertung |
|---|---|
| Secret-/Credential-Management | Stark |
| Web-/Session-Sicherheit | Stark |
| Injection-Resistenz (Shell/SQL/Code) | Stark |
| Auth-Defaults (Agent/Robot) | Verbesserungswürdig |
| XML-Härtung | Verbesserungswürdig |
| Teststruktur & CI | Stark |
| Wartbarkeit / Komplexität | Mittel |
| Typabdeckung (mypy) | Teilweise |

---

## 2. Stärken (was gut ist)

- **Keine gefährlichen Konstrukte:** kein `shell=True`, kein `eval`/`exec`,
  kein `os.system`, kein `pickle.load`, kein unsicheres `yaml.load`. Alle
  Subprocess-Aufrufe verwenden Listen-Argumente ohne Shell-Interpolation.
- **Subprocess mit Whitelist/Allowlist:** Prozess-Start (`process_commands`)
  nur aus fixer `START_WHITELIST`; Git-Befehle (`git_commands`) validieren
  Subcommands und Argumente gegen eine Allowlist.
- **Secret-Management:** `SecretStore` verschlüsselt Credentials mit Fernet
  (AES-128-CBC + HMAC), Masterkey bevorzugt im OS-Keyring (DPAPI/Keychain/
  Secret Service), Fallback-Datei mit `chmod 600`. `.env` ist nicht versioniert,
  keine hartkodierten Secrets im getrackten Quellcode gefunden.
- **Passwörter:** bcrypt mit Cost-Faktor 14, Mindestlänge 12 Zeichen.
- **Sessions:** HMAC-SHA256-signierte Cookies mit `iat`/`exp`, absolutem
  Lifetime-Cap, Sliding-Renewal und serverseitiger Revocation-Liste. Cookies
  mit `HttpOnly`, `SameSite=strict`, `Secure` (bei HTTPS).
- **Timing-sichere Vergleiche:** durchgängig `secrets.compare_digest` /
  `hmac.compare_digest` für Token- und Signaturprüfung.
- **Web-Härtung:** CORS auf konkrete Allowlist beschränkt (kein Wildcard),
  `allow_credentials=False`, Security-Header-Middleware, CSRF-Schutz per
  Origin-Check, Rate-Limiting mit Lockout auf den Token-Endpoints, generischer
  Exception-Handler ohne Detail-Leak.
- **CI-Pipeline:** ruff, mypy (auf core/tools/web/comms), pytest + Coverage zu
  Codecov (Ziel 70 %), `pip-audit --desc`, plus CodeQL-Workflow.
- **Supply-Chain-Bewusstsein:** FastAPI ist explizit gegen den Typosquat
  `fastar` (MAL-2026-4750) gepinnt und im `pyproject.toml` dokumentiert.
- **Sauberer Stil:** `ruff check` (voll) ist grün; Logging über
  `logging.getLogger(__name__)`, kein `print()` für Fehler; klare
  Paket-/Command-Registry-Architektur; gute (deutschsprachige) Doku.

---

## 3. Entdeckte Punkte (Befundliste)

### Sicherheit

**S1 — Fail-open-Auth bei Agent- und Robot-Server (Mittel)**
`AgentTokenMiddleware` und die Robot-Token-Middleware überspringen die
Authentifizierung vollständig, wenn kein Token konfiguriert ist
(`if not self._token: return await call_next(request)`). Ohne Token sind alle
Endpoints – inklusive aktionsauslösender – offen. Es wird zwar beim Start eine
`logger.warning` ausgegeben, aber der Server startet trotzdem und verweigert
auch bei Nicht-Localhost-Bind nicht. Risiko: versehentlicher LAN-/Prod-Betrieb
ohne gesetztes `ELDER_BERRY_AGENT_TOKEN` / `ELDER_BERRY_ROBOT_TOKEN`.
*Dateien:* `src/elder_berry/agent/server.py:67`, `src/elder_berry/robot/server.py:262`

**S2 — XML-Parsing externer Antworten ohne Härtung (Mittel/Niedrig)**
CardDAV-Sync und Nextcloud-Client parsen Server-Antworten mit der Stdlib
`xml.etree.ElementTree.fromstring`. bandit meldet B314/B405. Moderne Python-
Versionen expandieren keine externen Entities mehr, aber Entity-Expansion-/
Blow-up-Härtung (defusedxml) fehlt; bei kompromittiertem oder
fehlkonfiguriertem CardDAV-/Nextcloud-Host ist das eine vermeidbare Fläche.
*Dateien:* `src/elder_berry/tools/carddav_sync.py:764`,
`src/elder_berry/tools/nextcloud_files.py:371,585`

**S3 — Silent Exception Swallows (Niedrig)**
15 Stellen mit `try/except: pass` bzw. `try/except: continue` (bandit
B110/B112). Fehler werden ohne Log verschluckt – erschwert Diagnose und kann
echte Defekte maskieren (u. a. in `message_handlers.py`, `email_client.py`,
`carddav_sync.py`, `contact_store.py`, `proposal_store.py`).

**S4 — SQL per f-String zusammengebaut (Niedrig – aktuell nicht ausnutzbar)**
bandit B608 in `contact_store.py` (3×) und `proposal_store.py` (3×). In der
Praxis werden nur **fixe Spaltennamen** aus Klassenkonstanten (`_ALL_FIELDS`,
`_PROPOSAL_COLS`) interpoliert; alle Werte sind parametrisiert (`?`). Damit
derzeit **kein** Injection-Vektor – aber kein expliziter Allowlist-Guard, also
brüchig, falls die Spaltenliste je dynamisch/extern befüllt wird.

**S5 — Robot-Simulator kann ohne Auth auf 0.0.0.0 binden (Info)**
`robot/simulator.py` erlaubt `--bind 0.0.0.0` ohne Authentifizierung; opt-in
und mit Warnung. Nur als bewusstes Dev-Werkzeug akzeptabel.

**S6 — Bandit-False-Positives (Info, kein Handlungsbedarf)**
B105 „hardcoded password" betrifft Header-*Namen* (`X-Saleria-Agent-Token`
etc.), keine Secrets. B311 (`random`) wird nur in Avatar-/Robot-Rendering
(Idle/Lip-Sync/Jitter/Simulator) verwendet – nicht sicherheitsrelevant. B101
(`assert`, 118×) ist überwiegend in Tests/Invarianten unkritisch, sollte aber
nicht in sicherheitsentscheidenden Pfaden zur Durchsetzung genutzt werden
(läuft mit `python -O` nicht).

### Codequalität

**Q1 — Sehr große Dateien (Mittel)**
Die projekteigene Richtlinie (AGENTS.md: „max. ~400 Zeilen pro Datei-Chunk")
wird mehrfach deutlich überschritten:
`comms/message_handlers.py` (2235), `comms/commands/weather_commands.py`
(1156), `web/settings_dashboard.py` (1101), `core/assistant.py` (1092),
`comms/confirmation_handlers.py` (1087), `robot/server.py` (1011) u. a.
Wartbarkeits- und Komplexitäts-Hotspots.

**Q2 — Breite Exception-Behandlung (Mittel)**
347× `except Exception` in `src/`. Kein einziges nacktes `except:` (gut), aber
die breite Form reduziert Beobachtbarkeit; in Kombination mit S3 (Silent
Swallows) ein Diagnose-Risiko.

**Q3 — Typabdeckung nur partiell strikt (Mittel)**
mypy-`strict` ist sauber per Tier ausgerollt (core/comms/tools/web), aber die
Pakete `actions`, `agent`, `avatar`, `character`, `llm`, `memory`, `robot`,
`stt`, `system`, `tts`, `webapp` laufen mit `ignore_errors = true`. Damit
bleibt eine große – teils sicherheitsnahe (`agent`, `robot`) – Fläche
untypisiert.

**Q4 — CI-Lint enger als lokaler Check (Niedrig)**
Der blockierende CI-Schritt nutzt nur `ruff check --select E9,W605,F401,B`.
Lokal läuft der volle Ruff-Satz (grün). Regelabweichungen außerhalb des
Subsets würden in der CI nicht blockieren.

**Q5 — Offene Schuld-Marker (Niedrig)**
~49 `TODO`/`FIXME`/`HACK`/`XXX` in `src/` – moderat für 60k LOC, sollte aber
periodisch in das Journal/Backlog überführt werden.

---

## 4. Empfehlungsliste (priorisiert)

### Kurzfristig (Sicherheit, hohe Priorität)

1. **S1 – Auth fail-closed machen:** Server-Start ohne Token nur erlauben,
   wenn der Bind explizit `127.0.0.1`/`localhost` ist. Bei Nicht-Localhost-Bind
   ohne Token den Start **verweigern** (statt nur warnen) oder einen
   `--allow-insecure`-Schalter erzwingen.
2. **S2 – `defusedxml` einführen** (oder `defuse_stdlib()` zentral aufrufen)
   für alle Parser externer Antworten (CardDAV, Nextcloud/WebDAV). Neue
   Dependency in die passende optionale Gruppe (`nextcloud`/`tools`).
3. **S4 – Defensive Spalten-Allowlist:** vor jedem f-String-SQL ein
   `assert set(cols) <= ALLOWED_COLUMNS` bzw. Quoting-Helper, damit der heute
   sichere Zustand nicht still kippen kann. bandit-`# nosec`-Annotation mit
   Begründung ergänzen.

### Mittelfristig (Qualität & Robustheit)

4. **S3/Q2 – Silent Swallows beheben:** die 15 `except: pass/continue`-Stellen
   mit `logger.debug/warning` versehen; breites `except Exception` schrittweise
   auf konkrete Exception-Typen verengen, beginnend in `agent`/`robot`/`web`.
5. **Q1 – Große Dateien aufteilen:** `message_handlers.py` (2235 Z.) und die
   übrigen >900-Zeilen-Module entlang klarer Verantwortlichkeiten zerlegen –
   konform zur eigenen 400-Zeilen-Richtlinie.
6. **Q3 – mypy-strict-Rollout fortsetzen:** zuerst die sicherheitsnahen Pakete
   `agent` und `robot` aus `ignore_errors` herausnehmen, dann die restlichen
   Tiers.

### Laufend (Prozess)

7. **Q4 – CI-Lint angleichen:** im blockierenden CI-Schritt den vollen
   Ruff-Satz fahren (wie lokal), nicht nur das Subset.
8. **Dependencies:** `pip-audit` in der echten CI grün halten und das Ergebnis
   im Journal festhalten; Lockfiles regelmäßig gegen das aktuelle Advisory-DB
   prüfen (Supply-Chain-Disziplin ist bereits vorbildlich – beibehalten).
9. **Q5 – Schuld-Marker** periodisch ins Bramble-Journal/Backlog überführen
   und mit `resolves` schließen.

---

## 5. Methodik & Reproduzierbarkeit

```bash
# Statisch
bandit -r src -ll                 # Security-Lint (Medium+ manuell geprüft)
ruff check src tests              # Stil/Bug-Lint (grün)
mypy src/elder_berry/core ...     # Typcheck (Tier-Rollout)

# In echter CI zusätzlich
pip-audit --desc on               # Dependency-CVEs
# + CodeQL-Workflow (.github/workflows/codeql.yml)
```

**Manuell reviewt:** `core/secret_store.py`, `web/dashboard_auth*.py`,
`web/security_middleware.py`, `agent/server.py`, `robot/server.py`,
`comms/commands/cmd_utils.py`, `comms/commands/{process,git}_commands.py`,
`tools/{contact_store,proposal_store,carddav_sync,nextcloud_files}.py`.
