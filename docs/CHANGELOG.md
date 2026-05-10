# Elder-Berry – Changelog

Phasenbasierter Überblick über die Entwicklung. Format: Was wurde gebaut,
nicht jedes einzelne Commit. Für Architektur-Details siehe
[`architecture.md`](architecture.md), für die volle Roadmap siehe
[`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md).

> Phasen, die mit ✅ markiert sind, sind in der ausgelieferten Software
> aktiv. ⏸️ heißt zurückgestellt, 🔭 heißt Vision/nicht implementiert.

## 2026

### Phase 81 + 81b – Command-Fallback-UX + Self-Suggestion-Hook (Mai 2026) ✅

Zwischenschritt während Phase 80: zwei UX-Härtungen am Command-Router.

- **Phase 81 (Punkt 7)** – User-Feedback bei nicht-erkanntem
  `remote_command`. Wenn das LLM auch nach Retry kein Command findet,
  bekommt der User eine kurze Erklärung statt Schweigen ("Ich habe das
  als Befehl verstanden, konnte ihn aber keinem Command zuordnen — Tipp
  `hilfe` für die Übersicht.").
- **Phase 81b** – Der Fallback-Pfad legt zusätzlich einen
  Plugin-Vorschlag via Phase-78-Pipeline an (`IntentAggregator`).
  Vorab-Check auf `is_rejected`, damit der User nicht über
  bereits abgelehnte Features informiert wird. Erfolgt ein Vorschlag,
  ergänzt Saleria im User-Feedback "Ich habe Marcus eine Notiz
  hinterlassen — wenn das öfter vorkommt, kümmert er sich darum."

### Phase 80 – ConversationListStore + list_pick (Mai 2026) ✅

In-Memory-Liste pro `(user_id, list_type)` mit TTL=1h: Saleria
registriert strukturierte Mehrfachergebnisse (Web-Suche, Mail-Inbox,
Notiz-Treffer), und das LLM bekommt nur noch einen Index ("Treffer 2")
statt des realen Werts. Auflösung passiert serverseitig — verhindert
ID- und URL-Halluzinationen wie `web_summary` auf einer geratenen URL.
Etappen 1–3: Store + `web_search`-Integration + `mail_inbox`/`note_search`-
List-Types.

### Phase 79 – Richer Pseudocode ⏸️ ON HOLD

Idee: längere LLM-Pseudocode-Snippets für Plugin-Vorschläge im
Dashboard. Harter Trigger dokumentiert (5 Vorschläge in DB, 3
implementiert, jeweils Spec-Lücke). Selbst-Verpflichtung: wenn der
Trigger nach 6 Monaten nicht erfüllt ist, wird die Phase verworfen.

### Phase 78 – Plugin Self-Suggestion (Mai 2026) ✅

Saleria erkennt LLM-Fallback-Lücken und legt strukturierte
Plugin-Vorschläge an. `ProposalStore` (SQLite + FTS5 für Dedupe) +
`ProposalNotifier` als reaktiver Trigger + Dashboard-Modul mit
Status-Workflow (`new` → `reviewed` → `implemented`/`rejected`).
Explizit kein Auto-Load — Lera reviewt und implementiert manuell
(R1-Guard).

### Phase 77 + 77.5 – Commands-Plugin-Registry + Inspector (Mai 2026) ✅

Builtin-Handler ans `CommandPlugin`-Manifest migriert (Phase 77 Etappe 1
mit 3 Pilot-Handlern, Etappe 2 mit den restlichen 20; Phase 77.5
ergänzte den Plugin-Inspector inkl. eigenem `plugins`-Plugin — Stand
heute 24 Builtin-Plugins).
Registry lädt aus drei Quellen: Builtin im Repo, User-Dir
(`~/.elder-berry/plugins/`), Entry-Points. Conflict-Detector als
CI-Gate gegen kollidierende Patterns. Generator-Wizard
(`scripts/generate_plugin.py`). Phase 77.5: Plugin-Inspector als
Vorbedingung für Phase 78 (Quellen-Information pro Plugin sichtbar
im Dashboard).

### Phase 76 + 76b + 76c – mypy --strict Rollout (Mai 2026) ✅

`core/`, `comms/`, `tools/` und `web/` (insgesamt ~70 Module) auf
`mypy --strict` umgestellt, in 4–5 Tiers pro Sub-Paket. CI-Gate hart,
sodass Typ-Drift nicht mehr unbemerkt durchrutscht. Out-of-Scope-
Pakete (memory/, robot/, …) bleiben unter lockeren Defaults und sind
explizit gesilenced.

### Phase 75 + 75b – Repo-Hygiene + Format-Sweep (April–Mai 2026) ✅

Phase 75: 27 Local-Branches + 14 Worktrees aufgeräumt, 11 Stale-
Origin-Refs geprunt, Version-Bump auf `1.0.0-rc1`, pre-commit-Setup
(ruff Lint + EOL/Whitespace/YAML/TOML + Local check_public_readiness
als pre-push). Phase 75b: `ruff-format` über ~300 Python-Dateien,
Tests vor/nach Sweep identisch (5016 passed), Format-Hook von manual
auf default geschaltet.

### Phase 74 – Codecov-Integration (April 2026) ✅

Coverage-Reports in CI, Badge im README, weekly Test-Coverage-Drift-
Erkennung.

### Phase 73 – CodeQL-Triage + Security-PRs A/B/C (April 2026) ✅

241 offene CodeQL-Alerts triagiert: 9 echte Findings, 124 dokumentierte
False-Positives, ~108 Hygiene-Sweep-Themen. Drei Security-PRs:
- **PR-A** Partial-SSRF im Setup-Wizard (`setup_tests.py`):
  Schema-Whitelist, Userinfo-Verbot, RFC-1035-Hostname-Check,
  `follow_redirects=False`.
- **PR-B** Stack-Trace-Exposure: 8 echte Exception-Leaks gefixt
  (f-String mit `{exc}` raus, `logger.exception` rein, generische
  Response). 11 ValueError-Stellen bewusst nicht gefixt (Teil des
  UX-Vertrags).
- **PR-C** Log-Injection x14 + SSRF-Defense-in-Depth im Robot-Proxy:
  zentraler `safe_log()`-Helper (CR/LF → `\r`/`\n`-Tokens), raw-Host-
  Validierung vor Schema-Mutation.

### Phase 72 – Auth-Hardening: PW-Min 12 + bcrypt rounds 14 (April 2026) ✅

Mindest-Passwortlänge im Dashboard von 8 auf 12 angehoben, bcrypt-
Rounds von 12 auf 14 (~250 ms/Hash). Bestehende Hashes funktionieren
weiter (bcrypt liest Cost-Faktor aus dem Hash-Prefix).

### Phase 71 – Public-Release-Hygiene Runde 2 (April 2026) ✅

`hardware/enclosure/OldVersions/` explizit aus `.gitignore`,
`.claude/settings.local.json` ergänzt, GitHub-Templates (Bug/Feature/
PR), `check_public_readiness.py` konfigurierbar via optionale
`.public-readiness-blocklist.txt` (Forks bekommen "alles ok"-Default).
SECURITY.md: M1–M5 als bekannte Einschränkungen dokumentiert.

### Phase 70 – Session- + Web-Hardening (April 2026) ✅

Vier Hoch-Findings aus interner Security-Review:
- **H1** `SessionRevocationList`: Server-side Logout-Invalidation,
  Eintrag hält SHA-256 des Cookies (kein Klartext-Echo).
- **H2** `tempfile.mktemp()` → `NamedTemporaryFile(delete=False)`:
  TOCTOU-Symlink-Race-Vektor in `$TMP` zu.
- **H3** `WebFetcher` Stream-Cap: `httpx.stream()` + 5 MB Hard-Cap
  gegen Speicher-DoS.
- **H4** Absoluter Session-Cap: `iat_original` im Payload, Sliding-
  Renewal rollt den 24h-Cap nicht zurück.

### Phase 69 – Path-Traversal-Schutz für Matrix-Commands (April 2026) ✅

User-übergebene Pfade in `schick mir`, `download`, `zusammenfassung`
gegen Allowlist + `Path.resolve()`-Containment-Check geprüft. Keine
absoluten Pfade außerhalb `data/`, `logs/`, `~/Downloads`.

### Phase 68 + 68 B1 – Public-Release-Vorbereitung + Asset-Licensing (April 2026) ✅

Boilerplate für Public-Repo: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
`SECURITY.md`, GitHub-CodeQL-Workflow scharfgeschaltet,
`docs/assets/README.md` als Spec für Tranche-B-Bilder. Phase 68 B1:
MIT-Lizenzlage für eigene Assets (Saleria Voice-Samples, Avatar-
Sprites) explizit dokumentiert. Neue `NOTICE.md` mit Drittanbieter-
Übersicht (XTTS v2 CPML als Forking-Warnung besonders hervorgehoben).

### Phase 67 – Public-Readiness (April 2026) ✅

Audit + Sanitization für eine eventuelle Open-Source-Veröffentlichung:
hardcodete Domains, LAN-IPs, persönliche IDs und Server-Pfade durch
Beispielwerte / Konfiguration ersetzt. Audit-Tool
(`scripts/check_public_readiness.py`) bleibt im Repo.

### Phase 64 – CSRF/SSRF/Robot-Token Hard-Fail (April 2026) ✅

Drei kritische Findings aus einer internen Code-Review:

- **CSRF-Schutz**: Origin/Referer-Check-Middleware
  (`OriginCheckMiddleware`) für alle state-changing Dashboard-Routen,
  `SameSite=strict` für das Session-Cookie.
- **Robot-Token Hard-Fail**: RPi5-Service bricht beim Start ab, wenn
  kein Token gesetzt ist und der Bind-Host nicht Loopback. Verhindert
  versehentliches LAN-Exposure.
- **SSRF-Schutz** im `WebFetcher`: blockt private/loopback/
  metadata-IPs (z.B. `169.254.169.254` AWS-Metadata).

### Phase 65 – Mittlere Security-Fixes (M-1 … M-4) (April 2026) ✅

- **M-1 SecretStore → OS-Keyring**: Fernet-Masterkey wandert aus
  Plaintext-Datei in den Windows Credential Manager / macOS
  Keychain / Linux Secret Service. Auto-Migration mit
  Verify-before-Delete.
- **M-2 Globales Logout**: Session-Secret-Rotation per UI-Button im
  Settings-Panel.
- **M-3 Git-Command-Whitelist**: Matrix-User können `git log`/`git diff`
  nur noch mit explizit erlaubten Argumenten aufrufen.
- **M-4 Lockfiles + Dependabot**: `requirements-tower.lock`,
  `requirements-dev.lock`, weekly Security-Updates.

### Phase 66 – Robot-Reverse-Proxy (April 2026) ✅

Browser auf der öffentlichen Dashboard-Domain kann jetzt RPi5-Calls
ohne LAN-Zugriff und ohne Mixed-Content-Block ausführen: neuer
`/api/robot/*`-Proxy in Saleria reicht durch zum SSH-Tunnel-Endpoint
(127.0.0.1:12800), fügt Server-seitig den Robot-Token ein. Frontend
bleibt same-origin. Robot-Token verlässt das Backend nicht.

## 2025–2026

### Phase 60–63 – Auth, Logging, CSP (2026 Q1) ✅

Tower-Auth mit Token-Header, Remote-Log-Zugriff über Matrix
(read-only), Content-Security-Policy ohne `unsafe-inline`.
Alexa-Skill verifiziert Amazon-Signatur cryptographisch.

### Phase 57–59 – Security-Härtung Tier 1 (2026 Q1) ✅

CORS-Härtung, Rate-Limiting für Dashboard-Login (5 Versuche / 5 min →
15 min Lockout) und Robot-Token (10/min → 10 min Lockout),
Allowed-Senders-Whitelist für Matrix.

### Phase 52–56 – Settings Dashboard 2.0 (2025 Q4) ✅

Unified Settings Panel statt drei getrennter UIs, Avatar-Editor mit
WebSocket-Live-Preview, Setup-Wizard für Erst-Konfiguration,
Install-Script-Härtung, Migration auf Python 3.13 (pydub/audioop).

### Phase 44–51 – Server-Tier + Settings + UX (2025 Q3–Q4) ✅

Migration vom reinen Tower-Setup auf 4-Tier-Architektur (Rootserver
+ Tower + Laptop + RPi5). SSH-Reverse-Tunnels für Backend-Sichtbarkeit.
Settings-Dashboard, Setup-Wizard, Anhang-Aktionsmenü, Fehler-UX,
kontextsensitive Hilfe.

### Phase 36–43 – Nextcloud + Routenplanung (2025 Q3) ✅

Vollintegration Nextcloud (CalDAV-Kalender, CardDAV-Kontakte,
Datei-Hub mit Upload + Share-Links, Inhaltssuche, Tasks als
Todo-Backend). Dokument-Ablage mit Auto-Klassifikation. Google Maps
Directions-API für Routen mit Abfahrtszeit-Berechnung.

### Phase 26–35 – Bot-Vollausstattung (2025 Q2) ✅

Hauptphase der Assistenten-Funktionen: Kamera + Vision, Drehteller-
Steuerung, E-Mail-Reply mit LLM-Vorschlag, Kontaktbuch, Aufgabenliste,
Bridge-Refactoring (50+ Commands in 18 spezialisierte Handler-
Klassen), Test-Offensive (1500+ Tests), Smart-Context-Routing,
Briefing 2.0, Web-Summary.

### Phase 21–25 – Reasoning-Chains (2025 Q2) ✅

Kontext-Verknüpfung über Sessions, Intent-Routing, Chat-Summary,
Avatar-Asset-Pipeline, strukturiertes Logging.

### Phase 15–20 – Meta-Funktionen (2025 Q1–Q2) ✅

Self-Update + Backup/Rollback (auch über Matrix), Notizen mit FTS5,
Kalender-Watcher mit proaktiven Erinnerungen, Emotion-Tracking über
Nachrichten, Erinnerungen mit Wiederholungen (täglich/wöchentlich/
monatlich), Task-Chains.

### Phase 10–14 – Avatar + Multimodal (2025 Q1) ✅

Avatar-Display auf RPi5 (Pepper's Ghost Hologramm, layered Sprites,
Blink + Lip-Sync), PDF-Reader, Audio-Routing, Computer-Use via
Anthropic Vision, Brave-Web-Suche.

### Phase 9 – Multimodal + Autonomie 🔭

Vision: Saleria sieht über die Kamera, reagiert auf Anwesenheit/
Mimik. Bisher nur konzeptuell.

### Phase 5–8 – Erweiterte Software (2024 Q4) ✅

Matrix-Bridge (Synapse + Element), Remote-Steuerung des PCs, erste
Assistant-Tools (Kalender, Wetter, Mails). Phase 8 (Home-Assistant-
Integration) ⏸️ zurückgestellt.

### Phase 4 – Gehäuse + Drehteller 🔧

Hardware: 3D-gedrucktes Holunder-Baumstamm-Gehäuse, 360°-Drehteller
mit Hall-Sensor-Homing. In Arbeit.

### Phase 1–3 – Fundament (2024 Q3–Q4) ✅

Projektstruktur, System-Monitor, LLM-Router (Ollama lokal +
OpenRouter/Anthropic Fallback), Aktions-DB, PC-Steuerung,
Basis-TTS (SAPI5), Assistant-Integration, Charakter-Engine
"Saleria Berry" mit 10 Emotionen, Coqui XTTS v2 Voice Cloning,
PyGame-Avatar-Renderer.

---

## Offene Stränge / Vision

- Phase 9 (Multimodal + Autonomie) – Kamera-basierte Anwesenheits-
  Erkennung, proaktive Reaktion auf Mimik.
- Phase 41 (IR-Learning) – Geräte-Lernmodus für unbekannte
  Fernbedienungen.
- Phase 79 (Richer Pseudocode) – ON HOLD, wird verworfen wenn der
  Trigger (5 implementierte Plugin-Vorschläge mit Spec-Lücken) nach
  6 Monaten nicht erfüllt ist.
- Phase 4 (Hardware) – Gehäuse-Finish und Pepper's-Ghost-Kammer in
  Arbeit.
