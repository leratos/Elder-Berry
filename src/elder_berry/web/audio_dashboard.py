"""AudioDashboard – Minimales Web-UI zum Steuern des Audio-Routing-Modus,
der Monitor-Auswahl für Computer Use und der Allowed-Senders-Konfiguration.

Stellt eine FastAPI-App bereit mit:
- GET /             → HTML-Seite mit Audio-Toggle + Monitor-Dropdown + Sicherheit
- GET /api/audio    → aktueller Modus (JSON)
- POST /api/audio   → Modus setzen oder togglen (JSON)
- GET /api/monitors → verfügbare Monitore (JSON)
- POST /api/monitor → Monitor für Computer Use setzen (JSON)
- GET /api/allowed-senders  → Status (configured, count) – keine Klartext-IDs
- POST /api/allowed-senders → Sender setzen oder entfernen (JSON)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class AudioDashboard:
    """Web-Dashboard für Audio-Routing und Computer-Use-Monitor-Auswahl.

    Parameters
    ----------
    audio_router : AudioRouter
        Der gemeinsame AudioRouter (thread-safe).
    computer_use : ComputerUseController | None
        Optionaler ComputerUseController für Monitor-Auswahl.
    host : str
        Bind-Adresse (Default: 0.0.0.0).
    port : int
        Port (Default: 8090).
    """

    ALLOWED_SENDERS_KEY = "matrix_allowed_senders"

    def __init__(
        self,
        audio_router: AudioRouter,
        computer_use: ComputerUseController | None = None,
        secret_store: SecretStore | None = None,
        host: str = "0.0.0.0",
        port: int = 8090,
    ) -> None:
        self._router = audio_router
        self._computer_use = computer_use
        self._secret_store = secret_store
        self._host = host
        self._port = port
        self._app = FastAPI(title="Elder-Berry Settings Dashboard")
        self._thread = None
        self._register_routes()

    @property
    def app(self) -> FastAPI:
        """FastAPI-App-Instanz (für Tests oder externe Einbindung)."""
        return self._app

    def _register_routes(self) -> None:
        """Routen registrieren."""

        @self._app.get("/", response_class=HTMLResponse)
        async def dashboard():
            template_path = _TEMPLATE_DIR / "audio_dashboard.html"
            if template_path.exists():
                return HTMLResponse(template_path.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Template nicht gefunden</h1>", status_code=500)

        @self._app.get("/api/audio")
        async def get_audio_mode():
            return JSONResponse({
                "mode": self._router.mode.value,
                "local_available": self._router.local_available,
                "play_local": self._router.should_play_local(),
            })

        @self._app.post("/api/audio")
        async def set_audio_mode(body: dict | None = None):
            if body and "mode" in body:
                from elder_berry.core.audio_router import AudioOutputMode
                try:
                    mode = AudioOutputMode(body["mode"])
                except ValueError:
                    return JSONResponse(
                        {"error": f"Ungültiger Modus: {body['mode']}"},
                        status_code=400,
                    )
                new_mode = self._router.set_mode(mode)
            else:
                new_mode = self._router.toggle()

            logger.info("Audio-Modus geändert: %s", new_mode.value)
            return JSONResponse({
                "mode": new_mode.value,
                "local_available": self._router.local_available,
                "play_local": self._router.should_play_local(),
            })

        # ----------------------------------------------------------
        # Monitor-Auswahl (Computer Use)
        # ----------------------------------------------------------

        @self._app.get("/api/monitors")
        async def get_monitors():
            if not self._computer_use:
                return JSONResponse({
                    "available": False,
                    "monitors": [],
                    "selected": 1,
                })
            monitors = self._computer_use.get_available_monitors()
            return JSONResponse({
                "available": True,
                "monitors": monitors,
                "selected": self._computer_use.monitor_index,
            })

        @self._app.post("/api/monitor")
        async def set_monitor(body: dict | None = None):
            if not self._computer_use:
                return JSONResponse(
                    {"error": "Computer Use nicht verfügbar."},
                    status_code=400,
                )
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

            monitors = self._computer_use.get_available_monitors()
            valid_indices = {m["index"] for m in monitors}
            if index not in valid_indices:
                return JSONResponse(
                    {"error": f"Monitor {index} nicht verfügbar. "
                              f"Gültig: {sorted(valid_indices)}"},
                    status_code=400,
                )

            self._computer_use.monitor_index = index
            logger.info("Computer Use Monitor geändert: %d", index)
            return JSONResponse({
                "selected": index,
                "monitors": monitors,
            })

        # ----------------------------------------------------------
        # Allowed Senders (Matrix-Sicherheit)
        # ----------------------------------------------------------

        @self._app.get("/api/allowed-senders")
        async def get_allowed_senders():
            if not self._secret_store:
                return JSONResponse({
                    "available": False,
                    "configured": False,
                    "count": 0,
                })
            raw = self._secret_store.get_or_none(self.ALLOWED_SENDERS_KEY)
            if not raw:
                return JSONResponse({
                    "available": True,
                    "configured": False,
                    "count": 0,
                })
            senders = [s.strip() for s in raw.split(",") if s.strip()]
            return JSONResponse({
                "available": True,
                "configured": bool(senders),
                "count": len(senders),
            })

        @self._app.post("/api/allowed-senders")
        async def set_allowed_senders(body: dict | None = None):
            if not self._secret_store:
                return JSONResponse(
                    {"error": "SecretStore nicht verfügbar."},
                    status_code=400,
                )
            if not body:
                return JSONResponse(
                    {"error": "Request-Body fehlt."},
                    status_code=400,
                )

            # Entfernen-Aktion
            if body.get("action") == "remove":
                try:
                    self._secret_store.delete(self.ALLOWED_SENDERS_KEY)
                except Exception:
                    pass  # Key existiert nicht – OK
                logger.info("Allowed-Senders entfernt")
                return JSONResponse({
                    "configured": False,
                    "count": 0,
                })

            # Setzen-Aktion
            senders_raw = body.get("senders", "")
            if not isinstance(senders_raw, str) or not senders_raw.strip():
                return JSONResponse(
                    {"error": "Parameter 'senders' fehlt oder leer."},
                    status_code=400,
                )

            # Validierung: jede ID muss mit @ beginnen und : enthalten
            senders = [s.strip() for s in senders_raw.split(",") if s.strip()]
            invalid = [s for s in senders if not s.startswith("@") or ":" not in s]
            if invalid:
                return JSONResponse(
                    {"error": f"Ungültige Matrix-ID(s): {', '.join(invalid)}. "
                              "Format: @user:domain.com"},
                    status_code=400,
                )

            self._secret_store.set(
                self.ALLOWED_SENDERS_KEY,
                ",".join(senders),
            )
            logger.info("Allowed-Senders gesetzt: %d Sender", len(senders))
            return JSONResponse({
                "configured": True,
                "count": len(senders),
            })

    def _is_port_free(self) -> bool:
        """Prüft ob der Port frei ist."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((self._host, self._port))
                return True
            except OSError:
                return False

    def start(self) -> None:
        """Startet den Dashboard-Server in einem Hintergrund-Thread."""
        import threading
        import uvicorn

        if not self._is_port_free():
            logger.warning(
                "Settings-Dashboard: Port %d bereits belegt – übersprungen.",
                self._port,
            )
            return

        def _run():
            uvicorn.run(
                self._app,
                host=self._host,
                port=self._port,
                log_level="warning",
            )

        self._thread = threading.Thread(
            target=_run,
            name="settings-dashboard",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Settings-Dashboard gestartet: http://%s:%d", self._host, self._port,
        )

    def stop(self) -> None:
        """Stoppt den Server (Daemon-Thread endet mit Hauptprozess)."""
        self._thread = None
