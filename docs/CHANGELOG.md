# Elder-Berry – Changelog

Phasenbasierter Überblick über die Entwicklung. Format: Was wurde gebaut,
nicht jedes einzelne Commit. Für Architektur-Details siehe
[`architecture.md`](architecture.md), für die volle Roadmap siehe
[`PROJECT_ROADMAP.md`](PROJECT_ROADMAP.md).

> Phasen, die mit ✅ markiert sind, sind in der ausgelieferten Software
> aktiv. ⏸️ heißt zurückgestellt, 🔭 heißt Vision/nicht implementiert.

## 2026

### Phase 67 – Public-Readiness (April 2026) ✅

Audit + Sanitization für eine eventuelle Open-Source-Veröffentlichung:
hardcodete Domains, LAN-IPs, persönliche IDs und Server-Pfade durch
Beispielwerte / Konfiguration ersetzt. Audit-Tool
(`scripts/check_public_readiness.py`) bleibt im Repo.

### Phase 66 – RPi5-Reverse-Proxy über Saleria (April 2026) ✅

Browser auf der öffentlichen Dashboard-Domain kann jetzt RPi5-Calls
ohne LAN-Zugriff und ohne Mixed-Content-Block ausführen: neuer
`/api/robot/*`-Proxy in Saleria reicht durch zum SSH-Tunnel-Endpoint
(127.0.0.1:12800), fügt Server-seitig den Robot-Token ein. Frontend
bleibt same-origin. Robot-Token verlässt das Backend nicht.

### Phase 64–65 – Security-Härtung (April 2026) ✅

Drei kritische und vier mittlere Security-Findings aus einer
internen Code-Review umgesetzt:

- **CSRF-Schutz**: Origin/Referer-Check-Middleware für alle
  state-changing Dashboard-Routen, `SameSite=strict` für das
  Session-Cookie.
- **Robot-Token Hard-Fail**: RPi5-Service bricht beim Start ab, wenn
  kein Token gesetzt ist und der Bind-Host nicht Loopback. Verhindert
  versehentliches LAN-Exposure.
- **SSRF-Schutz** im `WebFetcher`: blockt private/loopback/
  metadata-IPs (z.B. `169.254.169.254` AWS-Metadata).
- **SecretStore → OS-Keyring**: Fernet-Masterkey wandert aus
  Plaintext-Datei in den Windows Credential Manager / macOS
  Keychain / Linux Secret Service. Auto-Migration mit
  Verify-before-Delete.
- **Globales Logout**: Session-Secret-Rotation per UI-Button im
  Settings-Panel.
- **Git-Command-Whitelist**: Matrix-User können `git log`/`git diff`
  nur noch mit explizit erlaubten Argumenten aufrufen.
- **Lockfiles + Dependabot**: `requirements-tower.lock`,
  `requirements-dev.lock`, weekly Security-Updates.

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

## Offene Strange / Vision

- Phase 9 (Multimodal + Autonomie) – Kamera-basierte Anwesenheits-
  Erkennung, proaktive Reaktion auf Mimik.
- Phase 41 (IR-Learning) – Geräte-Lernmodus für unbekannte
  Fernbedienungen.
- Avatar Hardware: Pepper's Ghost Hologramm-Setup mit DSI-Display.
