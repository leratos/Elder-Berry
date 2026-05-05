# Phase 76b – mypy-Rollout für `comms/` 🔍

**Status:** Konzept (2026-05-04)
**Branch:** `feature/phase-76b-mypy-rollout-comms` (Phasen-Branch),
Etappen-Sub-Branches `feature/phase-76b-mypy-tier{0..5}` zweigen davon ab
**Aufwand:** 6–8 Sessions verteilt (Schätzung höher als ursprüngliche
3–5-Annahme aus phase-76 §9, weil Ground Truth 197 statt ~100 Funde
liefert)
**Voraussetzungen:** Phase 76 (core/) + Phase 76c (tools/+web/) + Phase 77
(Plugin-Registry) — alle abgeschlossen
**Roadmap-Referenz:** Schwesterphase zu 76c (tools/+web/), letzte
nicht-trivial typisierte Säule. Folge: 76d (tests/) optional.

## 1. Ausgangslage

Phase 76 hat alle 14 `core/`-Module strict gemacht, Phase 76c alle 39
Module in `tools/`+`web/`, Phase 77 hat die Plugin-Registry etabliert
(`base.py` + `registry.py` sind dort bereits strict gesetzt). `comms/`
ist die letzte große Säule, die noch im silence-Block steht
(`elder_berry.comms.*` mit `follow_imports=silent` und
`ignore_errors=true`).

Die Plugin-Registry hat den Code-Zuschnitt verändert:

- **Vorher:** `RemoteCommandHandler.__init__` nahm 25+ Kwargs entgegen,
  baute die Handler-Liste manuell auf, jedes `*_commands.py` wurde
  direkt importiert.
- **Nachher (Phase 77):** Jedes `*_commands.py` exportiert ein
  `PLUGIN: CommandPlugin`-Objekt + eine `_factory(ctx: HandlerContext)`-
  Funktion. Der Orchestrator iteriert über `load_plugins()` und ruft
  Factories. `HandlerContext` ist ein zentraler Service-Container.

Konsequenzen für 76b:

1. **Re-use statt Re-invent:** Die `CommandHandler` ABC (strict in 77)
   typisiert `simple_commands`, `patterns`, `keywords`,
   `command_descriptions`, `execute`. Alle Subklassen müssen sich an
   diese Signaturen halten. `re.Pattern[str]` ist dort schon korrekt
   gesetzt — die ursprüngliche 76b-Schätzung von „~10× re.Pattern
   ohne Generics" entfällt weitgehend.
2. **`HandlerContext` ist die Optional-Source:** Jedes `_factory`
   liest aus `ctx.<service>` (alle Optional). Die Optional-Narrowing-
   Funde aus `mail_commands`, `weather_commands`, `note_commands`
   etc. konzentrieren sich jetzt am `_factory`-Eingang und im Handler
   selbst — wo der Service in einer `self._<service>: T | None`-
   Instance-Variable lebt.
3. **CommandPlugin ist frozen + strict:** Manifest-Felder werden nicht
   neu typisiert, sondern die Plugin-Definition pro Modul muss zu der
   strict-typisierten Dataclass aus `base.py` passen.

Ground Truth (gemessen 2026-05-04, siehe §3.6): **197 Funde in 34 Files
(47 Source-Files geprüft, 13 fund-frei)**. Damit deutlich über der
ursprünglichen 76b-Konzept-Schätzung von „~100 über mind. 12 Module".
Hauptursachen:

- `comms/` ist 47 Module (gegen 14 in core/, 39 in tools/+web/).
- Die Optional-Stores in `HandlerContext` (`NextcloudFilesClient | None`,
  `WeatherClient | None`, `EmailSender | None`, ...) tauchen in fast
  jedem Handler auf und produzieren `Item "None" of "X | None"`-Funde.
- `message_handlers.py` und die drei großen Command-Handler
  (`contact_commands`, `todo_commands`, ~~`mail_commands`~~) sind echte
  Brocken mit je 8–19 Funden.

## 2. Ziel

1. Alle 47 nicht-trivialen Module in `comms/` strict getypt
   (`base.py` + `registry.py` waren durch Phase 77 schon strict —
   bleiben unverändert).
