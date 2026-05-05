# Phase 77.5 – Plugin-Inspector + Phase-78-Voraussetzung 🔍

**Status:** Konzept (2026-05-05)
**Branch:** `feature/phase-77-5-plugin-inspector`
**Aufwand:** ~1 Session
**Voraussetzung:** Phase 77 Etappe 3 abgeschlossen
**Roadmap-Referenz:** Vorbereitung für Phase 78 (Self-Suggestion)

## 1. Ausgangslage

Mit Phase 77 ist die Plugin-Registry vollständig: 23 Builtin-Plugins,
User-Dir-Discovery, Entry-Points, Pattern-Konflikt-Detektor. Die Registry
ist Python-public, aber **niemand sieht sie**:

- Kein Dashboard-Endpoint. `grep load_plugins src/elder_berry/web/`
  liefert nichts.
- Kein Matrix-Command. `hilfe` zeigt Endnutzer-Kategorien
  (basis, mail, kalender, …), nicht das Manifest dahinter.
- Kein Quellen-Tracking. `load_plugins()` liefert eine flache Liste —
  ob ein Plugin Builtin, User-Dir oder Entry-Point ist, ist nach dem
  Laden nicht mehr unterscheidbar.

Beim Lesen des [Phase-78-Konzepts](phase-78-plugin-self-suggestion.md)
fällt eine **inhaltliche Lücke** im Dedupe-Check (§3.6) auf:

> *„Bevor Saleria einen Plugin-Kandidaten-JSON-Block emittiert, soll
> sie selbst prüfen, ob das Intent schon existiert. Dazu bekommt sie
> im System-Prompt eine Liste \[aus `proposal_store.list_active()`\]"*

Saleria sieht nur **Vorschläge**, nicht **bereits geladene Plugins**.
Heißt: sie kann „weather_plugin" als neuen Kandidaten vorschlagen,
obwohl `weather` Builtin ist. Das macht Phase 78 ohne Fix
strukturell unbrauchbar.

## 2. Ziel

1. Quellen-Tracking in der Registry: `(plugin, source)`-Paare,
   `source ∈ {"builtin", "user_dir", "entry_point"}`.
2. Read-Only-Dashboard-Tab `Plugins` mit Tabelle aller geladenen
   Plugins.
3. Matrix-Command `plugins` (auch ohne Browser zugänglich).
4. **Phase-78-Fix:** System-Prompt-Builder bekommt zusätzlich die
   Plugin-Namen, damit Saleria nicht für existierende Capabilities
   Vorschläge generiert. Ist für Phase 78 zwingend.

**Nicht-Ziele dieser Phase:**

- Kein Schreib-Zugriff (Plugin aktivieren/deaktivieren). Toggle wäre
  ein eigenes Konzept (Privilege-Level + Reload-Strategie).
- Keine Plugin-Detail-Page mit Pattern-Tester. Wenn Bedarf da ist,
  Folgephase.
- Kein Hot-Reload (Phase 79+).
- Keine Plugin-Health-Checks (Connectivity-Probes pro Service-Plugin).

## 3. Architektur

### 3.1 Quellen-Tracking in der Registry

Die drei Loader (`_load_builtin`, `_load_user_directory`,
`_load_entry_points`) liefern aktuell nur `Iterator[CommandPlugin]`.
Quelle geht verloren, sobald `load_plugins()` die Listen aneinander
hängt.

**Lösung A** (Plugin-Klasse erweitern): neues Feld `source: str` in
`CommandPlugin`. Nachteil: `CommandPlugin` ist `frozen=True` und das
Feld ist nicht vom Plugin-Autor zu setzen — Lader müsste das Plugin
nach `dataclasses.replace` neu konstruieren. Bricht außerdem
Plugin-Manifeste, die `frozen` als Identitätsgarantie nutzen.

**Lösung B** (separate Datenklasse): neues `LoadedPlugin`-Wrapper:

```python
@dataclass(frozen=True)
class LoadedPlugin:
    plugin: CommandPlugin
    source: PluginSource  # Enum: BUILTIN | USER_DIR | ENTRY_POINT
    source_path: str | None  # Datei oder Distribution-Name, debug-only
```

`load_plugins()` liefert weiterhin `list[CommandPlugin]` für
Abwärtskompatibilität, neuer Helfer `load_plugins_with_sources()`
liefert `list[LoadedPlugin]`. Der Orchestrator nutzt weiter die alte
API, der Inspector die neue.

**Empfehlung: Lösung B.** Kein Bruch der Plugin-Manifeste, klare
Separation von „was ein Plugin ist" und „woher es kam".

### 3.2 Dashboard-Tab `Plugins`

Im bestehenden Settings-Panel ([settings_panel.html](../../src/elder_berry/web/templates/settings_panel.html))
ist die Sidebar tab-basiert (`<div id="tabList">`). Der neue Tab
reiht sich nach den existierenden ein.

**Endpoint** in neuer Datei `src/elder_berry/web/plugins_api.py`:

