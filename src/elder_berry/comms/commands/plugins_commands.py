"""PluginsCommandHandler – Plugin-Inspector via Matrix (Phase 77.5).

Verwaltet:
- ``plugins`` -> kompakte Liste (Name, Source, Priority, Category)
- ``plugins konflikte`` -> nur Plugins mit conflicts != ()
- ``plugins detail <name>`` -> Manifest + help_section eines Plugins

Endnutzer-Sicht auf ``load_plugins_with_sources()``. Liest die Registry
selbst (kein Service aus HandlerContext noetig); Factory ist deshalb
unbedingt -- Plugin Nr. 24 ist immer aktiv.
"""

from __future__ import annotations

import logging
import re

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
)
from elder_berry.comms.commands.registry import (
    LoadedPlugin,
    load_plugins_with_sources,
)

logger = logging.getLogger(__name__)


# ``plugins detail <name>`` -- Name ist snake_case, daher [a-z0-9_].
_PLUGINS_DETAIL_PATTERN = re.compile(
    r"^plugins\s+detail\s+(?P<name>[a-z0-9_]+)$",
    re.IGNORECASE,
)


class PluginsCommandHandler(CommandHandler):
    """Handler fuer den Plugin-Inspector (drei Sub-Commands).

    Liest beim execute() jeweils frisch aus ``load_plugins_with_sources``
    -- weniger als 100ns/Call und garantiert konsistent mit dem
    Inspector-API.
    """

    @property
    def simple_commands(self) -> set[str]:
        return {"plugins", "plugins konflikte"}

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        return [
            (_PLUGINS_DETAIL_PATTERN, "plugins_detail", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "plugins": [
                "welche plugins",
                "plugin liste",
                "plugin inventar",
                "geladene plugins",
            ],
            "plugins konflikte": [
                "plugin konflikte",
                "plugin kollisionen",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "plugins: Geladene Plugins auflisten (Name, Source, Priority)",
            "plugins detail <name>: Manifest + Hilfe-Text eines Plugins",
            "plugins konflikte: Plugins mit conflicts-Eintrag",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "plugins":
            return self._cmd_plugins_list()
        if command == "plugins konflikte":
            return self._cmd_plugins_conflicts()
        if command == "plugins_detail":
            return self._cmd_plugins_detail(raw_text)
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter plugins-Sub-Command: {command}",
        )

    # --- Sub-Commands ---

    def _cmd_plugins_list(self) -> CommandResult:
        loaded = load_plugins_with_sources()
        if not loaded:
            return CommandResult(
                command="plugins",
                success=True,
                text="Keine Plugins geladen.",
            )

        lines = [f"Geladene Plugins ({len(loaded)}):"]
        for entry in loaded:
            lines.append(self._format_summary_line(entry))
        return CommandResult(
            command="plugins",
            success=True,
            text="\n".join(lines),
        )

    def _cmd_plugins_conflicts(self) -> CommandResult:
        loaded = load_plugins_with_sources()
        with_conflicts = [e for e in loaded if e.plugin.conflicts]
        if not with_conflicts:
            return CommandResult(
                command="plugins konflikte",
                success=True,
                text="Keine Plugins mit conflicts-Eintrag.",
            )

        lines = [f"Plugins mit Konflikten ({len(with_conflicts)}):"]
        for entry in with_conflicts:
            lines.append(
                f"- {entry.plugin.name} (prio {entry.plugin.priority}) "
                f"-> conflicts: {', '.join(entry.plugin.conflicts)}"
            )
        return CommandResult(
            command="plugins konflikte",
            success=True,
            text="\n".join(lines),
        )

    def _cmd_plugins_detail(self, raw_text: str) -> CommandResult:
        match = _PLUGINS_DETAIL_PATTERN.match(raw_text.strip())
        if match is None:
            return CommandResult(
                command="plugins_detail",
                success=False,
                text="Format: plugins detail <name>",
            )

        name = match.group("name").lower()
        loaded = load_plugins_with_sources()
        by_name = {entry.plugin.name: entry for entry in loaded}
        entry = by_name.get(name)
        if entry is None:
            available = ", ".join(sorted(by_name.keys()))
            return CommandResult(
                command="plugins_detail",
                success=False,
                text=(f"Plugin '{name}' nicht gefunden.\nVerfuegbar: {available}"),
            )

        plugin = entry.plugin
        conflicts = ", ".join(plugin.conflicts) if plugin.conflicts else "(keine)"
        requires = ", ".join(plugin.requires) if plugin.requires else "(keine)"
        body = [
            f"Plugin '{plugin.name}' (v{plugin.version})",
            f"  Source: {entry.source.value}"
            + (f" ({entry.source_path})" if entry.source_path else ""),
            f"  Priority: {plugin.priority}",
            f"  Category: {plugin.category}",
            f"  Conflicts: {conflicts}",
            f"  Requires: {requires}",
            "",
            plugin.help_section.rstrip(),
        ]
        return CommandResult(
            command="plugins_detail",
            success=True,
            text="\n".join(body),
        )

    # --- Format-Helpers ---

    @staticmethod
    def _format_summary_line(entry: LoadedPlugin) -> str:
        plugin = entry.plugin
        return (
            f"- {plugin.name} ({entry.source.value}, prio {plugin.priority}, "
            f"{plugin.category})"
        )


# ---------------------------------------------------------------------------
# Phase 77 / 77.5: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_PLUGINS = """Plugins / Inspector:
  plugins -- Geladene Plugins (Name, Source, Priority)
  plugins detail <name> -- Manifest + Hilfe eines Plugins
  plugins konflikte -- Plugins mit conflicts-Eintrag"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    return PluginsCommandHandler()


PLUGIN = CommandPlugin(
    name="plugins",
    priority=80,
    category="diagnose",
    help_section=HELP_SECTION_PLUGINS,
    factory=_factory,
)
