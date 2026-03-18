"""AudioDashboard – Minimales Web-UI zum Steuern des Audio-Routing-Modus.

Stellt eine FastAPI-App bereit mit:
- GET /          → HTML-Seite mit Toggle
- GET /api/audio → aktueller Modus (JSON)
- POST /api/audio → Modus setzen oder togglen (JSON)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from elder_berry.core.audio_router import AudioRouter

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class AudioDashboard:
    """Web-Dashboard für Audio-Routing-Steuerung.

    Parameters
    ----------
    audio_router : AudioRouter
        Der gemeinsame AudioRouter (thread-safe).
    host : str
        Bind-Adresse (Default: 0.0.0.0).
    port : int
        Port (Default: 8090).
    """

    def __init__(
        self,
        audio_router: AudioRouter,
        host: str = "0.0.0.0",
        port: int = 8090,
    ) -> None:
        self._router = audio_router
        self._host = host
        self._port = port
        self._app = FastAPI(title="Elder-Berry Audio Dashboard")
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

    def start(self) -> None:
        """Startet den Dashboard-Server in einem Hintergrund-Thread."""
        import threading
        import uvicorn

        def _run():
            uvicorn.run(
                self._app,
                host=self._host,
                port=self._port,
                log_level="warning",
            )

        self._thread = threading.Thread(
            target=_run,
            name="audio-dashboard",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "AudioDashboard gestartet: http://%s:%d", self._host, self._port,
        )

    def stop(self) -> None:
        """Stoppt den Server (Daemon-Thread endet mit Hauptprozess)."""
        self._thread = None
