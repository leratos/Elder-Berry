# Phase 76 – mypy-Rollout für `core/` 🔍

**Status:** Konzept (2026-04-29, gepatcht 2026-05-01: pyproject statt mypy.ini,
keyring-Override, non-blocking-CI explizit)
**Branch:** `feature/phase-76-mypy-rollout-core`
**Aufwand:** Setup + Tier 1 in einer Session, Tier 2–4 nebenläufig
(insgesamt ~4–6 Sessions verteilt)
**Voraussetzung:** Phase 75 (Repo-Hygiene) abgeschlossen
**Roadmap-Referenz:** Vorbereitung für Phase 77 (Plugin-Registry)

## 1. Ausgangslage

CI prüft heute `ruff` (`E9,W605,F401,B`) und `pip-audit`, aber **keinen
Type-Checker**. Der Codebase nutzt durchgängig Type-Hints
(`from __future__ import annotations`, Union-Syntax `X | None`,
`dataclass`-Felder), diese werden aber nirgends validiert. Praxiswert
unbekannt — vermutlich gibt es Drift zwischen Annotation und tatsächlichem
Verhalten.

`src/elder_berry/core/` ist 14 Dateien, ~3.2k LOC, und ist der naheliegende
Einstieg, weil:

- Es ist das **architekturelle Zentrum** (Assistant, SecretStore,
  TaskChain, SmartContext) — Type-Fehler hier wirken auf alle Aufrufer.
- Die Module sind **vergleichsweise klein und gut geschnitten** (Größenspanne
  29 LOC bis 587 LOC, Median ~170 LOC).
- Externe Dependencies sind **überschaubar** (cryptography, keyring,
  optional psutil) — die meisten Module sind reine Python-stdlib.
- `path_guard.py` (Phase 69) ist die **jüngste Datei** und vermutlich am
  saubersten getypt — gutes Referenzmodul.

## 2. Ziel

1. `mypy` als Pflicht-Werkzeug etabliert: in `pyproject.toml` `[dev]`-Gruppe,
   `[tool.mypy]`-Sektion in `pyproject.toml` (single source of truth, kein
   separates `mypy.ini`), CI-Job (zunächst non-blocking).
2. Vier Module in `core/` strict: `log_sanitize`, `prompts`, `path_guard`,
   `error_collector`.
3. Pattern dokumentiert für „strict pro Modul aktivieren": klare Anleitung
   für Tier 2–4.
4. Disziplin etabliert: jeder neue Code in `core/` ab dieser Phase **muss**
   strict sein.

**Nicht-Ziele dieser Phase:**
- Alle 14 Module strict. Tier 2–4 laufen nebenläufig in eigenen kleinen PRs.
- Strict in anderen Paketen (`comms/`, `tools/`, `web/`). Erst nach `core/`.
- `assistant.py` strict — der Boss kommt zuletzt (Tier 4).

## 3. Tier-Tabelle

| Tier | Modul | LOC | Begründung | Erwartete Funde |
|------|-------|-----|------------|-----------------|
| **1** | `log_sanitize.py` | 29 | Trivial, keine Klassen, kein I/O | 0–1 |
| **1** | `prompts.py` | 55 | Konstanten + reine Funktionen | 0–1 |
| **1** | `path_guard.py` | 178 | Frische Datei (Phase 69), klar geschnitten | 0–2 |
| **1** | `error_collector.py` | 85 | Reine Datenstruktur, in-memory | 1–2 |
| **2** | `audio_router.py` | 82 | Schmale Klasse, wenig State | 1–3 |
| **2** | `url_validator.py` | 127 | Reine Funktionen, urllib-Stubs | 1–3 |
| **2** | `startup_summary.py` | 151 | Read-only, psutil-Stubs nötig | 2–4 |
| **3** | `secret_store.py` | 376 | Crypto + Keyring (3rd-Party-Stubs) | 3–6 |
| **3** | `stt_router.py` | 169 | Optional Deps, viele Any-Inseln | 4–8 |
| **3** | `tts_router.py` | 185 | Optional Deps, viele Any-Inseln | 4–8 |
| **3** | `context_enricher.py` | 275 | LLM-nahe, async + Generics | 3–6 |
| **3** | `smart_context.py` | 363 | Größere Datenflüsse | 5–10 |
| **3** | `task_chain.py` | 296 | Async + Generics (TaskChain[T]) | 5–10 |
| **4** | `tower_agent.py` | 237 | I/O-lastig, viele DI-Schnittstellen | 5–10 |
| **4** | `assistant.py` | 587 | Orchestrator mit 22 Funktionen | 10–20 |

Reihenfolge innerhalb eines Tiers ist frei wählbar. Die Tier-Sortierung ist
**organisatorisch** motiviert (klein/einfach → groß/komplex, damit das Pattern
am simplen Beispiel etabliert wird), nicht technisch: mypy prüft jedes Modul
gegen seine eigene Konfiguration, Strictness ist nicht transitiv vererbt.
Ein Tier-3-Modul kann technisch jederzeit strict gemacht werden, sobald die
Tier-1/2-Module mit denen es typisch interagiert kein Type-Schweißband mehr
brauchen.

