"""DashboardAuthMiddleware – Phase 58.

Login-Layer für das Settings-Dashboard. Schützt **lesend und schreibend**
alle Pfade unterhalb der ``PROTECTED_PREFIXES``. Verlangt ein gültiges
``eb_dashboard_session``-Cookie (siehe :class:`DashboardAuthManager`).

Offen bleiben
-------------
- Statische Dashboard-Assets (sonst kann das Login-UI gar nicht laden).
- ``/api/dashboard/login``, ``/api/dashboard/logout``,
  ``/api/dashboard/auth/status`` (Login-Endpoints selbst).
- ``/harmony/*`` – Fernbedienung bleibt für LAN-Gäste offen.
- ``/api/setup/*`` – nur solange ``setup_wizard_completed != "true"``
  (analog zur SettingsTokenMiddleware).

Sliding Renewal
---------------
Bei jedem authentifizierten Request mit verbleibender Restlaufzeit
< ``ttl/2`` wird das Cookie verlängert (transparent über Set-Cookie
im Response).
"""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from elder_berry.web.dashboard_auth import (
    COOKIE_NAME,
    InvalidSessionError,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from elder_berry.core.secret_store import SecretStore
    from elder_berry.web.dashboard_auth import DashboardAuthManager

logger = logging.getLogger(__name__)


_active_middlewares: "weakref.WeakSet[DashboardAuthMiddleware]" = weakref.WeakSet()


def invalidate_setup_completion_cache() -> None:
    """Setzt den First-Run-Cache aller aktiven Auth-Middlewares zurück."""
    for middleware in list(_active_middlewares):
        middleware.invalidate_completion_cache()


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    """Erzwingt Login-Cookie für geschützte Pfade."""

    PROTECTED_PREFIXES: tuple[str, ...] = (
        "/api/secrets",
        "/api/settings",
        "/api/system",
        "/api/llm",
        "/api/audio",
        "/api/monitor",
        "/api/timezone",
        "/api/stt-timeout",
        "/api/allowed-senders",
        "/api/avatar",
        "/avatar/",
        # Phase 66: Robot-Proxy zum RPi5 -- nur eingeloggte User duerfen
        # ueber den Server-Tunnel auf den RPi5 zugreifen.
        "/api/robot",
    )
    # Endpoints, die innerhalb der geschützten Präfixe trotzdem offen
    # bleiben müssen (Login-Endpoints selbst).
    UNPROTECTED_EXACT: frozenset[str] = frozenset({
        "/api/dashboard/login",
        "/api/dashboard/logout",
        "/api/dashboard/auth/status",
    })
    # Wizard-Pfade: bedingt offen (nur vor First-Run).
    WIZARD_PREFIX = "/api/setup"
    SETUP_COMPLETE_KEY = "setup_wizard_completed"

    def __init__(
        self,
        app,
        auth_manager: DashboardAuthManager,
        secret_store: "SecretStore | None" = None,
    ) -> None:
        super().__init__(app)
        self._auth = auth_manager
        self._secret_store = secret_store
        self._setup_done: bool | None = None
        _active_middlewares.add(self)

    def _is_setup_done(self) -> bool:
        if self._secret_store is None:
            return False
        if self._setup_done is None:
            value = self._secret_store.get_or_none(self.SETUP_COMPLETE_KEY)
            self._setup_done = value == "true"
        return self._setup_done

    def invalidate_completion_cache(self) -> None:
        self._setup_done = None

    def _is_protected(self, path: str) -> bool:
        if path in self.UNPROTECTED_EXACT:
            return False
        # Wizard offen solange First-Run nicht abgeschlossen
        if path.startswith(self.WIZARD_PREFIX) and not self._is_setup_done():
            return False
        # Wizard nach First-Run: schützen
        if path.startswith(self.WIZARD_PREFIX):
            return True
        return any(path.startswith(p) for p in self.PROTECTED_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not self._is_protected(path):
            return await call_next(request)

        cookie = request.cookies.get(COOKIE_NAME)
        try:
            payload = self._auth.verify_session(cookie)
        except InvalidSessionError as exc:
            client_host = request.client.host if request.client else "unbekannt"
            logger.info(
                "Login fehlt/ungültig für %s %s von %s: %s",
                request.method, path, client_host, exc,
            )
            return JSONResponse(
                {
                    "error": "Login erforderlich.",
                    "code": "auth_required",
                },
                status_code=401,
            )

        response = await call_next(request)

        # Sliding Renewal: wenn weniger als ttl/2 Restlaufzeit übrig,
        # Cookie verlängern. Spart Round-Trips für aktive Sessions.
        # Phase 70 (H-4): ``extend_session()`` (statt ``issue_session()``)
        # uebernimmt das ``iat_original`` aus dem alten Cookie -- damit
        # rollt sliding renewal NICHT den absoluten Lifetime-Cap zurueck.
        # Wenn der Cap zwischen verify_session() und Renewal greift,
        # wird hier eine InvalidSessionError geworfen; wir verzichten
        # dann still auf das frische Cookie und liefern die normale
        # Antwort -- der Browser erbt das alte Cookie und faellt beim
        # naechsten Request automatisch in den 401-Pfad oben.
        import time
        remaining = int(payload["exp"]) - int(time.time())
        if remaining < self._auth.ttl_seconds // 2:
            try:
                new_cookie, _new_exp = self._auth.extend_session(cookie)
            except InvalidSessionError as exc:
                logger.info(
                    "Sliding-Renewal abgelehnt fuer %s %s (%s) -- altes "
                    "Cookie laeuft naturalmente ab.",
                    request.method, path, exc,
                )
            else:
                response.set_cookie(
                    COOKIE_NAME,
                    new_cookie,
                    max_age=self._auth.ttl_seconds,
                    httponly=True,
                    # Phase 64 (H-1): strict, konsistent mit Login-Route.
                    samesite="strict",
                    secure=request.url.scheme == "https",
                    path="/",
                )

        return response
