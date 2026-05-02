"""Security-Middleware – CORS, Security-Headers und globaler Exception-Handler.

Wird von SettingsDashboard eingebunden via ``setup_security()``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from elder_berry.web.origin_check_middleware import OriginCheckMiddleware

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Fügt Sicherheits-Header zu jeder Response hinzu."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Phase 63: 'unsafe-inline' entfernt. Alle Templates nutzen jetzt
        # externe CSS/JS aus /static/. Externe Requests (frueher direkt
        # zu nominatim.openstreetmap.org) laufen ueber Server-Proxies.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        # Permissions-Policy: Geräte- und Sensor-APIs deaktivieren, die
        # das Dashboard nicht benötigt.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), "
            "payment=(), usb=(), fullscreen=(self)"
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
        # Phase 64 (H-1): strict Typ-Check, damit die neue
        # OriginCheckMiddleware nicht mit Non-Strings (z.B. MagicMock
        # aus Tests) in urlparse crasht.
        if isinstance(dashboard_origin, str) and dashboard_origin.strip():
            allowed_origins.append(dashboard_origin.strip())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    # --- Security Response Headers ---
    app.add_middleware(SecurityHeadersMiddleware)

    # --- Phase 64 (H-1): CSRF-Schutz via Origin/Referer-Validierung ---
    # Wird ZULETZT hinzugefuegt -> laeuft als erstes auf dem Request.
    # Blockt state-changing Requests (POST/PUT/DELETE/PATCH) ohne
    # passenden Origin-Header.
    app.add_middleware(
        OriginCheckMiddleware,
        allowed_origins=allowed_origins,
    )

    # --- Globaler Exception-Handler ---
    @app.exception_handler(Exception)
    async def _global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unbehandelte Ausnahme in %s", request.url.path)
        return JSONResponse(
            {"error": "Interner Fehler – Details im Log."},
            status_code=500,
        )
