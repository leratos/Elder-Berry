# Phase 15: Self-Update (Git Pull + Dependency Install + Restart)

> **Status:** Geplant
> **Erstellt:** 2026-03-19 (Claude App)
> **Umsetzung:** Claude Code
> **Abhängigkeit:** Restart-Mechanismus (Phase 7, bereits abgeschlossen)
> **Branch:** `feature/phase-15-self-update`

---

## Übersicht

Saleria kann sich auf Befehl selbst aktualisieren: Code von GitHub ziehen,
neue Dependencies installieren und sich neu starten.

**Use-Case:** Entwicklung auf dem Laptop, Push nach GitHub, dann via Matrix:
"Schau dir deine neuen Funktionen an" → Saleria aktualisiert sich auf dem Tower.

**Abgrenzung zu bestehenden Commands:**
- `git pull` (Phase 7) → zieht nur Code, installiert nichts, startet nicht neu
- `restart` (Phase 7) → startet nur neu, zieht keinen Code
- `update` (NEU) → git pull + pip install + restart als atomare Sequenz

---

## VORBEREITUNG

Bevor du mit der Implementierung beginnst:

1. Lies `C:\Dev\Elder-Berry\docs\journal.txt` (letzte 80 Zeilen)
2. Lies dieses Konzept-Dokument komplett durch
3. Erstelle Branch: `git checkout -b feature/phase-15-self-update`
4. Schreibe Draft-Eintrag in journal.txt

---

## Bestehende Mechanismen (wiederverwenden)

### Git Pull (process_commands.py)
- `_cmd_git()` führt `git pull` via `subprocess.run()` aus
- CWD = `self._project_root` (C:\Dev\Elder-Berry)
- Whitelist: nur status/pull/log/diff erlaubt
- Output wird zurückgegeben (Text-Antwort an Matrix)

### Restart (system_commands.py + bridge.py)
- `_cmd_restart()` → `CommandResult(restart=True)`
- Bridge erkennt `result.restart` → `_perform_restart()`
- `_perform_restart()`: Flag-Datei schreiben → disconnect → `os.execv(python, [python, *sys.argv])`
- Nach Neustart: Flag-Datei lesen → "Bin wieder da!"-Nachricht an Matrix

---

## 15.1 – Update-Flow

### Sequenz (ein einziger Command)

```
User: "update dich" / "schau dir deine neuen Funktionen an"
    ↓
1. Saleria → Matrix: "Prüfe auf Updates..."
    ↓
2. git fetch + git status: Prüfe ob Remote-Änderungen vorliegen
    ↓
   Keine Änderungen → "Alles aktuell, kein Update nötig." → STOP
    ↓
3. git pull: Code aktualisieren
    ↓
   Conflict/Fehler → "Git Pull fehlgeschlagen: <output>" → STOP
    ↓
4. Prüfe ob pyproject.toml in geänderten Dateien
    ↓
   JA → pip install -e ".[alle-extras]" → Ergebnis melden
   NEIN → "Keine neuen Dependencies."
    ↓
5. Saleria → Matrix: "Update geladen: <git log --oneline der neuen Commits>.
   Starte neu..."
    ↓
6. CommandResult(restart=True) → Bridge → _perform_restart() → os.execv
    ↓
7. Nach Neustart: "Bin wieder da! Update abgeschlossen. 🌿"
```

### Wichtige Design-Entscheidung: Fortschrittsmeldungen

Das Problem: `execute()` gibt ein einzelnes `CommandResult` zurück. Der Update-Prozess
hat aber mehrere Schritte (fetch, pull, pip install), die jeweils 5-30 Sekunden dauern.
Der User sieht in Matrix erst die Antwort NACH dem kompletten Durchlauf.

**Option A: Alles in einem CommandResult (einfach)**
- Alle Schritte laufen, Gesamtergebnis als ein Text-Block
- User wartet 10-30s ohne Feedback
- Vorteil: Kein Umbau der Bridge nötig

**Option B: Callback für Zwischenmeldungen (besser UX)**
- `execute()` bekommt optionalen `progress_callback: Callable[[str], None]`
- Jeder Schritt meldet sich: "Git Pull...", "Dependencies installieren...", "Neustart..."
- Vorteil: User sieht Fortschritt live
- Nachteil: CommandHandler ABC muss erweitert oder Callback muss durch
  Orchestrator/Bridge durchgereicht werden

