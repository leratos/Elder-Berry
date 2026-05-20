"""Tests fuer den Plugin-Inventar-Block im System-Prompt (Phase 77.5).

Phase-78-Voraussetzung (Konzept §3.4): Saleria sieht beim Dedupe-Check
nicht nur die Vorschlags-Liste, sondern auch die heute geladenen
Builtin-Plugins. Hier wird verifiziert, dass dieser Block in beiden
System-Prompt-Pfaden (Character + Template-Fallback) erscheint und sein
Trim-Verhalten greift.

Test ist NICHT strict-mypy-geprueft (analog test_plugin_registry.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.comms.commands import registry
from elder_berry.core import assistant as assistant_module
from elder_berry.core.assistant import Assistant
from elder_berry.llm.base import LLMClient


def _make_assistant(tmp_path, character=None):
    return Assistant(
        llm=MagicMock(spec=LLMClient),
        actions_db=ActionsDB(db_path=tmp_path / "test_actions.db"),
        controller=MagicMock(spec=ActionController),
        tts=None,
        character=character,
    )


# --- Block enthaelt im Template-Pfad -----------------------------------


def test_inventory_block_in_template_path(tmp_path):
    """Assistant ohne CharacterEngine -> SYSTEM_PROMPT_TEMPLATE-Pfad."""
    a = _make_assistant(tmp_path)
    prompt = a._build_system_prompt()
    assert "[Bereits geladene Plugins" in prompt
    assert "kein Vorschlag wenn Match" in prompt
    # Mindestens 'weather' und 'advanced' (Builtins) in der Liste
    assert "- weather:" in prompt
    assert "- advanced:" in prompt


def test_inventory_block_in_character_path(tmp_path):
    """Assistant mit Saleria-Character -> Character.build_system_prompt-Pfad."""
    saleria = SaleriaEngine()
    a = _make_assistant(tmp_path, character=saleria)
    prompt = a._build_system_prompt()
    assert "[Bereits geladene Plugins" in prompt
    assert "- weather:" in prompt


# --- Block-Format ------------------------------------------------------


def test_inventory_block_format_has_closing_bracket(tmp_path):
    a = _make_assistant(tmp_path)
    block = a._build_plugin_inventory_block()
    # Letzte Zeile schliesst den Block
    assert block.rstrip().endswith("]")
    # Header + Trennzeile vorhanden
    assert block.startswith("[Bereits geladene Plugins")


def test_inventory_block_one_line_per_plugin_today(tmp_path):
    """Aktuell 25 Builtin-Plugins (Phase 92: multi_stop_route dazu)
    -> 25 Plugin-Zeilen + 1 Header = 26 Zeilen. Greift noch nicht
    das 30-Zeilen-Limit."""
    a = _make_assistant(tmp_path)
    block = a._build_plugin_inventory_block()
    plugin_lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    # 25 Builtin-Plugins, alle in der Liste
    assert len(plugin_lines) == 25


# --- Trim-Verhalten ----------------------------------------------------


def _make_loaded_plugin(name: str, priority: int) -> registry.LoadedPlugin:
    """Konstruiert einen LoadedPlugin mit minimal-aufgeloestem CommandPlugin."""
    plugin_obj = MagicMock()
    plugin_obj.name = name
    plugin_obj.priority = priority
    plugin_obj.category = "test"
    return registry.LoadedPlugin(
        plugin=plugin_obj,
        source=registry.PluginSource.BUILTIN,
        source_path=f"{name}.py",
    )


def test_inventory_block_trim_kicks_in_above_30_lines(tmp_path, monkeypatch):
    """Bei 50 simulierten Plugins: Block bleibt <=30 Zeilen + Trim-Hinweis."""
    fake = [_make_loaded_plugin(f"fake{i:02d}", priority=10 + i) for i in range(50)]

    monkeypatch.setattr(
        assistant_module,
        "load_plugins_with_sources",
        lambda: fake,
        raising=False,
    )
    # Da der Block die Funktion lokal importiert, muss der Monkey-Patch
    # auf das Quellmodul gehen.
    monkeypatch.setattr(registry, "load_plugins_with_sources", lambda: fake)

    a = _make_assistant(tmp_path)
    block = a._build_plugin_inventory_block()
    lines = block.splitlines()
    # Header + max_plugin_lines (29) = 30 Zeilen insgesamt
    assert len(lines) == 30
    # Letzte Zeile traegt den Trim-Hinweis + schliessende Klammer
    assert "weitere" in lines[-1]
    assert lines[-1].rstrip().endswith("]")


def test_inventory_block_no_trim_at_exact_limit(tmp_path, monkeypatch):
    """Genau 29 Plugins (= 30-1 fuer den Header) -> kein Trim, alle drin."""
    fake = [_make_loaded_plugin(f"fake{i:02d}", priority=10 + i) for i in range(29)]
    monkeypatch.setattr(registry, "load_plugins_with_sources", lambda: fake)

    a = _make_assistant(tmp_path)
    block = a._build_plugin_inventory_block()
    lines = block.splitlines()
    assert len(lines) == 30  # Header + 29 Plugin-Zeilen
    assert "weitere" not in block


# --- Robustness --------------------------------------------------------


def test_inventory_block_handles_registry_failure(tmp_path, monkeypatch):
    """Wenn die Registry crasht, soll der Build nicht kippen."""

    def boom() -> list[registry.LoadedPlugin]:
        raise RuntimeError("registry kaputt")

    monkeypatch.setattr(registry, "load_plugins_with_sources", boom)

    a = _make_assistant(tmp_path)
    block = a._build_plugin_inventory_block()
    assert block == ""

    # Voller Prompt darf trotzdem gebaut werden
    prompt = a._build_system_prompt()
    assert prompt
    assert "[Bereits geladene Plugins" not in prompt


def test_inventory_block_present_in_prompt_does_not_explode_length(tmp_path):
    """Block-Anteil bleibt klein gegenueber dem Gesamt-Prompt -- so ist
    der Plugin-Inventar-Block fuer's LLM-Kontextbudget vernachlaessigbar.
    """
    a = _make_assistant(tmp_path)
    prompt = a._build_system_prompt()
    block = a._build_plugin_inventory_block()
    assert len(block) < len(prompt)
    # Aktuell ~600-800 Zeichen Block bei einem >2000-Zeichen-Prompt;
    # Heuristik mit Spielraum fuer Phase 78.
    assert len(block) < 2000
