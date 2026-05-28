"""Phase 77: Tests fuer Plugin-Registry und alle Plugin-Manifeste.

Prueft:
- ``load_plugins()`` findet alle 23 Builtin-Plugins
- Sortierung nach Priority ist stabil
- Factory-Verhalten: Conditional-Plugins (note/contact/todo/route) liefern
  None ohne Service, Graceful-Degradation-Plugins (weather/git) liefern
  immer Handler
- Manifest-Integritaet (Name eindeutig, Help-Section nicht leer, Kategorie
  in CATEGORY_LABELS bekannt)
- RemoteCommandHandler-Konstruktor: Plugin-Pfad und Legacy-Kwargs.

Test ist NICHT strict-mypy-geprueft (Phase 76d Aufgabe).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import HandlerContext
from elder_berry.comms.commands.help_sections import CATEGORY_LABELS
from elder_berry.comms.commands.registry import (
    LoadedPlugin,
    PluginSource,
    load_plugins,
    load_plugins_with_sources,
)


# Etappe 2: alle Builtin-Plugins muessen geladen werden.
# Phase 77.5: PluginsCommandHandler dazu -> 24 Plugins.
# Phase 92: MultiStopRouteCommandHandler -> 25 Plugins.
EXPECTED_PLUGIN_NAMES = {
    "system",
    "weather",
    "mail",
    "calendar",
    "file",
    "cloud",
    "pdf",
    "filing",
    "process",
    "git",
    "docker",
    "wol",
    "update",
    "selfcheck",
    "turntable",
    "harmony",
    "camera",
    "log",
    "note",
    "contact",
    "todo",
    "route",
    "multi_stop_route",
    "plugins",
    "advanced",
}


# --- Discovery & Sortierung ----------------------------------------------


def test_load_plugins_finds_all_handlers() -> None:
    """Phase 77 Etappe 2: alle 23 *_commands.py haben Plugin-Manifest.

    Wenn ein Plugin fehlt: PLUGIN-Konstante in der jeweiligen Datei
    pruefen oder Tippfehler im Manifest-Append.
    """
    plugins = load_plugins()
    names = {p.name for p in plugins}
    missing = EXPECTED_PLUGIN_NAMES - names
    extra = names - EXPECTED_PLUGIN_NAMES
    assert not missing, f"Fehlende Plugins: {sorted(missing)}"
    assert not extra, f"Unerwartete Plugins: {sorted(extra)}"


def test_load_plugins_returns_sorted_by_priority() -> None:
    plugins = load_plugins()
    priorities = [p.priority for p in plugins]
    assert priorities == sorted(priorities), (
        f"Plugins nicht nach priority sortiert: {priorities}"
    )


def test_pilot_plugin_priorities_match_concept() -> None:
    """Konzept §3.4: weather=15 (vor calendar), git/note normale Prio."""
    by_name = {p.name: p for p in load_plugins()}
    assert by_name["weather"].priority == 15
    assert by_name["git"].priority == 50
    assert by_name["note"].priority == 70


def test_pattern_critical_priority_constraints() -> None:
    """Kritische Pattern-Reihenfolge-Constraints aus den WICHTIG-Kommentaren
    der alten remote_commands.py Handler-Liste:
    - weather VOR calendar (REMINDER_DELETE vs TERMIN_DELETE)
    - mail VOR calendar (MAIL_DELETE vs TERMIN_DELETE)
    - turntable VOR camera ('schau nach' Pattern-Konflikt)
    - advanced als Letztes (Catch-All / LLM-Fallback)
    """
    by_name = {p.name: p for p in load_plugins()}
    assert by_name["weather"].priority < by_name["calendar"].priority
    assert by_name["mail"].priority < by_name["calendar"].priority
    assert by_name["turntable"].priority < by_name["camera"].priority
    advanced_prio = by_name["advanced"].priority
    for name, plugin in by_name.items():
        if name == "advanced":
            continue
        assert plugin.priority < advanced_prio, (
            f"Plugin '{name}' (prio={plugin.priority}) nach advanced "
            f"(prio={advanced_prio}) -- advanced muss Catch-All sein"
        )


# --- Manifest-Integritaet ------------------------------------------------


def test_all_plugins_have_known_category() -> None:
    for plugin in load_plugins():
        assert plugin.category in CATEGORY_LABELS, (
            f"Plugin '{plugin.name}' hat unbekannte Kategorie "
            f"'{plugin.category}'. Eintrag in CATEGORY_LABELS fehlt."
        )


def test_all_plugins_have_non_empty_help_section() -> None:
    for plugin in load_plugins():
        assert plugin.help_section.strip(), (
            f"Plugin '{plugin.name}' hat leere help_section"
        )


def test_plugin_names_are_unique() -> None:
    plugins = load_plugins()
    names = [p.name for p in plugins]
    assert len(names) == len(set(names)), f"Duplikate in Plugin-Namen: {names}"


# --- Factory-Verhalten ---------------------------------------------------


def test_weather_factory_always_returns_handler() -> None:
    """Anders als note: weather macht graceful degradation (parse_command
    erkennt 'wetter' auch ohne Client; execute liefert dann
    'nicht konfiguriert'). Heisst: Factory liefert IMMER einen Handler,
    auch wenn ctx.weather=None.
    """
    by_name = {p.name: p for p in load_plugins()}
    weather_plugin = by_name["weather"]
    handler_no_client = weather_plugin.factory(HandlerContext())
    assert handler_no_client is not None
    handler_with_client = weather_plugin.factory(HandlerContext(weather=MagicMock()))
    assert handler_with_client is not None
    assert "wetter" in handler_with_client.simple_commands


def test_note_factory_returns_none_without_store() -> None:
    by_name = {p.name: p for p in load_plugins()}
    note_plugin = by_name["note"]
    ctx = HandlerContext()  # fact_store=None
    handler = note_plugin.factory(ctx)
    assert handler is None


def test_note_factory_returns_handler_with_store() -> None:
    by_name = {p.name: p for p in load_plugins()}
    note_plugin = by_name["note"]
    ctx = HandlerContext(fact_store=MagicMock(), default_user_id="@test:matrix")
    handler = note_plugin.factory(ctx)
    assert handler is not None


def test_git_factory_works_without_services() -> None:
    """Git-Handler hat keine harte Service-Abhaengigkeit."""
    by_name = {p.name: p for p in load_plugins()}
    git_plugin = by_name["git"]
    ctx = HandlerContext(project_root=Path("."))
    handler = git_plugin.factory(ctx)
    assert handler is not None


# --- CommandPlugin Frozen-Dataclass --------------------------------------


def test_command_plugin_is_frozen() -> None:
    """Manifeste duerfen zur Laufzeit nicht mutiert werden."""
    plugins = load_plugins()
    plugin = plugins[0]
    try:
        plugin.priority = 999  # type: ignore[misc]
    except Exception as exc:
        # FrozenInstanceError aus dataclasses
        assert (
            "frozen" in str(exc).lower() or "FrozenInstanceError" in type(exc).__name__
        )
    else:
        raise AssertionError("CommandPlugin sollte frozen sein, war es aber nicht")


# --- Konstruktor-Smoketest ----------------------------------------------


def test_remote_command_handler_constructs_with_legacy_kwargs() -> None:
    """Backwards-Compat: Bestehende Aufrufer mit Kwargs muessen weiter
    funktionieren. Etappe 2: Kwargs werden intern in HandlerContext
    konvertiert, alle Handler kommen aus der Plugin-Registry."""
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    handler = RemoteCommandHandler()  # alle Defaults None
    handler_types = {type(h).__name__ for h in handler._handlers}
    # Handler ohne harte Service-Bedingung -- immer da
    assert "WeatherCommandHandler" in handler_types
    assert "GitCommandHandler" in handler_types
    assert "SystemCommandHandler" in handler_types
    assert "AdvancedCommandHandler" in handler_types
    # Conditional-Handler ohne Service -- fehlen
    assert "NoteCommandHandler" not in handler_types
    assert "ContactCommandHandler" not in handler_types
    assert "TodoCommandHandler" not in handler_types
    assert "RouteCommandHandler" not in handler_types


def test_remote_command_handler_constructs_with_explicit_ctx() -> None:
    """Neuer Pfad: HandlerContext direkt uebergeben mit allen Conditionals."""
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    ctx = HandlerContext(
        weather=MagicMock(),
        fact_store=MagicMock(),
        contact_store=MagicMock(),
        task_client=MagicMock(),
        route_planner=MagicMock(),
    )
    handler = RemoteCommandHandler(ctx=ctx)
    handler_types = {type(h).__name__ for h in handler._handlers}
    # Phase 77.5: 24 Handler (PluginsCommandHandler dazu).
    assert "WeatherCommandHandler" in handler_types
    assert "NoteCommandHandler" in handler_types
    assert "GitCommandHandler" in handler_types
    assert "ContactCommandHandler" in handler_types
    assert "TodoCommandHandler" in handler_types
    assert "RouteCommandHandler" in handler_types
    assert "PluginsCommandHandler" in handler_types
    assert len(handler._handlers) == 24


def test_multi_stop_handler_constructs_without_anthropic_when_services_exist() -> None:
    """Phase 92 live-fix: Multi-Stop darf nicht an Sonnet geblockt sein.

    Wenn Google-Route-Services + ContactStore vorhanden sind, muss das
    Plugin auch ohne ``ctx.anthropic_client`` aktiv werden; der Parser
    hat einen lokalen Heuristik-Fallback.
    """
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.tools.route_session_store import RouteSessionStore

    ctx = HandlerContext(
        contact_store=MagicMock(),
        multi_stop_route_planner=MagicMock(),
        route_session_store=RouteSessionStore(),
    )
    handler = RemoteCommandHandler(ctx=ctx)
    handler_types = {type(h).__name__ for h in handler._handlers}
    assert "MultiStopRouteCommandHandler" in handler_types


def test_handler_order_matches_pre_plugin_layout() -> None:
    """Sicherheitsnetz: Reihenfolge muss exakt der alten Pre-Plugin-Liste
    entsprechen (siehe Phase 77 Etappe 1 Smoketest). Wenn das hier
    bricht, hat sich eine Plugin-Priority verschoben oder die Conditional-
    Logik ist umgesattelt -- sehr genau pruefen, ob das gewollt ist.
    """
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    ctx = HandlerContext(
        weather=MagicMock(),
        fact_store=MagicMock(),
        contact_store=MagicMock(),
        task_client=MagicMock(),
        route_planner=MagicMock(),
    )
    handler = RemoteCommandHandler(ctx=ctx)
    expected = [
        "SystemCommandHandler",
        "WeatherCommandHandler",
        "MailCommandHandler",
        "CalendarCommandHandler",
        "FileCommandHandler",
        "CloudCommandHandler",
        "PDFCommandHandler",
        "FilingCommandHandler",
        "ProcessCommandHandler",
        "GitCommandHandler",
        "DockerCommandHandler",
        "WolCommandHandler",
        "UpdateCommandHandler",
        "SelfcheckCommandHandler",
        "TurntableCommandHandler",
        "HarmonyCommandHandler",
        "CameraCommandHandler",
        "LogCommandHandler",
        "NoteCommandHandler",
        "ContactCommandHandler",
        "TodoCommandHandler",
        "RouteCommandHandler",
        # Phase 77.5: PluginsCommandHandler bei priority=80, nach
        # RouteCommandHandler (76) und vor AdvancedCommandHandler (99).
        "PluginsCommandHandler",
        "AdvancedCommandHandler",
    ]
    actual = [type(h).__name__ for h in handler._handlers]
    assert actual == expected


# --- Phase 77.5: Source-Tracking ----------------------------------------


def test_load_plugins_with_sources_returns_loaded_plugins() -> None:
    """load_plugins_with_sources() liefert LoadedPlugin-Wrapper."""
    loaded = load_plugins_with_sources()
    assert loaded, "Keine Plugins geladen"
    assert all(isinstance(entry, LoadedPlugin) for entry in loaded)


def test_load_plugins_with_sources_all_builtin_in_test_sandbox() -> None:
    """In der Test-Sandbox (conftest stubbed user_dir + entry_points)
    muessen alle Plugins source=BUILTIN haben."""
    loaded = load_plugins_with_sources()
    sources = {entry.source for entry in loaded}
    assert sources == {PluginSource.BUILTIN}, (
        f"Erwartet nur BUILTIN, gefunden: {sources}"
    )


def test_load_plugins_with_sources_source_path_for_builtin() -> None:
    """Builtin-Plugins haben den Modul-Dateinamen als source_path."""
    loaded = load_plugins_with_sources()
    by_name = {entry.plugin.name: entry for entry in loaded}
    weather = by_name["weather"]
    assert weather.source_path == "weather_commands.py"


def test_load_plugins_with_sources_priority_sort() -> None:
    """Sortierung nach plugin.priority bleibt stabil (analog
    test_load_plugins_returns_sorted_by_priority)."""
    loaded = load_plugins_with_sources()
    priorities = [entry.plugin.priority for entry in loaded]
    assert priorities == sorted(priorities)


def test_load_plugins_returns_unwrapped_command_plugins() -> None:
    """Backwards-Compat: load_plugins() liefert weiterhin CommandPlugin
    (nicht LoadedPlugin) -- alle bestehenden Aufrufer dürfen sich auf
    die alte Signatur verlassen."""
    plugins = load_plugins()
    # Smoke: kein Plugin ist ein LoadedPlugin-Wrapper
    assert not any(isinstance(p, LoadedPlugin) for p in plugins)
    # alle haben eine .name-Property (CommandPlugin-Manifest)
    assert all(hasattr(p, "name") and hasattr(p, "priority") for p in plugins)


def test_loaded_plugin_is_frozen() -> None:
    """LoadedPlugin ist frozen -- Loader-Outputs duerfen nicht mutiert
    werden."""
    loaded = load_plugins_with_sources()
    entry = loaded[0]
    try:
        entry.source = PluginSource.USER_DIR  # type: ignore[misc]
    except Exception as exc:
        assert (
            "frozen" in str(exc).lower() or "FrozenInstanceError" in type(exc).__name__
        )
    else:
        raise AssertionError("LoadedPlugin sollte frozen sein, war es aber nicht")
