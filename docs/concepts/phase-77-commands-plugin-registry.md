# Phase 77 – Commands Plugin-Registry 🧩

**Status:** Konzept (2026-04-29)
**Branch:** `feature/phase-77-commands-plugin-registry`
**Aufwand:** ~2–3 Sessions
**Voraussetzung:** Phase 75 (Hygiene), Phase 76 Tier 1 (mypy-Setup)
**Roadmap-Referenz:** Vorbereitung für Phase 78 (Self-Suggestion)

## 1. Ausgangslage

`src/elder_berry/comms/remote_commands.py` ist heute der zentrale
Orchestrator. Im `__init__` (ab Zeile 374) wird die Handler-Liste
manuell aufgebaut:

```python
self._handlers: list[CommandHandler] = [
    self._system, self._weather, self._mail, self._calendar,
    self._file, self._cloud, self._pdf, self._filing,
    self._process, self._git, self._docker, self._wol,
    self._update, self._selfcheck, self._turntable,
    self._harmony, self._camera, self._log,
]
if self._notes is not None: self._handlers.append(self._notes)
if self._contacts is not None: self._handlers.append(self._contacts)
...
```

Drei Probleme machen das Hinzufügen neuer Handler hakelig:

- **P1 – Reihenfolge ist Prioritätskontrolle, aber implizit.** Kommentare
  wie `# WICHTIG: _weather VOR _calendar weil REMINDER_DELETE vor TERMIN_DELETE
  matcht` zeigen: die Listen-Position codiert Pattern-Konflikte. Das ist
  Stammeswissen, kein Code-First-Citizen.
- **P2 – Konstruktor-Bloat.** `RemoteCommandHandler.__init__` nimmt 25+ Kwargs
  entgegen (jeder Service: `secret_store`, `weather_client`, `email_client`,
  `note_store`, ...). Jeder neue Handler erweitert die Signatur weiter.
- **P3 – Plugin-Hinzufügung erfordert ≥4 Touch-Points:**
  - Neue Datei in `comms/commands/<name>_commands.py`
  - Import + Konstruktion in `remote_commands.py`
  - Eintrag in `_handlers`-Liste an der richtigen Position
  - Eintrag in `help_sections.HELP_SECTIONS` + `CATEGORY_LABELS`

Das Ziel dieser Phase: **eine neue Capability = eine neue Datei**.

## 2. Ziel

1. Plugin-Manifest-Format (`CommandPlugin`-Dataclass) etabliert in
   `comms/commands/base.py`.
2. `HandlerContext`-Service-Container ersetzt die 25+ Kwargs.
3. Plugin-Discovery aus drei Quellen: builtin (Repo), user-directory
   (`~/.elder-berry/plugins/*.py`), entry-points (`pip install`-Plugins).
4. `RemoteCommandHandler` wird zum reinen Orchestrator — keine direkten
   Handler-Imports mehr.
5. Pattern-Konflikt-Detector als Test in CI.
6. Backwards-Compat-Shim für 1 Release.

**Nicht-Ziele dieser Phase:**
- Self-Suggestion-Mechanismus (Phase 78).
- Plugin-Hot-Reload (würde später als Phase 79 kommen).
- Plugin-Marketplace / Distribution (Phase 80+, sobald public).
- Refactoring der bestehenden Handler-Klassen selbst — die bleiben
  unverändert, bekommen nur ein Plugin-Manifest.

## 3. Architektur

### 3.1 Manifest-Datenklasse

In `src/elder_berry/comms/commands/base.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass, field

@dataclass(frozen=True)
class CommandPlugin:
    """Selbstbeschreibung eines Command-Handlers.

    Jedes Plugin-Modul exportiert genau ein PLUGIN-Objekt auf
    Modul-Ebene. Die Registry erkennt das automatisch.
    """

    name: str
    """Eindeutiger, snake_case Name. Wird als Key für Lookup,
    Help-Sektion und Logging genutzt."""

    priority: int
    """Niedrigere Zahl = früher geprüft. Empfohlene Werte:
    0–9     – kritische Pre-Filter (selten)
    10–49   – domänenspezifische Commands mit Pattern-Konflikten
    50–89   – normale Commands
    90–99   – Catch-All (z.B. AdvancedCommands für LLM-Fallback)"""

    category: str
    """Hilfe-Kategorie (siehe help_sections.CATEGORY_LABELS).
    Neue Kategorien müssen dort registriert werden."""

    help_section: str
    """Help-Text dieser Domäne. Wird in build_full_help() aggregiert."""

    factory: Callable[["HandlerContext"], "CommandHandler | None"]
    """Konstruktor-Funktion. Liest aus HandlerContext, was sie
    braucht. Darf None zurückgeben, wenn benötigte Services fehlen
    (z.B. NoteStore=None → kein NoteHandler)."""

    requires: tuple[str, ...] = field(default_factory=tuple)
    """Plugin-Namen, deren Handler vor diesem laufen müssen.
    Liefert Konflikt-Constraint für die Sortierung."""

    conflicts: tuple[str, ...] = field(default_factory=tuple)
    """Plugin-Namen, mit denen Patterns kollidieren könnten.
    Triggert Pattern-Konflikt-Test in CI."""

    version: str = "1.0.0"
    """Plugin-Version. Macht später Migrations möglich."""
```

