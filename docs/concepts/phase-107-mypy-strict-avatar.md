# Phase 107 – mypy-strict-Rollout avatar/ (Konzept)

**Befund:** Q3-Rest (Typabdeckung `avatar/` + `robot/rpi5_avatar` noch nicht strikt)
**Branch:** `feature/phase-107-avatar-strict`
**Status:** ✅ erledigt (PR #333 gemergt, Merge `ba475c8`). Setzt das
Tier-Rollout-Muster der Phasen 76/76b/76c/98/105 fort und schließt den in
Phase 105 bewusst aufgeschobenen, an `avatar/` gekoppelten Rest.

## Ziel

`avatar/` aus dem `ignore_errors = true`-Override (`pyproject.toml`,
`[[tool.mypy.overrides]]`) herauslösen und strict typchecken; danach
`robot/rpi5_avatar.py` nachziehen (war seit Phase 105 als eigener Tier
zurückgestellt, weil es an das noch nicht-strikte `avatar/` koppelte). Den
CI-`typecheck`-Scope um `src/elder_berry/avatar` erweitern.

## Bestandsaufnahme (gemessen 2026-06-26, Projekt-Config + installierte Deps)

> **Mess-Falle (#799):** `mypy --strict <pfad>` ohne Projekt-Config meldet
> false-negative „Success". Baseline + finale Zähler **immer** über
> `pyproject` + installierte Deps messen.

Baseline (avatar.* temporär strict, CI-Scope + `src/elder_berry/avatar`):
**16 Fehler in 4 Dateien** + 1 in `rpi5_avatar` – deutlich kleiner als in der
Phase-105-Voranalyse befürchtet. `character/` leckt **keine** untypisierten
Returns, war also kein Vorzieher.

Klassifikation:

- **9× mechanisch** – `self._screen: pygame.Surface | None`-Narrowing in
  privaten Draw-Helfern von `layered_renderer.py`
  (`_apply_rotation`/`_blit_faded_component`/`_composite_full`/
  `_add_weighted_plan`/`_composite_mouth_only`/`_blit_centered`), die nur nach
  dem öffentlichen `is None`-Guard laufen → `assert self._screen is not None`.
- **3× trivial** – nackte `dict`-Annotationen (`avatar_config_loader._parse_config`,
  `controller.get_state`, `rpi5_avatar.get_state`) → `dict[str, Any]`;
  `sprite_renderer.update` um `self._clock is None`-Guard erweitert.
- **2× read-only-Protocol** (`layered_renderer.py:527/623`) – `LayerSource`
  (`render_plan.py`) deklarierte **settable** Member; die `frozen`-Dataclasses
  `EmotionLayers`/`RenderPlan` sind read-only → `compose`-`arg-type`. Gleiche
  Ursache wie der aufgeschobene `rpi5_avatar.py:182`.
- **2× Duplikat-Klasse** (`layered_renderer.py:272/383`) – **zwei**
  byte-identische `frozen EmotionLayers` (`avatar_config_loader.py` +
  `layered_renderer.py`); `self._emotion_map` wird mit `config.emotions`
  (Loader-Typ) **und** `EMOTION_MAP` (Renderer-Typ) belegt → Typkonflikt.

## Design-Entscheidungen (Lera)

### B1 – `EmotionLayers` vereinheitlichen (statt nur Protocol-Typisierung)

Die zwei strukturgleichen `EmotionLayers` wurden zu **einer** Klasse
zusammengeführt: kanonisch in `avatar_config_loader.py`, von
`layered_renderer.py` top-level importiert **und re-exportiert** (Bestands-Importe
`from ...layered_renderer import EmotionLayers` in `tests/test_avatar_editor.py`
und die `EMOTION_MAP`-Annotation bleiben unverändert). Damit verschwindet der
`self._emotion_map`-Typkonflikt.

Verworfene Alternative **B2** (beide Klassen behalten, `self._emotion_map` als
`Mapping[Emotion, LayerSource]` typisieren): hätte `rpi5_avatar.py:172`
gebrochen, da dort `layers.can_blink` gelesen wird und `LayerSource` kein
`can_blink` hat.

Kein Import-Zyklus: `avatar_config_loader` importiert `layered_renderer` nicht;
`PyYAML` ist Basis-Dependency.

### Read-only `LayerSource`-Protocol

`LayerSource`-Member sind jetzt read-only `@property` statt settable
Annotationen → `frozen`-Dataclasses (`EmotionLayers`/`RenderPlan`) erfüllen das
Protocol. Das löst die `compose`-`arg-type`-Fehler **und** den früheren
`rpi5_avatar.py:182`-Mismatch in einem Schritt, ohne `cast`/`# type: ignore`.
Die Property-Bodies sind bewusst reine **Docstrings** statt `...` (ein bloßes
`...` löst CodeQL `py/ineffectual-statement` aus; als Protocol-Stub ist der
Docstring gleichwertig und alarmfrei).

## Umsetzung (1 Phase, 3 Etappen, 1 PR)

1. **Etappe 1 – mechanisch/trivial + `LayerSource`-@property.**
2. **Etappe 2 – `EmotionLayers`-Unify (B1)**; `avatar.*` aus dem
   `ignore_errors`-Block gelöst, eigener `strict = true`-Override (13 Module
   explizit, Muster wie 76b/105).
3. **Etappe 3 – `robot.rpi5_avatar`** aus `ignore_errors` in den robot-strict-Block
   verschoben (1 Restfehler: `get_state -> dict`); `robot/` damit **vollständig
   strict** (kein `ignore_errors`-Modul mehr). CI-`typecheck`-Command um
   `src/elder_berry/avatar` erweitert.

### Kein avatar-Install-Extra – aber env-robuste pygame-Ignores

`pygame`/`PIL` sind via `ignore_missing_imports` gedeckt; der `typecheck`-Job
installiert `.[avatar]`/pygame **nicht**. Das hat einen Stolperstein: die
`pygame = None  # type: ignore[assignment]`-Fallbacks
(`layered_renderer`/`sprite_renderer`/`crossfade_benchmark`) sind **nur mit**
installiertem pygame nötig. Ohne pygame ist `import pygame` via
`ignore_missing_imports` `Any`, die Zuweisung kein Fehler → bei
`warn_unused_ignores = true` meldet mypy `unused-ignore`. Lokal war pygame im
venv (für Tests) installiert, weshalb die Baseline das **verdeckte** (Mess-
Diskrepanz, vom CI-Lauf aufgedeckt).

Fix: `# type: ignore[assignment, unused-ignore]` – robust in **beiden**
Umgebungen (mit pygame greift `[assignment]`, ohne unterdrückt `[unused-ignore]`
die Unused-Warnung). Passt zum try/except-Design (Module laufen mit oder ohne
pygame).

## Verifikation

- `mypy` über den erweiterten CI-Scope (`core`+`tools`+`web`+`comms`+`agent`+
  `robot`+`avatar`): **199 Files, no issues**.
- `ruff` clean.
- Voller `pytest`: **7324 passed / 3 skipped**; keine Testdatei-Änderung
  (Re-Export hält alle Bestands-Importe).
- CodeQL: 0 offene Alerts auf dem Branch (die 5 `py/ineffectual-statement`-Funde
  auf die `@property`-Stubs durch Docstring-Bodies gefixt, ohne Dismissal).

## Definition of Done

1. ✅ `avatar/` + `robot/rpi5_avatar` strict im CI-`typecheck`-Job;
   `ignore_errors`-Block um beide geschrumpft (`robot/` jetzt vollständig strict).
2. ✅ Voller pytest grün; `mypy` über den erweiterten Scope grün; CodeQL grün.
3. ✅ `EmotionLayers`-Unify + read-only `LayerSource` ohne Verhaltensänderung
   (reine Typ-/Struktur-Qualität, kein Hardware-Bezug).

## Journal

- Start/Baseline: `elder-berry#871`
- Abschluss: `elder-berry#872`
- PR-#333-Watch (CI/Review-Fixes): `elder-berry#873`
- Vorgänger-Backlog: `elder-berry#833` (resolved)