```
GET /api/plugins  →  {
  "plugins": [
    {
      "name": "weather",
      "priority": 15,
      "category": "wetter",
      "version": "1.0.0",
      "source": "builtin",
      "source_path": "weather_commands.py",
      "conflicts": ["calendar"],
      "requires": [],
      "active": true,        // Factory hat einen Handler geliefert
      "help_section_excerpt": "Wetter:\n  wetter -- aktuelles Wetter…"
    },
    …
  ],
  "summary": {
    "total": 23,
    "by_source": {"builtin": 23, "user_dir": 0, "entry_point": 0}
  }
}
```

Auth: hinter `dashboard_auth_middleware` (Phase 58), wie alle
`/api/`-Routen mit Settings-Bezug.

**Frontend:** Tabelle mit Spalten Name | Source | Priority | Category |
Version | Conflicts | Active. Default-Sort nach Priority. Filter-
Dropdown für Source. Conflicts-Spalte verlinkt auf das andere Plugin
(scrollt in der Tabelle dahin). Kein Modal, keine Detail-Page —
„hilfe \<kategorie\>" liefert die Texte besser.

### 3.3 Matrix-Command `plugins`

Endnutzer-Sicht. Drei Sub-Commands:

```
plugins                  → kompakte Liste (Name, Priority, Source)
plugins detail <name>    → Manifest eines einzelnen Plugins
plugins konflikte        → nur die mit conflicts != ()
```

**Implementierung:** neuer Handler `plugins_commands.py` mit eigenem
PLUGIN-Manifest, Priority 80 (normal, kein Konflikt-Hotspot). Liest
über `load_plugins_with_sources()`, formatiert als Code-Block für
Element. `plugins detail weather` → Volltext der `help_section`.

Risiko: `plugins` ist ein generisches Wort. Schaut, ob es kollidiert
(höchstwahrscheinlich nicht — der Conflict-Detector aus 77 Etappe 3
fängt das im PR-Review).

### 3.4 Phase-78-Fix: System-Prompt-Erweiterung

Aktuell baut `core/assistant.py` (oder ähnlicher Builder, je nach
Stand) den System-Prompt aus statischen + dynamischen Blöcken. Phase 78
plant einen `[Vorhandene Plugin-Vorschläge]`-Block aus
`proposal_store.list_active()`. Vor diesem Block kommt zusätzlich:

```text
[Bereits geladene Plugins (kein Vorschlag wenn Match):
- weather: Wetter, Timer, Erinnerungen, Briefing
- calendar: Termine, Suche, Erstellen
- mail: Mails, Suche, Antworten
- …
- advanced: LLM-Fallback]
```

Generiert aus `[(p.name, p.category) for p in load_plugins()]`. Trim
nach 30 Zeilen falls die Liste wächst. Begrenzung der Prompt-Länge
ist relevant — 23 Zeilen heute, aber wenn User-Plugins dazukommen,
muss das nicht ungebremst wachsen.

**Wichtig:** Dieser Fix gehört organisatorisch zu Phase 78, wird hier
aber implementiert, weil:

1. Phase 78 läuft sonst sinnlos (Saleria duplicates Builtins).
2. Der Builder-Fix ist 5 Zeilen — getrennte Phase wäre Overhead.
3. Der Inspector-Tab sieht visuell genau das, was Saleria im Prompt
   sieht. Gemeinsame Impl spart Doppelarbeit.

## 4. Klassen-Layout

```
src/elder_berry/comms/commands/
└── registry.py                    (erweitert: PluginSource Enum,
                                    LoadedPlugin, load_plugins_with_sources)

src/elder_berry/comms/commands/
└── plugins_commands.py            (neu: PluginsCommandHandler + PLUGIN)

src/elder_berry/web/
└── plugins_api.py                 (neu: GET /api/plugins, hinter Login)

src/elder_berry/web/templates/
└── settings_panel.html            (erweitert: Plugins-Tab im tabList)

src/elder_berry/core/
└── assistant.py                   (erweitert: Plugin-Block im
                                    System-Prompt-Builder)
```

## 5. Etappen / Vorgehen

Eine Session, vier Schritte:

1. **Registry-Erweiterung** (~20 min)
   - `PluginSource`-Enum, `LoadedPlugin`-Dataclass.
   - `_load_builtin`/`_load_user_directory`/`_load_entry_points`
     liefern intern `LoadedPlugin`. `load_plugins()` bleibt rückwärts-
     kompatibel (extrahiert `.plugin` für die alte API). Neuer Helfer
     `load_plugins_with_sources()`.
   - Tests in `test_plugin_registry.py` ergänzen: source-Felder
     korrekt, Priority-Sort weiter stabil.
   - mypy strict (registry.py ist Tier 1).

2. **Plugin-Inspector-API + Frontend** (~30 min)
   - `plugins_api.py` mit `GET /api/plugins` hinter Login.
   - Tab im `settings_panel.html` + minimalistisches JS für Fetch + Render.
   - Tests: `test_plugins_api.py` (Auth-401, korrekte Felder, Source-
     Aggregation).

