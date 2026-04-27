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