2. Wildcard-Eintrag `elder_berry.comms.*` aus dem silence-Block ist
   durch enumerierte WIP-Liste ersetzt, die mit jedem Tier-Commit
   schrumpft. Am Ende von 76b ist die Liste leer und der WIP-Block
   wird entfernt.
3. CI-Job `typecheck` läuft am Ende von 76b gegen
   `src/elder_berry/core src/elder_berry/tools src/elder_berry/web
   src/elder_berry/comms` blockierend.
4. `pyproject.toml` bleibt single source of truth.
5. Patterns aus Phase 76 + 76c konsequent angewendet (Optional-
   Narrowing-Asserts, dict-Generics, PEP-695, Lazy-Init,
   `# type: ignore[assignment]` im except, IMAP-AnyStr-Wrapper,
   SQLite-Store-Pattern). Ein neues comms-spezifisches Pattern
   (Plugin-Factory-Optional-Filter) wird in §10.2 dokumentiert.

**Nicht-Ziele dieser Phase:**

- `tests/` strict — Phase 76d (optional).
- `avatar/`, `robot/`, `agent/`, `memory/`, `llm/`, `stt/`, `tts/`,
  `system/`, `actions/`, `webapp/`, `server/`, `character/` strict.
  Bleiben mit `follow_imports=silent` + `ignore_errors=true`.
- Bridge-Migration `RemoteCommandHandler`-Legacy-Kwargs → reines
  `HandlerContext`. Ist eigene Folgephase (siehe Phase 77 §8). 76b
  arbeitet mit dem heutigen Backwards-Compat-Shim.
- `DeprecationWarning`-Aktivierung für Legacy-Kwargs (Phase 77 hat
  diese bewusst nicht aktiviert, würde 5000+ Tests zumüllen — bleibt
  out of scope).

## 3. Tier-Tabelle

LOC-Stand 2026-05-04. Funde-Zahlen aus dem Ground-Truth-Probe (§3.6).
Reihenfolge innerhalb eines Tiers ist frei wählbar — Strictness ist
nicht transitiv. Tier-Sortierung ist organisatorisch motiviert
(klein/einfach → groß/komplex, Funde-Zahl als Hauptkriterium).

### Tier 1 — fund-frei + ≤2 Funde (11 Module, ~2200 LOC, ~2 Funde)

| Modul | LOC | Funde | Begründung |
|-------|-----|-------|------------|
| `commands/__init__.py` | 6 | 0 | Re-Exports |
| `commands/cmd_utils.py` | 54 | 0 | Reine Helpers |
| `allowed_senders.py` | 56 | 0 | Set-Wrapper |
| `message_channel.py` | 111 | 0 | ABC-Klasse |
| `pending_confirmation.py` | 150 | 0 | Dataclass + Store |
| `restart_manager.py` | 165 | 0 | Subprocess-Wrapper |
| `audio_converter.py` | 232 | 0 | wav-Konversion |
| `commands/wol_commands.py` | 145 | 0 | Wake-on-LAN |
| `commands/help_sections.py` | 272 | 0 | Statische Maps |
| `remote_commands.py` | 493 | 0 | Orchestrator (Phase 77) — saubere Annotations durch ctx-Migration |
| `reminder_scheduler.py` | 158 | 2 | APScheduler-Wrapper |

Diese Module sind entweder durch frühere Phasen schon sauber annotiert
oder so klein, dass strict ohne Code-Änderung durchläuft.

### Tier 2 — 1–3 Funde (13 Module, ~5300 LOC, ~17 Funde)

| Modul | LOC | Funde | Begründung |
|-------|-----|-------|------------|
| `briefing_scheduler.py` | 512 | 1 | Cron-Logik |
| `calendar_watcher.py` | 206 | 1 | iCal-Diff |
| `chat_history.py` | 207 | 1 | History-Store |
| `commands/docker_commands.py` | 164 | 1 | Docker-CLI-Wrap |
| `commands/file_commands.py` | 467 | 1 | File-Operations |
| `commands/git_commands.py` | 277 | 1 | Phase-77-Pilot, sehr nah dran |
| `commands/note_commands.py` | 414 | 1 | Phase-77-Pilot, sehr nah dran |
| `commands/process_commands.py` | 251 | 1 | psutil-Wrapper |
| `commands/route_commands.py` | 396 | 1 | RoutePlanner-Wrap |
| `commands/system_commands.py` | 829 | 1 | Trotz LOC nur 1 Fund |
| `commands/log_commands.py` | 255 | 3 | Log-Tail |
| `commands/update_commands.py` | 599 | 3 | Git-Pull-Logik |
| `claude_agent.py` | 893 | 3 | Trotz LOC nur 3 Funde |

