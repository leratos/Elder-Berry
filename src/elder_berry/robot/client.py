"""RobotClient – Tower-seitiger Client für die RPi5-Kommunikation."""
from __future__ import annotations

import logging

import httpx

from elder_berry.robot.protocol import (
    ApiResponse,
    BatteryStatus,
    HealthResponse,
    RobotStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0


class RobotClient:
    """
    HTTP-Client für die Kommunikation Tower → RPi5.

    Sendet Befehle an den RobotServer und empfängt Status-Daten.
    Verwendet httpx (bereits als Core-Dependency vorhanden).

    Args:
        base_url: URL des RobotServers (z.B. "http://192.168.1.50:8000").
        timeout: Timeout für HTTP-Requests in Sekunden.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
        )
        logger.info("RobotClient verbunden: %s", self._base_url)

    def close(self) -> None:
        """Schließt die HTTP-Verbindung."""
        self._client.close()

    # --- Health ---

    def health(self) -> HealthResponse:
        """Prüft ob der RPi5-Server erreichbar ist."""
        r = self._client.get("/health")
        r.raise_for_status()
        data = r.json()
        return HealthResponse(**data)

    def is_online(self) -> bool:
        """Gibt True zurück wenn der RPi5-Server erreichbar ist."""
        try:
            resp = self.health()
            return resp.status == "ok"
        except (httpx.HTTPError, Exception):
            return False

    # --- Status ---

    def get_status(self) -> RobotStatus:
        """Holt den Gesamtstatus des Roboters."""
        r = self._client.get("/status")
        r.raise_for_status()
        data = r.json()
        battery_data = data.pop("battery", {})
        data["battery"] = BatteryStatus(**battery_data)
        return RobotStatus(**data)

    # --- Avatar ---

    def set_emotion(self, emotion: str) -> ApiResponse:
        """Setzt die Avatar-Emotion auf dem RPi5-Display."""
        r = self._client.post("/avatar/emotion", json={"emotion": emotion})
        r.raise_for_status()
        return ApiResponse(**r.json())

    def set_speaking(self, is_speaking: bool) -> ApiResponse:
        """Aktiviert/deaktiviert Lip-Sync auf dem RPi5-Display."""
        r = self._client.post(
            "/avatar/emotion", json={"is_speaking": is_speaking},
        )
        r.raise_for_status()
        return ApiResponse(**r.json())

    def set_avatar(self, emotion: str | None = None,
                   is_speaking: bool | None = None) -> ApiResponse:
        """Setzt Emotion und Sprechzustand gleichzeitig."""
        payload = {}
        if emotion is not None:
            payload["emotion"] = emotion
        if is_speaking is not None:
            payload["is_speaking"] = is_speaking

        r = self._client.post("/avatar/emotion", json=payload)
        r.raise_for_status()
        return ApiResponse(**r.json())

    # --- Motoren ---

    def drive(self, direction: str, speed: float = 0.5) -> ApiResponse:
        """Sendet Fahrbefehl an den Roboter."""
        r = self._client.post(
            "/motor/drive",
            json={"direction": direction, "speed": speed},
        )
        r.raise_for_status()
        return ApiResponse(**r.json())

    def stop(self, reason: str = "manual") -> ApiResponse:
        """Notfall-Stopp aller Motoren."""
        r = self._client.post("/motor/stop", json={"reason": reason})
        r.raise_for_status()
        return ApiResponse(**r.json())

    # --- Sensoren ---

    def get_battery(self) -> BatteryStatus:
        """Holt den Akku-Status."""
        r = self._client.get("/sensor/battery")
        r.raise_for_status()
        return BatteryStatus(**r.json())

    def get_sensors(self) -> dict:
        """Holt alle Sensor-Daten."""
        r = self._client.get("/sensor/all")
        r.raise_for_status()
        return r.json()