### 3.2 HandlerContext (Service-Container)

```python
@dataclass
class HandlerContext:
    """Service-Container für Plugin-Factories.

    Ersetzt die alte Kwargs-Liste. Jede Factory liest, was sie braucht;
    optionale Felder sind None, wenn der Service nicht konfiguriert ist.

    Pflicht-Felder (immer gesetzt):
    """
    project_root: Path
    secret_store: "SecretStore"

    # --- Tools (alle Optional, Plugin entscheidet selbst) ---
    weather_client: "WeatherClient | None" = None
    reminder_store: "ReminderStore | None" = None
    briefing_scheduler: "BriefingScheduler | None" = None
    email_client: "IMAPEmailClient | None" = None
    google_calendar: "GoogleCalendarClient | None" = None
    note_store: "NoteStore | None" = None
    contact_store: "ContactStore | None" = None
    todo_client: "CalDAVTaskClient | None" = None
    pending_confirmation: "PendingConfirmationStore | None" = None
    nextcloud_files: "NextcloudFilesClient | None" = None
    document_classifier: "DocumentClassifier | None" = None
    stirling_pdf: "StirlingPDFClient | None" = None
    route_planner: "RoutePlanner | None" = None
    web_fetcher: "WebFetcher | None" = None
    brave_search: "BraveSearchClient | None" = None
    document_reader: "DocumentReader | None" = None
    gym_data: "GymDataClient | None" = None
    carddav_sync: "CardDAVSyncClient | None" = None

    # --- System / Aktionen ---
    system_monitor: "SystemMonitor | None" = None
    action_controller: "ActionController | None" = None
    computer_use: "ComputerUseController | None" = None
    audio_router: "AudioRouter | None" = None
    avatar_renderer: "AvatarRenderer | None" = None
    robot_client: "RobotClient | None" = None
    tower_agent: "TowerAgent | None" = None
    anthropic_client: "AnthropicClient | None" = None
```

Die Liste ist die Konsolidierung aller bisherigen `RemoteCommandHandler`-
Kwargs an einer Stelle.

### 3.3 Discovery

Neue Datei `src/elder_berry/comms/commands/registry.py`:

```python
import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Iterator

from elder_berry.comms.commands.base import CommandPlugin

logger = logging.getLogger(__name__)

# --- Quellen ---

def _load_builtin() -> Iterator[CommandPlugin]:
    """Lädt alle PLUGIN-Objekte aus comms/commands/<name>_commands.py."""
    base_dir = Path(__file__).parent
    for path in sorted(base_dir.glob("*_commands.py")):
        module_name = f"elder_berry.comms.commands.{path.stem}"
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            logger.warning("Builtin-Plugin %s übersprungen: %s",
                           path.stem, exc)
            continue
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, CommandPlugin):
            yield plugin

def _load_user_directory() -> Iterator[CommandPlugin]:
    """Lädt Plugins aus ~/.elder-berry/plugins/*.py."""
    user_dir = Path.home() / ".elder-berry" / "plugins"
    if not user_dir.exists():
        return
    for path in sorted(user_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(
            f"elder_berry_user_plugin_{path.stem}", path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.warning("User-Plugin %s fehlgeschlagen: %s",
                           path.name, exc)
            continue
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, CommandPlugin):
            yield plugin

def _load_entry_points() -> Iterator[CommandPlugin]:
    """Lädt Plugins aus pip-installierten Paketen mit entry_point
    'elder_berry.commands'."""
    from importlib.metadata import entry_points
    for ep in entry_points(group="elder_berry.commands"):
        try:
            plugin = ep.load()
        except Exception as exc:
            logger.warning("Entry-Point %s fehlgeschlagen: %s",
                           ep.name, exc)
            continue
        if isinstance(plugin, CommandPlugin):
            yield plugin

def load_plugins() -> list[CommandPlugin]:
    """Lädt alle Plugins, sortiert nach Priorität."""
    plugins = list(_load_builtin())
    plugins.extend(_load_user_directory())
    plugins.extend(_load_entry_points())
    # Eindeutigkeit per Name (User > Entry-Point > Builtin)
    by_name: dict[str, CommandPlugin] = {}
    for p in plugins:
        if p.name in by_name:
            logger.info("Plugin %s wird überschrieben (von %s)",
                        p.name, p.version)
        by_name[p.name] = p
    return sorted(by_name.values(), key=lambda p: p.priority)
```