**Empfehlung: Option A für v1.**
Ein Update ist ein seltener, expliziter Vorgang (1-2x pro Woche). 10-30s Wartezeit
ist akzeptabel. Callback-Infrastruktur für einen einzigen Command überkomplex.
Stattdessen: Gesamtergebnis als mehrzeiliger Text mit Status pro Schritt.

---

## 15.2 – Implementierung

### Geänderte Datei: `src/elder_berry/comms/commands/process_commands.py`

**Neues Pattern:**
```python
UPDATE_PATTERN = re.compile(
    r"^(?:update|aktualisier|updat)\s*(?:dich|saleria)?",
    re.IGNORECASE,
)
```

**Neuer Simple-Command:** `"update"` in `simple_commands` Set

**Neue Keywords:**
```python
"update": [
    "update dich", "aktualisiere dich", "neue funktionen",
    "schau dir deine neuen funktionen an", "mach ein update",
    "git pull und neustart", "update saleria",
],
```

**Neue Methode: `_cmd_update()`**

```python
def _cmd_update(self) -> CommandResult:
    """Self-Update: git pull + pip install (wenn nötig) + restart.

    Sequenz:
    1. git fetch origin
    2. Prüfe ob lokaler Branch hinter Remote ist
    3. git pull
    4. Prüfe ob pyproject.toml geändert wurde
    5. pip install -e ".[extras]" wenn nötig
    6. Return restart=True

    Returns:
        CommandResult mit restart=True bei Erfolg.
    """
    if not self._project_root:
        return CommandResult(
            command="update",
            success=False,
            text="Projekt-Root nicht konfiguriert.",
        )

    cwd = str(self._project_root)
    steps: list[str] = []  # Fortschrittsmeldungen sammeln

    # --- Schritt 1: git fetch ---
    fetch = self._run_cmd(["git", "fetch", "origin"], cwd=cwd, timeout=30)
    if not fetch.success:
        return CommandResult(
            command="update",
            success=False,
            text=f"Git Fetch fehlgeschlagen:\n{fetch.output}",
        )
```

```python
    # --- Schritt 2: Prüfe ob Änderungen vorliegen ---
    status = self._run_cmd(
        ["git", "status", "-uno", "--porcelain"],
        cwd=cwd, timeout=10,
    )
    behind = self._run_cmd(
        ["git", "rev-list", "--count", "HEAD..@{u}"],
        cwd=cwd, timeout=10,
    )
    commits_behind = int(behind.output.strip()) if behind.success else 0

    if commits_behind == 0:
        return CommandResult(
            command="update",
            success=True,
            text="✅ Alles aktuell – kein Update nötig.",
        )

    steps.append(f"📥 {commits_behind} neue(r) Commit(s) verfügbar")

    # --- Schritt 3: Prüfe auf lokale Änderungen (uncommitted) ---
    if status.success and status.output.strip():
        return CommandResult(
            command="update",
            success=False,
            text=(
                "⚠️ Lokale Änderungen vorhanden – Update abgebrochen.\n"
                "Bitte erst committen oder stashen:\n"
                f"```\n{status.output.strip()}\n```"
            ),
        )
```

```python
    # --- Schritt 4: git pull ---
    # Merke Commit-Hash vorher (für Diff)
    old_hash = self._run_cmd(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=cwd, timeout=5,
    )

    pull = self._run_cmd(["git", "pull", "--ff-only"], cwd=cwd, timeout=60)
    if not pull.success:
        return CommandResult(
            command="update",
            success=False,
            text=f"❌ Git Pull fehlgeschlagen:\n{pull.output}",
        )
    steps.append("✅ Code aktualisiert")

    # Neue Commits auflisten (was hat sich geändert?)
    new_hash = self._run_cmd(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=cwd, timeout=5,
    )
    if old_hash.success and new_hash.success:
        log = self._run_cmd(
            ["git", "log", "--oneline",
             f"{old_hash.output.strip()}..{new_hash.output.strip()}"],
            cwd=cwd, timeout=10,
        )
        if log.success and log.output.strip():
            steps.append(f"📋 Änderungen:\n{log.output.strip()}")
```

