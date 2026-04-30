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


ROBOT_TOKEN_HEADER = "X-Saleria-Robot-Token"


class RobotClient:
    """
    HTTP-Client für die Kommunikation Tower → RPi5.

    Sendet Befehle an den RobotServer und empfängt Status-Daten.
    Verwendet httpx (bereits als Core-Dependency vorhanden).

    Args:
        base_url: URL des RobotServers (z.B. "http://192.168.1.50:8000").
        timeout: Timeout für HTTP-Requests in Sekunden.
        robot_token: Phase 59 – Token für ``X-Saleria-Robot-Token`` Header.
            Ohne Token werden Requests ohne Auth-Header gesendet
            (kompatibel mit Token-freien Deployments).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = DEFAULT_TIMEOUT,
        robot_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        headers = {}
        if robot_token:
            headers[ROBOT_TOKEN_HEADER] = robot_token
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
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
            "/avatar/emotion",
            json={"is_speaking": is_speaking},
        )
        r.raise_for_status()
        return ApiResponse(**r.json())

    def set_avatar(
        self, emotion: str | None = None, is_speaking: bool | None = None
    ) -> ApiResponse:
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

    # --- Kamera ---

    def capture_image(self, quality: int = 85) -> bytes | None:
        """Nimmt ein Bild über die RPi5-Kamera auf.

        Args:
            quality: JPEG-Qualität (1-100).

        Returns:
            JPEG-Bytes oder None wenn Kamera nicht verfügbar.

        Raises:
            httpx.HTTPError: Bei Verbindungsproblemen.
        """
        r = self._client.get("/camera/capture", params={"quality": quality})
        r.raise_for_status()
        data = r.json()

        if not data.get("success"):
            logger.warning("Kamera: %s", data.get("message", "unbekannter Fehler"))
            return None

        import base64

        return base64.b64decode(data["image_base64"])

    def camera_status(self) -> dict:
        """Gibt den Kamera-Status vom RPi5 zurück."""
        r = self._client.get("/camera/status")
        r.raise_for_status()
        return r.json()

    # --- Drehteller ---

    def rotate_turntable(
        self,
        target_degrees: float | None = None,
        relative_degrees: float | None = None,
    ) -> ApiResponse:
        """Drehteller rotieren (absolut oder relativ)."""
        payload: dict = {}
        if target_degrees is not None:
            payload["target_degrees"] = target_degrees
        if relative_degrees is not None:
            payload["relative_degrees"] = relative_degrees
        r = self._client.post("/turntable/rotate", json=payload)
        r.raise_for_status()
        return ApiResponse(**r.json())

    def home_turntable(self) -> ApiResponse:
        """Homing-Sequenz des Drehtellers starten."""
        r = self._client.post("/turntable/home")
        r.raise_for_status()
        return ApiResponse(**r.json())

    def stop_turntable(self) -> ApiResponse:
        """Drehteller-Rotation sofort stoppen."""
        r = self._client.post("/turntable/stop")
        r.raise_for_status()
        return ApiResponse(**r.json())

    def turntable_status(self) -> dict:
        """Drehteller-Status abfragen."""
        r = self._client.get("/turntable/status")
        r.raise_for_status()
        return r.json()

    # --- Harmony Hub ---

    def harmony_status(self) -> dict:
        """GET /harmony/status → {"connected": bool, "current_activity": str|null}"""
        try:
            r = self._client.get("/harmony/status")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_status fehlgeschlagen: %s", e)
            return {"connected": False, "current_activity": None}

    def harmony_config(self) -> dict:
        """GET /harmony/config → {"activities": [...], "devices": [...]}"""
        try:
            r = self._client.get("/harmony/config")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_config fehlgeschlagen: %s", e)
            return {"activities": [], "devices": []}

    def harmony_config_detailed(self) -> dict:
        """GET /harmony/config/detailed → Devices mit ControlGroups + Commands."""
        try:
            r = self._client.get("/harmony/config/detailed")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_config_detailed fehlgeschlagen: %s", e)
            return {"activities": [], "devices": []}

    def harmony_layouts(self) -> dict:
        """GET /harmony/layouts → Fernbedienungs-Layouts."""
        try:
            r = self._client.get("/harmony/layouts")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_layouts fehlgeschlagen: %s", e)
            return {"activities": {}, "devices": {}}

    def harmony_save_layouts(self, layouts: dict) -> bool:
        """POST /harmony/layouts → Layouts speichern."""
        try:
            r = self._client.post("/harmony/layouts", json=layouts)
            r.raise_for_status()
            return r.json().get("success", False)
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_save_layouts fehlgeschlagen: %s", e)
            return False

    def harmony_start_activity(self, activity: str) -> bool:
        """POST /harmony/activity"""
        try:
            r = self._client.post(
                "/harmony/activity",
                json={"activity": activity},
            )
            r.raise_for_status()
            return r.json().get("success", False)
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_start_activity fehlgeschlagen: %s", e)
            return False

    def harmony_send_command(
        self,
        device: str,
        command: str,
        repeat: int = 1,
    ) -> bool:
        """POST /harmony/command"""
        try:
            r = self._client.post(
                "/harmony/command",
                json={"device": device, "command": command, "repeat": repeat},
            )
            r.raise_for_status()
            return r.json().get("success", False)
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_send_command fehlgeschlagen: %s", e)
            return False

    # --- Harmony Szenen ---

    def harmony_scenes(self) -> list[dict]:
        """GET /harmony/scenes → Liste aller Szenen."""
        try:
            r = self._client.get("/harmony/scenes")
            r.raise_for_status()
            return r.json().get("scenes", [])
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_scenes fehlgeschlagen: %s", e)
            return []

    def harmony_save_scene(self, scene: dict) -> bool:
        """POST /harmony/scenes → Szene erstellen/aktualisieren."""
        try:
            r = self._client.post("/harmony/scenes", json=scene)
            r.raise_for_status()
            return r.json().get("success", False)
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_save_scene fehlgeschlagen: %s", e)
            return False

    def harmony_start_scene(self, name: str) -> dict:
        """POST /harmony/scene/start → Szene starten."""
        try:
            r = self._client.post(
                "/harmony/scene/start",
                json={"name": name},
            )
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_start_scene fehlgeschlagen: %s", e)
            return {"success": False, "error": str(e)}

    def harmony_delete_scene(self, name: str) -> bool:
        """DELETE /harmony/scene/{name} → Szene löschen."""
        try:
            r = self._client.delete(f"/harmony/scene/{name}")
            r.raise_for_status()
            return r.json().get("success", False)
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_delete_scene fehlgeschlagen: %s", e)
            return False

    def harmony_power_off(self) -> bool:
        """POST /harmony/off"""
        try:
            r = self._client.post("/harmony/off")
            r.raise_for_status()
            return r.json().get("success", False)
        except (httpx.HTTPError, Exception) as e:
            logger.error("harmony_power_off fehlgeschlagen: %s", e)
            return False

    # --- System ---

    def update_rpi(self) -> ApiResponse:
        """RPi5 aktualisieren: git pull + pip install + systemctl restart."""
        r = self._client.post("/system/update", timeout=120.0)
        r.raise_for_status()
        return ApiResponse(**r.json())
