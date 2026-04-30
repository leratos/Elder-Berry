"""LLM-API – Status- und Mode-Endpoints für den LLMRouter.

Wird von SettingsDashboard eingebunden via ``register_llm_routes()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import Body, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class _DashboardLike(Protocol):
    """Strukturelles Subset von ``SettingsDashboard``, das die LLM-Routen
    benötigen. Vermeidet einen Modul-Zyklus mit ``settings_dashboard``
    (CodeQL ``py/cyclic-import``).
    """

    LLM_MODE_KEY: str
    _llm_router: Any
    _secret_store: Any
    _write_lock: asyncio.Lock


def register_llm_routes(app: FastAPI, dashboard: _DashboardLike) -> None:
    """Registriert die LLM-Status- und Mode-Endpoints auf der FastAPI-App."""

    @app.get("/api/llm/status")
    async def llm_status():
        if not dashboard._llm_router:
            return JSONResponse(
                {
                    "available": False,
                    "mode": None,
                    "active_backend": "none",
                    "primary": {"name": None, "available": False},
                    "fallback": {"name": None, "available": False},
                }
            )
        return JSONResponse(
            {
                "available": True,
                "mode": dashboard._llm_router.mode,
                "active_backend": dashboard._llm_router.active_backend,
                "primary": {
                    "name": dashboard._llm_router.primary_name,
                    "available": dashboard._llm_router.primary_available,
                },
                "fallback": {
                    "name": dashboard._llm_router.fallback_name,
                    "available": dashboard._llm_router.fallback_available,
                },
            }
        )

    @app.post("/api/llm/mode")
    async def llm_mode(request: Request, body: dict = Body(...)):
        if not dashboard._llm_router:
            return JSONResponse(
                {"error": "LLMRouter nicht verfügbar."},
                status_code=503,
            )
        new_mode = body.get("mode")
        if new_mode not in ("api_preferred", "local_only"):
            return JSONResponse(
                {
                    "error": f"Ungültiger Modus: {new_mode}. "
                    "Erlaubt: api_preferred, local_only"
                },
                status_code=400,
            )
        dashboard._llm_router.mode = new_mode
        if dashboard._secret_store:
            async with dashboard._write_lock:
                dashboard._secret_store.set(dashboard.LLM_MODE_KEY, new_mode)
        client_host = request.client.host if request.client else "unbekannt"
        logger.info(
            "AUDIT: LLM-Modus auf '%s' gesetzt von %s",
            new_mode,
            client_host,
        )
        return JSONResponse(
            {
                "mode": dashboard._llm_router.mode,
                "active_backend": dashboard._llm_router.active_backend,
            }
        )
