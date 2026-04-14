# Phase 52 – Unified Settings & Startup-Feedback

**Status:** Konzept (2026-04-14)
**Branch (geplant):** `feature/phase-52-unified-settings`
**Roadmap-Referenz:** PROJECT_ROADMAP.md Phase 52 (52.1 – 52.3)

## 1. Ausgangslage

Die Konfiguration von Saleria ist heute auf drei Oberflächen verteilt:

1. **Setup-Wizard** (`/setup`, 8 Schritte) – einmalige Erst-Einrichtung, eigenes
   Template, eigene Test-Endpoints (`/api/setup/test/{service}`), eigener
   Step-Flow.
2. **Settings-Dashboard** (`/settings`, Phase 45) – aktuell nur 4 Verhalten-
   Settings (`allowed_senders`, `timezone`, `stt_timeout`, `llm_mode`) als
   `SettingDefinition`-Liste in `settings_dashboard.py`.
3. **Secrets-API** (`/api/secrets/*`, `secrets_api.py`) – ~30 Einträge in
   `SECRET_REGISTRY` (kategorisiert), wird vom Wizard und vom Dashboard
   konsumiert, hat aber kein eigenes UI.

**Folgen:**
- `matrix_allowed_senders` ist doppelt gepflegt (Registry **und**
  SettingDefinition).
- Wer einen API-Key wechseln will, muss den Wizard re-durchlaufen oder die
  API direkt callen – kein UI.
- `start_saleria.py` loggt Einzelmeldungen, gibt aber keine Übersicht „was
  läuft, was fehlt".
- **Sicherheitslücke:** `settings_dashboard` bindet `0.0.0.0:8090` ohne Auth
  (`settings_dashboard.py:134`). Wer im LAN ist, kann Secrets lesen/schreiben.
  Phase 52 darf das nicht ignorieren – ein Unified Panel macht den Zugriff
  bequemer und damit auch missbrauchbarer.

## 2. Ziele

1. **Eine Quelle der Wahrheit** für Konfigurations-Definitionen.
2. **Ein UI** für Re-Konfiguration (`/settings`), Wizard nur noch für
   First-Run.
3. **Verständliches Startup-Feedback** statt verstreuter Log-Zeilen.
4. **Sicherheitsbasis:** Loopback-Only Bind + Token-Header, bevor das
   Unified-Panel den Zugriff vereinfacht.

**Nicht-Ziele (bewusst ausgeschlossen):**
- YAML-basierte Settings-Definitionen → Phase 53.3.
- Komplette Wizard-Entfernung. Wizard bleibt als First-Run-Pfad.
- Migration auf eine andere Auth-Lösung als statischer Token (kein OAuth,
  kein Login-System).

## 3. Architektur-Entscheidungen

### 3.1 Schema-Konsolidierung (52.0, Vorarbeit)

`SECRET_REGISTRY` wird Single Source of Truth. Erweiterung:

```python
class SecretRegistryEntry(TypedDict):
    key: str
    label: str
    category: str
    sensitive: NotRequired[bool]            # Default: True
    behavior: NotRequired[bool]             # NEU – non-secret behavior setting
    requires_restart: NotRequired[bool]
    type: NotRequired[str]                  # str | int | float | url | select | textarea
    options: NotRequired[list[dict]]        # NEU – für select-Typen
    min: NotRequired[float | int]
    max: NotRequired[float | int]
    pattern: NotRequired[str]
    description: NotRequired[str]
    link: NotRequired[str]
    risk_level: NotRequired[str]            # NEU – "low" | "medium" | "high"
```

Die heutige `_setting_definitions()`-Liste in `settings_dashboard.py`
verschwindet. Die 4 Verhalten-Settings werden Registry-Einträge mit
`behavior=True, sensitive=False`. Der Doppel-Eintrag `allowed_senders` ↔
`matrix_allowed_senders` wird auf den Registry-Key konsolidiert.