### 3.4 Migrations-Beispiel: WeatherCommandHandler

`src/elder_berry/comms/commands/weather_commands.py` bekommt am Ende:

```python
def _factory(ctx: HandlerContext) -> CommandHandler | None:
    if ctx.weather_client is None:
        return None
    return WeatherCommandHandler(
        weather=ctx.weather_client,
        reminders=ctx.reminder_store,
        briefing=ctx.briefing_scheduler,
        gym=ctx.gym_data,
    )

PLUGIN = CommandPlugin(
    name="weather",
    priority=15,  # vor calendar (20) wegen REMINDER_DELETE-Konflikt
    category="wetter",
    help_section=HELP_SECTION_WEATHER,  # bereits in der Datei
    factory=_factory,
    conflicts=("calendar",),  # explizit dokumentiert
)
```

### 3.5 Neuer Orchestrator

`RemoteCommandHandler.__init__` reduziert sich auf:

```python
def __init__(self, ctx: HandlerContext) -> None:
    self._ctx = ctx
    plugins = load_plugins()
    self._handlers: list[CommandHandler] = [
        h for p in plugins
        if (h := p.factory(ctx)) is not None
    ]
    self._simple_commands = {
        c for h in self._handlers for c in h.simple_commands
    }
    self._command_handler_map: dict[str, CommandHandler] = {
        c: h for h in self._handlers for c in h.simple_commands
    }
    self.keyword_map = _build_keyword_map(self._handlers)
```

## 4. Help-Sections-Migration

`help_sections.py` bleibt für `CATEGORY_LABELS` zuständig, aber
`HELP_SECTIONS` wird zur Laufzeit aus den Plugins aggregiert:

```python
def build_help_sections(plugins: list[CommandPlugin]) -> dict[str, str]:
    """Aggregiert help_section pro Kategorie."""
    by_cat: dict[str, list[str]] = {}
    for p in plugins:
        by_cat.setdefault(p.category, []).append(p.help_section)
    return {cat: "\n\n".join(sections) for cat, sections in by_cat.items()}
```

`CATEGORY_LABELS` bleibt statisch (Layout-Reihenfolge der Hilfe-Kategorien).
Eine neue Kategorie hinzufügen heißt: Eintrag in `CATEGORY_LABELS` + Plugins
mit dieser `category` referenzieren.

## 5. Plugin-Template

Datei `docs/templates/plugin_template.py.template` (neu):

```python
"""<NameDeinesHandlers>CommandHandler – <Kurzbeschreibung>.

Plugin-Template für Phase 77 Plugin-Registry.
Kopieren nach src/elder_berry/comms/commands/<name>_commands.py
oder ~/.elder-berry/plugins/<name>.py
"""
from __future__ import annotations

import re
from elder_berry.comms.commands.base import (
    CommandHandler, CommandResult, CommandPlugin, HandlerContext,
)

# --- Patterns ---
EXAMPLE_PATTERN = re.compile(r"^example\s+(.+)$", re.IGNORECASE)


class ExampleCommandHandler(CommandHandler):

    @property
    def simple_commands(self) -> set[str]:
        return {"example"}

    @property
    def patterns(self):
        return [(EXAMPLE_PATTERN, "example_with_arg", False, False)]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {"example": ["beispiel", "muster"]}

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "example: Beispiel-Befehl ohne Argument",
            "example <text>: Beispiel-Befehl mit Argument",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "example":
            return CommandResult(command=command, success=True,
                                 text="Beispiel ohne Argument.")
        if command == "example_with_arg":
            match = EXAMPLE_PATTERN.match(raw_text.strip())
            arg = match.group(1) if match else ""
            return CommandResult(command=command, success=True,
                                 text=f"Beispiel mit: {arg}")
        return CommandResult(command=command, success=False,
                             text="Unbekannter Sub-Command.")


# --- Plugin-Manifest ---

HELP_SECTION_EXAMPLE = """Example:
  example – Beispiel-Befehl ohne Argument
  example <text> – Beispiel-Befehl mit Argument"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    # Bei Service-Abhängigkeiten hier prüfen und None zurückgeben
    return ExampleCommandHandler()


PLUGIN = CommandPlugin(
    name="example",
    priority=50,
    category="basis",  # muss in CATEGORY_LABELS existieren
    help_section=HELP_SECTION_EXAMPLE,
    factory=_factory,
)
```

