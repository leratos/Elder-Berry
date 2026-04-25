"""AgentServer – FastAPI-Server für den Laptop (Client-Tier).

Empfängt Befehle vom Tower und führt sie lokal aus:
- PC-Aktionen (Tastatur, Maus, Fenster, Lautstärke) via ActionController
- Audio-Playback (WAV-Dateien vom Tower, via multipart Upload)
- Health / Status

Authentifizierung: Optionaler statischer Token via ``ELDER_BERRY_AGENT_TOKEN``
Env-Var oder Konstruktor-Parameter ``agent_token``. Wenn gesetzt, verlangt der
Server den Header ``X-Saleria-Agent-Token`` bei jedem Request. Ohne Token:
keine Auth (Backwards-Compat / Tests), aber Startup-Warning.

Plattformhinweis: Läuft auf Windows (Laptop).
"""
from __future__ import annotations

import io
import logging
import platform
import secrets as _secrets
import time
from dataclasses import asdict

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from elder_berry.actions.base import ActionController
from elder_berry.agent.protocol import (
    ActionResult,
    AgentStatus,
    ApiResponse,
    HealthResponse,
)
from elder_berry.web.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent-Token-Auth (Phase Security-Fix)
# ---------------------------------------------------------------------------

AGENT_TOKEN_HEADER = "X-Saleria-Agent-Token"

# Rate-Limit für fehlgeschlagene Agent-Token-Versuche: 10 / 1 min → 10 min Lockout.
_agent_token_limiter = RateLimiter(
    max_attempts=10,
    window_seconds=60,
    lockout_seconds=600,
    name="agent_token",
)


class AgentTokenMiddleware(BaseHTTPMiddleware):
    """Schützt alle AgentServer-Endpoints mit ``X-Saleria-Agent-Token``.

    Wenn kein Token konfiguriert ist (``None``), wird die Middleware
    übersprungen (Backwards-Compat für Tests und Token-freie Deployments).
    """

    def __init__(self, app, agent_token: str | None) -> None:
        super().__init__(app)
        self._token = agent_token

    async def dispatch(self, request: Request, call_next):
        if not self._token:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        token = request.headers.get(AGENT_TOKEN_HEADER)
        if not token or not _secrets.compare_digest(token, self._token):
            allowed = await _agent_token_limiter.check_and_record(client_ip)
            if not allowed:
                return JSONResponse(
                    {
                        "error": "Zu viele fehlgeschlagene Versuche. Temporär gesperrt.",
                        "header": AGENT_TOKEN_HEADER,
                    },
                    status_code=429,
                )
            return JSONResponse(
                {
                    "error": "Agent-Token erforderlich oder ungültig.",
                    "header": AGENT_TOKEN_HEADER,
                },
                status_code=401,
            )
        await _agent_token_limiter.reset(client_ip)
        return await call_next(request)


# Alle Aktionen die der ActionController unterstützt
SUPPORTED_ACTIONS = [
    "press_key", "type_text", "hotkey",
    "move_mouse", "click",
    "list_windows", "focus_window", "minimize_window", "maximize_window",
    "get_volume", "set_volume", "mute",
]


# ---------------------------------------------------------------------------
# Pydantic Models (FastAPI Request-Validierung)
# ---------------------------------------------------------------------------

class ActionRequestModel(BaseModel):
    """Request: Aktion ausführen."""
    action_type: str
    params: dict = {}


# ---------------------------------------------------------------------------
# Server-Klasse
# ---------------------------------------------------------------------------