## 4. Konkrete `mypy`-Konfiguration

### 4.1 `[tool.mypy]`-Sektion in `pyproject.toml`

Single source of truth — keine zusätzliche `mypy.ini`. Phase 75 hat
`pyproject.toml` als zentrale Konfig-Datei etabliert (ruff, pytest, build),
mypy fügt sich dort ein.

```toml
[tool.mypy]
python_version = "3.12"
mypy_path = "src"
namespace_packages = true
explicit_package_bases = true

# Globale Defaults: locker. Strict wird per-Modul aktiviert.
warn_unused_ignores = true
warn_redundant_casts = true
warn_unreachable = true
no_implicit_optional = true
show_error_codes = true
pretty = true

# --- Drittanbieter-Ignores (kein Stub-Paket verfügbar) ---
[[tool.mypy.overrides]]
module = [
    "pyautogui.*",
    "pygame.*",
    "coqui_tts.*",
    "faster_whisper.*",
    "mss.*",
    "pyperclip.*",
    "pycaw.*",
    "comtypes.*",
    "PyGetWindow.*",
    "pyttsx3.*",
    "aioharmony.*",
    "vobject.*",
    "caldav.*",
    "trafilatura.*",
    "chromadb.*",
    "matrix_nio.*",
    "nio.*",
    "keyring.*",      # types-keyring existiert nicht (Stand 2026-04, R5)
    "sounddevice.*",
]
ignore_missing_imports = true

# --- Tier 1: sofort strict ---
[[tool.mypy.overrides]]
module = [
    "elder_berry.core.log_sanitize",
    "elder_berry.core.prompts",
    "elder_berry.core.path_guard",
    "elder_berry.core.error_collector",
]
strict = true

# --- Tier 2–4: später aktivieren ---
# Folgt dem Schema:
# [[tool.mypy.overrides]]
# module = ["elder_berry.core.<modul>"]
# strict = true
```

### 4.2 Dependency-Eintrag in `pyproject.toml`

```toml
[project.optional-dependencies]
dev = [
    "pytest-timeout>=2.4.0",
    "pytest-cov>=5.0",
    "pip-tools>=7.0",
    "mypy>=1.13",  # Phase 76: Type-Checking core/
    "types-PyYAML",  # Stubs für YAML-Konfiguration
    "types-psutil",  # Stubs für system/info.py + startup_summary.py
]
```

### 4.3 CI-Integration (zunächst non-blocking)

In `.github/workflows/ci.yml` zwischen `lint`-Job und `security`-Job:

```yaml
typecheck:
  runs-on: ubuntu-latest
  permissions:
    contents: read
  # Phase 76 Tier 1–3: Job darf rot werden, ohne den Pipeline-Status
  # zu kippen. In Etappe 4 entfernen, sobald alle 14 core/-Module
  # strict sind.
  continue-on-error: true

  steps:
    - uses: actions/checkout@v6

    - name: Set up Python
      uses: actions/setup-python@v6
      with:
        python-version: "3.12"

    - name: Install mypy + Stubs
      run: |
        pip install "mypy>=1.13" types-PyYAML types-psutil

    - name: Type-check core/
      # Phase 76 Tier 1: Nur die strict-aktivierten Module werden
      # streng geprüft. Andere Module laufen mit den globalen
      # (lockeren) Defaults und können Any-Lecks haben.
      run: mypy src/elder_berry/core
```

## 5. Etappen / Vorgehen

**Branch-Strategie:** Alle Tier-Sub-Branches zweigen aus
`feature/phase-76-mypy-rollout-core` ab und werden dorthin gemerged. Die
Phase bleibt im CLAUDE.md-Sinne **ein Branch**; die Tier-Branches sind nur
PR-Verpackung, damit Tier 2–4 ggf. nebenläufig durchlaufen können, ohne
sich gegenseitig zu blockieren.

### 5.1 Etappe 1 — Setup + Tier 1 (1 Session)

- `pyproject.toml`: `mypy` + Stubs zu `[dev]` hinzufügen, `[tool.mypy]`-
  Sektion mit Globaleinstellungen + Tier 1 ergänzen.
- Lokal `mypy src/elder_berry/core` laufen lassen.
- Funde fixen (Erwartung: 0–4 Issues).
- CI-Job hinzufügen (non-blocking via `continue-on-error: true`).
- **Branch:** `feature/phase-76-mypy-rollout-core` (Etappe 1 läuft direkt
  auf dem Phasen-Branch, weil sie das Setup-Fundament für Tier 2–4 ist).
- **Akzeptanzkriterium:** `mypy src/elder_berry/core` läuft mit
  `Success: no issues found`, CI-Job `typecheck` grün, Pytest-Suite
  weiterhin grün.

### 5.2 Etappe 2 — Tier 2 (1 Session)

