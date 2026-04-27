<!--
  Danke fuer den PR. Bevor du auf "Create Pull Request" klickst:
  - Pflicht: Tests gruen lokal (.venv\Scripts\python.exe -m pytest).
  - Pflicht: keine neuen Secrets / personenbezogenen Daten im Diff.
  - Bei groesseren Aenderungen: vorher ein Issue (siehe CONTRIBUTING.md).
-->

## Was

<!-- Eine bis zwei Sätze: was ändert dieser PR? -->

## Warum

<!-- Welches Problem löst das? Verlinkter Issue / Roadmap-Phase. -->

Closes #

## Test-Plan

<!-- Wie hast du das getestet? Welche Tests sind neu/angepasst? -->

- [ ] Unit-Tests laufen lokal grün (`.venv\Scripts\python.exe -m pytest`)
- [ ] Linting grün (`ruff check src/ tests/ --select E9,W605,F401,B --ignore B008`)
- [ ] Manueller Smoke-Test (falls UI / externer Service): ___

## Plattform-Impact

- [ ] Tower (Windows)
- [ ] Laptop-Client (Windows)
- [ ] RPi5 (Linux)
- [ ] Plattform-unabhängig

## Checkliste

- [ ] Tests grün, keine neuen Skips ohne Begründung im Code-Kommentar
- [ ] Keine neuen Hardcoded-Secrets, IPs, Domains, Hostnames
- [ ] Keine neuen Dependencies in `[dependencies]` ohne Diskussion
  (Optional-Gruppen sind ok, siehe `pyproject.toml`)
- [ ] Journal aktualisiert (falls Phase abgeschlossen — `docs/journal.txt`)
- [ ] Roadmap aktualisiert (falls Phase abgeschlossen —
  `docs/PROJECT_ROADMAP.md`)
- [ ] Doku/README angepasst, falls sich Verhalten oder Setup ändert

## Sonstiges

<!-- Breaking-Changes, Migration-Hinweise, bekannte Limitierungen. -->