class AgentServer:
    """
    FastAPI-basierter Server für die Tower → Laptop Kommunikation.

    Der ActionController wird per DI übergeben (Konstruktor).
    Audio-Playback nutzt sounddevice + numpy.

    Parameters
    ----------
    agent_token : str | None
        Wenn gesetzt, verlangt der Server den Header
        ``X-Saleria-Agent-Token`` bei jedem Request. Ohne Token:
        keine Auth (Backwards-Compat für Tests). Kann über die
        Env-Var ``ELDER_BERRY_AGENT_TOKEN`` konfiguriert werden.
    """

    def __init__(
        self,
        controller: ActionController,
        hostname: str | None = None,
        agent_token: str | None = None,
    ) -> None:
        self._controller = controller
        self._hostname = hostname or platform.node()
        self._start_time = time.monotonic()

        self.app = FastAPI(title="Elder-Berry Agent API", version="0.1.0")
        self.app.add_middleware(AgentTokenMiddleware, agent_token=agent_token)
        self._register_routes()

        if not agent_token:
            logger.warning(
                "AgentServer: kein agent_token konfiguriert – "
                "alle Endpoints sind ohne Authentifizierung erreichbar. "
                "Für Produktionsbetrieb ELDER_BERRY_AGENT_TOKEN setzen."
            )

        logger.info("AgentServer initialisiert: %s", self._hostname)

    def _register_routes(self) -> None:
        """Registriert alle API-Endpoints."""

        @self.app.get("/health")
        def health() -> dict:
            uptime = time.monotonic() - self._start_time
            resp = HealthResponse(
                status="ok",
                hostname=self._hostname,
                uptime=round(uptime, 1),
            )
            return asdict(resp)

        @self.app.get("/status")
        def status() -> dict:
            uptime = time.monotonic() - self._start_time
            agent_status = AgentStatus(
                online=True,
                hostname=self._hostname,
                uptime=round(uptime, 1),
                available_actions=list(SUPPORTED_ACTIONS),
            )
            return asdict(agent_status)

        @self.app.post("/action/execute")
        def execute_action(request: ActionRequestModel) -> dict:
            result = self._execute(request.action_type, request.params)
            return asdict(result)

        @self.app.post("/audio/play")
        async def play_audio(
            file: UploadFile = File(...),
            emotion: str = Form("neutral"),
        ) -> dict:
            try:
                wav_bytes = await file.read()
                self._play_wav(wav_bytes)
                resp = ApiResponse(
                    success=True,
                    message=f"Audio abgespielt ({len(wav_bytes)} bytes, emotion={emotion})",
                )
            except Exception as e:
                logger.error("Audio-Playback fehlgeschlagen: %s", e)
                resp = ApiResponse(success=False, message="Audio-Fehler – Details im Log.")
            return asdict(resp)

    def _execute(self, action_type: str, params: dict) -> ActionResult:
        """Führt eine Aktion über den ActionController aus."""
        if action_type not in SUPPORTED_ACTIONS:
            return ActionResult(
                success=False,
                action_type=action_type,
                message=f"Unbekannte Aktion: {action_type}",
            )

        try:
            result = self._dispatch(action_type, params)
            return ActionResult(
                success=True,
                action_type=action_type,
                message="OK",
                return_value=result,
            )
        except (KeyError, TypeError) as e:
            logger.error("Aktion '%s' – fehlende Parameter: %s", action_type, e)
            return ActionResult(
                success=False,
                action_type=action_type,
                message=f"Fehlende Parameter: {e}",
            )
        except Exception as e:
            logger.error("Aktion '%s' fehlgeschlagen: %s", action_type, e)
            return ActionResult(
                success=False,
                action_type=action_type,
                message=str(e),
            )

    def _dispatch(self, action_type: str, params: dict):
        """Dispatcht Aktion an die richtige ActionController-Methode."""
        match action_type:
            case "press_key":
                self._controller.press_key(params["key"])
            case "type_text":
                self._controller.type_text(
                    params["text"], interval=params.get("interval", 0.02),
                )
            case "hotkey":
                self._controller.hotkey(*params["keys"])
            case "move_mouse":
                self._controller.move_mouse(
                    params["x"], params["y"],
                    duration=params.get("duration", 0.25),
                )
            case "click":
                self._controller.click(
                    x=params.get("x"), y=params.get("y"),
                    button=params.get("button", "left"),
                )
            case "list_windows":
                windows = self._controller.list_windows()
                return [{"title": w.title, "handle": w.handle} for w in windows]
            case "focus_window":
                return self._controller.focus_window(params["title"])
            case "minimize_window":
                return self._controller.minimize_window(params["title"])
            case "maximize_window":
                return self._controller.maximize_window(params["title"])
            case "get_volume":
                return self._controller.get_volume()
            case "set_volume":
                self._controller.set_volume(params["level"])
            case "mute":
                self._controller.mute(params.get("state", True))
        return None

    @staticmethod
    def _play_wav(wav_bytes: bytes) -> None:
        """Spielt WAV-Daten ab (sounddevice + numpy, lazy import)."""
        import wave

        import numpy as np
        import sounddevice as sd

        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw_data = wf.readframes(wf.getnframes())

        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        dtype = dtype_map.get(sample_width, np.int16)
        audio = np.frombuffer(raw_data, dtype=dtype)

        if n_channels > 1:
            audio = audio.reshape(-1, n_channels)

        # Normalisieren auf float32 [-1.0, 1.0]
        max_val = np.iinfo(dtype).max
        audio_float = audio.astype(np.float32) / max_val

        sd.play(audio_float, samplerate=sample_rate)
        sd.wait()
