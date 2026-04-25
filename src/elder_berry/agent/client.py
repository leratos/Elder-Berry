"""AgentClient – Tower-seitiger Client für die Laptop-Kommunikation."""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from elder_berry.agent.protocol import (
    ActionResult,
    AgentStatus,
    ApiResponse,
    HealthResponse,
)
from elder_berry.agent.server import AGENT_TOKEN_HEADER

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0
AUDIO_TIMEOUT = 30.0  # Audio-Upload kann länger dauern


class AgentClient:
    """
    HTTP-Client für die Kommunikation Tower → Laptop.

    Sendet Aktions-Befehle und Audio-Dateien an den AgentServer.
    Verwendet httpx (bereits als Core-Dependency vorhanden).

    Args:
        base_url: URL des AgentServers (z.B. "http://192.168.1.51:8001").
        timeout: Timeout für HTTP-Requests in Sekunden.
        agent_token: Optionaler Agent-Token für die Token-Auth. Wird als
            ``X-Saleria-Agent-Token``-Header bei jedem Request gesendet.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        timeout: float = DEFAULT_TIMEOUT,
        agent_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        headers = {}
        if agent_token:
            headers[AGENT_TOKEN_HEADER] = agent_token
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
        )
        logger.info("AgentClient verbunden: %s", self._base_url)

    def close(self) -> None:
        """Schließt die HTTP-Verbindung."""
        self._client.close()

    # --- Health ---

    def health(self) -> HealthResponse:
        """Prüft ob der Laptop-Agent erreichbar ist."""
        r = self._client.get("/health")
        r.raise_for_status()
        return HealthResponse(**r.json())

    def is_online(self) -> bool:
        """Gibt True zurück wenn der Laptop-Agent erreichbar ist."""
        try:
            resp = self.health()
            return resp.status == "ok"
        except (httpx.HTTPError, Exception):
            return False

    # --- Status ---

    def get_status(self) -> AgentStatus:
        """Holt den Gesamtstatus des Laptop-Agents."""
        r = self._client.get("/status")
        r.raise_for_status()
        return AgentStatus(**r.json())

    # --- Aktionen ---

    def execute_action(self, action_type: str, params: dict | None = None) -> ActionResult:
        """Sendet einen Aktionsbefehl an den Laptop-Agent."""
        r = self._client.post(
            "/action/execute",
            json={"action_type": action_type, "params": params or {}},
        )
        r.raise_for_status()
        return ActionResult(**r.json())

    # --- Audio ---

    def play_audio(
        self,
        wav_data: bytes,
        emotion: str = "neutral",
        filename: str = "tts_output.wav",
    ) -> ApiResponse:
        """
        Sendet WAV-Daten an den Laptop zur Wiedergabe (multipart Upload).

        Args:
            wav_data: Rohe WAV-Bytes.
            emotion: Emotion für Avatar-Sync auf dem Laptop.
            filename: Dateiname für den Upload.
        """
        r = self._client.post(
            "/audio/play",
            files={"file": (filename, wav_data, "audio/wav")},
            data={"emotion": emotion},
            timeout=AUDIO_TIMEOUT,
        )
        r.raise_for_status()
        return ApiResponse(**r.json())

    def play_audio_file(
        self,
        path: Path | str,
        emotion: str = "neutral",
    ) -> ApiResponse:
        """
        Sendet eine WAV-Datei an den Laptop zur Wiedergabe.

        Args:
            path: Pfad zur WAV-Datei.
            emotion: Emotion für Avatar-Sync.
        """
        path = Path(path)
        wav_data = path.read_bytes()
        return self.play_audio(wav_data, emotion=emotion, filename=path.name)