**Migration:** Alte Storage-Keys werden beim Lesen einmal auf den neuen Key
gemappt, danach unter dem neuen Key gespeichert. Mapping-Tabelle in
`secrets_api.py` als Konstante. Keine Datenverluste – der SecretStore wird
nicht migriert, nur der Lese-Pfad.

### 3.2 Unified Settings-Panel (52.1)

- **Route:** `GET /settings` rendert HTML statt JSON. JSON-Endpoints
  (`/api/secrets/*`) bleiben unverändert (Tests, Skripte).
- **Tabs (aus `category` der Registry, Reihenfolge fest):**
  1. KI & Sprache
  2. Suche & Karten
  3. Matrix
  4. E-Mail
  5. Nextcloud
  6. Wetter & Standort
  7. Dienste
  8. Infrastruktur
  9. **Verhalten** (Tab nur für `behavior=True`)
  10. **Sicherheit** (CORS, Allowed Senders – kommt aus Registry mit
      `risk_level="high"`)
- **Pro Feld:** Inline-Edit, "Verbindung testen"-Button (nur wenn ein Test
  in `/api/setup/test/{service}` existiert – der Wizard-Endpoint wird
  geteilt, *nicht* dupliziert), Hilfe-Link, "Restart nötig"-Badge.
- **Sensitive Felder:** GET liefert nur `{"set": true}` oder `{"set":
  false}`, niemals den Klartext. PUT akzeptiert neuen Wert.
- **Templates:** `web/templates/settings_panel.html`. Vermutlich 2 Chunks
  (Layout + Tab-Komponente, Inline-Edit-JS). Kein Build-Step, Vanilla JS.

### 3.3 Auth-Modell für `/settings` (NEU – nicht in Roadmap, aber Pflicht)

Aktuell: `host="0.0.0.0"`, kein Token. Phase 52 fixt das in zwei Stufen:

1. **Default-Bind auf `127.0.0.1`.** Wer Remote-Zugriff will, setzt
   `SALERIA_SETTINGS_BIND=0.0.0.0` explizit per ENV.
2. **Statischer Token im Header `X-Saleria-Settings-Token`.** Token wird
   beim ersten Start generiert und im SecretStore unter
   `settings_dashboard_token` abgelegt. Beim Start wird der Token einmal in
   die Konsole geloggt (wie Jupyter es macht). Alle PUTs auf
   `/api/secrets/*` und `/api/settings/*` prüfen den Header. GETs auf
   nicht-sensitive Felder bleiben offen (für Status-Anzeige).
3. **Re-Confirm für Felder mit `risk_level="high"`:** Frontend zeigt einen
   zusätzlichen Bestätigungsdialog bevor PUT gesendet wird. Nur UI – kein
   zweiter Backend-Roundtrip.

**Bewusst nicht:** Login-System, Sessions, CSRF-Tokens. Token-Header reicht
für Single-User-Saleria.

### 3.4 Startup-Summary (52.2)

Neues Modul `src/elder_berry/core/startup_summary.py`:

```python
class StartupSummary:
    def add(self, component: str, status: Literal["ok","warn","fail"],
            detail: str = "") -> None: ...
    def render(self) -> str: ...        # ASCII-Box
    def to_matrix_message(self) -> str: ...
```

`scripts/start_saleria.py` instanziiert eine Summary, jede `init_*`-Funktion
ruft `summary.add(...)` statt nur `logger.info`. Am Ende von `main()` wird
`render()` über `print()` ausgegeben und – falls Matrix verfügbar – als
Nachricht gesendet (best effort, kein Hard-Fail).

**Warum eigenes Modul statt lokaler Funktion?** Testbarkeit (CLAUDE.md:
eine Klasse pro Datei) und mögliche Wiederverwendung im `/api/status`
Endpoint später.

### 3.5 Setup-Wizard → Settings-Migration (52.3)

