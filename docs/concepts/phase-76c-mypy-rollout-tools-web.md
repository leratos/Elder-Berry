# Phase 76c – mypy-Rollout für `tools/` + `web/` 🔍

**Status:** Abgeschlossen (Etappe 0–5, 2026-05-04). Alle 39 `tools/`- und
`web/`-Module strict getypt, CI-Gate hart auf
`src/elder_berry/core src/elder_berry/tools src/elder_berry/web`,
WIP-Blöcke aus `pyproject.toml` entfernt.
**Branch:** `feature/phase-76c-mypy-rollout-tools-web` (Phasen-Branch),
Etappen-Sub-Branches `feature/phase-76c-mypy-tier{0..5}` zweigen davon ab
**Aufwand:** 9–11 Sessions verteilt
**Voraussetzung:** Phase 76 (core/) abgeschlossen, CI-Gate hart auf
`src/elder_berry/core`
**Roadmap-Referenz:** Schwesterphase zu 76b (comms/), Vorbereitung für
Phase 77 (Plugin-Registry)

## 1. Ausgangslage

Phase 76 hat alle 14 `core/`-Module strict gemacht und das CI-Gate hart
gezogen. `tools/` und `web/` stehen aktuell in `[tool.mypy.overrides]`
mit `follow_imports = "silent"` und `ignore_errors = true` — Imports
aus `core/` werden für Type-Resolution gefolgt, aber Funde in den
Paketen selbst werden unterdrückt. Das ist die Krücke aus Phase 76, die
verhindert hat, dass `mypy src` Hunderte vor-bestehender Funde meldet.

Ohne dieses Silencing meldet mypy auf `tools/` und `web/` derzeit eine
unbekannte Anzahl Funde (Schätzung Bauchgefühl: 80–150 in tools/,
40–80 in web/, plus Nebeneffekte aus Stub-Lücken bei
`google-api-python-client`, `icalendar`, `googleapiclient`). Tier-Sortierung
ist nötig, weil ein "alle Module strict in einem Schritt"-Vorgehen den
Diff unleserlich machen würde und Bug-Risiken in nicht prüfbarer Menge
einführt.

