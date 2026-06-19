"""``/api/settings/*``-Routen des Settings-Dashboards (Phase 106).

Ausgelagert aus ``SettingsDashboard._register_routes``: Schema, Values, Status
und Update der generischen Settings-API. Wird von ``SettingsDashboard.__init__``
via ``register_settings_api_routes(app, self)`` eingebunden. Nutzt – wie
``settings_routes``/``secrets_api`` – ein lokales ``_DashboardLike``-Protocol,
um einen Modul-Zyklus zu vermeiden (CodeQL ``py/cyclic-import``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import Body
from fastapi.responses import JSONResponse

from elder_berry.core.log_sanitize import safe_log
from elder_berry.web.settings_registry import (
    SettingDefinition,
    serialize_setting_definition,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class _DashboardLike(Protocol):
    """Strukturelles Subset von ``SettingsDashboard`` für die Settings-API.

    Vermeidet einen Modul-Zyklus mit ``settings_dashboard``
    (CodeQL ``py/cyclic-import``).
    """

    _secret_store: Any
    _write_lock: asyncio.Lock
    LLM_MODE_KEY: str
    TIMEZONE_KEY: str

    def _setting_definitions(self) -> list[SettingDefinition]: ...

    def _setting_definition_map(self) -> dict[str, SettingDefinition]: ...

    def _get_setting_value(self, key: str) -> str | float: ...

    def _validate_setting_value(
        self, definition: SettingDefinition, value: Any
    ) -> str | float: ...

    def _store_setting_value(
        self, definition: SettingDefinition, value: str | float
    ) -> None: ...

    async def _get_monitor_status(self) -> dict[str, Any]: ...


def register_settings_api_routes(app: FastAPI, dashboard: _DashboardLike) -> None:
    """Registriert die ``/api/settings/*``-Endpoints (Schema/Values/Status/Update)."""

    @app.get("/api/settings/schema")
    async def settings_schema() -> JSONResponse:
        definitions = [
            serialize_setting_definition(definition)
            for definition in dashboard._setting_definitions()
        ]
        return JSONResponse({"settings": definitions})

    @app.get("/api/settings/values")
    async def settings_values() -> JSONResponse:
        values = {
            definition.key: dashboard._get_setting_value(definition.key)
            for definition in dashboard._setting_definitions()
        }
        return JSONResponse({"values": values})

    @app.get("/api/settings/status")
    async def settings_status() -> JSONResponse:
        settings = dashboard._setting_definitions()
        categories: dict[str, int] = {}
        configured = 0
        restart_required = []
        for definition in settings:
            categories[definition.category] = (
                categories.get(definition.category, 0) + 1
            )
            value = dashboard._get_setting_value(definition.key)
            is_set = bool(str(value).strip()) if isinstance(value, str) else True
            if is_set:
                configured += 1
            if definition.restart_required:
                restart_required.append(definition.key)
        return JSONResponse(
            {
                "configured": configured,
                "total": len(settings),
                "categories": categories,
                "llmMode": dashboard._get_setting_value(dashboard.LLM_MODE_KEY),
                "timezone": dashboard._get_setting_value(dashboard.TIMEZONE_KEY),
                "restartRequiredSettings": restart_required,
                "monitor": await dashboard._get_monitor_status(),
                "towerTopology": {
                    "dashboardRemote": True,
                    "towerLocal": True,
                },
            }
        )

    @app.post("/api/settings/update")
    async def settings_update(body: Any = Body(...)) -> JSONResponse:
        # body als Any (statt dict[str, Any]), damit der isinstance-
        # Check unten als Defense-in-Depth gegen non-dict-Bodies
        # erhalten bleibt (FastAPI-Body parst zwar dict, aber der
        # Schutz ist beabsichtigt -- gleicher Trick wie avatar_editor
        # _validate_config gegen yaml.safe_load).
        if not dashboard._secret_store:
            return JSONResponse(
                {"error": "SecretStore nicht verfügbar"}, status_code=503
            )
        if not isinstance(body, dict):
            return JSONResponse({"error": "JSON-Objekt erwartet"}, status_code=400)

        key = body.get("key")
        value = body.get("value")
        definition = dashboard._setting_definition_map().get(str(key)) if key else None
        if not definition:
            return JSONResponse({"error": "Unbekanntes Setting"}, status_code=400)

        try:
            validated = dashboard._validate_setting_value(definition, value)
            async with dashboard._write_lock:
                dashboard._store_setting_value(definition, validated)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception:
            logger.exception(
                "Settings-Update fehlgeschlagen (%s)",
                safe_log(key),
            )
            return JSONResponse(
                {"error": "Setting konnte nicht gespeichert werden"},
                status_code=500,
            )

        return JSONResponse(
            {
                "status": "ok",
                "key": definition.key,
                "value": dashboard._get_setting_value(definition.key),
                "restartRequired": definition.restart_required,
                "riskLevel": definition.risk_level,
            }
        )