```python
    # --- Schritt 5: Dependency-Check ---
    # Prüfe ob pyproject.toml in den geänderten Dateien ist
    diff_files = self._run_cmd(
        ["git", "diff", "--name-only",
         f"{old_hash.output.strip()}..{new_hash.output.strip()}"],
        cwd=cwd, timeout=10,
    )
    dep_files_changed = False
    if diff_files.success:
        changed = diff_files.output.strip().lower()
        dep_files_changed = (
            "pyproject.toml" in changed
            or "requirements" in changed
            or "setup.cfg" in changed
        )

    if dep_files_changed:
        steps.append("📦 Dependencies geändert – installiere...")
        # pip install über sys.executable → nutzt die aktive venv
        pip = self._run_cmd(
            [sys.executable, "-m", "pip", "install", "-e",
             ".[windows,tts-neural,avatar,matrix,remote,memory,stt]",
             "--quiet"],
            cwd=cwd, timeout=300,  # pip kann langsam sein
        )
        if pip.success:
            steps.append("✅ Dependencies installiert")
        else:
            # pip-Fehler ist nicht fatal – neuer Code KÖNNTE trotzdem laufen
            steps.append(f"⚠️ pip install Warnung:\n{pip.output[:500]}")
    else:
        steps.append("📦 Keine neuen Dependencies")

    # --- Schritt 6: Restart ---
    steps.append("🔄 Starte neu...")

    return CommandResult(
        command="update",
        success=True,
        text="\n".join(steps),
        restart=True,
    )
```

**Helper-Methode (subprocess-Wrapper):**
```python
@dataclass
class _CmdResult:
    success: bool
    output: str

def _run_cmd(
    self, cmd: list[str], cwd: str, timeout: int = 30,
) -> _CmdResult:
    """Führt einen Shell-Befehl aus und gibt Ergebnis zurück."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = result.stdout or result.stderr or ""
        return self._CmdResult(
            success=result.returncode == 0,
            output=output,
        )
    except subprocess.TimeoutExpired:
        return self._CmdResult(success=False, output=f"Timeout ({timeout}s)")
    except FileNotFoundError:
        return self._CmdResult(
            success=False,
            output=f"Befehl nicht gefunden: {cmd[0]}",
        )
    except Exception as e:
        return self._CmdResult(success=False, output=str(e))
```

**WICHTIG: `sys` Import:**
```python
import sys  # Für sys.executable (pip im richtigen venv)
```

---

## 15.3 – Integration

### Geänderte Dateien

**`src/elder_berry/comms/commands/process_commands.py`:**
- `UPDATE_PATTERN` Regex hinzufügen
- `"update"` in `simple_commands`
- `"update"` Keywords in `keywords` Property
- `_cmd_update()` Methode
- `_CmdResult` Dataclass + `_run_cmd()` Helper
- `import sys` ergänzen
- In `execute()`: `if command == "update": return self._cmd_update()`

**`src/elder_berry/comms/remote_commands.py`:**
- HELP_TEXT ergänzen:
```
🔄 Self-Update:
  update                       – Git Pull + Dependencies + Neustart
```

**`src/elder_berry/character/saleria.yaml`:**
- Remote-Tool-Liste: "update" ergänzen

**`src/elder_berry/core/assistant.py`:**
- Fallback-Prompt Remote-Tool-Liste: "update" ergänzen

### KEINE neuen Dateien nötig
Der Update-Command wird in den bestehenden `ProcessCommandHandler` integriert.
Kein neuer Handler, keine neue Klasse.

---

## 15.4 – Tests

### Geänderte Datei: `tests/test_remote_commands.py` (oder neue Datei `tests/test_self_update.py`)

**Tests (~12-15 Tests):**
1. Pattern: "update" → update Command
2. Pattern: "update dich" → update Command
3. Pattern: "aktualisiere dich" → update Command
4. Keyword: "schau dir deine neuen funktionen an" → update
5. Keyword: "mach ein update" → update
6. Execute: Kein project_root → Fehlermeldung
7. Execute: git fetch schlägt fehl → Fehler, kein Pull
8. Execute: 0 Commits behind → "Alles aktuell", kein Restart
9. Execute: Lokale Änderungen → Abbruch mit Warnung
10. Execute: git pull --ff-only fehlgeschlagen → Fehler, kein Restart
11. Execute: Erfolg ohne Dependency-Änderung → restart=True, "Keine neuen Dependencies"
12. Execute: Erfolg mit pyproject.toml geändert → pip install läuft, restart=True
13. Execute: pip install fehlgeschlagen → Warnung (nicht fatal), restart=True
14. _run_cmd: Timeout → success=False
15. _run_cmd: FileNotFoundError → success=False