### Tier 3 — 4–6 Funde (6 Module, ~2880 LOC, ~31 Funde)

| Modul | LOC | Funde | Begründung |
|-------|-----|-------|------------|
| `commands/camera_commands.py` | 238 | 4 | Cam-Snapshot |
| `commands/advanced_commands.py` | 618 | 4 | LLM-Fallback |
| `alert_monitor.py` | 229 | 5 | Schwellwert-Watch |
| `commands/turntable_commands.py` | 305 | 6 | RPi-GPIO-Wrap |
| `commands/selfcheck_commands.py` | 643 | 6 | Diagnose-Suite |
| `commands/calendar_commands.py` | 732 | 6 | Termin-Verwaltung |

### Tier 4 — 7–12 Funde (11 Module, ~6800 LOC, ~93 Funde)

| Modul | LOC | Funde | Begründung |
|-------|-----|-------|------------|
| `audio_pipeline.py` | 363 | 7 | STT-Pipeline |
| `confirmation_handlers.py` | 907 | 7 | Pending-Action-Logik |
| `scheduler_manager.py` | 113 | 7 | Trotz LOC viele Funde |
| `bridge.py` | 475 | 8 | Matrix-Bridge-Orchestrator |
| `commands/mail_commands.py` | 782 | 8 | IMAP/SMTP-Wrap |
| `commands/pdf_commands.py` | 696 | 8 | Stirling-PDF-Wrap |
| `matrix_channel.py` | 735 | 8 | nio-Adapter |
| `commands/weather_commands.py` | 941 | 9 | Phase-77-Pilot, dennoch viele Funde |
| `commands/cloud_commands.py` | 513 | 9 | Nextcloud-Wrap |
| `commands/harmony_commands.py` | 485 | 10 | aioharmony-Wrap |
| `commands/filing_commands.py` | 637 | 12 | Mail→PDF→Cloud-Chain |

### Tier 5 — 19 Funde (3 Module, ~2490 LOC, ~57 Funde)

| Modul | LOC | Funde | Begründung |
|-------|-----|-------|------------|
| `commands/contact_commands.py` | 949 | 19 | CardDAV + Search |
| `commands/todo_commands.py` | 600 | 19 | CalDAV-Tasks |
| `message_handlers.py` | 941 | 19 | Bridge-Orchestrator |

**CI-Gate-Erweiterung** (letzter Commit der Phase, kein Modul):
`mypy src/elder_berry/core src/elder_berry/tools src/elder_berry/web
src/elder_berry/comms` blockierend, WIP-Block aus pyproject entfernt.

### 3.6 Ground Truth (gemessen 2026-05-04 in Vorprüfung)

