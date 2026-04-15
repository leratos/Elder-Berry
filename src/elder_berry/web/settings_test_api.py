"""Settings-Test- und Security-API – Phase 52.1a.

Stellt zwei Endpoint-Gruppen für das Settings-Panel bereit:

- ``POST /api/settings/test/{service}`` – Verbindungstest für einen Dienst,
  ohne Credentials im Request mitzugeben (Werte werden aus dem SecretStore
  gelesen). Nutzt ``SetupTests`` aus ``setup_tests.py``.
- ``GET /api/settings/security`` – read-only Überblick über die Sicherheits-
  konfiguration (CORS-Origins, Allowed-Senders-Count).
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from fastapi.responses import JSONResponse

from elder_berry.web.setup_tests import SetupTests

if TYPE_CHECKING:
    from fastapi import FastAPI

    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service-Registry: name → (collect-credentials, run-test)
# ---------------------------------------------------------------------------

class _MissingSecret(ValueError):
    """Wird geworfen wenn ein für den Test benötigter Key fehlt."""


def _require(store: SecretStore, key: str) -> str:
    value = store.get_or_none(key) if store else None
    if not value:
        raise _MissingSecret(f"Setting '{key}' fehlt – bitte zuerst speichern.")
    return value


async def _run_anthropic(store: SecretStore) -> dict[str, Any]:
    return await SetupTests.test_anthropic(_require(store, "anthropic_api_key"))


async def _run_groq(store: SecretStore) -> dict[str, Any]:
    return await SetupTests.test_groq(_require(store, "groq_api_key"))


async def _run_brave(store: SecretStore) -> dict[str, Any]:
    return await SetupTests.test_brave(_require(store, "brave_api_key"))


async def _run_google_maps(store: SecretStore) -> dict[str, Any]:
    return await SetupTests.test_google_maps(_require(store, "google_maps_api_key"))


async def _run_matrix(store: SecretStore) -> dict[str, Any]:
    homeserver = _require(store, "matrix_homeserver")
    user_id = _require(store, "matrix_user_id")
    token = store.get_or_none("matrix_access_token")
    if not token:
        raise _MissingSecret(
            "matrix_access_token fehlt – bitte Token speichern oder per Setup-Wizard "
            "neu authentisieren."
        )
    room_id = store.get_or_none("matrix_room_id")
    return await SetupTests.test_matrix(homeserver, user_id, token, room_id)


async def _run_nextcloud(store: SecretStore) -> dict[str, Any]:
    return await SetupTests.test_nextcloud(
        _require(store, "nextcloud_url"),
        _require(store, "nextcloud_user"),
        _require(store, "nextcloud_app_password"),
    )


async def _run_email(store: SecretStore) -> dict[str, Any]:
    imap_host = _require(store, "email_imap_host")
    imap_port = int(store.get_or_none("email_imap_port") or "993")
    smtp_host = _require(store, "smtp_host")
    smtp_port = int(store.get_or_none("smtp_port") or "465")
    return await SetupTests.test_email(
        imap_host, imap_port, smtp_host, smtp_port,
        _require(store, "email_user"),
        _require(store, "email_password"),
    )


async def _run_ollama(store: SecretStore) -> dict[str, Any]:
    return SetupTests.test_ollama()


async def _run_tower(store: SecretStore) -> dict[str, Any]:
    host = _require(store, "tower_host")
    from elder_berry.core.tower_agent import TowerAgent
    agent = TowerAgent(tower_host=host)
    online = False
    try:
        online = await agent.heartbeat()
    except Exception as exc:
        return {"success": False, "host": host, "error": str(exc)}
    return {"success": bool(online), "host": host}


async def _run_rpi5(store: SecretStore) -> dict[str, Any]:
    host = _require(store, "robot_host")
    try:
        from elder_berry.robot.client import RobotClient
        client = RobotClient(base_url=host)
        online = bool(client.is_online())
    except Exception as exc:
        return {"success": False, "host": host, "error": str(exc)}
    return {"success": online, "host": host}


_TestRunner = Callable[["SecretStore"], Awaitable[dict[str, Any]]]

SERVICE_TESTS: dict[str, _TestRunner] = {
    "anthropic": _run_anthropic,
    "groq": _run_groq,
    "brave": _run_brave,
    "google_maps": _run_google_maps,
    "matrix": _run_matrix,
    "nextcloud": _run_nextcloud,
    "email": _run_email,
    "ollama": _run_ollama,
    "tower": _run_tower,
    "rpi5": _run_rpi5,
}


# ---------------------------------------------------------------------------
# Security-Status – CORS + Allowed Senders
# ---------------------------------------------------------------------------

ALLOWED_SENDERS_KEY = "matrix_allowed_senders"


def _compute_cors_origins(secret_store: SecretStore | None, port: int) -> list[str]:
    """Spiegelt die Logik aus security_middleware.setup_security() für die UI."""
    origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    if secret_store:
        extra = secret_store.get_or_none("dashboard_origin")
        if extra:
            origins.append(extra)
    return origins


def _allowed_senders_count(secret_store: SecretStore | None) -> int:
    if not secret_store:
        return 0
    raw = secret_store.get_or_none(ALLOWED_SENDERS_KEY)
    if not raw:
        return 0
    return len([s for s in raw.split(",") if s.strip()])


# ---------------------------------------------------------------------------
# Route-Registrierung
# ---------------------------------------------------------------------------

def register_settings_test_routes(
    app: FastAPI,
    secret_store: SecretStore | None,
    port: int,
) -> None:
    """Hängt /api/settings/test/{service} und /api/settings/security an die App."""

    @app.post("/api/settings/test/{service}")
    async def test_service(service: str):
        if service not in SERVICE_TESTS:
            return JSONResponse(
                {"error": f"Unbekannter Service '{service}'.",
                 "available": sorted(SERVICE_TESTS.keys())},
                status_code=404,
            )
        if secret_store is None:
            return JSONResponse(
                {"error": "SecretStore nicht verfügbar."},
                status_code=503,
            )
        runner = SERVICE_TESTS[service]
        try:
            result = await runner(secret_store)
        except _MissingSecret as exc:
            return JSONResponse(
                {"success": False, "error": str(exc), "missing_config": True},
                status_code=400,
            )
        except Exception as exc:
            logger.error("Verbindungstest '%s' fehlgeschlagen: %s", service, exc)
            return JSONResponse(
                {"success": False, "error": str(exc)},
                status_code=500,
            )
        if not isinstance(result, dict):
            result = {"success": bool(result)}
        result.setdefault("service", service)
        return JSONResponse(result)

    @app.get("/api/settings/security")
    async def security_overview():
        return JSONResponse({
            "cors": {
                "origins": _compute_cors_origins(secret_store, port),
                "methods": ["GET", "POST", "DELETE"],
                "allow_credentials": False,
                "editable": False,
                "note": (
                    "Origins werden aus Port + 'dashboard_origin' (SecretStore) "
                    "abgeleitet. Änderungen erfordern Neustart."
                ),
            },
            "allowed_senders": {
                "count": _allowed_senders_count(secret_store),
                "configured": _allowed_senders_count(secret_store) > 0,
            },
        })
