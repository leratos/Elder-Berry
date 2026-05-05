"""Tests fuer PluginsCommandHandler (Phase 77.5).

Prueft:
- Drei Sub-Commands: plugins / plugins konflikte / plugins detail <name>.
- Detail-Lookup: bekanntes Plugin -> Manifest, unbekanntes -> Fehlermeldung.
- Konflikt-Filter zeigt nur Plugins mit conflicts != ().
- Plugin-Manifest: priority=80, category="diagnose", Factory liefert
  immer einen Handler.

Test ist NICHT strict-mypy-geprueft (analog test_plugin_registry.py).
"""

from __future__ import annotations

from elder_berry.comms.commands.base import HandlerContext
from elder_berry.comms.commands.plugins_commands import (
    PLUGIN as PLUGINS_PLUGIN,
    PluginsCommandHandler,
)


# --- Manifest -----------------------------------------------------------


def test_plugin_manifest_priority_and_category() -> None:
    assert PLUGINS_PLUGIN.name == "plugins"
    assert PLUGINS_PLUGIN.priority == 80
    assert PLUGINS_PLUGIN.category == "diagnose"


def test_plugin_factory_always_returns_handler() -> None:
    handler = PLUGINS_PLUGIN.factory(HandlerContext())
    assert isinstance(handler, PluginsCommandHandler)


# --- plugins (List) -----------------------------------------------------


def test_plugins_list_contains_self_and_summary_header() -> None:
    handler = PluginsCommandHandler()
    result = handler.execute("plugins", "plugins")
    assert result.success
    assert result.text is not None
    text = result.text
    # Header mit Anzahl
    assert "Geladene Plugins" in text
    # Plugin-Inspector listet sich selbst
    assert "plugins (builtin" in text
    # Andere Builtin-Plugins drin
    assert "weather" in text
    assert "advanced" in text


def test_plugins_list_format_per_line() -> None:
    handler = PluginsCommandHandler()
    result = handler.execute("plugins", "plugins")
    assert result.text is not None
    body_lines = [line for line in result.text.splitlines() if line.startswith("- ")]
    # Jede Zeile: "- <name> (<source>, prio <n>, <category>)"
    for line in body_lines:
        assert "(builtin" in line
        assert "prio " in line


# --- plugins konflikte --------------------------------------------------


def test_plugins_conflicts_only_returns_with_conflicts() -> None:
    handler = PluginsCommandHandler()
    result = handler.execute("plugins konflikte", "plugins konflikte")
    assert result.success
    assert result.text is not None
    # Entweder Header + Liste, oder freundliche Leer-Antwort.
    if "Keine Plugins" not in result.text:
        # Liste -- jedes Listenelement enthaelt -> conflicts:
        body_lines = [
            line for line in result.text.splitlines() if line.startswith("- ")
        ]
        assert body_lines, "Konflikt-Plugins erwartet, aber Liste war leer."
        for line in body_lines:
            assert "conflicts:" in line


# --- plugins detail <name> ----------------------------------------------


def test_plugins_detail_known_plugin_shows_manifest() -> None:
    handler = PluginsCommandHandler()
    result = handler.execute("plugins_detail", "plugins detail weather")
    assert result.success
    assert result.text is not None
    text = result.text
    assert "Plugin 'weather'" in text
    assert "Source: builtin" in text
    assert "Priority: 15" in text
    assert "Category: wetter" in text
    # help_section sollte mit drin sein (Wetter-Sektion enthaelt "Wetter:")
    assert "Wetter:" in text


def test_plugins_detail_unknown_plugin_returns_friendly_error() -> None:
    handler = PluginsCommandHandler()
    result = handler.execute("plugins_detail", "plugins detail does_not_exist")
    assert result.success is False
    assert result.text is not None
    assert "nicht gefunden" in result.text
    assert "Verfuegbar:" in result.text


def test_plugins_detail_invalid_format_returns_format_hint() -> None:
    """Wenn der raw_text das Pattern nicht matched (z.B. weil execute
    direkt mit unpassendem Text aufgerufen wird), soll der Handler
    nicht crashen, sondern den Format-Hint zurueckgeben."""
    handler = PluginsCommandHandler()
    result = handler.execute("plugins_detail", "plugins detail")
    assert result.success is False
    assert result.text is not None
    assert "plugins detail <name>" in result.text


def test_plugins_detail_self_lookup() -> None:
    """plugins detail plugins -> sich selbst."""
    handler = PluginsCommandHandler()
    result = handler.execute("plugins_detail", "plugins detail plugins")
    assert result.success
    assert result.text is not None
    assert "Plugin 'plugins'" in result.text
    assert "Priority: 80" in result.text
    assert "Category: diagnose" in result.text


# --- Unbekannter Sub-Command --------------------------------------------


def test_plugins_handler_unknown_command_returns_failure() -> None:
    handler = PluginsCommandHandler()
    result = handler.execute("plugins_bogus", "plugins bogus")
    assert result.success is False
    assert result.text is not None
    assert "Unbekannter" in result.text
