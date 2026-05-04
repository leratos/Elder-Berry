"""Phase 77 Etappe 1: Tests fuer Plugin-Registry und Pilot-Plugins.

Prueft:
- ``load_plugins()`` findet die drei Pilot-Manifeste (weather, note, git)
- Sortierung nach Priority ist stabil
- Factory-Verhalten: weather/note brauchen Service, git nicht
- Manifest-Integritaet (Name eindeutig, Help-Section nicht leer, Kategorie
  in CATEGORY_LABELS bekannt)

Test ist NICHT strict-mypy-geprueft (Phase 76d Aufgabe).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from elder_berry.comms.commands.base import HandlerContext
from elder_berry.comms.commands.help_sections import CATEGORY_LABELS
from elder_berry.comms.commands.registry import load_plugins


# --- Discovery & Sortierung ----------------------------------------------


def test_load_plugins_finds_three_pilots() -> None:
    """Etappe 1 hat 3 Pilot-Plugins. Wenn weniger gefunden werden, ist
    eine PLUGIN-Konstante kaputt; wenn mehr, ist Etappe 2 schon
    voraus geeilt -- dann bitte den Test anpassen."""
    plugins = load_plugins()
    names = {p.name for p in plugins}
    assert {"weather", "note", "git"} <= names, (
        f"Pilot-Plugins unvollstaendig: {sorted(names)}"
    )


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
    ctx = HandlerContext()  # note_store=None
    handler = note_plugin.factory(ctx)
    assert handler is None


def test_note_factory_returns_handler_with_store() -> None:
    by_name = {p.name: p for p in load_plugins()}
    note_plugin = by_name["note"]
    ctx = HandlerContext(note_store=MagicMock(), default_user_id="@test:matrix")
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
    funktionieren. Plugin-Pfad wird intern aktiviert (weather/git/note
    aus Plugin-Registry, Rest legacy)."""
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    handler = RemoteCommandHandler()  # alle Defaults None
    handler_types = {type(h).__name__ for h in handler._handlers}
    # weather + git haben keine harte Service-Bedingung, sind immer da
    assert "WeatherCommandHandler" in handler_types
    assert "GitCommandHandler" in handler_types
    # note braucht NoteStore, ohne fehlt der Handler
    assert "NoteCommandHandler" not in handler_types


def test_remote_command_handler_constructs_with_explicit_ctx() -> None:
    """Neuer Pfad: HandlerContext direkt uebergeben."""
    from elder_berry.comms.remote_commands import RemoteCommandHandler

    ctx = HandlerContext(weather=MagicMock(), note_store=MagicMock())
    handler = RemoteCommandHandler(ctx=ctx)
    handler_types = {type(h).__name__ for h in handler._handlers}
    assert "WeatherCommandHandler" in handler_types
    assert "NoteCommandHandler" in handler_types
    assert "GitCommandHandler" in handler_types
