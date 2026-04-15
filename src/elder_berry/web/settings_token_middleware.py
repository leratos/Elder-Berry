"""Settings-Token-Middleware (Phase 52.1a).

Schützt schreibende Endpoints des Settings-Dashboards mit einem statischen
Token im Header ``X-Saleria-Settings-Token``. Lesende Endpoints (GET) und
der Setup-Wizard-Pfad (``/api/setup/*``) bleiben offen, damit die
Erst-Einrichtung möglich ist.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from starlette.requests import Request

    from elder_berry.web.settings_token import SettingsTokenManager

logger = logging.getLogger(__name__)


class SettingsTokenMiddleware(BaseHTTPMiddleware):
    """Lehnt schreibende Requests ohne gültigen Token ab.

    Parameters
    ----------
    app
        Die FastAPI-App.
    token_manager
        Der SettingsTokenManager, dessen Token validiert wird.

    Notes
    -----
    Geschützt werden POST/PUT/DELETE/PATCH unterhalb der Pfad-Präfixe in
    ``PROTECTED_PREFIXES``. Der Wizard-Pfad ``/api/setup`` ist explizit
    ausgenommen, weil er die Erst-Einrichtung trägt – sobald Phase 52.3
    den First-Run-Marker eingebaut hat, kann diese Ausnahme verschärft
    werden.

    GET-Requests sind generell ausgenommen – sie liefern für sensitive
    Felder ohnehin nur Status-Informationen, keinen Klartext.
    """

    HEADER_NAME = "X-Saleria-Settings-Token"
    PROTECTED_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
    PROTECTED_PREFIXES: tuple[str, ...] = (
        "/api/secrets",
        "/api/settings",
        "/api/allowed-senders",
        "/api/timezone",
        "/api/stt-timeout",
        "/api/llm",
        "/api/audio",
        "/api/monitor",
        "/api/avatar",
    )
    EXEMPT_PREFIXES: tuple[str, ...] = (
        "/api/setup",
    )

    def __init__(self, app, token_manager: SettingsTokenManager) -> None:
        super().__init__(app)
        self._token_manager = token_manager

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in self.PROTECTED_METHODS:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)
        if not any(path.startswith(p) for p in self.PROTECTED_PREFIXES):
            return await call_next(request)

        token = request.headers.get(self.HEADER_NAME)
        if not self._token_manager.validate(token):
            client_host = request.client.host if request.client else "unbekannt"
            logger.warning(
                "Settings-Token ungültig oder fehlt: %s %s von %s",
                request.method, path, client_host,
            )
            return JSONResponse(
                {
                    "error": "Settings-Token erforderlich oder ungültig.",
                    "header": self.HEADER_NAME,
                },
                status_code=401,
            )
        return await call_next(request)