- Drei Module einzeln strict machen, jedes als eigener Commit.
- Stubs für `psutil` und `urllib3` falls nötig nachziehen.
- **Branch:** `feature/phase-76-mypy-tier2` (zweigt aus dem Phasen-Branch ab).
- **Akzeptanzkriterium:** sieben Module strict, mypy grün.

### 5.3 Etappe 3 — Tier 3 (2 Sessions)

- Sechs Module, davon drei mit Async/Generics (`task_chain`,
  `context_enricher`, `smart_context`).
- Genauer Blick auf Generics-Definitionen (`TaskChain[T]`, ggf.
  `Protocol`-Klassen für Service-Schnittstellen).
- **Branch:** `feature/phase-76-mypy-tier3` (zweigt aus dem Phasen-Branch ab).
- **Akzeptanzkriterium:** dreizehn Module strict, mypy grün.

### 5.4 Etappe 4 — Tier 4 + Gate hart (1 Session)

- `tower_agent.py` und `assistant.py` strict.
- CI-Job blockierend machen: `continue-on-error: true` aus dem
  `typecheck`-Job entfernen.
- README-Badge hinzufügen (`mypy: passing`, optional).
- **Branch:** `feature/phase-76-mypy-tier4-gate` (zweigt aus dem
  Phasen-Branch ab).
- **Akzeptanzkriterium:** alle 14 `core/`-Module strict, CI failt bei
  Type-Fehler.

## 6. Risiken / aktive Hinweise

- **R1 – `assistant.py` ist groß.** 587 LOC, 22 Funktionen, viele
  `secret_store.get(...)`-Aufrufe (returns `str | None`, oft als `str`
  benutzt). Erwarte 10–20 echte Funde. Plane Tier 4 mit Puffer ein.
- **R2 – Optional-Dependencies erzeugen `Any`-Lecks.** `tts_router` und
  `stt_router` haben Code-Pfade, die nur mit installiertem `coqui_tts` /
  `faster_whisper` funktionieren. Beide werden via `ignore_missing_imports`
  durchgewunken — die Funktionsergebnisse landen als `Any`. Mitigation:
  `Protocol`-Klassen für die Service-Interfaces, sodass die `core/`-Seite
  nur das Protocol sieht.
- **R3 – `warn_unused_ignores=True` zwingt Disziplin.** Wenn ein
  `# type: ignore` überflüssig wird (weil die Lib einen Stub bekommt),
  failt mypy. Das ist gewollt — heißt aber, dass ein Lib-Update
  überraschend rot wird.
- **R4 – Type-Disziplin verfällt ohne CI-Gate.** Tier 1–3 mit
  non-blocking CI hat den Risiko-Punkt: ein Drive-by-PR kann ein neues
  ungetyptes Funktion einführen, ohne dass der Job rot wird. Mitigation:
  pre-commit-Hook (siehe Phase 75) oder Tier 4 möglichst zügig.
- **R5 – Stub-Verfügbarkeit ist nicht garantiert.** `types-psutil` existiert,
  `types-keyring` existiert nicht (Stand 2026-04). Module mit
  Stub-Lücken müssen mit `# type: ignore[import-untyped]` arbeiten und
  Eigenstubs in `stubs/`-Verzeichnis pflegen, falls die Annotationen
  wertvoll wären.
- **R6 – Test-Code wird hier NICHT typgeprüft.** `tests/` ist mit ~54k LOC
  doppelt so groß wie `src/`. Würde Tier-5-Phase werden, ist aber bewusst
  out-of-scope dieser Phase.

## 7. Tests / Akzeptanzkriterien

Pro Etappe:
- `mypy src/elder_berry/core` läuft mit Exit-Code 0.
- Bestehende Pytest-Suite weiterhin grün, kein neuer Skip — keine
  Verhaltensänderungen erlaubt.
- CI-Job `typecheck` grün.

Nach Etappe 4:
- `mypy src/elder_berry/core --strict` läuft sauber durch.
- CI-Job blockierend (`continue-on-error` aus dem Job entfernt).
- Alle 14 Module in `[tool.mypy]`-Overrides als `strict = true` markiert.

## 8. Out of Scope

- Type-Checking in `src/elder_berry/comms/`, `src/elder_berry/tools/`,
  `src/elder_berry/web/`. Folgephasen.
- Test-Code typprüfen.
- `mypy --strict` global aktivieren (zu aggressiv für Optional-Deps-Module).
- Eigenstubs für `pygame`, `pyautogui` etc. — `ignore_missing_imports`
  ist die richtige Antwort dort.

## 9. Folge-Phasen

- **Phase 76b (offen):** mypy für `comms/` — direkt sinnvoll nach
  Phase 77 (Plugin-Registry), weil das Plugin-Manifest dort lebt und
  Generics-lastig wird.
- **Phase 76c (offen):** mypy für `tools/` und `web/`.
- **Phase 76d (offen):** Test-Code optional typprüfen
  (`disallow_untyped_defs = False` für `tests/`, aber Annotation-
  Korrektheit prüfen).
