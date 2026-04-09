"""Security-Middleware – CORS, Security-Headers und globaler Exception-Handler.

Wird von SettingsDashboard eingebunden via ``setup_security()``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Fügt Sicherheits-Header zu jeder Response hinzu."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline';"
        )
        return response


def setup_security(
    app: FastAPI,
    port: int,
    secret_store: SecretStore | None = None,
) -> None:
    """Konfiguriert CORS, Security-Headers und globalen Exception-Handler."""

    # --- CORS ---
    allowed_origins = [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]
    if secret_store:
        dashboard_origin = secret_store.get_or_none("dashboard_origin")
        if dashboard_origin:
            allowed_origins.append(dashboard_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    # --- Security Response Headers ---
    app.add_middleware(SecurityHeadersMiddleware)

    # --- Globaler Exception-Handler ---
    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unbehandelte Ausnahme in %s", request.url.path)
        return JSONResponse(
            {"error": "Interner Fehler – Details im Log."},
            status_code=500,
        )
