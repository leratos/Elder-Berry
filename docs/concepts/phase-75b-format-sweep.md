# Phase 75b – Format-Sweep mit ruff-format 🎨

**Status:** Konzept (2026-05-01)
**Branch:** `chore/phase-75b-format-sweep`
**Aufwand:** ~30 Min (1 Befehl + Verifikation)
**Voraussetzung:** Phase 75 (Repo-Hygiene) gemerged
**Roadmap-Referenz:** Folge-Quick-Win nach Phase 75, vor Phase 76 (mypy)

## 1. Ausgangslage

In Phase 75 hat der erste pre-commit-Lauf gezeigt, dass `ruff format`
**~300 Python-Dateien** reformatieren würde. Die Codebase ist nie
ruff-format-konsistent geworden — vermutlich, weil das Projekt vor
ruff-Adoption mit verschiedenen Formattern (autopep8, black) und
Hand-Edit lief.

In Phase 75 wurde der Format-Sweep bewusst ausgeklammert (`stages: [manual]`),
weil 300-Dateien-Diff disproportional zu „Repo-Hygiene" gewesen wäre und
`git blame` für 300 Files verschoben hätte. Phase 75b holt das jetzt
gezielt nach — als eigener PR, der nichts anderes tut.

## 2. Ziel

1. Komplette Python-Codebase einmal durch `ruff format` schicken.
2. `.pre-commit-config.yaml`: `ruff-format` von `stages: [manual]`
   zurück auf default (= bei jedem Commit), damit der formatierte Stand
   nicht wieder driftet.
3. Tests vor/nach identisch grün (5016 passed, 3 skipped).
4. Genau ein Commit, klar als „nur Format" markiert für späteres
   `git blame --ignore-revs-file`.

**Nicht-Ziele:**
- Code-Logik anfassen.
- Lint-Regeln ändern (ruff lint bleibt wie in Phase 75: `E9,W605,F401,B,!B008`).
- Docstrings, Type-Hints oder Kommentar-Inhalte editieren.
- Imports neu sortieren (`ruff check --fix --select I` wäre eigene Phase).

## 3. Vorgehen

### 3.1 Auf dem Tower

```powershell
cd C:\Dev\Elder-Berry
git checkout main
git pull --ff-only
git checkout -b chore/phase-75b-format-sweep

# Tests vor Sweep (Baseline)
.venv\Scripts\python.exe -m pytest tests/ -q
# Erwartung: 5016 passed, 3 skipped

# Format-Sweep ueber alles, was ruff sieht
pre-commit run --hook-stage manual ruff-format --all-files
# Alternativ direkt:
# .venv\Scripts\python.exe -m ruff format src/ tests/ scripts/

# Tests nach Sweep (muessen identisch sein)
.venv\Scripts\python.exe -m pytest tests/ -q
# Erwartung: 5016 passed, 3 skipped (unveraendert)

# Diff-Stat zur Sicht
git diff --stat | tail -1
# Erwartung: ~300 files changed
```

### 3.2 pre-commit-Config zurückstellen

`stages: [manual]`-Zeile aus `.pre-commit-config.yaml` entfernen, sodass
der Hook bei jedem Commit läuft. Der Kommentar von Phase 75 wird
ebenfalls aktualisiert.

### 3.3 Commit-Layout

**Genau ein Commit:**

```
chore(phase-75b): ruff-format sweep -- alle Python-Dateien angeglichen
```

Body sagt explizit:
- 300 Dateien reformatiert, kein Code-Verhalten geändert.
- Tests vor/nach identisch (5016 passed, 3 skipped).
- pre-commit-Hook von manual auf default zurück.
- Empfehlung: Commit-SHA in `.git-blame-ignore-revs` eintragen.

### 3.4 `.git-blame-ignore-revs`-Empfehlung (optional, Folge-Phase)

GitHub und IDEs respektieren `.git-blame-ignore-revs` — eine Datei mit
Commit-SHAs, die `git blame` automatisch überspringen soll (z. B. reine
Format-Sweeps). Nach dem Push:

```bash
echo "<phase-75b-commit-sha>  # Phase 75b ruff-format sweep" \
    >> .git-blame-ignore-revs
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

Das wäre ein winziger Folge-Commit (nicht Teil von 75b selbst, weil die
SHA erst nach dem Format-Commit existiert).

## 4. Risiken / aktive Hinweise

- **R1 — Test-Drift trotz reinem Format:** `ruff format` ändert keine
  Semantik, aber wenn ein Test sich auf exakte Formatierung in einem
  String oder Repr verlässt, kann er failen. Mitigation: Tests vor und
  nach Sweep vergleichen, bei Drift Test inspizieren.
- **R2 — Imports werden nicht sortiert.** `ruff format` macht nur
  Format, kein Import-Sort. Falls du Import-Sort willst, ist das
  separate Phase (`ruff check --select I --fix`).
- **R3 — `git blame` für 300 Files verschoben.** Das ist der Preis. Mit
  `.git-blame-ignore-revs` (siehe 3.4) lässt sich der Effekt
  zurücknehmen.
- **R4 — VS Code File-Watcher:** Bei 300 gleichzeitigen Datei-Änderungen
  kann VS Code's TypeScript/Python-Server ins Stolpern kommen.
  Mitigation: VS Code während Sweep schließen oder Workspace neu laden
  danach.
- **R5 — Merge-Konflikte mit offenen PRs:** Falls aktuell ein anderer
  Branch geöffnet ist, der Code-Änderungen enthält, kollidieren die
  Format-Änderungen oft mit Code-Änderungen. Aktuell keine offenen
  Phase-Branches (Phase 75 ist gemerged, 76 noch nicht gestartet) —
  daher kein Risiko jetzt. **Phase 75b sollte vor Phase 76 laufen,
  nicht parallel.**

## 5. Tests / Akzeptanzkriterien

- `pytest tests/ -q` vor & nach Sweep: identische Zahlen
  (5016 passed, 3 skipped).
- `ruff format --check src/ tests/ scripts/`: Exit 0 (alles formatiert).
- `pre-commit run --all-files` (mit dem geupdatetern Hook):
  ruff-format `Passed`.
- `git diff --stat | tail -1`: ~300 Dateien geändert, alle in
  `src/`, `tests/`, `scripts/`.
- Spot-Check: drei zufällige reformatierte Dateien öffnen und
  überprüfen, dass nur Format geändert wurde (Whitespace, Zeilenumbrüche,
  Anführungszeichen-Style).

## 6. Folge-Phasen

- **Phase 75c (optional):** `.git-blame-ignore-revs` mit dem Phase-75b-
  Commit-SHA pflegen. Winziger Commit, kann auch in Phase 76 mitgenommen
  werden.
- **Phase 75d (optional):** Import-Sort mit `ruff check --select I --fix`
  über die Codebase. Eigener PR, weil das semantisch *näher* an Code
  ist (Import-Reihenfolge kann minimale Verhalten beeinflussen, z. B.
  Side-Effects beim Import).