Das Template erscheint zusätzlich als generierter Output via
`scripts/generate_plugin.py` (neu in dieser Phase) — interaktiver Wizard
für „Plugin-Name eingeben → Datei wird erzeugt".

## 6. Pattern-Konflikt-Detector (CI-Test)

`tests/test_plugin_pattern_conflicts.py` (neu):

```python
"""Pre-Flight-Check: prüft alle Plugin-Patterns gegeneinander.

Wenn zwei Plugins dieselbe Beispielanfrage matchen würden, liegt ein
Konflikt vor — entweder priority anpassen oder Pattern verschärfen.
"""
import pytest
from elder_berry.comms.commands.registry import load_plugins

# Beispieltexte aus echtem Matrix-Verkehr (anonymisiert)
SAMPLE_INPUTS = [
    "lösche erinnerung 3",
    "lösche termin morgen",
    "lösche die mail #5",
    "schau nach was im briefing steht",
    "schau in die mail",
    "wetter morgen",
    "termin morgen 14:00",
    # ... wachsende Liste aus produktiven Matrix-Logs
]


def test_no_pattern_collision():
    plugins = load_plugins()
    collisions = []
    for text in SAMPLE_INPUTS:
        matchers = []
        for plugin in plugins:
            handler = plugin.factory(...)  # Mock-Context
            if handler is None:
                continue
            for pat, cmd, _, use_search in handler.patterns:
                if (pat.search if use_search else pat.match)(text):
                    matchers.append((plugin.name, cmd, plugin.priority))
        if len(matchers) > 1:
            # Akzeptiert nur, wenn der erste Match (niedrigste priority)
            # auch in plugin.conflicts steht
            primary, *secondary = matchers
            for sname, _, _ in secondary:
                if sname not in plugin.conflicts:
                    collisions.append(
                        f"'{text}': {primary} vs. {(sname, ...)} "
                        f"— nicht in conflicts deklariert"
                    )
    assert not collisions, "\n".join(collisions)
```

Damit sind Pattern-Konflikte im PR-Review sichtbar, bevor sie in
Production landen.

## 7. Etappen / Vorgehen

### 7.1 Etappe 1 — Manifest + 3 Pilot-Handler (1 Session)

- `CommandPlugin` und `HandlerContext` in `base.py` ergänzen.
- `registry.py` mit `_load_builtin` (User-Dir + Entry-Points zunächst leer).
- Drei Handler exemplarisch migrieren: `weather`, `note`, `git`
  (verschiedene Priorität, optionale Service-Abhängigkeit, keine).
- Neuer `RemoteCommandHandler.__init__(ctx)` parallel zum alten
  Konstruktor (Branch-Logik intern: wenn Plugins gefunden, neuer Pfad,
  sonst Legacy).
- **Akzeptanzkriterium:** drei Handler laufen über die Registry, alle
  Tests grün.

### 7.2 Etappe 2 — Restliche 22 Handler migrieren (1 Session)

- Pro Handler: `_factory` + `PLUGIN`-Manifest hinzufügen, Help-Section
  als Konstante extrahieren.
- Wenn kein neuer Bug: Legacy-Konstruktor entfernen, Bridge auf neuen
  Konstruktor umstellen.
- **Akzeptanzkriterium:** alle 25 Handler über Registry, alle Tests grün.

### 7.3 Etappe 3 — User-Dir + Entry-Points + Conflict-Detector (1 Session)

- `_load_user_directory` und `_load_entry_points` aktivieren.
- `tests/test_plugin_pattern_conflicts.py` mit ~20 Sample-Inputs.
- `scripts/generate_plugin.py` (Wizard).
- Doku-Update: `docs/USAGE.md` Abschnitt „Eigene Plugins schreiben".
- **Akzeptanzkriterium:** ein Beispiel-User-Plugin in
  `~/.elder-berry/plugins/` wird geladen und ist in `hilfe`-Output
  sichtbar.

## 8. Backwards-Compat

Bestehende Aufrufer (`MatrixBridge`, Tests, Setup-Wizard) konstruieren
`RemoteCommandHandler` mit den alten Kwargs. Übergangsweise:

```python
def __init__(
    self,
    *,
    ctx: HandlerContext | None = None,
    # --- LEGACY: alte Kwargs ---
    secret_store: "SecretStore | None" = None,
    project_root: Path | None = None,
    weather_client: "WeatherClient | None" = None,
    # ... alle alten Kwargs ...
) -> None:
    if ctx is not None and any(legacy_kw is not None for legacy_kw in [...]):
        raise TypeError("Either ctx= or legacy kwargs, not both.")
    if ctx is None:
        warnings.warn(
            "RemoteCommandHandler-Kwargs sind deprecated. Nutze HandlerContext.",
            DeprecationWarning, stacklevel=2,
        )
        ctx = self._build_legacy_context(secret_store=..., ...)
    # ... wie oben
```

Migration in einem Release. Alte Kwargs nach 6 Monaten entfernen.

## 9. Risiken / aktive Hinweise

- **R1 – Pattern-Konflikte verschwinden nicht magisch.** Der
  Conflict-Detector ist ein Pre-Flight-Check, kein Auto-Fix. Bei einem
  echten Konflikt muss entweder `priority` angepasst oder Pattern
  verschärft werden.
- **R2 – Unbeabsichtigtes Plugin-Override.** Ein User-Plugin mit
  `name="weather"` würde das Builtin überschreiben. Das ist Feature
  (Plugin-Customization), aber muss klar dokumentiert sein. Evtl.
  Warnung im Log: `Plugin weather wird von User-Dir überschrieben`.
- **R3 – Entry-Points sind Vertrauensfrage.** Wer ein
  `pip install elder-berry-plugin-irgendwas` macht, lädt Code.
  Mitigation: Entry-Points in dieser Phase aktivieren, aber später
  per Setting deaktivierbar machen (`registry.allow_entry_points = False`).
- **R4 – `HandlerContext` wird bei jedem neuen Service breiter.** Pro
  Service ein neues Feld. Kein direkter Schmerzpunkt, aber bei 50+
  Services wird das Dataclass unübersichtlich. Akzeptiert für jetzt;
  Service-Locator-Pattern (`ctx.get("weather_client")`) als Folgephase
  möglich.
- **R5 – Backwards-Compat-Shim verlängert die Migration.** Alte Bridge-
  Aufrufer bleiben 6 Monate auf Kwargs. Wer den Shim entfernt, muss
  alle Aufrufer fixen. Mitigation: `DeprecationWarning` ab Tag 1
  laut, im Test-Run sichtbar.
- **R6 – User-Plugins können das System brechen.** Ein fehlerhaftes
  User-Plugin könnte beim Laden eine Exception werfen, die den Bot
  killt. Mitigation: `_load_user_directory` fängt alle Exceptions
  pro Plugin und überspringt fehlerhafte (loggt Warnung).

## 10. Tests / Akzeptanzkriterien

- `pytest tests/` weiterhin grün (4916+ passed).
- `tests/test_plugin_registry.py` (neu) prüft:
  - alle Builtin-Plugins werden geladen
  - Prioritäten sind eindeutig
  - jedes Plugin hat einen Help-Section-Eintrag
  - User-Plugin aus tmp-Verzeichnis wird geladen
- `tests/test_plugin_pattern_conflicts.py` (neu) prüft 20+
  Sample-Inputs ohne Konflikte.
- `mypy src/elder_berry/comms/commands` — neue Dateien strict
  (Tier 1 von Phase 76 als Vorbild).
- Manueller Smoketest: ein User-Plugin in `~/.elder-berry/plugins/`
  ablegen, Saleria starten, `hilfe`-Befehl zeigt es als Sektion.

## 11. Out of Scope

- Plugin-Hot-Reload (Saleria läuft, neues Plugin reinwerfen ohne
  Neustart). Folgephase, wenn Bedarf da ist.
- Plugin-Marketplace (Discovery von Drittanbieter-Plugins über GitHub-
  Topic-Suche oder PyPI-Suche).
- Plugin-Sandboxing (RestrictedPython etc.). Plugins laufen mit vollen
  Rechten — bewusste Designentscheidung, weil sie Nutzer-Code sind.
- Versionskonflikte zwischen Plugin-API-Versionen. Aktuell ist
  `version = "1.0.0"` im Manifest informativ, Migrations kommen erst
  bei Bedarf.

## 12. Folge-Phasen

- **Phase 78 (Plugin-Self-Suggestion):** Saleria erkennt fehlende
  Capabilities und schlägt neue Plugins vor. Setzt das Manifest-Format
  dieser Phase voraus.
- **Phase 79 (offen) – Plugin-Hot-Reload:** Ändern eines User-Plugins
  ohne Saleria-Neustart anwenden.
- **Phase 80 (offen) – Plugin-Distribution:** GitHub-Template-Repo
  + PyPI-Topic + `gh search` für Discovery.
