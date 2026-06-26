# Phase 105 – mypy-strict-Rollout agent/robot (Konzept)

**Befund:** Q3 (Typabdeckung nur partiell strikt)
**Branch (geplant):** `feature/phase-105-mypy-strict-agent-robot`
**Status:** ✅ erledigt (PR #323 gemergt). Setzt das Tier-Rollout-Muster der
Phasen 76/76b/76c/98 fort. Der bewusst aufgeschobene, an `avatar/` gekoppelte
Rest (`rpi5_avatar.py:182`, zwei `EmotionLayers`-Klassen) wurde in **Phase 107**
nachgezogen → `docs/concepts/phase-107-mypy-strict-avatar.md`.

## Ziel

Die sicherheitsnahen Pakete `agent/` und `robot/` aus dem
`ignore_errors = true`-Override (`pyproject.toml` Z. 254-271) herauslösen und
strict typchecken, damit die netz-exponierten Server-Pfade die gleiche
Typabdeckung bekommen wie `core/`/`comms/`/`tools/`/`web/`.

## Bestandsaufnahme (gemessen 2026-06-16, Projekt-Config + Stubs)

> **Mess-Falle:** `mypy --strict <pfad>` ohne Projekt-Config meldet
> false-negative „Success" (untypisierte Drittlib-Imports werden still
> übersprungen). Die Zahlen unten stammen aus einem Lauf mit strict-Override +
> installierten Deps; die **finalen** Zähler im CI-Lauf festnageln, nicht hier
> zementieren.

**`agent/` — Aufwand KLEIN (~13 Fehler, 4 Module):**
- `protocol.py`, `__init__.py`: 0 Fehler, sofort strict-fähig.
- `client.py`: 1 (`params: dict | None` → `dict[str, Any] | None`).
- `server.py`: ~12, fast alle trivial (nackte `dict`-Annotationen →
  `dict[str, Any]`, Middleware-`__init__`/`dispatch`-Annotationen, `np.iinfo`
  type-var).

**`robot/` — Aufwand MITTEL-GROSS (~129 Fehler, 12 Module), ~90% mechanisch:**
- Trivial (0 Fehler): `protocol.py`, `harmony_layout_manager.py`.
- Klein: `simulator.py` (3), `turntable_controller.py` (2), `rpi5_avatar.py` (2),
  `harmony_scene_manager.py` (5).
- Mittel: `camera_controller.py` (6), `harmony_adapter.py` (9).
- Groß (Volumen, mechanisch): `client.py` (31, fast alle `-> dict`/`r.json()`-Any),
  `alexa_skill_handler.py` (20), `server.py` (51, u. a. 17-19× `JSONResponse`
  zurückgegeben wo `-> dict` deklariert).

**Echte Logik-Fixes (nicht annotationsneutral, Tests gegenprüfen):**
- `robot/server.py:610` — `rotate_by(float | None)` braucht echten None-Guard.
- `robot/alexa_skill_handler.py:226-227` — `cert.public_key().verify(...)` über
  großen Union; sauberer `isinstance(public_key, rsa.RSAPublicKey)`-Guard
  (Security-Pfad → sauber, nicht `# type: ignore`).
- `robot/rpi5_avatar.py:182` — echter cross-package arg-type-Mismatch
  `EmotionLayers` vs. `LayerSource` (es gibt zwei konkurrierende
  `EmotionLayers`-Klassen → möglicher Design-Smell). Kopplung an `avatar/` (steht
  selbst noch im `ignore_errors`-Block).
- `robot/harmony_scene_manager.py:163-174` — result-dict ist `dict[str, object]`
  → `dict[str, Any]`/TypedDict.
- `robot/turntable_controller.py:255` — `target: callable` → `Callable[[], None]`.

## Tier-Rollout-Plan

1. **105-A `agent` strict:** neuer `[[tool.mypy.overrides]]`-Block
   `module = ["elder_berry.agent.protocol", ".client", ".server", "elder_berry.agent"]`,
   `strict = true`; `agent.*` aus dem `ignore_errors`-Block entfernen. CI
   `typecheck`-Job um `src/elder_berry/agent` erweitern; `pip install` um den
   bereits existierenden `agent`-Extra (python-multipart/sounddevice/numpy)
   ergänzen. ~13 Fixes, 1 Etappe.
2. **105-B1 `robot` trivial:** `protocol`, `harmony_layout_manager`, `simulator`,
   `turntable_controller`, `harmony_scene_manager`, `rpi5_avatar`,
   `camera_controller`, `harmony_adapter` strict (~27 Fixes).
3. **105-B2 `robot` core:** `client`, `server`, `alexa_skill_handler` strict
   (~102 Fehler, ggf. in 2 Etappen `client+alexa`, dann `server`).
4. Bei jeder Etappe den Wildcard `elder_berry.robot.*` durch Einzel-Einträge der
   noch nicht strikten Module ersetzen (wie `comms` in 76b).
5. **Neue `ignore_missing_imports`-Einträge:** `lgpio` + `picamera2` explizit
   ergänzen (analog `pyautogui`/`pygame`). `aioharmony.*` ist bereits gedeckt;
   `sounddevice`/`numpy` ebenfalls.
   - **`PIL.*` (Codex-Review PR #320):** `robot/camera_controller.py` und
     `robot/simulator.py` importieren `PIL.Image`. Pillow ist nur in der
     `computer-use`-Gruppe deklariert, die der `typecheck`-Job heute **nicht**
     installiert. Sobald die Robot-Module in den mypy-Scope kommen, würde der
     Job an `Cannot find implementation or library stub for module named 'PIL'`
     scheitern, **bevor** die eigentlichen Annotationen geprüft werden. Daher
     entweder `computer-use` im `typecheck`-Install ergänzen **oder** einen
     bewussten `PIL.*`-Override setzen (empfohlen: `PIL.*`-Override, da Pillow
     nur fürs Test-/Sim-Bild gebraucht wird und keine Typabdeckung beisteuert).

## Offene Entscheidungen (für Lera)

- `rpi5_avatar.py:182`: wegen `avatar/`-Kopplung in einen eigenen späteren Tier
  schieben (bis `avatar/` strict ist) oder lokalen `cast`/`# type: ignore` setzen?
  → **Entschieden:** eigener späterer Tier. In **Phase 107** umgesetzt — die zwei
  `EmotionLayers`-Klassen wurden vereinheitlicht und `LayerSource` auf read-only
  `@property` umgestellt, womit der `:182`-Mismatch ohne `cast`/`# type: ignore`
  entfiel.
- `server.py` JSONResponse-Routen: Return-Annotation auf
  `dict[str, Any] | JSONResponse` aufweiten oder einheitlich `Response`? (Mögliche
  OpenAPI-Schema-Konsequenz prüfen.)

## Risiken

- `mypy --strict <pfad>` ohne Projekt-Config täuscht „Success" vor — das Gate
  **muss** über `pyproject` + installierte Deps laufen.
- Die echten Logik-Fixes (server:610, alexa:226, rpi5_avatar:182) können Verhalten
  minimal ändern → Robot-/Alexa-Tests gegenprüfen.

## Definition of Done

1. `agent` + `robot` strict im CI-`typecheck`-Job; `ignore_errors`-Block
   geschrumpft.
2. Voller pytest grün; `mypy` über den erweiterten Scope grün.
3. Echte Logik-Fixes mit Test abgesichert; Journal-Eintrag mit finalen
   Fehler-Zählern aus dem CI-Lauf.
