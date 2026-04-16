"""Auth-Endpoints für das Dashboard (Phase 58).

Stellt 4 Endpoints bereit:

- ``POST /api/dashboard/login``      – PW prüfen, Cookie setzen
- ``POST /api/dashboard/logout``     – Cookie löschen
- ``GET  /api/dashboard/auth/status`` – ist eingeloggt? PW gesetzt? Expiry?
- ``POST /api/dashboard/password``   – PW ändern (verlangt aktuelles PW
  oder gültiges Login-Cookie)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from elder_berry.web.dashboard_auth import (
    COOKIE_NAME,
    InvalidSessionError,
    PasswordNotSetError,
)

if TYPE_CHECKING:
    from elder_berry.web.dashboard_auth import DashboardAuthManager

logger = logging.getLogger(__name__)


def register_dashboard_auth_routes(
    app: FastAPI,
    auth_manager: DashboardAuthManager,
) -> None:
    """Registriert alle 4 Dashboard-Auth-Endpoints."""

    def _set_session_cookie(
        response: JSONResponse, cookie: str, request: Request,
    ) -> None:
        response.set_cookie(
            COOKIE_NAME,
            cookie,
            max_age=auth_manager.ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )

    @app.post("/api/dashboard/login")
    async def login(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        password = body.get("password", "")
        if not isinstance(password, str) or not password:
            return JSONResponse(
                {"error": "Passwort fehlt", "code": "missing_password"},
                status_code=400,
            )
        try:
            valid = auth_manager.verify_password(password)
        except PasswordNotSetError:
            return JSONResponse(
                {
                    "error": "Kein Dashboard-Passwort gesetzt – siehe Setup",
                    "code": "password_not_set",
                },
                status_code=409,
            )
        if not valid:
            client_host = request.client.host if request.client else "unbekannt"
            logger.warning("Dashboard-Login fehlgeschlagen von %s", client_host)
            return JSONResponse(
                {"error": "Falsches Passwort", "code": "invalid_password"},
                status_code=401,
            )
        cookie, exp = auth_manager.issue_session()
        response = JSONResponse({"ok": True, "expires_at": exp})
        _set_session_cookie(response, cookie, request)
        logger.info("Dashboard-Login erfolgreich")
        return response

    @app.post("/api/dashboard/logout")
    async def logout(request: Request) -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/api/dashboard/auth/status")
    async def auth_status(request: Request) -> JSONResponse:
        password_set = auth_manager.is_password_set()
        cookie = request.cookies.get(COOKIE_NAME)
        authenticated = False
        expires_at: int | None = None
        if cookie:
            try:
                payload = auth_manager.verify_session(cookie)
                authenticated = True
                expires_at = int(payload["exp"])
            except InvalidSessionError:
                pass
        return JSONResponse({
            "authenticated": authenticated,
            "expires_at": expires_at,
            "password_set": password_set,
        })

    @app.post("/api/dashboard/password")
    async def change_password(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        current = body.get("current_password", "")
        new = body.get("new_password", "")
        if not isinstance(new, str) or not new:
            return JSONResponse(
                {"error": "Neues Passwort fehlt", "code": "missing_password"},
                status_code=400,
            )

        # Wenn noch kein PW gesetzt: Setup-Modus, current nicht nötig.
        # (Aber DashboardAuthMiddleware hat den Pfad in dem Fall offen
        # gelassen, weil es vor dem ersten PW noch keinen Login gibt.)
        if auth_manager.is_password_set():
            try:
                if not auth_manager.verify_password(current):
                    return JSONResponse(
                        {
                            "error": "Aktuelles Passwort falsch",
                            "code": "invalid_current_password",
                        },
                        status_code=401,
                    )
            except PasswordNotSetError:
                pass  # Race-Condition – fällt in den Setup-Pfad

        try:
            auth_manager.set_password(new)
        except ValueError as exc:
            return JSONResponse(
                {"error": str(exc), "code": "weak_password"},
                status_code=400,
            )

        # Frisches Cookie ausgeben (damit Wechsel ohne Re-Login wirkt)
        cookie, exp = auth_manager.issue_session()
        response = JSONResponse({"ok": True, "expires_at": exp})
        _set_session_cookie(response, cookie, request)
        logger.info("Dashboard-Passwort geändert (frisches Cookie ausgegeben)")
        return response
