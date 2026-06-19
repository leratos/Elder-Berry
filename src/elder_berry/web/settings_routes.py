"""Core-Routen des Settings-Dashboards (Phase 106).

Ausgelagert aus ``SettingsDashboard._register_routes``: Audio-/Monitor-/
Allowed-Senders-/Timezone-/STT-Timeout-Endpoints, die HTML-Seiten und der
Health-Check. Die ``/api/settings/*``-Endpoints liegen in
``settings_api_routes.py``.

Wird von ``SettingsDashboard.__init__`` via ``register_core_routes(app, self)``
eingebunden. Wie ``secrets_api``/``llm_api`` wird ein lokales
``_DashboardLike``-Protocol verwendet statt ``SettingsDashboard`` zu
importieren – das vermeidet einen Modul-Zyklus (CodeQL ``py/cyclic-import``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import Response

from elder_berry.core.log_sanitize import safe_log
from elder_berry.core.secret_store import SecretNotFoundError

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class _DashboardLike(Protocol):
    """Strukturelles Subset von ``SettingsDashboard`` für die Core-Routen.

    Vermeidet einen Modul-Zyklus mit ``settings_dashboard``
    (CodeQL ``py/cyclic-import``).
    """

    _secret_store: Any
    _router: Any
    _tower_agent: Any
    _computer_use: Any
    _audio_pipeline: Any
    AVAILABLE_TIMEZONES: list[str]
    ALLOWED_SENDERS_KEY: str
    TIMEZONE_KEY: str
    STT_TIMEOUT_KEY: str

    def get_timezone(self) -> str: ...

    def _get_stt_timeout(self) -> float: ...


def register_core_routes(app: FastAPI, dashboard: _DashboardLike) -> None:
    """Registriert die Core-Endpoints (Audio/Monitor/Senders/TZ/STT/Health)."""

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_page() -> Response:
        # Redirect zum Setup-Wizard wenn Setup nicht abgeschlossen
        if dashboard._secret_store and not dashboard._secret_store.has(
            "setup_wizard_completed"
        ):
            from fastapi.responses import RedirectResponse

            return RedirectResponse(url="/setup", status_code=302)
        template_path = _TEMPLATE_DIR / "audio_dashboard.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Template nicht gefunden</h1>", status_code=500)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_panel() -> HTMLResponse:
        """Phase 52.1b: Unified Settings-Panel."""
        template_path = _TEMPLATE_DIR / "settings_panel.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            "<h1>settings_panel.html nicht gefunden</h1>", status_code=500
        )

    @app.get("/api/audio")
    async def get_audio_mode() -> JSONResponse:
        return JSONResponse(
            {
                "mode": dashboard._router.mode.value,
                "local_available": dashboard._router.local_available,
                "play_local": dashboard._router.should_play_local(),
            }
        )

    @app.post("/api/audio")
    async def set_audio_mode(body: dict[str, Any] | None = None) -> JSONResponse:
        if body and "mode" in body:
            from elder_berry.core.audio_router import AudioOutputMode

            try:
                mode = AudioOutputMode(body["mode"])
            except ValueError:
                return JSONResponse(
                    {"error": f"Ungültiger Modus: {body['mode']}"},
                    status_code=400,
                )
            new_mode = dashboard._router.set_mode(mode)
        else:
            new_mode = dashboard._router.toggle()

        logger.info("Audio-Modus geändert: %s", new_mode.value)
        return JSONResponse(
            {
                "mode": new_mode.value,
                "local_available": dashboard._router.local_available,
                "play_local": dashboard._router.should_play_local(),
            }
        )

    # --- Monitor-Auswahl (Computer Use) ---

    @app.get("/api/monitors")
    async def get_monitors() -> JSONResponse:
        if dashboard._tower_agent:
            try:
                data = await dashboard._tower_agent.get_monitors()
                return JSONResponse(data)
            except Exception as e:
                logger.warning("Tower Monitor-Abfrage fehlgeschlagen: %s", e)
                return JSONResponse(
                    {
                        "available": False,
                        "monitors": [],
                        "selected": 1,
                        "error": "Tower nicht erreichbar",
                    }
                )
        if not dashboard._computer_use:
            return JSONResponse(
                {
                    "available": False,
                    "monitors": [],
                    "selected": 1,
                }
            )
        monitors = dashboard._computer_use.get_available_monitors()
        return JSONResponse(
            {
                "available": True,
                "monitors": monitors,
                "selected": dashboard._computer_use.monitor_index,
            }
        )

    @app.post("/api/monitor")
    async def set_monitor(body: dict[str, Any] | None = None) -> JSONResponse:
        if not body or "index" not in body:
            return JSONResponse(
                {"error": "Parameter 'index' fehlt."},
                status_code=400,
            )
        try:
            index = int(body["index"])
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": "Ungültiger Monitor-Index."},
                status_code=400,
            )

        if dashboard._tower_agent:
            try:
                data = await dashboard._tower_agent.set_monitor(index)
                logger.info("Tower Monitor geändert: %d", index)
                return JSONResponse(data)
            except Exception:
                logger.exception("Tower Monitor-Setzen fehlgeschlagen")
                return JSONResponse(
                    {"error": "Tower nicht erreichbar."},
                    status_code=502,
                )

        if not dashboard._computer_use:
            return JSONResponse(
                {"error": "Computer Use nicht verfügbar."},
                status_code=400,
            )

        monitors = dashboard._computer_use.get_available_monitors()
        valid_indices = {m["index"] for m in monitors}
        if index not in valid_indices:
            return JSONResponse(
                {
                    "error": f"Monitor {index} nicht verfügbar. "
                    f"Gültig: {sorted(valid_indices)}"
                },
                status_code=400,
            )

        dashboard._computer_use.monitor_index = index
        logger.info("Computer Use Monitor geändert: %d", index)
        return JSONResponse(
            {
                "selected": index,
                "monitors": monitors,
            }
        )

    # --- Allowed Senders (Matrix-Sicherheit) ---

    @app.get("/api/allowed-senders")
    async def get_allowed_senders() -> JSONResponse:
        if not dashboard._secret_store:
            return JSONResponse(
                {
                    "available": False,
                    "configured": False,
                    "count": 0,
                }
            )
        raw = dashboard._secret_store.get_or_none(dashboard.ALLOWED_SENDERS_KEY)
        if not raw:
            return JSONResponse(
                {
                    "available": True,
                    "configured": False,
                    "count": 0,
                }
            )
        senders = [s.strip() for s in raw.split(",") if s.strip()]
        return JSONResponse(
            {
                "available": True,
                "configured": bool(senders),
                "count": len(senders),
            }
        )

    @app.post("/api/allowed-senders")
    async def set_allowed_senders(
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        if not dashboard._secret_store:
            return JSONResponse(
                {"error": "SecretStore nicht verfügbar."},
                status_code=400,
            )
        if not body:
            return JSONResponse(
                {"error": "Request-Body fehlt."},
                status_code=400,
            )

        if body.get("action") == "remove":
            try:
                dashboard._secret_store.delete(dashboard.ALLOWED_SENDERS_KEY)
            except SecretNotFoundError:
                # Idempotent: Allowed-Senders-Key kann bereits fehlen.
                pass
            logger.info("Allowed-Senders entfernt")
            return JSONResponse(
                {
                    "configured": False,
                    "count": 0,
                }
            )

        senders_raw = body.get("senders", "")
        if not isinstance(senders_raw, str) or not senders_raw.strip():
            return JSONResponse(
                {"error": "Parameter 'senders' fehlt oder leer."},
                status_code=400,
            )

        senders = [s.strip() for s in senders_raw.split(",") if s.strip()]
        invalid = [s for s in senders if not s.startswith("@") or ":" not in s]
        if invalid:
            return JSONResponse(
                {
                    "error": f"Ungültige Matrix-ID(s): {', '.join(invalid)}. "
                    "Format: @user:domain.com"
                },
                status_code=400,
            )

        dashboard._secret_store.set(
            dashboard.ALLOWED_SENDERS_KEY,
            ",".join(senders),
        )
        logger.info("Allowed-Senders gesetzt: %d Sender", len(senders))
        return JSONResponse(
            {
                "configured": True,
                "count": len(senders),
            }
        )

    # --- Timezone ---

    @app.get("/api/timezone")
    async def get_timezone() -> JSONResponse:
        tz = dashboard.get_timezone()
        return JSONResponse(
            {
                "timezone": tz,
                "available": sorted(dashboard.AVAILABLE_TIMEZONES),
            }
        )

    @app.post("/api/timezone")
    async def set_timezone(body: dict[str, Any] | None = None) -> JSONResponse:
        if not dashboard._secret_store:
            return JSONResponse(
                {"error": "SecretStore nicht verfügbar."},
                status_code=400,
            )
        if not body or "timezone" not in body:
            return JSONResponse(
                {"error": "Parameter 'timezone' fehlt."},
                status_code=400,
            )
        tz_name = body["timezone"]

        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz_name)
        except (KeyError, Exception):
            return JSONResponse(
                {"error": f"Ungültige Zeitzone: {tz_name}"},
                status_code=400,
            )

        dashboard._secret_store.set(dashboard.TIMEZONE_KEY, tz_name)
        logger.info("Zeitzone geändert: %s", safe_log(tz_name))
        return JSONResponse(
            {
                "timezone": tz_name,
                "available": sorted(dashboard.AVAILABLE_TIMEZONES),
            }
        )

    # --- STT-Timeout ---

    @app.get("/api/stt-timeout")
    async def get_stt_timeout() -> JSONResponse:
        timeout = dashboard._get_stt_timeout()
        return JSONResponse(
            {
                "timeout": timeout,
                "available": dashboard._audio_pipeline is not None,
            }
        )

    @app.post("/api/stt-timeout")
    async def set_stt_timeout(body: dict[str, Any] | None = None) -> JSONResponse:
        if not body or "timeout" not in body:
            return JSONResponse(
                {"error": "Parameter 'timeout' fehlt."},
                status_code=400,
            )
        try:
            timeout = float(body["timeout"])
            if not (5.0 <= timeout <= 600.0):
                raise ValueError("Out of range")
        except (ValueError, TypeError):
            return JSONResponse(
                {
                    "error": f"Ungültiger Timeout: {body['timeout']}. "
                    "Erlaubt: 5–600 Sekunden."
                },
                status_code=400,
            )

        if dashboard._audio_pipeline is not None:
            dashboard._audio_pipeline.stt_timeout = timeout

        if dashboard._secret_store:
            dashboard._secret_store.set(dashboard.STT_TIMEOUT_KEY, str(timeout))

        logger.info("STT-Timeout geändert: %.0fs", timeout)
        return JSONResponse(
            {
                "timeout": timeout,
                "available": dashboard._audio_pipeline is not None,
            }
        )

    # --- Health ---

    @app.get("/health")
    async def health() -> JSONResponse:
        import platform

        return JSONResponse(
            {
                "status": "ok",
                "hostname": platform.node(),
                "saleria_running": True,
            }
        )
