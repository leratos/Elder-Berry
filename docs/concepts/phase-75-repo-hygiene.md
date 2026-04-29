# Phase 75 – Repo-Hygiene 🧹

**Status:** Konzept (2026-04-29)
**Branch:** `chore/phase-75-repo-hygiene`
**Aufwand:** ~1–2 Stunden
**Voraussetzung:** keine
**Roadmap-Referenz:** Quick Win vor Phase 76 (mypy) und Phase 77 (Plugin-Registry)

## 1. Ausgangslage

Nach 74 abgeschlossenen Phasen hat sich im lokalen Repo Sediment angesammelt,
das vor den nächsten größeren Refactorings (mypy-Rollout, Plugin-Registry)
weggeräumt werden sollte. Konkrete Funde aus Audit am 2026-04-29:

- **A1 – Mindestens 10 lokale Branches sind gemergt** (`git branch --merged main`):
  `claude/elated-morse`, `claude/elegant-cannon-09b34d`, `claude/happy-newton-a496df`,
  `claude/peaceful-brahmagupta-ec3b6c`, `claude/recursing-hofstadter-c5efe9`,
  `claude/reverent-sammet-3b1164` und weitere. Bei Squash-Merges sind sie
  via `--merged` nicht erkannt — die tatsächliche Zahl ist höher.
- **A2 – Phase-Branches nach Abschluss nicht aufgeräumt:** `chore/auth-hardening-pw-bcrypt`,
  `chore/public-release-cleanup`, `chore/public-release-hygiene-round-2`,
  `feature/phase-73-*` (vier Stück), `feature/phase-74-codecov`,
  `fix/path-traversal-document-pdf-commands`, `fix/session-and-web-hardening`,
  `docs/asset-licensing` — alle laut Journal abgeschlossen.
- **A3 – Alter Stash:** `stash@{0}: WIP on feature/phase-33-smart-context-layer:
  baf75e9 feat(phase-33): Smart Context Layer ...`. Phase 33 ist seit längerem
  in `main`, der Stash ist tot.
- **A4 – `.git/index.lock` blockiert sporadisch:** Beim Status-Check trat
  `warning: unable to unlink '.git/index.lock'` auf. Vermutlich ein hängender
  Background-Prozess (VS Code Git-Indexer, PowerShell-Tab).
- **A5 – Versionsstand inkonsistent:** `pyproject.toml` enthält weiterhin
  `version = "0.1.0"`, obwohl 70+ Phasen abgeschlossen sind. Forks und
  Issue-Reporter haben keinen Versions-Anker.
- **A6 – Kein lokales pre-commit:** CI prüft `ruff` + `pip-audit`, aber
  Lint-Fehler werden erst nach Push sichtbar — verursacht Mini-PRs nur für
  Lint-Fixes.

## 2. Ziel

1. Alle gemergten Branches lokal entfernt, ohne Datenverlust.
2. Alter Stash gesichert und gedroppt.
3. `.git/index.lock`-Quelle geklärt und Datei entfernt.
4. `pyproject.toml`-Version auf einen ehrlichen Stand bringen.
5. Optional: `pre-commit`-Hook etabliert, der `ruff` und
   `check_public_readiness.py` lokal prüft.

## 3. Vorgehen

### 3.1 Branch-Cleanup (sicher)

Drei-Schritt mit `-d` (klein), nicht `-D`:

```bash
# Schritt 1: Echte Merges identifizieren
git branch --merged main | grep -v "^\* main$" > /tmp/merged.txt

# Schritt 2: Squash-Merges via gh CLI (falls verfügbar)
gh pr list --state merged --limit 200 --json headRefName \
  --jq '.[].headRefName' > /tmp/squashed.txt

# Schritt 3: Per Branch löschen mit -d (Git verweigert bei unmerged Commits)
for b in $(cat /tmp/merged.txt); do git branch -d "$b"; done
for b in $(cat /tmp/squashed.txt); do git branch -d "$b" 2>/dev/null || true; done

# Schritt 4: Remote-Tracking pruning
git remote prune origin
git config --global fetch.prune true
```

`-d` ist die Sicherung: bei tatsächlich verlorenen Commits verweigert Git die
Löschung. Erst dann darf manuell mit `git log <branch>` geprüft werden, ob der
Inhalt noch gebraucht wird.

### 3.2 Stash-Cleanup

