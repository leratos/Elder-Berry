# Security Policy

## Disclosure-Pfad

Sicherheitslücken bitte **nicht als öffentliches Issue** melden,
sondern als privater
**[GitHub Security Advisory](https://github.com/leratos/Elder-Berry/security/advisories/new)**.

GitHub leitet das direkt an mich (Maintainer) weiter, ohne dass die
Information öffentlich wird, bis ein Fix released ist. Du kannst
optional schon einen CVE-Request über denselben Workflow stellen.

Bitte gib mit:
- **Komponente** (Modul / Pfad), wo der Bug ist.
- **Reproduktion**: konkrete Schritte oder ein Proof-of-Concept.
- **Impact-Einschätzung**: was kann ein Angreifer damit machen?
- **Versions-Info**: Commit-SHA oder Release-Tag.

## Was ich als Maintainer zusichere

- **Bestätigung** des Eingangs innerhalb von **7 Werktagen**.
- **Erste Einschätzung** innerhalb von **14 Werktagen** (kritisch /
  hoch / niedrig / kein Bug).
- **Fix-Zeitrahmen** je nach Severity:
  - kritisch (RCE, Auth-Bypass, Daten-Leak): so schnell wie möglich,
    Ziel < 7 Tage
  - hoch: < 30 Tage
  - mittel/niedrig: nach Abstimmung, oft im nächsten Release
- **Credit** im Changelog/Release-Notes, wenn du das willst.

## Was ich **nicht** zusichern kann

Elder-Berry ist ein **persönliches Projekt**, kein kommerzielles
Produkt. Konsequenz:
- Keine 24/7-Bereitschaft. Reaktion erfolgt in meiner Freizeit.
- Keine garantierten SLAs.
- Keine Bug-Bounty.

Wenn du eine Lücke findest, die im professionellen Einsatz wichtig
wäre, melde sie trotzdem — ich nehme jeden gut beschriebenen
Report ernst.

## Unterstützte Versionen

Aktuell wird nur die `main`-Branch unterstützt. Es gibt (noch)
keine Tagged-Releases mit Long-Term-Support.

| Version  | Unterstützt |
|----------|:-----------:|
| `main`   | ✅          |
| Forks    | ❌          |

## Sicherheits-Maßnahmen im Repo

- **Dependabot** scannt wöchentlich alle Dependencies auf bekannte
  CVEs (Konfiguration in [.github/dependabot.yml](.github/dependabot.yml)).
- **CodeQL** läuft auf jedem Push und PR (Konfiguration in
  [.github/workflows/codeql.yml](.github/workflows/codeql.yml)).
- **`pip-audit`** ist Teil des CI-Workflows
  ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Bekannte Schwachstellen-Klassen, die wir aktiv adressieren

Aus früheren internen Audits adressiert (siehe [CHANGELOG.md](docs/CHANGELOG.md)):

- ✅ CSRF-Schutz auf state-changing Dashboard-Routen (Phase 64)
- ✅ SSRF-Blockade für private/loopback/metadata-IPs (Phase 64)
- ✅ Robot-Token Hard-Fail bei non-loopback-Bind (Phase 64)
- ✅ Fernet-Masterkey im OS-Keyring (Phase 65)
- ✅ Globales Logout / Session-Secret-Rotation (Phase 65)
- ✅ Rate-Limiting für Dashboard-Login + Robot-Token (Phase 59)
- ✅ Content-Security-Policy ohne `unsafe-inline` (Phase 63)

## Bekannte Einschränkungen / Known Limitations

Diese Punkte sind aus internen Security-Reviews als **mittlere Findings**
bekannt. Sie sind kein Blocker für die Veröffentlichung — der typische
Threat-Vektor (versehentliche Internet-Exposition) wird durch andere
Härtungen abgedeckt — werden aber **nach Public-Release** adressiert.
Wenn du eines dieser Verhalten in der Praxis ausnutzen kannst, melde
es trotzdem bitte als Advisory.

### M1 — `allowed_rooms` fail-open

Wenn die Room-Allowlist nicht gesetzt ist (z.B. nach frischem Setup),
antwortet der Matrix-Bot in **jeder** Room, in die er von einem
Allow-Sender eingeladen wird. Die Sender-Allowlist (`allowed_senders`)
schützt davor, dass beliebige Matrix-User antworten bekommen, aber
ein kompromittierter / überredeter Allow-Sender kann den Bot in eine
fremde Room einladen.

**Mitigation:** Sender-Allowlist konsequent pflegen. Setup-Wizard sollte
bei der Ersteinrichtung explizit Rooms konfigurieren (Phase 46
adressiert das teilweise). Code:
[matrix_channel.py](src/elder_berry/comms/matrix_channel.py).

### M2 — Setup-Wizard ohne Brute-Force-Schutz

Solange der Setup-Wizard **nicht** abgeschlossen ist (`setup_state.json`
mit `complete: false`), sind die Setup-Endpoints unauthenticated. Das
ist by design — der Wizard läuft genau dafür, dass es noch keine
Credentials gibt. Es gibt aber keine Rate-Limit-Bremse auf den Setup-
Endpoints (`/setup/*`).

**Mitigation:** Der Wizard ist ein **kurzes einmaliges Fenster** beim
ersten Start. Wer das Dashboard öffentlich auf 0.0.0.0 bindet, bevor
der Wizard durch ist, hat ein anderes Problem. Empfohlen: Setup
**ausschliesslich über Loopback / VPN** (Phase 57 / Phase 64
Robot-Token Hard-Fail). Nach Abschluss greift der reguläre Login-
Rate-Limiter (Phase 59).

### M3 — Robot-/Settings-Token ohne automatische Rotation

Die statischen Tokens für Tower-Auth (`tower_auth_token`),
Robot-API (`robot_api_token`) und Settings-API (`settings_api_token`)
werden **nicht automatisch rotiert**. Sie sind im OS-Keyring
verschlüsselt (Phase 65) und werden bis zur manuellen Rotation
unverändert genutzt.

**Mitigation:** Tokens liegen im SecretStore (Fernet-verschlüsselt,
Masterkey im OS-Keyring) und können jederzeit über das Settings-
Dashboard oder direkt im SecretStore neu gesetzt werden — Token-Klau
benötigt also Filesystem-Zugriff plus den Keyring. Eine zeitgesteuerte
Auto-Rotation wird erst sinnvoll, wenn separate Refresh-/Access-Tokens
eingeführt werden (Token-Familien, siehe Phase-70-Notiz im Journal).

### M4 — LLM-Provider-Sichtbarkeit

Alle Matrix-Inhalte, Doc-Summary-Resultate und Web-Search-Snippets
gehen **1:1** an den konfigurierten LLM-Provider (Anthropic / OpenRouter
/ Ollama). Das ist kein Bug, sondern Architektur — aber jeder Nutzer
sollte wissen, dass private Matrix-Konversationen damit beim Provider
landen.

**Mitigation:** Wer das vermeiden will, nutzt **lokales Ollama**
(Default für Embeddings, optional auch für Generation). Die Auswahl
des LLM-Providers ist im Setup-Wizard (Phase 46) sichtbar
dokumentiert. Privacy-Policy je Provider:
- Anthropic: kein Training auf API-Daten
- OpenRouter: variiert je Backend, siehe Provider-Settings
- Ollama: lokal, kein Cloud-Traffic

### M5 — CSRF-Schutz: SameSite-strict statt Token

State-changing Dashboard-Routen verlassen sich auf **`SameSite=strict`-
Cookies + Origin-Check** (Phase 64), nicht auf einen klassischen
CSRF-Token im Formular. Das Real-Risk ist in modernen Browsern minimal:
SameSite-strict verhindert Cross-Site-Requests komplett, der Origin-
Check fängt böswillige Same-Site-Requests von Subdomains ab.

**Mitigation:** Kein zusätzlicher Schutz nötig für den Threat-Vektor
"böswillige fremde Website tricks Browser". Wenn ein Angreifer JS
auf einer Same-Site-Domain ausführen kann, ist das ein anderes
Problem (XSS, das CSP in Phase 63 entschärft hat). Für strenge
Compliance-Anforderungen wäre ein Double-Submit-Cookie- oder
Synchronizer-Token-Pattern nachrüstbar.

## Threat-Model in Kurzform

Elder-Berry ist als **persönlicher Assistent** designt — primärer
Threat-Vektor ist **versehentliche Exposition ins Internet**, nicht
gezielte Angriffe. Das Repo enthält bewusst Härtungen für den Fall,
dass jemand z.B. den RPi5-Server versehentlich auf `0.0.0.0` exponiert.

Außerhalb des Threat-Models (würde ich akzeptieren, ohne zu fixen):
- Lokaler Angreifer mit OS-Account auf der Tower-Maschine
  (kann sowieso alles)
- Browser-Extensions, die das Dashboard manipulieren (User vertraut
  seinem eigenen Browser)

Wenn du dir unsicher bist, ob etwas im Threat-Model liegt — einfach
einen Advisory aufmachen, lieber einen False-Positive als ein
übersehenes Problem.
