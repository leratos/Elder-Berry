"""LLM-API – Status- und Mode-Endpoints für den LLMRouter.

Wird von SettingsDashboard eingebunden via ``register_llm_routes()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import Body, Request
from fastapi.responses import JSONResponse

from elder_berry.core.log_sanitize import safe_log
from elder_berry.llm.modes import LLM_MODES, normalize_llm_mode

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_ALLOWED_MODES = ", ".join(LLM_MODES)


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
    async def llm_status() -> JSONResponse:
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
                "degraded": dashboard._llm_router.degraded,
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
    async def llm_mode(
        request: Request, body: dict[str, Any] = Body(...)
    ) -> JSONResponse:
        if not dashboard._llm_router:
            return JSONResponse(
                {"error": "LLMRouter nicht verfügbar."},
                status_code=503,
            )
        raw_mode = body.get("mode")
        new_mode = normalize_llm_mode(raw_mode if isinstance(raw_mode, str) else None)
        if new_mode is None:
            return JSONResponse(
                {"error": f"Ungültiger Modus: {raw_mode}. Erlaubt: {_ALLOWED_MODES}"},
                status_code=400,
            )
        dashboard._llm_router.mode = new_mode
        if dashboard._secret_store:
            async with dashboard._write_lock:
                dashboard._secret_store.set(dashboard.LLM_MODE_KEY, new_mode)
        client_host = request.client.host if request.client else "unbekannt"
        # safe_log: new_mode ist zwar via normalize_llm_mode allowlist-normalisiert,
        # aber CodeQL trackt es aus dem Request-Body (py/log-injection).
        logger.info(
            "AUDIT: LLM-Modus auf '%s' gesetzt von %s",
            safe_log(new_mode),
            client_host,
        )
        return JSONResponse(
            {
                "mode": dashboard._llm_router.mode,
                "active_backend": dashboard._llm_router.active_backend,
            }
        )