Probe-Run mit allen 47 comms-Modulen auf `strict = true` ergab
**197 Funde in 34 Files** (47 source files geprüft, 13 fund-frei).
Damit ~70% über der ursprünglichen Konzept-Schätzung („100+ über mind.
12 Module" aus Phase 76 §9).

**Top-Treffer (≥7 Funde):**

| Modul | Tier | Funde |
|-------|------|-------|
| `message_handlers.py` | 5 | 19 |
| `commands/todo_commands.py` | 5 | 19 |
| `commands/contact_commands.py` | 5 | 19 |
| `commands/filing_commands.py` | 4 | 12 |
| `commands/harmony_commands.py` | 4 | 10 |
| `commands/weather_commands.py` | 4 | 9 |
| `commands/cloud_commands.py` | 4 | 9 |
| `matrix_channel.py` | 4 | 8 |
| `commands/pdf_commands.py` | 4 | 8 |
| `commands/mail_commands.py` | 4 | 8 |
| `bridge.py` | 4 | 8 |
| `scheduler_manager.py` | 4 | 7 |
| `confirmation_handlers.py` | 4 | 7 |
| `audio_pipeline.py` | 4 | 7 |

**Beobachtung:** die drei Tier-5-Module + Tier-4 zusammen produzieren
**150 von 197 Funden (76% des Totals)**. Tier 1–3 sind mit 50 Funden
vergleichsweise sanft. Heißt: 76b ist **frontloaded** — die ersten
drei Etappen sind zügig durch, die letzten zwei brauchen Substanz.

**Häufigste Fehlertypen (Stichprobe):**

- `union-attr` (Item "None" of "X | None" has no attribute Y) —
  ~50% aller Funde. Hauptquelle: HandlerContext-Optional-Stores.
- `no-untyped-def` (fehlende Annotations) — ~20%. Hauptsächlich in
  `message_handlers.py` und privaten Helpern.
- `arg-type` (z.B. `bytes | None` als `Sized` übergeben) — ~10%.
- `no-any-return` — ~5%. Returning Any aus deklariertem Type.
- `union-attr` Sonderfall PendingAction → `Item "None" of
  "PendingAction | None"` (in `bridge.py`).
- `unreachable` und Sonstiges — ~15%.

## 4. Konkrete `mypy`-Konfiguration

### 4.1 Wildcard → enumerierte WIP-Liste (Variante A, wie 76c)

In Etappe 0 wird der bestehende `[tool.mypy.overrides]`-Out-of-Scope-
Block

```toml
[[tool.mypy.overrides]]
module = [
    "elder_berry.actions.*",
    "elder_berry.agent.*",
    "elder_berry.avatar.*",
    "elder_berry.character.*",
    "elder_berry.comms.*",            # <-- raus
    "elder_berry.llm.*",
    ...
]
follow_imports = "silent"
ignore_errors = true
```

aufgeteilt in zwei Blöcke:

```toml
# --- Out-of-Scope-Pakete (unverändert silenced bis eigene Phase) ---
[[tool.mypy.overrides]]
module = [
    "elder_berry.actions.*",
    "elder_berry.agent.*",
    "elder_berry.avatar.*",
    "elder_berry.character.*",
    "elder_berry.llm.*",
    "elder_berry.memory.*",
    "elder_berry.robot.*",
    "elder_berry.server.*",
    "elder_berry.stt.*",
    "elder_berry.system.*",
    "elder_berry.tts.*",
    "elder_berry.webapp.*",
    "scripts.*",
]
follow_imports = "silent"
ignore_errors = true

# --- Phase 76b WIP: noch nicht-strict comms/-Module ---
# Liste schrumpft mit jedem Tier-Commit. Am Ende von 76b leer und
# der Block wird geloescht.
[[tool.mypy.overrides]]
module = [
    "elder_berry.comms.alert_monitor",
    "elder_berry.comms.allowed_senders",
    # ... alle 47 comms-Module initial (außer base + registry)
]
follow_imports = "silent"
ignore_errors = true
```

Pro strict-Commit wandert das Modul aus der WIP-Liste in den
`strict = true`-Block. Diff bleibt sichtbar, kein impliziter
Override-Precedence-Trick.

### 4.2 Neue Drittanbieter-Ignores

`matrix_nio.*` und `nio.*` stehen schon im Block (Phase 76 Etappe 0).
`aioharmony.*` ebenfalls. Weitere Probe in Etappe 0 ob Imports wie
`PIL.Image`, `markdown`, `bleach` Funde produzieren — falls ja,
ergänzen.

### 4.3 CI-Erweiterung in der letzten Etappe

`.github/workflows/ci.yml` `typecheck`-Job läuft heute gegen
`src/elder_berry/core src/elder_berry/tools src/elder_berry/web`.
Im **letzten Commit von Etappe 5** wird der Scope erweitert auf
`src/elder_berry/core src/elder_berry/tools src/elder_berry/web
src/elder_berry/comms`. Während der Etappen 1–4 werden comms-Funde
lokal verifiziert (`.venv\Scripts\python.exe -m mypy
src/elder_berry/comms/<modul>.py`).

Risiko siehe R6 (analog 76c R6).

## 5. Etappen / Vorgehen

**Branch-Strategie:** Phasen-Branch `feature/phase-76b-mypy-rollout-comms`
zweigt aus `main`. Etappen-Sub-Branches zweigen aus dem Phasen-Branch
ab und werden dorthin gemerged. Pro Etappe ein PR (User macht den
selbst).

### 5.1 Etappe 0 — Setup (1 Session)

- `pyproject.toml`: Wildcard-Block aufgeteilt (siehe §4.1), Probe-Run
  und Funde-Anzahl als Ground Truth (197 Funde) im journal.txt sichern.
- Falls neue 3rd-Party-Ignores nötig (PIL, markdown, bleach), ergänzen.
- Plugin-Factory-Optional-Filter-Pattern in §10.2 dieses Konzepts
  dokumentieren.
- **Branch:** `feature/phase-76b-mypy-tier0-setup`.
- **Akzeptanzkriterium:** `mypy src/elder_berry/core src/elder_berry/
  tools src/elder_berry/web` weiterhin grün (kein Regress), pytest
  grün, neue WIP-Liste im pyproject sichtbar.

### 5.2 Etappe 1 — Tier 1 (1 Session, 10 Module)

- 10 fund-arme Module einzeln strict, jedes als eigener Commit.
- Pro Commit: Modul aus WIP-Block raus, in strict-Block rein.
- **Branch:** `feature/phase-76b-mypy-tier1`.
- **Akzeptanzkriterium:** alle 10 Module strict, mypy auf
  core+tools+web+comms (für die strict-aktivierten) grün lokal,
  pytest grün.

### 5.3 Etappe 2 — Tier 2 (1–2 Sessions, 13 Module)

- 13 Module mit 1–3 Funden, jedes als eigener Commit.
- `claude_agent.py` (893 LOC, nur 3 Funde) bekommt eigenen
  Commit mit Pytest-Pause — ist anthropic-API-Wrapper, ggf.
  TYPE_CHECKING-Imports nötig.
- **Branch:** `feature/phase-76b-mypy-tier2`.
- **Akzeptanzkriterium:** 23/47 Module strict, mypy grün, pytest grün.

### 5.4 Etappe 3 — Tier 3 (1 Session, 6 Module)

- 6 mittelgroße Module mit 4–6 Funden.
- `commands/calendar_commands.py` (732 LOC) ist Kalender-kritisch —
  Pytest für `tests/test_calendar_commands*.py` nach dem Commit.
- **Branch:** `feature/phase-76b-mypy-tier3`.
- **Akzeptanzkriterium:** 29/47 Module strict, mypy grün, pytest grün.

### 5.5 Etappe 4 — Tier 4 (2 PRs, 11 Module)

Während der Umsetzung wurde Tier 4 in **4a + 4b** gesplittet — 11
Module mit 93 Funden waren als ein PR review-technisch zu groß.
Aufteilung nach Risiko:

**Etappe 4a — 6 Command-Handler (mechanisch, niedriges Risiko)**
- `cloud_commands` (9), `filing_commands` (12), `harmony_commands`
  (10), `mail_commands` (7+1 Bug-Fix), `pdf_commands` (8),
  `weather_commands` (9).
- ~56 Funde, alle ähnliche Patterns (re.Pattern[str] +
  Optional-Stores).
- **Branch:** `feature/phase-76b-mypy-tier4a`.
- **Akzeptanzkriterium:** 37/47 Module strict, mypy grün, pytest grün.

**Etappe 4b — 5 Infrastruktur-Module (Orchestrator-nah, höheres Risiko)**
- `audio_pipeline` (7), `scheduler_manager` (7), `bridge` (8),
  `matrix_channel` (8), `confirmation_handlers` (7).
- ~37 Funde, mehr Optional-Verkettung quer durch Bridge/Matrix-Layer.
- Pytest-Pause nach jedem Commit (per R-Pflicht).
- `audio_pipeline.py` (R7) potenziell echte bytes|None-Bugs — falls
  einer drin ist, kommt der als separater Bug-Fix-Commit + Test
  vor dem strict-Commit (Pattern §10.1.9).
- **Branch:** `feature/phase-76b-mypy-tier4b`.
- **Akzeptanzkriterium:** 42/47 Module strict, mypy grün, pytest grün.

**Pattern-Wahl-Notiz aus 4a (Sec. 10.2 vs. Sec. 10.1):** §10.2
(Plugin-Factory-Optional-Filter) wäre für `cloud_commands` und
`pdf_commands` theoretisch passend, würde aber die "X nicht
konfiguriert"-User-Message verlieren (Handler würde gar nicht
existieren → Silent-Fallthrough zur LLM). Entscheidung: §10.1
(Optional-Stores + assert) bleibt der Default für 76b — konsistent
mit Etappen 1–3, behält UX. §10.2 ist erst sinnvoll, wenn die
Bridge-Migration die Backwards-Compat-Kwargs entfernt.

