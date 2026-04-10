"""Setup-Wizard – FastAPI-Routes für den Installationsassistenten.

Wird von SettingsDashboard eingebunden via ``register_setup_wizard_routes()``.
Kann auch standalone gestartet werden via ``run_setup_wizard()``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Body
from fastapi.responses import HTMLResponse, JSONResponse

from elder_berry.web.setup_tests import EMAIL_PROVIDERS, SetupTests

if TYPE_CHECKING:
    from fastapi import FastAPI

    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Wizard-Schritte: (step_number, name, required_keys, optional_keys)
WIZARD_STEPS: list[dict[str, Any]] = [
    {
        "step": 1,
        "name": "Willkommen",
        "required_keys": [],
        "optional_keys": [],
    },
    {
        "step": 2,
        "name": "LLM-Backend",
        "required_keys": ["anthropic_api_key"],
        "optional_keys": [],
    },
    {
        "step": 3,
        "name": "Matrix",
        "required_keys": [
            "matrix_homeserver",
            "matrix_user_id",
            "matrix_access_token",
            "matrix_room_id",
            "matrix_allowed_senders",
        ],
        "optional_keys": ["matrix_password"],
    },
    {
        "step": 4,
        "name": "Nextcloud",
        "required_keys": [],
        "optional_keys": [
            "nextcloud_url",
            "nextcloud_user",
            "nextcloud_app_password",
        ],
    },
    {
        "step": 5,
        "name": "E-Mail",
        "required_keys": [],
        "optional_keys": [
            "email_user",
            "email_password",
            "email_imap_host",
            "email_imap_port",
            "smtp_host",
            "smtp_port",
        ],
    },
    {
        "step": 6,
        "name": "Standort & Wetter",
        "required_keys": [],
        "optional_keys": [
            "weather_city",
            "weather_latitude",
            "weather_longitude",
            "user_timezone",
        ],
    },
    {
        "step": 7,
        "name": "Optionale Dienste",
        "required_keys": [],
        "optional_keys": [
            "brave_api_key",
            "elevenlabs_api_key",
            "elevenlabs_voice_id",
            "groq_api_key",
            "berry_gym_api_token",
            "google_maps_api_key",
            "robot_host",
        ],
    },
    {
        "step": 8,
        "name": "Zusammenfassung",
        "required_keys": [],
        "optional_keys": [],
    },
]

# Alle Keys die in einem Schritt gesetzt werden dürfen (Whitelist)
_ALL_WIZARD_KEYS: set[str] = set()
for _step in WIZARD_STEPS:
    _ALL_WIZARD_KEYS.update(_step["required_keys"])
    _ALL_WIZARD_KEYS.update(_step["optional_keys"])

# Keys die als sensitiv gelten (Passwörter/Tokens – nie per GET zurückgeben)
_SENSITIVE_KEYS: set[str] = {
    "anthropic_api_key",
    "matrix_access_token",
    "matrix_password",
    "nextcloud_app_password",
    "email_password",
    "brave_api_key",
    "elevenlabs_api_key",
    "groq_api_key",
    "berry_gym_api_token",
    "google_maps_api_key",
}

SETUP_COMPLETE_KEY = "setup_wizard_completed"


def _get_setup_status(secret_store: SecretStore) -> dict[str, Any]:
    """Ermittelt den aktuellen Setup-Status."""
    configured: list[str] = []
    missing: list[str] = []

    # Pflicht-Dienste prüfen
    service_checks = {
        "anthropic": ["anthropic_api_key"],
        "matrix": [
            "matrix_homeserver",
            "matrix_user_id",
            "matrix_access_token",
            "matrix_room_id",
        ],
    }
    # Optionale Dienste
    optional_checks = {
        "nextcloud": ["nextcloud_url", "nextcloud_user", "nextcloud_app_password"],
        "email": ["email_user", "email_password", "email_imap_host", "smtp_host"],
        "weather": ["weather_city"],
        "brave": ["brave_api_key"],
        "elevenlabs": ["elevenlabs_api_key"],
        "groq": ["groq_api_key"],
        "google_maps": ["google_maps_api_key"],
        "rpi5": ["robot_host"],
    }

    for service, keys in {**service_checks, **optional_checks}.items():
        if all(secret_store.has(k) for k in keys):
            configured.append(service)
        else:
            missing.append(service)

    # Aktuellen Schritt bestimmen (erster Schritt mit fehlenden Pflicht-Keys)
    current_step = 1
    for step_def in WIZARD_STEPS:
        req = step_def["required_keys"]
        if req and not all(secret_store.has(k) for k in req):
            current_step = step_def["step"]
            break
    else:
        # Alle Pflicht-Schritte erfüllt
        current_step = 8

    completed = secret_store.has(SETUP_COMPLETE_KEY)

    return {
        "completed": completed,
        "current_step": current_step,
        "steps_total": len(WIZARD_STEPS),
        "configured": configured,
        "missing": missing,
    }


def register_setup_wizard_routes(
    app: FastAPI, secret_store: SecretStore
) -> None:
    """Registriert die Setup-Wizard-Endpoints auf der FastAPI-App."""

    @app.get("/setup")
    async def setup_page():
        """Liefert die Setup-Wizard HTML-Seite."""
        template_path = _TEMPLATE_DIR / "setup_wizard.html"
        if not template_path.exists():
            return HTMLResponse(
                "<h1>Setup-Wizard Template fehlt</h1>",
                status_code=500,
            )
        return HTMLResponse(template_path.read_text(encoding="utf-8"))

    @app.get("/api/setup/status")
    async def setup_status():
        """Liefert den aktuellen Setup-Status."""
        return JSONResponse(_get_setup_status(secret_store))

    @app.get("/api/setup/step/{step_num}")
    async def setup_step_get(step_num: int):
        """Liefert gespeicherte Werte für einen Schritt (ohne Passwörter)."""
        if step_num < 1 or step_num > len(WIZARD_STEPS):
            return JSONResponse(
                {"error": f"Ungültiger Schritt: {step_num}"},
                status_code=400,
            )
        step_def = WIZARD_STEPS[step_num - 1]
        values: dict[str, Any] = {}
        for key in step_def["required_keys"] + step_def["optional_keys"]:
            if key in _SENSITIVE_KEYS:
                # Nur anzeigen ob gesetzt, nicht den Wert
                values[key] = {"is_set": secret_store.has(key)}
            else:
                val = secret_store.get_or_none(key)
                values[key] = {"value": val} if val else {"is_set": False}
        return JSONResponse({
            "step": step_num,
            "name": step_def["name"],
            "values": values,
        })

    @app.post("/api/setup/step/{step_num}")
    async def setup_step_save(step_num: int, body: dict = Body(...)):
        """Speichert Werte für einen Schritt und führt Verbindungstests aus."""
        if step_num < 1 or step_num > len(WIZARD_STEPS):
            return JSONResponse(
                {"error": f"Ungültiger Schritt: {step_num}"},
                status_code=400,
            )
        step_def = WIZARD_STEPS[step_num - 1]
        allowed_keys = set(
            step_def["required_keys"] + step_def["optional_keys"]
        )

        # Pflicht-Keys prüfen
        for key in step_def["required_keys"]:
            if key not in body or not body[key]:
                return JSONResponse(
                    {"error": f"Pflichtfeld '{key}' fehlt."},
                    status_code=400,
                )

        # Nur erlaubte Keys speichern
        saved_keys: list[str] = []
        for key, value in body.items():
            if key not in allowed_keys:
                continue
            if not value or not str(value).strip():
                continue
            secret_store.set(key, str(value).strip())
            saved_keys.append(key)

        # Verbindungstests basierend auf Schritt
        tests: dict[str, Any] = {}
        if step_num == 2:
            tests = await _run_llm_tests(secret_store)
        elif step_num == 3:
            tests = await _run_matrix_tests(secret_store)
        elif step_num == 4:
            tests = await _run_nextcloud_tests(secret_store)
        elif step_num == 5:
            tests = await _run_email_tests(secret_store)

        return JSONResponse({
            "success": True,
            "saved_keys": saved_keys,
            "tests": tests,
        })

    @app.get("/api/setup/prerequisites")
    async def setup_prerequisites():
        """Prüft Systemvoraussetzungen."""
        return JSONResponse(SetupTests.check_prerequisites())

    @app.post("/api/setup/test/{service}")
    async def setup_test_service(service: str, body: dict = Body(...)):
        """Testet einen einzelnen Dienst mit übergebenen Credentials."""
        try:
            result = await _run_single_test(service, body)
            return JSONResponse(result)
        except ValueError as e:
            return JSONResponse(
                {"error": str(e)}, status_code=400
            )

    @app.post("/api/setup/complete")
    async def setup_complete():
        """Markiert das Setup als abgeschlossen."""
        secret_store.set(SETUP_COMPLETE_KEY, "true")
        logger.info("Setup-Wizard abgeschlossen")
        return JSONResponse({
            "success": True,
            "redirect": "/",
        })

    @app.get("/api/setup/providers")
    async def setup_providers():
        """Liefert die Liste der bekannten E-Mail-Provider."""
        result = {}
        for name, (imap_host, imap_port, smtp_host, smtp_port) in EMAIL_PROVIDERS.items():
            result[name] = {
                "imap_host": imap_host,
                "imap_port": imap_port,
                "smtp_host": smtp_host,
                "smtp_port": smtp_port,
            }
        return JSONResponse(result)


async def _run_llm_tests(secret_store: SecretStore) -> dict[str, Any]:
    """Führt LLM-Verbindungstests aus."""
    tests: dict[str, Any] = {}
    api_key = secret_store.get_or_none("anthropic_api_key")
    if api_key:
        tests["anthropic"] = await SetupTests.test_anthropic(api_key)
    tests["ollama"] = SetupTests.test_ollama()
    return tests


async def _run_matrix_tests(secret_store: SecretStore) -> dict[str, Any]:
    """Führt Matrix-Verbindungstests aus."""
    homeserver = secret_store.get_or_none("matrix_homeserver")
    user_id = secret_store.get_or_none("matrix_user_id")
    token = secret_store.get_or_none("matrix_access_token")
    room_id = secret_store.get_or_none("matrix_room_id")
    if not all([homeserver, user_id, token]):
        return {"matrix": {"success": False, "error": "Fehlende Angaben"}}
    return {
        "matrix": await SetupTests.test_matrix(
            homeserver, user_id, token, room_id  # type: ignore[arg-type]
        )
    }


async def _run_nextcloud_tests(secret_store: SecretStore) -> dict[str, Any]:
    """Führt Nextcloud-Verbindungstests aus."""
    url = secret_store.get_or_none("nextcloud_url")
    user = secret_store.get_or_none("nextcloud_user")
    pw = secret_store.get_or_none("nextcloud_app_password")
    if not all([url, user, pw]):
        return {"nextcloud": {"success": False, "error": "Fehlende Angaben"}}
    return {
        "nextcloud": await SetupTests.test_nextcloud(
            url, user, pw  # type: ignore[arg-type]
        )
    }


async def _run_email_tests(secret_store: SecretStore) -> dict[str, Any]:
    """Führt E-Mail-Verbindungstests aus."""
    email_user = secret_store.get_or_none("email_user")
    email_pw = secret_store.get_or_none("email_password")
    imap_host = secret_store.get_or_none("email_imap_host")
    imap_port = secret_store.get_or_none("email_imap_port")
    smtp_host = secret_store.get_or_none("smtp_host")
    smtp_port = secret_store.get_or_none("smtp_port")
    if not all([email_user, email_pw, imap_host, smtp_host]):
        return {"email": {"success": False, "error": "Fehlende Angaben"}}
    return {
        "email": await SetupTests.test_email(
            imap_host,  # type: ignore[arg-type]
            int(imap_port or 993),
            smtp_host,  # type: ignore[arg-type]
            int(smtp_port or 465),
            email_user,  # type: ignore[arg-type]
            email_pw,  # type: ignore[arg-type]
        )
    }


async def _run_single_test(
    service: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Führt einen einzelnen Verbindungstest aus."""
    if service == "anthropic":
        if "api_key" not in params:
            raise ValueError("api_key fehlt")
        return await SetupTests.test_anthropic(params["api_key"])
    if service == "matrix":
        for k in ("homeserver", "user_id", "token"):
            if k not in params:
                raise ValueError(f"{k} fehlt")
        return await SetupTests.test_matrix(
            params["homeserver"],
            params["user_id"],
            params["token"],
            params.get("room_id"),
        )
    if service == "nextcloud":
        for k in ("url", "user", "password"):
            if k not in params:
                raise ValueError(f"{k} fehlt")
        return await SetupTests.test_nextcloud(
            params["url"], params["user"], params["password"]
        )
    if service == "email":
        for k in ("imap_host", "smtp_host", "user", "password"):
            if k not in params:
                raise ValueError(f"{k} fehlt")
        return await SetupTests.test_email(
            params["imap_host"],
            int(params.get("imap_port", 993)),
            params["smtp_host"],
            int(params.get("smtp_port", 465)),
            params["user"],
            params["password"],
        )
    if service == "ollama":
        return SetupTests.test_ollama()
    if service == "brave":
        if "api_key" not in params:
            raise ValueError("api_key fehlt")
        return await SetupTests.test_brave(params["api_key"])
    if service == "groq":
        if "api_key" not in params:
            raise ValueError("api_key fehlt")
        return await SetupTests.test_groq(params["api_key"])
    if service == "google_maps":
        if "api_key" not in params:
            raise ValueError("api_key fehlt")
        return await SetupTests.test_google_maps(params["api_key"])
    raise ValueError(f"Unbekannter Service: {service}")


def run_setup_wizard(secret_store: SecretStore, port: int = 8090) -> None:
    """Startet den Setup-Wizard als Standalone-Server (blockierend).

    Wird von start_saleria.py aufgerufen wenn kein Matrix-Token vorhanden ist.
    """
    import uvicorn

    app = FastAPI(title="Elder-Berry Setup-Wizard")
    register_setup_wizard_routes(app, secret_store)

    logger.info("Setup-Wizard gestartet auf http://localhost:%d/setup", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