`tools/` ist 22 Dateien, ~7900 LOC. `web/` ist 17 Dateien, ~5200 LOC.
Zusammen ~13.1k LOC, das ist gut **4× core/**. Inhaltlich:

- `tools/` ist hauptsächlich Drittanbieter-Clients (Google, CalDAV,
  CardDAV, Brave, ElevenLabs, Stirling-PDF, IMAP/SMTP) und lokale
  Stores (Contacts, Notes, Reminders, Todos).
- `web/` ist FastAPI-Bindung: Dashboard-Routen, Middleware,
  Setup-Wizard, Token-Handling.

## 2. Ziel

1. Alle 39 Module in `tools/` und `web/` strict getypt.
2. Wildcard-Eintrag `elder_berry.tools.*` und `elder_berry.web.*` aus
   dem silence-Block ist durch enumerierte Listen ersetzt, die
   schrumpfen während Etappen laufen. Am Ende von 76c sind beide
   Listen leer und die Wildcards können entfernt werden.
3. CI-Job `typecheck` läuft am Ende von 76c gegen
   `src/elder_berry/core src/elder_berry/tools src/elder_berry/web`
   blockierend.
4. `pyproject.toml` bleibt single source of truth (kein separates
   `mypy.ini`).
5. Patterns aus Phase 76 (Optional-Asserts, dict-Generics, PEP-695,
   cast(json.loads), `# type: ignore[assignment]` im except)
   konsequent angewendet, ein neues Pattern (IMAP-AnyStr-Wrapper)
   ergänzt.

**Nicht-Ziele dieser Phase:**
- `comms/` strict (Phase 76b, parallel/separat).
- `tests/` strict (Phase 76d, optional).
- `avatar/`, `robot/`, `agent/`, `memory/`, `llm/`, `stt/`, `tts/`,
  `system/`, `actions/`, `webapp/`, `server/`, `character/` strict.
  Diese bleiben mit `follow_imports = silent` + `ignore_errors = true`.

## 3. Tier-Tabelle

LOC-Stand 2026-05-02. Reihenfolge innerhalb eines Tiers ist frei
wählbar — Strictness ist nicht transitiv, mypy prüft jedes Modul gegen
seine eigene Konfiguration. Tier-Sortierung ist organisatorisch
motiviert (klein/einfach → groß/komplex).

### Tier 1 — sehr klein, wenig State (7 Module, ~890 LOC)

| Paket | Modul | LOC | Begründung | Erwartete Funde |
|-------|-------|-----|------------|-----------------|
| web | `llm_api.py` | 95 | Reine API-Routen, FastAPI-Idiom | 0–2 |
| web | `security_middleware.py` | 98 | Schmale Klasse | 0–2 |
| web | `origin_check_middleware.py` | 118 | Reine Validierung | 1–2 |
| web | `settings_token.py` | 149 | HMAC-Token-Helper | 1–3 |
| tools | `cloud_stt_client.py` | 133 | Schmaler HTTP-Client | 1–3 |
| tools | `elevenlabs_client.py` | 147 | Schmaler HTTP-Client | 1–3 |
| tools | `route_planner.py` | 157 | Reine Logik | 1–3 |

### Tier 2 — Middleware + leichte Clients (10 Module, ~2040 LOC)

| Paket | Modul | LOC | Begründung | Erwartete Funde |
|-------|-------|-----|------------|-----------------|
| web | `settings_token_middleware.py` | 183 | Token-Bearer-Middleware | 1–3 |
| web | `dashboard_auth_middleware.py` | 184 | Cookie-Validierung | 2–4 |
| web | `rate_limiter.py` | 193 | In-Memory-Limiter | 2–4 |
| web | `secrets_api.py` | 197 | API-Routen für Secrets | 2–4 |
| web | `session_revocation_list.py` | 220 | List-Verwaltung | 1–3 |
| tools | `email_sender.py` | 189 | SMTP-Client | 2–4 |
| tools | `brave_search_client.py` | 199 | HTTP-Client | 2–4 |
| tools | `gym_data.py` | 205 | YAML-Daten + dataclass | 2–4 |
| tools | `document_reader.py` | 213 | Datei-IO + parsing | 2–4 |
| tools | `recurrence.py` | 258 | Datums-Logik | 2–4 |

### Tier 3 — Stores + Auth-Routen + Web-Helfer (10 Module, ~3070 LOC)

| Paket | Modul | LOC | Begründung | Erwartete Funde |
|-------|-------|-----|------------|-----------------|
| web | `avatar_editor.py` | 226 | API + State | 2–5 |
| web | `dashboard_auth_routes.py` | 254 | Login-Routen | 3–5 |
| web | `robot_proxy.py` | 317 | HTTP-Proxy | 3–6 |
| web | `setup_tests.py` | 347 | Test-Runner-API | 3–6 |
| web | `dashboard_auth.py` | 416 | Auth-Logik (bcrypt+HMAC) | 5–8 |
| tools | `web_fetcher.py` | 263 | HTTP + trafilatura | 3–5 |
| tools | `reminder_store.py` | 263 | SQLite-Store | 3–5 |
| tools | `todo_store.py` | 282 | SQLite-Store | 3–5 |
| tools | `weather_client.py` | 362 | HTTP-Client + parsing | 4–7 |
| tools | `document_classifier.py` | 365 | LLM-Aufrufe + dataclass | 4–8 |

### Tier 4 — 3rd-Party-lastig + größere Stores (7 Module, ~3430 LOC)

| Paket | Modul | LOC | Begründung | Erwartete Funde |
|-------|-------|-----|------------|-----------------|
| tools | `note_store.py` | 391 | SQLite + LLM | 5–8 |
| tools | `stirling_pdf.py` | 417 | HTTP + Multipart | 5–8 |
| web | `secrets_registry.py` | 427 | Crypto + Registry | 5–9 |
| tools | `google_calendar.py` | 452 | google-api, ohne Stubs | 6–10 |
| tools | `caldav_calendar.py` | 462 | caldav, vobject, ohne Stubs | 6–10 |
| tools | `caldav_tasks.py` | 633 | caldav + `_call_with_retry[T]` | 8–14 |
| tools | `email_client.py` | 645 | imaplib + AnyStr-Wrapper-Pattern | 10–15 |

### Tier 5 — die Brocken + CI-Gate (5 Module, ~4107 LOC)

| Paket | Modul | LOC | Begründung | Erwartete Funde |
|-------|-------|-----|------------|-----------------|
| tools | `nextcloud_files.py` | 660 | WebDAV-Client | 8–14 |
| web | `setup_wizard.py` | 712 | FastAPI + Templates + State | 10–18 |
| tools | `carddav_sync.py` | 809 | vobject, große Sync-Logik | 12–20 |
| tools | `contact_store.py` | 854 | SQLite + Search + dedup | 12–20 |
| web | `settings_dashboard.py` | 1072 | FastAPI + 30+ Routen | 15–25 |

**Summe Funde-Schätzung:** ~140–230 über alle Tiers. Größenordnung
analog Phase 76 (dort 46 Funde initial gemeldet, ~70 final fixiert
inklusive CI-Iteration). Schätzung ist grob — Etappe 0 ergibt
Ground Truth.

### 3.6 Ground Truth (gemessen 2026-05-02 in Etappe 0)

Probe-Run mit allen 39 Modulen + zwei `__init__.py` auf `strict = true`,
ergab **268 Funde in 34 Files** (41 source files geprüft, 7 Files
fund-frei). Damit ~17% über der oberen Konzept-Schätzung.

**Top-Treffer (>5 Funde):**

| Modul | Tier | Funde | Schätzung | Delta |
|-------|------|-------|-----------|-------|
| `tools/caldav_tasks.py` | 4 | 49 | 8–14 | +35 |
| `tools/caldav_calendar.py` | 4 | 39 | 6–10 | +29 |
| `tools/google_calendar.py` | 4 | 32 | 6–10 | +22 |
| `web/settings_dashboard.py` | 5 | 29 | 15–25 | +4 |
| `web/setup_wizard.py` | 5 | 23 | 10–18 | +5 |
| `tools/gym_data.py` | 2 | 16 | 2–4 | +12 |
| `web/avatar_editor.py` | 3 | 9 | 2–5 | +4 |
| `tools/email_client.py` | 4 | 8 | 10–15 | -2 |
| `web/secrets_api.py` | 2 | 6 | 2–4 | +2 |
| `tools/weather_client.py` | 3 | 6 | 4–7 | 0 |

**Überraschend sauber (kleiner als geschätzt):**

| Modul | Tier | Funde | Schätzung |
|-------|------|-------|-----------|
| `tools/contact_store.py` | 5 | 4 | 12–20 |
| `tools/carddav_sync.py` | 5 | 4 | 12–20 |
| `tools/nextcloud_files.py` | 5 | 2 | 8–14 |
| `web/dashboard_auth.py` | 3 | 1 | 5–8 |
| `tools/note_store.py` | 4 | 1 | 5–8 |

**Beobachtung:** die drei Caldav/Google-Module dominieren mit zusammen
**120 Funden (45% des Totals)**. Hauptursache vermutlich `Any`-Lecks
durch die jetzt stub-losen Imports (`icalendar`, `caldav`, `google.*`,
`googleapiclient.*`). Viele werden mit gebündelten `cast(dict[str,
Any], ...)`-Hilfen oder einem dünnen API-Wrapper pro Modul wegfallen.
Heißt: 49 ≠ 49 commits, eher 5–8 strukturelle Fixes pro Modul.

**Konsequenz für Etappe 4:** evtl. 3 Sessions statt 2. Tier 4 enthält
**127 von 268 Funden (47%)**. Tier 5 dagegen entspannter als geschätzt
(60 Funde statt 70+).

## 4. Konkrete `mypy`-Konfiguration

### 4.1 Wildcard → enumerierte Liste (Variante A)

In Etappe 0 wird der bestehende `[tool.mypy.overrides]`-Block

```toml
[[tool.mypy.overrides]]
module = [
    "elder_berry.actions.*",
    ...
    "elder_berry.tools.*",
    ...
    "elder_berry.web.*",
    ...
]
follow_imports = "silent"
ignore_errors = true
```

aufgeteilt in **drei** Blöcke:

```toml
# --- Out-of-Scope-Pakete (unverändert silenced bis eigene Phase) ---
[[tool.mypy.overrides]]
module = [
    "elder_berry.actions.*",
    "elder_berry.agent.*",
    "elder_berry.avatar.*",
    "elder_berry.character.*",
    "elder_berry.comms.*",
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

# --- Phase 76c WIP: noch nicht-strict tools/-Module ---
# Liste schrumpft mit jedem Tier-Commit. Am Ende von 76c leer und
# der Block wird geloescht.
[[tool.mypy.overrides]]
module = [
    "elder_berry.tools.brave_search_client",
    "elder_berry.tools.caldav_calendar",
    # ... alle 22 tools/-Module initial
]
follow_imports = "silent"
ignore_errors = true

# --- Phase 76c WIP: noch nicht-strict web/-Module ---
[[tool.mypy.overrides]]
module = [
    "elder_berry.web.avatar_editor",
    "elder_berry.web.dashboard_auth",
    # ... alle 17 web/-Module initial
]
follow_imports = "silent"
ignore_errors = true
```

Pro strict-Commit wandert das Modul aus dem WIP-Block in den
`strict = true`-Block. Diff bleibt sichtbar, kein impliziter
Override-Precedence-Trick.

### 4.2 Neue Drittanbieter-Ignores

Zum bestehenden `ignore_missing_imports`-Block kommen in Etappe 0:

```toml
[[tool.mypy.overrides]]
module = [
    # ... bestehende Einträge
    "icalendar.*",                          # caldav_calendar, caldav_tasks
    "google.auth.*",                        # google_calendar
    "google.oauth2.*",                      # google_calendar
    "google_auth_oauthlib.*",               # google_calendar (OAuth-Flow)
    "googleapiclient.*",                    # google_calendar
]
ignore_missing_imports = true
```

Zusätzlich: **vor** dem ersten strict-Commit pro Modul wird per Probe
geprüft, ob das Modul weitere Stub-lose Libs importiert. Ground Truth
in Etappe 0.

### 4.3 CI bleibt unverändert während 76c

`.github/workflows/ci.yml` `typecheck`-Job läuft weiter gegen
`src/elder_berry/core`. Erst im **letzten Commit von Etappe 5**
wird der Scope erweitert auf
`src/elder_berry/core src/elder_berry/tools src/elder_berry/web`.
Während der Etappen 1–4 werden tools/web-Funde lokal verifiziert
(`.venv\Scripts\python.exe -m mypy src/elder_berry/<paket>/<modul>.py`).

Risiko siehe R6.

## 5. Etappen / Vorgehen

**Branch-Strategie:** Phasen-Branch `feature/phase-76c-mypy-rollout-tools-web`
zweigt aus `main`. Etappen-Sub-Branches zweigen aus dem Phasen-Branch
ab und werden dorthin gemerged. Pro Etappe ein PR (User macht den
selbst, kein automatischer PR aus Code-Side).

### 5.1 Etappe 0 — Setup (1 Session)

- `pyproject.toml`: Wildcard-Block aufgeteilt (siehe §4.1), neue
  3rd-Party-Ignores ergänzt (siehe §4.2).
- `mypy src/elder_berry/tools src/elder_berry/web` einmal laufen lassen,
  Funde-Anzahl als Ground Truth in journal.txt sichern.
- IMAP-AnyStr-Wrapper-Pattern in §10 dieses Konzepts dokumentieren
  (für Etappe 4, email_client).
- **Branch:** `feature/phase-76c-mypy-tier0-setup`.
- **Akzeptanzkriterium:** `mypy src/elder_berry/core` weiterhin grün
  (kein Regress), pytest grün, neue Listen im pyproject sichtbar im
  Diff.

### 5.2 Etappe 1 — Tier 1 (1 Session, 7 Module)

- 7 kleine Module einzeln strict, jedes als eigener Commit.
- Pro Commit: Modul aus WIP-Block raus, in strict-Block rein.
- **Branch:** `feature/phase-76c-mypy-tier1`.
- **Akzeptanzkriterium:** alle 7 Module strict, mypy auf core+tools+web
  grün (lokal), pytest grün.

### 5.3 Etappe 2 — Tier 2 (1–2 Sessions, 10 Module)

- 10 mittlere Module, jedes als eigener Commit.
- Bei Bedarf: weitere `ignore_missing_imports`-Einträge.
- **Branch:** `feature/phase-76c-mypy-tier2`.
- **Akzeptanzkriterium:** 17/39 Module strict, mypy grün, pytest grün.

### 5.4 Etappe 3 — Tier 3 (2 Sessions, 10 Module)

- 10 mittel-große Module, jedes als eigener Commit.
- Achtung: `dashboard_auth.py` (416 LOC, bcrypt+HMAC) ist Auth-kritisch
  — Type-Annotation darf keine Verhaltensänderung schmuggeln. Pytest
  für `tests/test_dashboard_auth*.py` nach jedem Commit.
- **Branch:** `feature/phase-76c-mypy-tier3`.
- **Akzeptanzkriterium:** 27/39 Module strict, mypy grün, pytest grün.

### 5.5 Etappe 4 — Tier 4 (2 Sessions, 7 Module)

- 7 große, 3rd-party-lastige Module.
- IMAP-AnyStr-Wrapper für `email_client` einführen (siehe §10).
- `_call_with_retry`-Generics für `caldav_tasks` und `google_calendar`
  (PEP-695-Pattern aus Phase 76).
- **Branch:** `feature/phase-76c-mypy-tier4`.
- **Akzeptanzkriterium:** 34/39 Module strict, mypy grün, pytest grün.

### 5.6 Etappe 5 — Tier 5 + CI-Gate (2–3 Sessions, 5 Module)

- 5 größte Module, jedes als eigener Commit + Pause für Pytest.
- `settings_dashboard.py` (1072 LOC) bekommt ggf. seinen eigenen
  Branch-Push und Diff-Review-Pause; falls Funde >25, wird Etappe 5b
  abgespalten.
- Letzter Commit der Etappe: CI-Job-Scope auf
  `src/elder_berry/core src/elder_berry/tools src/elder_berry/web`
  erweitern. WIP-Blocks aus pyproject löschen (sind dann leer).
- **Branch:** `feature/phase-76c-mypy-tier5-gate`.
- **Akzeptanzkriterium:** alle 39 Module strict, mypy auf
  core+tools+web grün lokal **und** im CI, pytest grün, WIP-Blocks
  in pyproject entfernt.

## 6. Risiken / aktive Hinweise

- **R1 — `settings_dashboard.py` ist 1072 LOC.** Das ist 1.8× größer
  als der bisher größte Brocken (`assistant.py`). Erwarte 15–25 Funde,
  vermutlich FastAPI-`Depends()`-Returns als Any, viele Jinja-Render-
  Calls, viele Form-Body-Parsings. Mitigation: bei >25 Funde wird
  Etappe 5b abgespalten, Modul in zwei Commits gepackt (z.B. Routen
  vs. Helpers).
- **R2 — Externe Libs ohne Stubs.** `google-api-python-client`,
  `icalendar`, `googleapiclient`, `google-auth-oauthlib`. Werden in
  Etappe 0 in den `ignore_missing_imports`-Block aufgenommen. Folge:
  alle Returns aus diesen Libs sind `Any`. In den Modulen
  (`google_calendar`, `caldav_*`) muss konsequent `cast(dict[str,
  Any], r.json())` oder ein dünner Wrapper genutzt werden.
- **R3 — `_call_with_retry`-Generics.** `caldav_tasks._call_with_retry`
  und `google_calendar._call_with_retry` brauchen den gleichen
  PEP-695-Fix wie `_run_async` aus Phase 76. Pattern in §10 dokumentiert.
- **R4 — `contact_store.py` (854) + `carddav_sync.py` (809).** Größte
  Stores, vermutlich viele Optional-Narrowing-Stellen + dict-Generics.
  Mitigation: Optional-Narrowing-Asserts an klar abgegrenzten privaten
  Methoden, deren Vorbedingung der Aufrufer filtert (Pattern aus Phase
  76, sechsmal in `assistant.py` angewendet).
- **R5 — Variante A heißt längere Listen im pyproject.toml.** Während
  76c läuft, steht eine WIP-Liste mit 22 (sinkend) tools/-Modulen und
  17 (sinkend) web/-Modulen im pyproject. Diff-Lärm pro Commit. In
  Kauf nehmbar wegen Sichtbarkeit; Variante B (impliziter
  Override-Precedence) wurde bewusst verworfen.
- **R6 — CI bleibt während Etappen 1–4 stumm für tools/web.** Heißt:
  ein Drive-by-PR auf `tools/` oder `web/` kann ungetypten Code
  einführen, ohne dass der Job rot wird. Bestehende WIP-Listen in
  `pyproject.toml` (mit `ignore_errors = true`) decken das ab. Ist
  identisch zur Phase-76-Situation während Tier 1–3 (R4 dort).
  Mitigation: Etappe 5 zügig nach Etappe 4 anschließen.
- **R7 — `setup_wizard.py` (712) und `settings_dashboard.py` (1072)
  sind FastAPI + Jinja-lastig.** Falls Jinja2-Stubs (`jinja2.*`) Funde
  produzieren, ergänzen wir den `ignore_missing_imports`-Block. Sollte
  aber nicht nötig sein — `jinja2` hat eigene Stubs.
- **R8 — IMAP-Stub-Mismatch ist kein universelles Pattern.** Beim
  Vorab-Lesen von `email_client.py` wurden alle 6 mypy-Mismatches als
  Annotation-Lärm bestätigt (stdlib-`AnyStr`-Constraint vs. echte
  Polymorphie). **Aber:** nicht jedes Stub-Mismatch ist Annotation-Lärm.
  Bei jedem neuen Modul-Fund wird die runtime-Semantik geprüft, bevor
  der Cast/Wrapper kommt. Wenn ein Fund ein echter Bug ist, kommt der
  Bug-Fix als **separater Commit + Test** vor dem strict-Commit.
- **R9 — `warn_unused_ignores=True` zwingt Disziplin.** Wenn ein
  `# type: ignore` überflüssig wird (Lib bekommt Stub, Stub wird
  präziser), failt mypy. Wert: Drift wird sichtbar. Kosten: pflichtige
  Pflege bei Lib-Updates. Identisch zu R3 aus Phase 76.

## 7. Tests / Akzeptanzkriterien

Pro Etappe:
- `mypy src/elder_berry/core src/elder_berry/tools src/elder_berry/web`
  läuft lokal mit Exit-Code 0 (auf den jeweils strict-aktivierten
  Modulen + den noch silenced Modulen).
- `mypy src/elder_berry` (alle 155+ files) läuft lokal grün.
- Pytest-Suite weiterhin grün, kein neuer Skip — keine
  Verhaltensänderungen erlaubt.
- CI-Job `typecheck` grün (während Etappen 1–4 nur core/, ab Etappe 5
  inklusive tools/+web/).

Nach Etappe 5:
- Alle 39 Module in `tools/` + `web/` als `strict = true` markiert.
- WIP-Blocks aus `pyproject.toml` entfernt.
- CI-Scope auf `src/elder_berry/core src/elder_berry/tools
  src/elder_berry/web`.
- Phase 76c als abgeschlossen in journal.txt + CHANGELOG.md vermerkt.

## 8. Out of Scope

- `comms/` strict — Phase 76b (separat, parallel zulässig).
- `tests/` strict — Phase 76d (optional).
- `avatar/`, `robot/`, `agent/`, `memory/`, `llm/`, `stt/`, `tts/`,
  `system/`, `actions/`, `webapp/`, `server/`, `character/` strict —
  jeweils eigene Phase oder gar nicht (Cost-Benefit prüfen).
- Eigenstubs (`stubs/`-Verzeichnis) für `google-api-python-client` &
  Konsorten. `ignore_missing_imports` ist die richtige Antwort, bis
  ein Stub-Paket verfügbar ist.

## 9. Folge-Phasen

- **Phase 76b (offen):** mypy für `comms/`. Kann parallel laufen,
  unabhängige Tier-Sortierung.
- **Phase 76d (offen):** Test-Code typprüfen, optional.
- **Phase 77 (offen):** Plugin-Registry (sieht 76c als Vorbedingung).

## 10. Patterns

### 10.1 Aus Phase 76 übernehmen

1. **Optional-Narrowing-Assert** in privaten Methoden mit Filter-
   Vorbedingung im Aufrufer:
   ```python
   def _do_thing(self) -> None:
       assert self._client is not None  # caller filtered None
       self._client.do()
   ```

2. **`cast(dict[str, Any], json.loads(...))`** für JSON-Parsing
   ohne TypedDict.

3. **`cast(dict[str, Any], r.json())`** für httpx/requests-Returns.

4. **PEP-695-Generics** für generische Helfer:
   ```python
   def _call_with_retry[T](self, op: Callable[[], T]) -> T:
       ...
   ```

5. **`dict` ohne Generics → `dict[str, Any]`** für heterogene
   API-Bodies.

6. **`# type: ignore[assignment]` direkt im except** für
   try/except-ImportError-Fallbacks. **Kein** `var: Any`-Vor-
   Annotation-Pattern (war fragil, Journal 2026-05-01).

7. **`re.Pattern` ohne Generics → `re.Pattern[str]`.**

### 10.2 Neu für 76c

8. **IMAP-AnyStr-Wrapper** für `email_client.py`. Hintergrund:
   `imaplib.IMAP4.uid()` deklariert in stdlib-Stubs `*args: AnyStr`
   (TypeVar-Constraint, alle Args müssen einheitlich `str` ODER
   einheitlich `bytes` sein). CPythons echte Implementation in
   `Lib/imaplib.py` akzeptiert mixed `str`/`bytes` und `None` und
   encoded selbst. RFC 3501 §6.4.4 erlaubt `SEARCH None criteria`
   für „kein CHARSET". Lösung:

   ```python
   def _uid(
       conn: imaplib.IMAP4,
       command: str,
       *args: object,
   ) -> tuple[str, list[Any]]:
       """imaplib.IMAP4.uid()-Wrapper.

       stdlib-Stub erzwingt AnyStr fuer alle args, runtime akzeptiert
       mixed str/bytes/None (RFC 3501 §6.4.4). Kein Bug-Fix noetig --
       runtime-Semantik ist seit Python 2 stabil.
       """
       return conn.uid(command, *args)  # type: ignore[arg-type]
   ```

   Alle 6 Aufrufer in `email_client.py` verwenden den Wrapper. Wert:
   eine zentrale `# type: ignore`-Stelle statt sechs verstreute, mit
   Begründung im Docstring. Bei Stub-Update muss nur eine Stelle
   gepflegt werden.

9. **Bug-Fix vor Strict-Commit (Notfall-Pattern).** Falls bei einem
   Modul ein Stub-Mismatch ein **echter** Runtime-Bug ist (nicht nur
   Annotation-Lärm wie bei IMAP), kommt der Bug-Fix als separater
   Commit mit eigenem Test, **bevor** der strict-Commit das Modul
   stricten macht. Aktuell nicht erwartet (siehe R8), aber Pattern
   reserviert.

10. **Starlette-Middleware dispatch-Annotation** (etabliert in Etappe
    1 mit `security_middleware` und `origin_check_middleware`,
    wiederholt sich in Tier 2/3 für alle weiteren BaseHTTPMiddleware-
    Subklassen):

    ```python
    from starlette.middleware.base import (
        BaseHTTPMiddleware,
        RequestResponseEndpoint,
    )
    from starlette.responses import Response
    from starlette.types import ASGIApp

    class XMiddleware(BaseHTTPMiddleware):
        def __init__(self, app: ASGIApp, ...) -> None: ...

        async def dispatch(
            self, request: Request, call_next: RequestResponseEndpoint
        ) -> Response: ...
    ```

    Wird in Tier 2 für `rate_limiter`, `settings_token_middleware`,
    `dashboard_auth_middleware` kopiert.

11. **Lazy-Init-Client-Pattern** (etabliert in Etappe 2 mit
    `brave_search_client` und `gym_data`, kommt voraussichtlich in
    Tier 3/4 für caldav/google-Clients wieder). Hintergrund: viele
    Clients initialisieren `self._client = None` und erstellen erst
    beim ersten Aufruf einen `httpx.Client`. Mypy infert ohne
    Annotation den Typ `None`, womit die spätere Zuweisung scheitert
    und der Early-Return als unreachable markiert wird:

    ```python
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import httpx  # nur fuer Annotation -- runtime-import bleibt lazy

    class XClient:
        def __init__(self, ...) -> None:
            self._client: httpx.Client | None = None

        def _get_client(self) -> httpx.Client:
            if self._client is not None:
                return self._client
            import httpx  # lazy fuer Tower-Startup-Geschwindigkeit
            self._client = httpx.Client(...)
            return self._client
    ```

    Der `import httpx` bleibt absichtlich lazy in der Methode (Tower-
    Startup-Geschwindigkeit, optional-Dep), die Annotation kommt
    separat über `TYPE_CHECKING`.

12. **SQLite-Store-Pattern** (etabliert in Etappe 3 mit
    `reminder_store` und `todo_store`, kommt voraussichtlich in Tier
    4/5 für `note_store`, `contact_store`, `caldav_tasks` wieder).
    Drei wiederkehrende Mini-Funde pro Store:

    ```python
    from typing import Any

    # 1. cursor.lastrowid ist int | None, dataclass.id erwartet int.
    cursor = self._conn.execute("INSERT ...", (...))
    self._conn.commit()
    # Nach erfolgreichem INSERT setzt sqlite3 lastrowid garantiert.
    assert cursor.lastrowid is not None
    return Item(id=cursor.lastrowid, ...)

    # 2. Heterogene Query-Parameter:
    params: list[Any] = [user_id]
    if priority:
        params.append(priority)

    # 3. DB-Rows sind heterogene tuples:
    @staticmethod
    def _row_to_item(row: tuple[Any, ...]) -> Item: ...
    ```

    Die `assert lastrowid is not None`-Stelle ist nicht Defense-in-
    Depth; sie ist die einzige Stelle, an der mypy unterscheidet
    zwischen "INSERT war erfolgreich" und "lastrowid könnte None sein
    (z.B. nach einem SELECT)".

---

**Akzeptanz dieses Konzepts durch User → Etappe 0 startet.**
