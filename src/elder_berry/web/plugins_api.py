"""Plugin-Inspector-API – Read-Only-Endpoint fuer geladene Plugins (Phase 77.5).

Wird von SettingsDashboard eingebunden via ``register_plugins_routes()``.

Liefert eine Uebersicht aller via ``load_plugins_with_sources()``
sichtbaren Plugins inklusive Quelle (builtin/user_dir/entry_point), so
dass Lera im Dashboard sehen kann, was Saleria gerade laed -- ohne
Matrix-Command und ohne Restart.

Auth: laeuft hinter ``DashboardAuthMiddleware`` (Phase 58). Plugin-Liste
leakt Capability-Konfiguration (z.B. dass cloud/email aktiv ist), darum
ist der Endpoint NICHT oeffentlich -- siehe Konzept §7 R5.

Hinweis zum ``active``-Feld: Das hier verwendete ``active`` bedeutet
"sichtbar in der Registry nach Dedupe" -- nicht "Factory hat einen
Handler geliefert". Letzteres haengt am ``HandlerContext`` und ist nur
mit Zugriff auf den ``RemoteCommandHandler`` ableitbar; das ist
absichtlich nicht durch das Dashboard durchgereicht (eigene Phase, falls
Bedarf).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from elder_berry.comms.commands.registry import (
    LoadedPlugin,
    load_plugins_with_sources,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _help_section_excerpt(help_section: str, max_chars: int = 200) -> str:
    """Trimmt help_section auf eine kompakte Vorschau fuer die Tabelle."""
    text = help_section.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _serialize_loaded_plugin(entry: LoadedPlugin) -> dict[str, Any]:
    """Konvertiert einen LoadedPlugin-Wrapper in den JSON-Body-Eintrag."""
    plugin = entry.plugin
    return {
        "name": plugin.name,
        "priority": plugin.priority,
        "category": plugin.category,
        "version": plugin.version,
        "source": entry.source.value,
        "source_path": entry.source_path,
        "conflicts": list(plugin.conflicts),
        "requires": list(plugin.requires),
        # Siehe Modul-Docstring: vereinfachtes "active"-Signal.
        "active": True,
        "help_section_excerpt": _help_section_excerpt(plugin.help_section),
    }


def register_plugins_routes(app: FastAPI) -> None:
    """Registriert ``GET /api/plugins`` auf der FastAPI-App.

    Wird im SettingsDashboard nach den Auth-Middlewares angesteckt, so
    dass die Route automatisch hinter dem Login liegt.
    """

    @app.get("/api/plugins")
    async def get_plugins() -> JSONResponse:
        """Listet alle geladenen Plugins inklusive Quelle.

        Sortierung: nach ``priority`` (wie ``load_plugins_with_sources``).
        Body-Format: ``{plugins: [...], summary: {total, by_source}}``.
        """
        loaded = load_plugins_with_sources()
        plugins_body: list[dict[str, Any]] = [
            _serialize_loaded_plugin(entry) for entry in loaded
        ]

        source_counter: Counter[str] = Counter(entry.source.value for entry in loaded)
        # Alle Source-Werte aus der Enum vorbelegen, damit der Client auch
        # bei 0-Counts einen vollstaendigen Schluesselraum bekommt.
        by_source: dict[str, int] = {
            "builtin": source_counter.get("builtin", 0),
            "user_dir": source_counter.get("user_dir", 0),
            "entry_point": source_counter.get("entry_point", 0),
        }

        return JSONResponse(
            {
                "plugins": plugins_body,
                "summary": {
                    "total": len(plugins_body),
                    "by_source": by_source,
                },
            }
        )