**Mock-Strategie:**
- `subprocess.run` mocken (kein echtes git/pip)
- Verschiedene Szenarien über Return-Codes und stdout simulieren
- `sys.executable` nicht mocken (wird nur für pip-Pfad genutzt)

---

## 15.5 – Edge Cases & Bekannte Risiken

1. **Git Merge-Konflikte:** `--ff-only` verhindert Merge-Commits.
   Wenn der lokale Branch Commits hat die nicht auf Remote sind → Fehler.
   Das ist gewollt: auf dem Tower soll NICHT entwickelt werden.
   Wenn es doch passiert → User muss manuell resolven (SSH/Remote Desktop).

2. **pip install bricht Laufzeit-Zustand:** Zwischen pip install und Restart
   laufen noch Requests mit dem alten Code. Da der Restart sofort nach pip
   kommt und keine weiteren User-Nachrichten verarbeitet werden (execute()
   ist blockierend), ist das unkritisch.

3. **pip install mit falschen Extras:** Die Extras-Liste
   `[windows,tts-neural,avatar,matrix,remote,memory,stt]` ist hardcoded.
   Wenn sich die Extra-Namen in pyproject.toml ändern → pip-Fehler.
   Lösung v1: Hardcoded ist OK, Extras ändern sich selten.
   Lösung v2: Extras aus pyproject.toml dynamisch parsen (overengineered).

4. **Netzwerk-Timeout:** git fetch/pull braucht Internet. Bei schlechter
   Verbindung → Timeout (30s/60s). User bekommt Fehlermeldung, kein Crash.

5. **Branch-Mismatch:** Saleria läuft auf main, aber der Push ging auf
   einen Feature-Branch → fetch holt Änderungen, aber pull sieht nichts.
   Das ist korrekt: Saleria aktualisiert sich nur vom eigenen Branch.
   Wenn User explizit einen Branch will → manuell per "git checkout X".

6. **Halber Update (Pull OK, pip fehlgeschlagen):** pip-Fehler ist NICHT fatal.
   Restart passiert trotzdem. Neuer Code könnte crashen wenn er neue Dependencies
   braucht die nicht installiert sind. Aber: der alte Code ist weg (git pull).
   Trade-off: Besser mit neuem Code + fehlendem Package starten (klarer Fehler)
   als mit altem Code weiterlaufen (unsichtbares Problem).

7. **Windows-spezifisch:** `os.execv` auf Windows verhält sich anders als auf
   Linux (neuer Prozess statt Replace). Der bestehende Restart-Mechanismus
   (Phase 7) funktioniert aber bereits auf Windows → kein neues Risiko.

---

## 15.6 – Sicherheit

- **Kein automatisches Update:** Update wird NUR auf expliziten User-Befehl ausgeführt.
  Kein Auto-Update, kein Cron, kein Polling auf neue Commits.
- **--ff-only:** Kein Merge, nur Fast-Forward. Verhindert unerwartete Code-Änderungen.
- **Keine Remote-URL-Änderung:** `git pull` nutzt die existierende Remote-Config.
  Kein Angriffsvektor über manipulierte URLs.
- **pip install -e .:** Installiert nur das eigene Projekt + deklarierte Dependencies.
  Kein `pip install <beliebiges-package>` von außen steuerbar.

---

## 15.7 – Abhängigkeiten

- **Neue Packages:** Keine
- **Bestehende Imports:** subprocess, sys, pathlib (alle stdlib)
- **Dateien die gelesen werden müssen BEVOR implementiert wird:**
  - `src/elder_berry/comms/commands/process_commands.py` ✅ (git-Commands, Struktur)
  - `src/elder_berry/comms/commands/base.py` ✅ (CommandResult mit restart-Flag)
  - `src/elder_berry/comms/bridge.py` ✅ (_perform_restart Mechanismus)
  - `src/elder_berry/comms/remote_commands.py` (HELP_TEXT)
