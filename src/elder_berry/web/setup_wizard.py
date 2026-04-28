"""Setup-Wizard – FastAPI-Routes für den Installationsassistenten.

Wird von SettingsDashboard eingebunden via ``register_setup_wizard_routes()``.
Kann auch standalone gestartet werden via ``run_setup_wizard()``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import Body
from fastapi.responses import HTMLResponse, JSONResponse

from elder_berry.web.setup_tests import EMAIL_PROVIDERS, SetupTests

# Phase 63: Nominatim-User-Agent ist gemaess Nutzungsbedingungen Pflicht.
_NOMINATIM_USER_AGENT = "Elder-Berry/1.0 (self-hosted home assistant)"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODE_MAX_QUERY_LEN = 200

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
            "berry_gym_url",
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

    # Aktuellen Schritt bestimmen (erster Schritt mit fehlenden Pflicht-Keys).
    # for-else: Loop-Body setzt current_step bei Break, sonst else-Branch.
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
    async def setup_page(force: int = 0):
        """Liefert die Setup-Wizard HTML-Seite.

        Phase 52.3: Wenn das Setup bereits abgeschlossen ist, wird auf
        ``/settings`` umgeleitet. Mit ``?force=1`` lässt sich der Wizard
        trotzdem öffnen (Recovery-Pfad).
        """
        if force != 1 and secret_store.has(SETUP_COMPLETE_KEY):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/settings", status_code=307)
        template_path = _TEMPLATE_DIR / "setup_wizard.html"
        if not template_path.exists():
            return HTMLResponse(
                "<h1>Setup-Wizard Template fehlt</h1>",
                status_code=500,
            )
        html = template_path.read_text(encoding="utf-8")
        # Phase 57.1a: Compat-Banner injizieren wenn Grace-Period aktiv
        if getattr(app.state, "compat_mode", False):
            _banner = (
                '<div style="background:#fff3cd;color:#856404;padding:12px 16px;'
                "border:1px solid #ffc107;border-radius:6px;margin:16px;"
                'font-size:14px;text-align:center">'
                "Dieser Setup-Wizard l&auml;uft einmalig im "
                "LAN-Kompatibilit&auml;tsmodus. Ab dem n&auml;chsten "
                "Neustart bindet er auf 127.0.0.1 (Loopback). Setze "
                "<code>ELDER_BERRY_SETUP_BIND=0.0.0.0</code> wenn du "
                "den LAN-Zugriff dauerhaft brauchst.</div>"
            )
            html = html.replace("<body>", f"<body>{_banner}", 1)
        return HTMLResponse(html)

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

        # Pflicht-Keys prüfen (auch Whitespace-only abfangen)
        # Bereits gespeicherte Keys akzeptieren (z.B. nach Page-Refresh)
        for key in step_def["required_keys"]:
            val = body.get(key)
            if (not val or not str(val).strip()) and not secret_store.has(key):
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

    @app.post("/api/setup/dashboard-password")
    async def setup_dashboard_password(body: dict = Body(...)):
        """Setzt das Dashboard-Passwort während des Setup-Wizards (Phase 58).

        Pflicht-Schritt: Ohne gesetztes Passwort verweigert
        ``/api/setup/complete`` den Abschluss.
        """
        from elder_berry.web.dashboard_auth import DashboardAuthManager
        password = body.get("password", "")
        if not isinstance(password, str) or not password:
            return JSONResponse(
                {"error": "Passwort fehlt", "code": "missing_password"},
                status_code=400,
            )
        auth = DashboardAuthManager(secret_store)
        try:
            auth.set_password(password)
        except ValueError as exc:
            return JSONResponse(
                {"error": str(exc), "code": "weak_password"},
                status_code=400,
            )
        return JSONResponse({"success": True})

    @app.post("/api/setup/complete")
    async def setup_complete():
        """Markiert das Setup als abgeschlossen.

        Phase 58: Verlangt vorher ein gesetztes Dashboard-Passwort,
        damit nach dem Setup nicht versehentlich ohne Login-Layer
        gestartet wird.
        """
        from elder_berry.web.dashboard_auth import PASSWORD_HASH_KEY
        if not secret_store.has(PASSWORD_HASH_KEY):
            return JSONResponse(
                {
                    "error": "Dashboard-Passwort muss gesetzt sein, bevor "
                             "das Setup abgeschlossen werden kann.",
                    "code": "dashboard_password_required",
                },
                status_code=409,
            )
        secret_store.set(SETUP_COMPLETE_KEY, "true")
        logger.info("Setup-Wizard abgeschlossen")

        # Phase 57.2: Cache der SettingsTokenMiddleware invalidieren,
        # damit der Wechsel des First-Run-Markers sofort greift und
        # /api/setup/* ab dem nächsten Request den Token verlangt.
        from elder_berry.web.settings_token_middleware import (
            invalidate_setup_completion_cache,
        )
        invalidate_setup_completion_cache()

        # Phase 58: Auch den Cache der DashboardAuthMiddleware
        # invalidieren – nach Wizard-Abschluss verlangt /api/setup
        # auch dort einen Login.
        from elder_berry.web.dashboard_auth_middleware import (
            invalidate_setup_completion_cache as
            invalidate_auth_setup_cache,
        )
        invalidate_auth_setup_cache()

        # Phase 57.1a: Marker-Datei schreiben, damit die Grace-Period
        # beim nächsten Start nicht mehr greift.
        marker = getattr(app.state, "migration_marker", None)
        if marker:
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("done", encoding="utf-8")
                logger.info("Phase-57-Migration-Marker angelegt: %s", marker)
            except OSError as exc:
                logger.warning(
                    "Migration-Marker konnte nicht geschrieben werden: %s", exc,
                )

        # Im Standalone-Modus Server nach kurzer Verzögerung beenden
        if getattr(app.state, "standalone", False):
            import asyncio
            async def _shutdown():
                await asyncio.sleep(1.0)
                logger.info("Standalone-Wizard wird beendet")
                import os
                import signal
                os.kill(os.getpid(), signal.SIGINT)
            asyncio.create_task(_shutdown())

        return JSONResponse({
            "success": True,
            "redirect": "/",
            "standalone": getattr(app.state, "standalone", False),
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

    @app.get("/api/setup/geocode")
    async def setup_geocode(q: str = ""):
        """Phase 63: Server-seitiger Nominatim-Proxy.

        Der Setup-Wizard hatte frueher direkt im Browser Nominatim angefragt.
        Mit der strikten CSP (``connect-src 'self'``) ist externer fetch()
        blockiert -- der Proxy liefert dasselbe Ergebnis in einem schlanken
        Format.
        """
        query = q.strip()
        if not query:
            return JSONResponse(
                {"success": False, "error": "Bitte Stadt eingeben."},
                status_code=400,
            )
        if len(query) > _GEOCODE_MAX_QUERY_LEN:
            return JSONResponse(
                {"success": False, "error": "Stadt-Name zu lang."},
                status_code=400,
            )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    _NOMINATIM_URL,
                    params={"format": "json", "limit": 1, "q": query},
                    headers={
                        "Accept-Language": "de",
                        "User-Agent": _NOMINATIM_USER_AGENT,
                    },
                )
        except httpx.HTTPError:
            logger.exception("Geocoding-Netzwerkfehler")
            return JSONResponse(
                {"success": False, "error": "Netzwerkfehler beim Geocoding."},
                status_code=502,
            )
        if resp.status_code != 200:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"Geocoding-API: HTTP {resp.status_code}",
                },
                status_code=502,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning("Geocoding-Antwort nicht JSON: %s", exc)
            return JSONResponse(
                {"success": False, "error": "Ungueltige API-Antwort."},
                status_code=502,
            )
        if not isinstance(data, list) or not data:
            return JSONResponse({"success": False, "error": "Ort nicht gefunden."})
        hit = data[0]
        try:
            return JSONResponse({
                "success": True,
                "lat": float(hit["lat"]),
                "lon": float(hit["lon"]),
                "display_name": str(hit.get("display_name", "")),
            })
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Geocoding-Antwortformat unerwartet: %s", exc)
            return JSONResponse(
                {"success": False, "error": "Unerwartetes API-Format."},
                status_code=502,
            )


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


def build_standalone_wizard_app(
    secret_store: SecretStore,
    port: int = 8090,
    compat_mode: bool = False,
    migration_marker: Path | None = None,
):
    """Baut die FastAPI-App fuer den Standalone-Setup-Wizard (ohne uvicorn).

    Phase 63: Der Standalone-Wizard muss dieselben Static-Assets liefern
    wie das eingebettete Dashboard (CSS/JS unter /static/*), sonst laeuft
    keine Interaktivitaet (Navigation, Tests, Geocoding, Completion). Die
    Security-Middleware setzt zusaetzlich die strikte CSP auch im Erst-
    Setup durch.
    """
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from elder_berry.web.security_middleware import setup_security

    app = FastAPI(title="Elder-Berry Setup-Wizard")
    app.state.standalone = True
    app.state.compat_mode = compat_mode
    app.state.migration_marker = migration_marker

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    setup_security(app, port, secret_store)

    register_setup_wizard_routes(app, secret_store)
    return app


def run_setup_wizard(
    secret_store: SecretStore,
    port: int = 8090,
    bind: str = "127.0.0.1",
    compat_mode: bool = False,
    migration_marker: Path | None = None,
) -> None:
    """Startet den Setup-Wizard als Standalone-Server (blockierend).

    Wird von start_saleria.py aufgerufen wenn kein Matrix-Token vorhanden ist.
    Beendet sich automatisch nach Abschluss des Setups.

    Parameters
    ----------
    bind
        Bind-Adresse (Phase 57.1, Default ``127.0.0.1``).
    compat_mode
        Phase 57.1a: Wenn True, rendert der Wizard ein gelbes Banner
        im UI, das auf den einmaligen LAN-Kompatibilitätsmodus hinweist.
    migration_marker
        Phase 57.1a: Pfad zur Marker-Datei. Wird nach Wizard-Abschluss
        geschrieben, damit die Grace-Period beim nächsten Start inaktiv ist.
    """
    import uvicorn

    app = build_standalone_wizard_app(
        secret_store,
        port=port,
        compat_mode=compat_mode,
        migration_marker=migration_marker,
    )
    logger.info("Setup-Wizard gestartet auf http://%s:%d/setup", bind, port)
    uvicorn.run(app, host=bind, port=port)
