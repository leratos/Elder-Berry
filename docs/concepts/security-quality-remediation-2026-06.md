# Sicherheit & Codequalität – Remediation-Übersicht (Phasen 103–106)

**Stand:** 2026-06-16 · **Quelle:** `docs/analyse-sicherheit-codequalitaet-2026-06-09.md`
**Methode:** Jeder Befund der Analyse wurde am 2026-06-15/16 gegen den aktuellen
`main`-Code re-verifiziert (Multi-Agent-Mapping, je Befund file:line + adversariale
Prüfung). Diese Übersicht bündelt die Befunde zu umsetzbaren Konzept-Paketen.

## Befund → Phase / Status

| Befund | Kurz | Status (2026-06-16) | Phase |
|---|---|---|---|
| **S1** | Fail-open-Auth Agent/Robot | Teilweise offen* | **103** |
| **S2** | XML-Parsing ungehärtet (XXE/Billion-Laughs) | Offen | **103** |
| **S4** | SQL per f-String (kein Allowlist-Guard) | Offen | **103** |
| **S3** | Silent Exception Swallows | Offen (kleiner als gedacht**) | **104** |
| **Q2** | Breite `except Exception` | Offen | **104** |
| **Q5** | Schuld-Marker (TODO/FIXME) → Journal | Offen | **104** |
| **Q3** | mypy-strict nur partiell (agent/robot) | Offen | **105** |
| **Q1** | Sehr große Dateien | Offen (leicht gewachsen) | **106** |
| S5 | Simulator 0.0.0.0 ohne Auth | In S1/Phase 103 mitbehandelt | 103 |
| S6 | Bandit-False-Positives | Kein Handlungsbedarf | — |
| **Q4** | CI-Lint enger als lokal | ✅ **erledigt** (Phase 99) | — |

\* **S1-Korrektur:** Der RPi-Robot-Start (`scripts/start_rpi5.py`) ist seit
Phase 64 **bereits fail-closed** (`_enforce_robot_token_policy` → `sys.exit(2)`
bei Non-Loopback-Bind ohne Token, voll getestet in `tests/test_start_rpi5_token.py`).
Die Fail-open-Stellen in den Middlewares (`agent/server.py:67`, `robot/server.py:262`)
sind *by design* — der Schutz gehört in den Start-/Bind-Pfad. Real offen sind nur
zwei Einstiegspunkte: der **Robot-Simulator** (`simulator.py` bindet auf `0.0.0.0`
nur mit Warnung) und der **AgentServer** (hat gar keinen produktiven Start-Pfad,
nur eine Konstruktor-Warnung).

\** **S3-Korrektur:** Von den ~15 von bandit gemeldeten `except: pass/continue`
sind die meisten bewusst korrekte *enge* Catches (best-effort cleanup, optionale
Dependency, Encoding-/Timezone-Fallback). Nur **eine** Stelle
(`carddav_sync.py:799`, breiter Swallow bei Netzfehlern → stilles falsches
„Kontakt nicht gefunden") hat echtes Daten-/Funktions-Risiko.

## Leitprinzipien der Remediation

- **Klein, nachvollziehbar, testbar** (AGENTS.md): jede Phase ist ein eigener
  Branch mit eigenem Konzept-Doc und voller pytest-Abdeckung; keine großen,
  unklaren Umbauten in einem Schritt.
- **Verhalten erhalten, Sicherheit erhöhen**: S1/S2/S4 sind additive Härtungen,
  die den Happy-Path nicht ändern (Guards, die im Normalpfad nicht auslösen;
  XML-Drop-in; defensive Allowlist).
- **Fail-closed statt fail-open** für netz-/extern-exponierte Pfade.
- **Eine Quelle der Wahrheit**: die Bind-Policy (S1) lebt künftig an *einer*
  Stelle (`core/bind_policy.py`) statt dreifach kopiert.

## Reihenfolge & Begründung

1. **Phase 103 (Sicherheit, zuerst):** S1 + S2 + S4. Kleinster Aufwand, höchster
   Sicherheitsnutzen, kein Architektur-Risiko.
2. **Phase 104 (Robustheit):** S3 + Q2 + Q5. Beobachtbarkeit; beginnt mit dem
   einen echten S3-Fund und den netz-exponierten Q2-Hotspots (robot/agent),
   nicht mit dem riskanten comms-Cluster.
3. **Phase 105 (Typen):** Q3. mypy-strict für agent (klein) und robot (mittel).
4. **Phase 106 (Wartbarkeit):** Q1. Modul-Entflechtung der >1000-Zeilen-Dateien,
   beginnend mit `message_handlers.py`. Größter Umbau, daher zuletzt.

## Laufende Prozess-Punkte (keine eigene Phase)

- **pip-audit** in der echten CI grün halten (Empfehlung #8 der Analyse) – ist
  bereits Pipeline-Schritt (`ci.yml` security-Job), Ergebnis periodisch ins
  Journal.
- **Q4** (CI-Lint-Angleichung) wurde in **Phase 99** erledigt: der blockierende
  CI-Schritt fährt jetzt den vollen Ruff-Satz zentral aus `pyproject.toml`
  (`ruff check src/ tests/ scripts/ tower/`), kein Subset mehr.

## Detail-Konzepte

- `docs/concepts/phase-103-server-parser-haertung.md` (S1, S2, S4)
- `docs/concepts/phase-104-fehler-disziplin-beobachtbarkeit.md` (S3, Q2, Q5)
- `docs/concepts/phase-105-mypy-strict-agent-robot.md` (Q3)
- `docs/concepts/phase-106-modul-entflechtung.md` (Q1)