- Im SecretStore neuer Key `setup_completed` (boolean as `"1"`/`"0"`).
- Wird gesetzt nach erfolgreichem `POST /api/setup/complete`.
- `GET /setup` ohne `?force=1` und mit `setup_completed=="1"` liefert
  `307 → /settings`.
- `audio_dashboard.html` "Re-Setup"-Button wird entfernt, durch Link auf
  `/settings#kategorie` ersetzt (Anchor lädt den passenden Tab via JS).
- Bestehende Wizard-Schritte/Templates bleiben unverändert.

## 4. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Schema-Migration verliert Settings | Lese-Mapping statt Datenmigration; alte Keys bleiben im Store |
| Token im Klartext in der Konsole | Akzeptiert (Single-User, lokal); Token rotiert nur bei manueller Löschung |
| Loopback-Default bricht bestehende Remote-Setups | ENV-Override dokumentiert; Migrations-Hinweis im Startup-Log |
| `/settings` und Wizard driften wieder auseinander | Tests prüfen, dass jeder Wizard-Step nur Registry-Keys schreibt |
| Sensitive-Felder im GET geleakt | Test-Suite prüft, dass Klartext nirgends im JSON-Response erscheint |
| Startup-Summary blockiert Matrix-Send | Send läuft mit `try/except` + Timeout, niemals blocking |

## 5. Testplan

Neue Test-Dateien (eine pro Klasse/Modul):

- `tests/test_secret_registry.py` – Schema-Vollständigkeit, keine Doppel-Keys,
  alle Wizard-Step-Keys vorhanden, behavior-Flag korrekt.
- `tests/test_settings_panel.py` – Rendering pro Tab, Sensitive-Maskierung,
  Token-Auth (PUT ohne Token → 401, mit Token → 200), Loopback-Bind-Default.
- `tests/test_startup_summary.py` – `add/render`, leere Summary, alle drei
  Status, Matrix-Message-Format.
- `tests/test_setup_wizard.py` (erweitern) – Marker-Logik, Redirect ohne
  `?force=1`, Wiederholbar mit `?force=1`.

Bestehende Tests, die migriert werden müssen:
- `tests/test_settings_dashboard.py` – auf neue Registry-basierte
  Definitionen umstellen.
- `tests/test_secrets_api.py` – Token-Header-Erwartung.

## 6. Reihenfolge der Umsetzung

1. **52.0** Schema-Konsolidierung + Tests (kleine PR-Einheit, isoliert).
2. **52.1a** Auth (Loopback + Token) – muss vor dem UI live sein.
3. **52.1b** Settings-Panel-Template + Route.
4. **52.2** StartupSummary-Modul + Integration in `start_saleria.py`.
5. **52.3** Wizard-Marker + Dashboard-Link.

Jeder Teilschritt: betroffene Tests grün → Zwischenstand in journal.txt →
nächster Teilschritt.

## 7. Festgelegte Detail-Entscheidungen (2026-04-14)

- **ENV-Variable Bind-Override:** `ELDER_BERRY_SETTINGS_BIND` (Default
  `127.0.0.1`). Folgt der bestehenden `ELDER_BERRY_*`-Konvention für
  Saleria-eigene Variablen.
- **Token-Persistenz:** Hybrid – Datei `${ELDER_BERRY_HOME}/settings_token`
  (`chmod 600` auf POSIX) **und** beim ersten Start einmal in der Konsole
  geloggt. Token rotiert nur durch manuelles Löschen der Datei.
- **`risk_level`:** drei Stufen (`low`/`medium`/`high`):
  - `low`: PUT ohne Confirm-Dialog (z.B. `weather_city`)
  - `medium`: Confirm-Dialog im UI (z.B. `stt_timeout`)
  - `high`: Confirm-Dialog + sichtbarer "Restart nötig"-Hinweis + Audit-Log-
    Eintrag (z.B. `matrix_allowed_senders`, `anthropic_api_key`)