### 5.6 Etappe 5 — Tier 5 + CI-Gate (2 Sessions, 3 Module + CI)

- 3 Brocken (`message_handlers`, `todo_commands`, `contact_commands`),
  jedes als eigener Commit + Pause für Pytest.
- `message_handlers.py` (941 LOC, 19 Funde) ist Bridge-Inner-Loop —
  potenzielle Verhaltens-Drift-Stelle. Pytest für
  `tests/test_message_handlers*.py` und `tests/test_bridge*.py` nach
  dem Commit.
- `contact_commands.py` (949 LOC, 19 Funde) und `todo_commands.py`
  (600 LOC, 19 Funde): Search/Filter-Logik — vermutlich viele
  `Optional[ContactStore]`-Narrowings + dict-Generics.
- Letzter Commit der Etappe: CI-Job-Scope auf
  `src/elder_berry/core src/elder_berry/tools src/elder_berry/web
  src/elder_berry/comms` erweitern. WIP-Block aus pyproject löschen
  (sind dann leer).
- **Branch:** `feature/phase-76b-mypy-tier5-gate`.
- **Akzeptanzkriterium:** alle 47 Module strict, mypy auf
  core+tools+web+comms grün lokal **und** im CI, pytest grün, WIP-Block
  in pyproject entfernt.