```bash
# Backup als Patch-Datei (nur für Notfall, nicht ins Repo committen)
git stash show -p stash@{0} > ~/elder-berry-stash-phase33-backup.patch

# Drop
git stash drop stash@{0}
git stash list  # sollte leer sein
```

Phase 33 (Smart Context Layer) ist seit 2026-02 in `main` — kein offener
Punkt mehr. Backup-Patch dient nur der Beruhigung.

### 3.3 Index-Lock klären

```bash
# Nur wenn KEIN Git-Prozess läuft
ps aux | grep -i git | grep -v grep   # leer?
ls -la .git/index.lock                # noch da?
rm .git/index.lock
```

Falls die Datei wiederkommt:
- VS Code Git-Erweiterung deaktivieren / Workspace neu öffnen
- PowerShell-Tabs schließen
- `.vscode/settings.json` prüfen, ob ein Watcher das Repo scant

### 3.4 Versionsbump

Zwei Vorschläge zur Wahl:

**Option A — Phasen-Tracking:** `version = "0.74.0"` (folgt der
Phasen-Nummerierung, transparent für Kontext).

**Option B — Public-Release-RC:** `version = "1.0.0-rc1"` (signalisiert
Reife in Richtung Public-Launch).

Empfehlung: **Option A**. Die Phasen-Nummer ist die de-facto-Versionierung
des Projekts. Bei Public-Release dann gezielter Sprung auf `1.0.0`.

Zusätzlich `__version__` in `src/elder_berry/__init__.py`:

```python
"""Elder-Berry – modulare KI-Assistentin."""
__version__ = "0.74.0"
```

Damit funktioniert `python -c "import elder_berry; print(elder_berry.__version__)"`
und Setup-Wizard / Self-Update-Phase können die Version sauber lesen.

### 3.5 pre-commit (optional)

`.pre-commit-config.yaml` im Repo-Root:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.13.0
    hooks:
      - id: ruff
        args: [--select, "E9,W605,F401,B", --ignore, "B008"]
      - id: ruff-format

  - repo: local
    hooks:
      - id: public-readiness
        name: Public-Readiness Check
        entry: python scripts/check_public_readiness.py
        language: system
        pass_filenames: false
        stages: [pre-push]
```

Aktivierung:
```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type pre-push
```

`pre-push` (statt `pre-commit`) für `check_public_readiness.py`, weil der Check
eher selten und dafür gründlich laufen soll, nicht bei jedem Mini-Commit.

## 4. Risiken

- **R1 – Verlust unmerged Commits in `claude/*`-Branches:**
  Mitigation: `git branch -d` (klein) verweigert; Backup-Patch falls nötig.
- **R2 – Versionsbump bricht Semver-Erwartung:**
  Sprung von `0.1.0` auf `0.74.0` ist groß. Falls extern jemand `pip install elder-berry`
  macht, bekommt er die neue Version. Da das Repo nicht auf PyPI steht,
  Risiko praktisch null.
- **R3 – pre-commit blockiert legitime Commits:**
  Fallback: `git commit --no-verify` für Notfälle dokumentieren. Generell
  pre-commit nur als *Empfehlung* dieser Phase, nicht zwingend.

## 5. Tests / Akzeptanzkriterien

- `git branch -a | wc -l` deutlich kleiner (Ziel: <10 lokale Branches).
- `git stash list` ist leer.
- `.git/index.lock` ist nicht mehr da.
- `python -c "import elder_berry; print(elder_berry.__version__)"` gibt `0.74.0`.
- `pyproject.toml` `version = "0.74.0"`.
- Optional: `pre-commit run --all-files` läuft fehlerfrei durch.
- Pytest-Suite läuft weiterhin grün (4916 passed, 29 skipped — keine Code-Änderungen außer Versions-Strings).

## 6. Out of Scope

- Refactoring von Code in `src/`. Reine Hygiene-Phase.
- Änderungen an `docs/`, außer dieser Konzeptdatei selbst.
- Roadmap-Update — erfolgt erst beim Phasen-Start als „IN ARBEIT" und
  am Ende als „ABGESCHLOSSEN".

## 7. Folge-Phasen

- **Phase 76 (mypy-Rollout core/):** profitiert von sauberem Branch-Stand
  und etabliertem `pre-commit`, falls dort später `mypy` als Hook läuft.
- **Phase 77 (Plugin-Registry):** profitiert vom Versionsbump (klare
  Version pro Plugin-Manifest später).
