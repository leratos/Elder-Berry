"""Settings-Token-Middleware (Phase 52.1a + 57.2 + Phase 58 Cookie-OR-Token).

Schützt schreibende Endpoints des Settings-Dashboards mit einem statischen
Token im Header ``X-Saleria-Settings-Token``. Lesende Endpoints (GET)
bleiben offen. Der Setup-Wizard-Pfad (``/api/setup/*``) ist **solange
der Wizard noch nicht abgeschlossen ist** ebenfalls offen – nach dem
First-Run (Marker ``setup_wizard_completed`` im SecretStore) entfällt
die Exemption und ``/api/setup/*`` verlangt den Token genauso wie jeder
andere schreibende Endpoint (Phase 57.2).

Phase 58: Wenn ein ``DashboardAuthManager`` injiziert wird, akzeptiert
die Middleware **entweder** einen gültigen Token-Header **oder** ein
gültiges Session-Cookie (``eb_dashboard_session``). Eingeloggte Browser-
Sessions können damit schreibende Operationen ausführen, ohne dass das
JS einen Token kennen muss; CLI-Skripte nutzen weiter den Token.
"""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from elder_berry.web.dashboard_auth import (
    COOKIE_NAME as DASHBOARD_COOKIE_NAME,
    InvalidSessionError,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import ASGIApp

    from elder_berry.core.secret_store import SecretStore
    from elder_berry.web.dashboard_auth import DashboardAuthManager
    from elder_berry.web.settings_token import SettingsTokenManager

logger = logging.getLogger(__name__)


# Phase 57.2: WeakSet-Registry aktiver Middleware-Instanzen. Ermöglicht
# Cache-Invalidation nach dem Setup-Wizard-Finish (``/api/setup/complete``),
# ohne dass der Endpoint eine direkte Referenz auf die Middleware-Instanz
# braucht. WeakSet vermeidet Memory-Leaks in Tests: tote Instanzen werden
# automatisch entfernt.
_active_middlewares: "weakref.WeakSet[SettingsTokenMiddleware]" = weakref.WeakSet()


def invalidate_setup_completion_cache() -> None:
    """Setzt den First-Run-Cache auf allen aktiven Middleware-Instanzen zurück.

    Wird vom Setup-Wizard-Finish-Endpoint gerufen, nachdem
    ``setup_wizard_completed=true`` im SecretStore gespeichert wurde.
    Der nächste Request lädt den Marker frisch aus dem Store und sieht
    damit, dass die Wizard-Exemption entfallen muss.
    """
    for middleware in list(_active_middlewares):
        middleware.invalidate_completion_cache()


class SettingsTokenMiddleware(BaseHTTPMiddleware):
    """Lehnt schreibende Requests ohne gültigen Token ab.

    Parameters
    ----------
    app
        Die FastAPI-App.
    token_manager
        Der SettingsTokenManager, dessen Token validiert wird.
    secret_store
        Optional (Phase 57.2). Wenn gesetzt, prüft die Middleware
        ``setup_wizard_completed`` und hebt die ``/api/setup``-Exemption
        auf, sobald der Marker auf ``"true"`` steht. Ohne Store verhält
        sich die Middleware wie in Phase 52.1a – Exemption permanent,
        backwards-kompatibel für Tests und Legacy-Setups.

    Notes
    -----
    Geschützt werden POST/PUT/DELETE/PATCH unterhalb der Pfad-Präfixe in
    ``PROTECTED_PREFIXES``. ``/api/setup`` ist **bedingt** exempted – nur
    solange ``setup_wizard_completed`` noch nicht gesetzt ist.

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
    EXEMPT_PREFIXES: tuple[str, ...] = ("/api/setup",)
    SETUP_COMPLETE_KEY = "setup_wizard_completed"

    def __init__(
        self,
        app: ASGIApp,
        token_manager: SettingsTokenManager,
        secret_store: "SecretStore | None" = None,
        auth_manager: "DashboardAuthManager | None" = None,
    ) -> None:
        super().__init__(app)
        self._token_manager = token_manager
        self._secret_store = secret_store
        # Phase 58: Optional. Wenn gesetzt, akzeptiert die Middleware
        # zusätzlich ein gültiges Session-Cookie als Auth-Nachweis.
        self._auth_manager = auth_manager
        # Phase 57.2: Lazy-Load-Cache. None = noch nicht geladen,
        # True/False = aus SecretStore gelesen.
        self._setup_done: bool | None = None
        _active_middlewares.add(self)

    def _is_setup_done(self) -> bool:
        """Liest ``setup_wizard_completed`` aus dem SecretStore (cached).

        Ohne Store immer ``False`` → Exemption bleibt wie in Phase 52.1a.
        """
        if self._secret_store is None:
            return False
        if self._setup_done is None:
            value = self._secret_store.get_or_none(self.SETUP_COMPLETE_KEY)
            self._setup_done = value == "true"
        return self._setup_done

    def invalidate_completion_cache(self) -> None:
        """Zwingt den nächsten Request dazu, den Marker neu zu laden."""
        self._setup_done = None

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method.upper() not in self.PROTECTED_METHODS:
            return await call_next(request)

        path = request.url.path
        is_exempt_path = any(path.startswith(p) for p in self.EXEMPT_PREFIXES)
        is_protected_path = any(path.startswith(p) for p in self.PROTECTED_PREFIXES)

        # Phase 57.2: Exemption greift nur, solange der Setup-Wizard
        # noch nicht abgeschlossen ist. Nach dem First-Run verlangt
        # auch /api/setup den Token – Re-Konfigurieren nach Setup ist
        # dann ein bewusster Akt.
        if is_exempt_path and not self._is_setup_done():
            return await call_next(request)

        if not is_exempt_path and not is_protected_path:
            return await call_next(request)

        # Phase 58: Cookie-OR-Token. Browser-Sessions kommen mit
        # gültigem Session-Cookie durch, CLI-Skripte mit Token-Header.
        if self._auth_manager is not None:
            cookie = request.cookies.get(DASHBOARD_COOKIE_NAME)
            if cookie:
                try:
                    self._auth_manager.verify_session(cookie)
                    return await call_next(request)
                except InvalidSessionError:
                    pass  # Fallback auf Token-Header

        token = request.headers.get(self.HEADER_NAME)
        if not self._token_manager.validate(token):
            client_host = request.client.host if request.client else "unbekannt"
            logger.warning(
                "Settings-Token ungültig oder fehlt: %s %s von %s",
                request.method,
                path,
                client_host,
            )
            return JSONResponse(
                {
                    "error": "Settings-Token erforderlich oder ungültig.",
                    "header": self.HEADER_NAME,
                },
                status_code=401,
            )
        return await call_next(request)
