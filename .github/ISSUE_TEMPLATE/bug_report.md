---
name: Bug Report
about: Etwas funktioniert nicht wie erwartet.
title: "[Bug] "
labels: bug
assignees: ''
---

> Erst die Lese-Liste: passt das hier zur [Maintenance-Pace](../../blob/main/CONTRIBUTING.md#was-das-bedeutet)
> (persönliches Projekt, keine SLA)? Wenn nicht — danke trotzdem fürs
> Schauen, aber dann lieber kein Issue.

## Was ist passiert?

<!-- Eine bis zwei Sätze. Kurz und konkret. -->

## Wie reproduzieren?

1. ...
2. ...
3. ...

## Erwartetes Verhalten

<!-- Was hättest du erwartet? -->

## Tatsächliches Verhalten

<!-- Was ist stattdessen passiert? Stack-Trace bitte komplett, nicht abgeschnitten. -->

```text
<Stack-Trace / Log-Output hier>
```

## Umgebung

- **Komponente** (welcher Teil von Elder-Berry?):
  - [ ] Tower (Hauptmaschine, Windows)
  - [ ] Laptop-Client (Windows)
  - [ ] RPi5 (Linux, Avatar/Display)
  - [ ] Matrix-Bot
  - [ ] Dashboard / Webapp
  - [ ] CLI / Setup-Wizard
  - [ ] Andere: ___
- **OS / Plattform**: <!-- z.B. Windows 11 24H2, Raspberry Pi OS Bookworm -->
- **Python-Version**: <!-- python --version -->
- **Commit-SHA / Branch**: <!-- git rev-parse HEAD -->
- **Installation**: pip install -e ".[...]" mit welchen Optional-Gruppen?

## Zusatz-Kontext

<!-- Screenshots, Logs, alles was hilft. Bitte keine Secrets posten -->
<!-- (.env, Tokens, IPs aus Heimnetz). -->

## Sicherheits-Bug?

Wenn das eine Sicherheitslücke ist: **bitte kein öffentliches Issue**,
sondern via [GitHub Security Advisory](https://github.com/leratos/Elder-Berry/security/advisories/new).
Details in [SECURITY.md](../../blob/main/SECURITY.md).