## 6. Risiken / aktive Hinweise

- **R1 — `message_handlers.py` ist 941 LOC + 19 Funde.** Der Bridge-
  Inner-Loop (parse_command, LLM-Fallback, TaskChain-Aufruf,
  Pending-Action-Routing). Vermutlich viele `Optional[X]`-Narrowings,
  einige `no-untyped-def` für private Helper. Mitigation:
  Optional-Asserts pro privater Methode, Aufrufer filtert. Pattern
  aus Phase 76 (`smart_context.py`).
- **R2 — `contact_commands.py` und `todo_commands.py` sind je 19 Funde.**
  Beide haben CardDAV/CalDAV-Stores als Optional. Die Funde sind
  vermutlich sehr ähnlich strukturiert (gleiches Pattern, dreimal
  wiederholt). Mitigation: einmal sauber im erstmigrierten Modul
  fixen, das Pattern dann mechanisch auf die anderen anwenden.
- **R3 — `confirmation_handlers.py` (907 LOC, 7 Funde).** Hat Routing-
  zu-Filing/Mail-Reply/Mail-Send-Logik mit verschachtelten Optional-
  Stores. Wenig Funde, aber kritisch (User-Bestätigung-Pfad).
  Verhaltens-Test essentiell.
- **R4 — Phase-77-Restrukturierung verschiebt Funde.** Die ursprüngliche
  76b-Schätzung („~10× re.Pattern ohne Generics") greift nicht mehr,
  weil `re.Pattern[str]` schon in der ABC steht. Stattdessen
  konzentrieren sich die Funde auf:
  - HandlerContext-Optional-Stores in `_factory()` und Handler-
    Konstruktoren.
  - `_factory(ctx) -> CommandHandler | None` — return-Type-Annotation
    fehlt manchmal.
  - PLUGIN-Manifest selbst ist strict via `CommandPlugin` (frozen
    dataclass) — dort keine Funde.
- **R5 — Bridge-Layer + Matrix-Layer mischen 3rd-party-Calls (nio,
  matrix_nio).** `matrix_channel.py` (8 Funde) und `bridge.py`
  (8 Funde) haben viele `await client.send_text(...)`-Calls mit
  Returns aus dem nio-Stub. Mitigation: nio ist im
  `ignore_missing_imports`-Block, alle Returns sind `Any`. Cast/
  Assert-Pattern.
- **R6 — CI bleibt während Etappen 1–4 stumm für comms.** Heißt: ein
  Drive-by-PR auf `comms/` kann ungetypten Code einführen, ohne dass
  der Job rot wird. WIP-Liste mit `ignore_errors = true` deckt das
  ab. Identisch zu 76c R6. Mitigation: Etappe 5 zügig nach Etappe 4
  anschließen.
- **R7 — `audio_pipeline.py` (7 Funde) hat `bytes | None` als
  Sized/Buffer.** Echte Optional-Lecks in der STT-Pipeline. Bei
  jedem Fund prüfen, ob das Optional ein Bug ist (nicht nur
  Annotation-Lärm wie bei IMAP in 76c R8). Falls Bug: Bug-Fix als
  separater Commit + Test **vor** dem strict-Commit (Pattern 9 aus
  76c §10).
- **R8 — `warn_unused_ignores=True` zwingt Disziplin.** Wenn ein
  `# type: ignore` überflüssig wird, failt mypy. Identisch zu 76 R3
  und 76c R9.
- **R9 — Phase 77 Bridge-Migration ist nicht abgeschlossen.** Die
  Backwards-Compat-Kwargs in `RemoteCommandHandler.__init__` sind
  noch da. Strict-Typing im `_build_legacy_context` muss alle
  ~25 Optional-Kwargs sauber umpacken. Falls einer fehlt, ist das
  ein echter Bug — also Pattern 9 (Bug-Fix vor Strict-Commit).

## 7. Tests / Akzeptanzkriterien

Pro Etappe:
- `mypy src/elder_berry/core src/elder_berry/tools src/elder_berry/web
  src/elder_berry/comms` läuft lokal mit Exit-Code 0 (auf den jeweils
  strict-aktivierten Modulen + den noch silenced Modulen).
- `mypy src/elder_berry` (alle 156+ files) läuft lokal grün.
- Pytest-Suite weiterhin grün, kein neuer Skip — keine
  Verhaltensänderungen erlaubt.
- CI-Job `typecheck` grün (während Etappen 1–4 nur core+tools+web,
  ab Etappe 5 inklusive comms).

Nach Etappe 5:
- Alle 47 Module in `comms/` als `strict = true` markiert.
- WIP-Block aus `pyproject.toml` entfernt.
- CI-Scope auf `src/elder_berry/core src/elder_berry/tools
  src/elder_berry/web src/elder_berry/comms`.
- Phase 76b als abgeschlossen in journal.txt + CHANGELOG.md vermerkt.

## 8. Out of Scope

- `tests/` strict — Phase 76d (optional).
- `avatar/`, `robot/`, `agent/`, `memory/`, `llm/`, `stt/`, `tts/`,
  `system/`, `actions/`, `webapp/`, `server/`, `character/` strict —
  jeweils eigene Phase oder gar nicht (Cost-Benefit prüfen).
- Bridge-Migration `RemoteCommandHandler`-Legacy-Kwargs entfernen.
  Eigene Folgephase nach 76b.
- `DeprecationWarning` für Legacy-Kwargs aktivieren.

## 9. Folge-Phasen

- **Phase 76d (offen):** Test-Code typprüfen, optional.
- **Bridge-Migration (offen):** Legacy-Kwargs in
  `RemoteCommandHandler.__init__` entfernen, alle Aufrufer auf
  `HandlerContext` umstellen, `DeprecationWarning` aktivieren.
- **Phase 78 (offen):** Plugin-Self-Suggestion, baut auf Manifest
  aus Phase 77 auf. Profitiert davon, wenn 76b Plugin-Factories
  strict typisiert hat.

## 10. Patterns

### 10.1 Aus Phase 76 + 76c übernehmen (1:1)

Alle 12 Patterns aus Phase 76c §10 sind in 76b anwendbar:

1. Optional-Narrowing-Assert in privaten Methoden mit Filter-
   Vorbedingung im Aufrufer.
2. `cast(dict[str, Any], json.loads(...))` für JSON-Parsing.
3. `cast(dict[str, Any], r.json())` für httpx/requests-Returns.
4. PEP-695-Generics für generische Helfer.
5. `dict` ohne Generics → `dict[str, Any]` für heterogene API-Bodies.
6. `# type: ignore[assignment]` direkt im except für try/except-
   ImportError-Fallbacks.
7. `re.Pattern` ohne Generics → `re.Pattern[str]` (in 76b weniger
   relevant — ABC hat das schon).
8. IMAP-AnyStr-Wrapper (in 76b nur relevant, falls neue IMAP-Calls
   außerhalb `tools/email_client` auftauchen — unwahrscheinlich).
9. Bug-Fix vor Strict-Commit (Notfall-Pattern für echte Optional-
   Lecks, siehe R7 für `audio_pipeline.py`).
10. Starlette-Middleware dispatch-Annotation (in 76b nicht relevant —
    `comms/` hat keine Middleware).
11. Lazy-Init-Client-Pattern (relevant für `claude_agent.py`,
    möglicherweise `audio_pipeline.py`).
12. SQLite-Store-Pattern (in 76b unwahrscheinlich — Stores leben in
    `tools/`).

### 10.2 Neu für 76b — Plugin-Factory-Optional-Filter

Hintergrund: Phase 77 etabliert das Pattern, dass `_factory(ctx)`
None zurückgibt, wenn benötigte Services fehlen. Strict-Typing
zwingt zur expliziten Filter-Logik:

```python
from __future__ import annotations

from elder_berry.comms.commands.base import (
    CommandHandler, CommandPlugin, HandlerContext,
)


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    # Mehrere Pflicht-Services -- alle prüfen, frühzeitig None.
    if ctx.email_client is None:
        return None
    if ctx.note_store is None:
        return None
    # Ab hier: mypy weiß, dass ctx.email_client und ctx.note_store
    # nicht None sind. Aber: die Variablen werden später erneut
    # gelesen, mypy verliert das Narrowing. Lokal binden:
    email = ctx.email_client
    notes = ctx.note_store
    return MailCommandHandler(email_client=email, note_store=notes)


PLUGIN = CommandPlugin(
    name="mail",
    priority=30,
    category="kommunikation",
    help_section=HELP_SECTION_MAIL,
    factory=_factory,
)
```

Alternative ohne lokale Bindung: Optional-Stores im Handler-Konstruktor
übernehmen, dann gilt der `assert self._x is not None`-Pattern aus
Phase 76 in jeder Methode. Trade-off:

- **Lokale Bindung in `_factory`:** kein `assert` in der Handler-
  Klasse, aber Handler-Konstruktor nimmt `<Service>` (nicht-Optional)
  entgegen. Sauberer, aber zwingt einen Konstruktor-Refactor pro
  Handler.
- **Optional-Stores im Handler:** Handler-Konstruktor nimmt
  `<Service> | None` entgegen, jede Methode hat
  `assert self._service is not None` als erste Zeile. Mechanischer,
  weniger Diff, aber Defense-in-Depth-Optik.

**Empfehlung 76b:** lokale Bindung in `_factory` als Default. Bei
Handlern mit zu vielen Services oder schon existierenden Optional-
Stores die zweite Variante. Pro Modul entscheiden, im Commit
begründen.

### 10.3 Neu für 76b — HandlerContext-Lese-Pattern

Wenn ein Handler nur ein paar Services aus `HandlerContext` braucht,
kein eigener Konstruktor-Param-Spagat:

```python
class WeatherCommandHandler(CommandHandler):
    def __init__(
        self,
        weather: WeatherClient,
        reminders: ReminderStore | None = None,
        briefing: BriefingScheduler | None = None,
        gym: GymDataClient | None = None,
    ) -> None:
        self._weather = weather
        self._reminders = reminders
        self._briefing = briefing
        self._gym = gym
```

`weather` ist hier nicht-Optional — die `_factory` filtert vorher.
Die optionalen Felder werden mit `if self._reminders is None: return
not_configured(...)`-Pattern abgefedert. Konsistent mit dem
Pattern, das Phase 77 Etappe 1 für `weather`/`note`/`git`
demonstriert hat.

---

**Akzeptanz dieses Konzepts durch User → Etappe 0 startet.**
