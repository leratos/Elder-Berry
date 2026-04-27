# Contributing to Elder-Berry

Erstmal: Danke, dass du reinschaust. Bevor du Zeit investierst, eine
ehrliche Erwartungshaltung — Elder-Berry ist ein **persönliches
Projekt**, kein Community-getriebenes Open-Source-Produkt.

## Was das bedeutet

- **Pull Requests sind willkommen**, aber ich rekrutiere nicht aktiv
  und kann keine Garantien für Bug-Fixes auf fremder Hardware geben.
- **Issues sind ok**, aber Setup-spezifische Probleme (z.B. "läuft
  nicht auf meinem Synology NAS") werde ich oft nicht selbst
  reproduzieren können.
- **Feature-Requests** beantworte ich nach persönlicher Roadmap. Was
  ich nicht selbst nutze, baue ich nicht.
- **Maintenance-Pace**: ein paar Tage bis ein paar Wochen
  Reaktionszeit. Antworten möglich, aber nicht garantiert.

Wenn du auf der Basis trotzdem mitmachen willst — fantastisch, los
geht's.

## Was bei mir gut ankommt

### 1. Bug-Fixes mit Test-Abdeckung
Pull Request mit:
- Klarer Reproduktion des Fehlers (Schritte, Plattform, Stack-Trace)
- Fix, der die Ursache adressiert (nicht nur das Symptom)
- Test, der den Fehler vorher zeigt und nachher grün ist

Lauf der vollen Testsuite (`pytest tests/ -q`) muss durchgehen.

### 2. Plattform-Verbesserungen
Elder-Berry läuft offiziell nur auf Windows (Tower/Laptop) und Linux
(RPi5/Server). macOS-Support oder Container-Verbesserungen sind sehr
willkommen, solange sie die bestehenden Pfade nicht brechen.

### 3. Doku-Verbesserungen
Tippfehler, fehlende Setup-Schritte, unklare Beispiele — sehr gerne.
Doku-PRs reviewe ich am schnellsten.

### 4. Sicherheits-Reports
Bitte **nicht** als öffentliches Issue, sondern via
[GitHub Security Advisory](https://github.com/leratos/Elder-Berry/security/advisories/new).
Details in [SECURITY.md](SECURITY.md).

## Was bei mir eher nicht ankommt

- **Größere Refactors ohne vorherige Diskussion.** Bitte erst ein
  Issue aufmachen und Konsens suchen, bevor du 2000 Zeilen Diff
  abschickst.
- **Architektur-Änderungen, die meinen Workflow brechen.** Konkretes
  Beispiel: Rewrite vom SecretStore auf Vault. Würde ich nicht
  mergen, weil zu invasiv für ein Privat-Setup.
- **PRs ohne Tests.** Auch kleine Features brauchen einen
  Happy-Path-Test.
- **Style-Wars.** Linting läuft in CI (ruff). Was da grün ist, ist
  ok — bitte keine Diskussionen über Quote-Style oder Line-Length.

## Entwicklungs-Setup (lokal)

```bash
git clone https://github.com/leratos/Elder-Berry.git
cd Elder-Berry

# Python 3.12+
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\activate              # Windows

# Core + Dev-Dependencies
pip install -e ".[robot,agent,dev]"

# Optional: Tower-Vollausstattung (nur Windows)
pip install -e ".[tower]"

# Tests laufen
pytest tests/ -q

# Linting
ruff check src/ tests/ --select E9,W605,F401,B --ignore B008
```

## Commit-Message-Stil

Frei, aber bitte **deutsch oder englisch konsistent** und ein klares
Subject (≤ 70 Zeichen). Body mit Begründung wenn nicht trivial.
Beispiele aus dem Repo:

```
feat(security): Phase 64 -- CSRF/SSRF/Robot-Token Hard-Fail
fix: PR #124 review (P1) -- Berry-Gym Default + Matrix-Homeserver
docs: Phase 67 -- CHANGELOG.md fuer Public-Story
```

Phasen-Nummern in Commits beziehen sich auf die interne Roadmap und
sind für Externe optional.

## Lizenz

Beiträge stehen unter der [MIT-Lizenz](LICENSE) — dieselbe wie der
Rest des Projekts.

## Code of Conduct

Siehe [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). TL;DR: Sei
respektvoll, sei konkret, kein Ad-hominem.

---

Bei Fragen zum Beitragen einfach ein Issue mit Label `question`
öffnen.