3. **Matrix-Command `plugins`** (~20 min)
   - Neuer Handler in `plugins_commands.py`, drei Sub-Commands.
   - HELP_SECTION_PLUGINS + PLUGIN-Manifest, Priority 80, Kategorie
     `system` oder `diagnose`.
   - Tests: `test_plugins_commands.py` analog zu anderen Handlern.
   - Builtin-Count steigt von 23 auf 24. `EXPECTED_PLUGIN_NAMES` in
     `test_plugin_registry.py` mitziehen.

4. **System-Prompt-Erweiterung** (~15 min)
   - `_build_plugin_inventory_block()` in `assistant.py`.
   - Test: Prompt enthält Plugin-Namen, ist kürzer als ein Limit
     (z. B. 80 Zeilen für den Block).
   - Phase-78-Vorbereitung: Dedupe-Check kann später diesen Block
     mitlesen.

## 6. Tests / Akzeptanzkriterien

- `pytest tests/test_plugin_registry.py` weiterhin grün, neue
  Source-Tests bestanden.
- `pytest tests/test_plugins_api.py` (neu): Auth, JSON-Format,
  Aggregations-Counts.
- `pytest tests/test_plugins_commands.py` (neu): drei Sub-Commands,
  Detail-Lookup, Konflikt-Filter.
- `pytest tests/test_assistant_prompt.py` (oder analog, je nach
  Stand): Plugin-Block im System-Prompt enthalten, Trim-Verhalten.
- Pattern-Konflikt-Detector aus 77.3 weiterhin grün — `plugins`-
  Patterns neu, Risiko gering.
- Smoketest:
  - Dashboard öffnen → Tab `Plugins`, 23 Builtin-Plugins sichtbar.
  - User-Plugin in `~/.elder-berry/plugins/` ablegen, Saleria neu
    starten, Tab refreshen → Plugin in der Liste mit `source=user_dir`.
  - Matrix `plugins` → Liste in Element.
  - Matrix `plugins detail weather` → Help-Section.

## 7. Risiken / aktive Hinweise

- **R1 – Registry-API-Bruch.** `load_plugins()` bleibt
  abwärtskompatibel (liefert weiterhin `list[CommandPlugin]`). Wenn
  ich versucht bin, alle Aufrufer auf `load_plugins_with_sources()`
  umzustellen — *nicht jetzt*. Das ist ein eigener Migrations-Schritt.

- **R2 – Plugin-Liste im System-Prompt wächst.** 23 Zeilen heute, mit
  User-Plugins potenziell mehr. Heuristisches Limit: 30 Zeilen, danach
  Truncate mit „… (N weitere)". Bei 100+ Plugins ist die Heuristik
  selbst das Problem.

- **R3 – `plugins` als Matrix-Command kollidiert mit User-Sprache.**
  Falls jemand „plugins" als Notiz/Mail-Suchbegriff tippt. Mitigation:
  exact-match auf `simple_commands`, kein Regex-Pattern, der breit
  fängt. Der Konflikt-Detektor aus 77.3 fängt das beim Schreiben.

- **R4 – Source-Tracking lügt nicht, aber kann veralten.** Wenn ein
  User-Plugin nach dem Start in `~/.elder-berry/plugins/` gelegt wird,
  wird es erst beim nächsten Saleria-Start sichtbar. Bewusste
  Designentscheidung — Hot-Reload ist Phase 79.

- **R5 – Dashboard-Auth.** `/api/plugins` MUSS hinter
  `dashboard_auth_middleware`. Plugin-Liste leakt, welche Capabilities
  konfiguriert sind (`active=true` zeigt z. B. dass `email_client`
  läuft). Klein, aber Information-Disclosure.

- **R6 – Phase 78 wird nicht automatisch korrekt.** Der hier
  implementierte System-Prompt-Block ist *Voraussetzung*, nicht
  *Lösung*. Phase 78 muss den Block beim Dedupe-Check tatsächlich
  konsultieren — das ist Phase-78-Aufgabe, nicht 77.5.

## 8. Out of Scope

- Plugin-Toggle (aktivieren/deaktivieren) im Dashboard. Setting-Storage
  + Reload-Strategie + Conflict-Replanung wären eigene Phase.
- Pattern-Tester im Frontend („gib einen Text ein, sieh welches
  Plugin matched"). Wäre nett, kein Akzeptanz-Driver.
- Plugin-Doku-Generator (alle Help-Sections als Markdown-Datei
  exportieren). Folgephase, wenn Public-Docs-Need entsteht.
- Quellen-Erweiterung um Hot-Loaded-Plugins. Phase 79.

## 9. Folge-Phasen

- **Phase 78 (Self-Suggestion)** kann starten, sobald 77.5 gemerged ist.
  Der Dedupe-Check in 78 §3.6 muss explizit auf die hier eingeführte
  Plugin-Inventar-Liste im System-Prompt referenzieren — Phase-78-
  Konzept-Update als erstes Etappen-Item.
- **Phase 79 (Hot-Reload)** würde `LoadedPlugin.source_path` als
  Watch-Target nutzen.
- **Phase 80 (Plugin-Toggle)** baut auf der Inspector-UI auf — UI ist
  da, nur die Toggle-Logik fehlt.
