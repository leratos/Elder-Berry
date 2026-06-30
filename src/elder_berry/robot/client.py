"""RobotClient – Tower-seitiger Client für die RPi5-Kommunikation."""

from __future__ import annotations

import logging
from typing import Any, Literal, cast

import httpx

from elder_berry.character.emotion_resolver import EmotionDecision
from elder_berry.core.audio_analyzer import AmplitudeTrack
from elder_berry.robot.protocol import (
    ApiResponse,
    BatteryStatus,
    HealthResponse,
    RobotStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0


ROBOT_TOKEN_HEADER = "X-Saleria-Robot-Token"


def _add_amplitude(payload: dict[str, Any], audio_meta: AmplitudeTrack | None) -> None:
    """Hängt das Amplitude-Profil additiv an das ``/avatar/emotion``-Payload.

    No-op, wenn kein nutzbarer Track vorliegt (→ RandomLipSyncDriver, §4.4).
    """
    if audio_meta is not None and not audio_meta.is_empty():
        payload["amplitude"] = audio_meta.samples
        payload["amplitude_duration_ms"] = audio_meta.duration_ms


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

    def probe(self) -> Literal["ok", "auth", "rate_limited", "unreachable"]:
        """Klassifiziert die Erreichbarkeit des RPi5-Servers (Phase 96).

        Trennt Auth-Fehler (401/403) und Rate-Limit (429) von echten
        Netz-/Transportfehlern, damit der Aufrufer eine differenzierte Meldung
        ausgeben kann. Härtung gegen non-200/non-JSON-Antworten (z.B. 502 mit
        nginx-/Tunnel-HTML): ein ``JSONDecodeError`` ist **kein**
        ``httpx.HTTPError`` und würde sonst ungefangen durchschlagen.

        Returns:
            ``"ok"`` – ``/health`` liefert 200 mit ``{"status": "ok"}``.
            ``"auth"`` – 401/403 (Token fehlt/ungültig).
            ``"rate_limited"`` – 429 (Lockout der RobotTokenMiddleware).
            ``"unreachable"`` – ConnError/Timeout, anderer Status-Code, oder
            unlesbarer/abweichender Body.
        """
        try:
            r = self._client.get("/health")
        except httpx.HTTPError:
            return "unreachable"
        if r.status_code in (401, 403):
            return "auth"
        if r.status_code == 429:
            return "rate_limited"
        if r.status_code != 200:
            return "unreachable"
        try:
            data = r.json()
        except ValueError:
            return "unreachable"
        # 200 mit gueltigem aber Nicht-Objekt-JSON (z.B. [] oder null von einem
        # fehlkonfigurierten Proxy) darf nicht via data.get() durchschlagen –
        # is_online() faengt seit Phase 96 nicht mehr breit ab.
        if not isinstance(data, dict):
            return "unreachable"
        return "ok" if data.get("status") == "ok" else "unreachable"

    def is_online(self) -> bool:
        """Gibt True zurück wenn der RPi5-Server erreichbar ist.

        Phase 96: zurückgeführt auf :meth:`probe`. Backwards-kompatibel als
        ``bool``; nur ``probe() == "ok"`` gilt als online. Nicht-``httpx``-Fehler
        (z.B. Programmierfehler) werden bewusst NICHT mehr verschluckt.
        """
        return self.probe() == "ok"

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

    def set_emotion(
        self, emotion: str, decision: EmotionDecision | None = None
    ) -> ApiResponse:
        """Setzt die Avatar-Emotion auf dem RPi5-Display.

        Phase 83.5/108/110: ``decision`` (Resolver-Entscheidung) wird additiv
        mitgesendet. ``confidence`` steuert das StateMachine-Gate (Phase 108),
        ``intensity`` die Anzeige-Tiefe/den Blend (Phase 110). Ohne ``decision``
        bleibt das Payload rückwärtskompatibel (String-only → voll/opak).
        """
        payload: dict[str, Any] = {"emotion": emotion}
        if decision is not None:
            payload["decision"] = {
                "emotion": decision.emotion.value,
                "confidence": decision.confidence,
                "source": decision.source,
                "intensity": decision.intensity,  # Phase 110: Anzeige-Tiefe
            }
        r = self._client.post("/avatar/emotion", json=payload)
        r.raise_for_status()
        return ApiResponse(**r.json())

    def set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> ApiResponse:
        """Aktiviert/deaktiviert Lip-Sync auf dem RPi5-Display.

        Phase 83.4: ``audio_meta`` (nur Playback-Modus) wird additiv als
        ``amplitude``/``amplitude_duration_ms`` mitgesendet, sodass der RPi5 den
        AmplitudeLipSyncDriver nutzt; ohne Track → RandomLipSyncDriver (§4.4).
        """
        payload: dict[str, Any] = {"is_speaking": is_speaking}
        _add_amplitude(payload, audio_meta)
        r = self._client.post("/avatar/emotion", json=payload)
        r.raise_for_status()
        return ApiResponse(**r.json())

    def set_avatar(
        self,
        emotion: str | None = None,
        is_speaking: bool | None = None,
        audio_meta: AmplitudeTrack | None = None,
    ) -> ApiResponse:
        """Setzt Emotion und Sprechzustand (optional mit Amplitude-Profil)."""
        payload: dict[str, Any] = {}
        if emotion is not None:
            payload["emotion"] = emotion
        if is_speaking is not None:
            payload["is_speaking"] = is_speaking
        _add_amplitude(payload, audio_meta)

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

    def get_sensors(self) -> dict[str, Any]:
        """Holt alle Sensor-Daten."""
        r = self._client.get("/sensor/all")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

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

    def camera_status(self) -> dict[str, Any]:
        """Gibt den Kamera-Status vom RPi5 zurück."""
        r = self._client.get("/camera/status")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    # --- Drehteller ---

    def rotate_turntable(
        self,
        target_degrees: float | None = None,
        relative_degrees: float | None = None,
    ) -> ApiResponse:
        """Drehteller rotieren (absolut oder relativ)."""
        payload: dict[str, Any] = {}
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

    def turntable_status(self) -> dict[str, Any]:
        """Drehteller-Status abfragen."""
        r = self._client.get("/turntable/status")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    # --- Harmony Hub ---

    def harmony_status(self) -> dict[str, Any]:
        """GET /harmony/status → {"connected": bool, "current_activity": str|null}

        Phase 96: HTTP-/Transportfehler werden NICHT mehr verschluckt, sondern
        an den Aufrufer (Command-Handler) durchgereicht, damit 401 (Auth) von
        ConnError (Netz) unterscheidbar bleibt. Gilt für alle ``harmony_*``.
        """
        r = self._client.get("/harmony/status")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    def harmony_config(self) -> dict[str, Any]:
        """GET /harmony/config → {"activities": [...], "devices": [...]}"""
        r = self._client.get("/harmony/config")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    def harmony_config_detailed(self) -> dict[str, Any]:
        """GET /harmony/config/detailed → Devices mit ControlGroups + Commands."""
        r = self._client.get("/harmony/config/detailed")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    def harmony_layouts(self) -> dict[str, Any]:
        """GET /harmony/layouts → Fernbedienungs-Layouts."""
        r = self._client.get("/harmony/layouts")
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    def harmony_save_layouts(self, layouts: dict[str, Any]) -> bool:
        """POST /harmony/layouts → Layouts speichern."""
        r = self._client.post("/harmony/layouts", json=layouts)
        r.raise_for_status()
        return cast(bool, r.json().get("success", False))

    def harmony_start_activity(self, activity: str) -> bool:
        """POST /harmony/activity"""
        r = self._client.post(
            "/harmony/activity",
            json={"activity": activity},
        )
        r.raise_for_status()
        return cast(bool, r.json().get("success", False))

    def harmony_send_command(
        self,
        device: str,
        command: str,
        repeat: int = 1,
    ) -> bool:
        """POST /harmony/command"""
        r = self._client.post(
            "/harmony/command",
            json={"device": device, "command": command, "repeat": repeat},
        )
        r.raise_for_status()
        return cast(bool, r.json().get("success", False))

    # --- Harmony Szenen ---

    def harmony_scenes(self) -> list[dict[str, Any]]:
        """GET /harmony/scenes → Liste aller Szenen."""
        r = self._client.get("/harmony/scenes")
        r.raise_for_status()
        return cast(list[dict[str, Any]], r.json().get("scenes", []))

    def harmony_save_scene(self, scene: dict[str, Any]) -> bool:
        """POST /harmony/scenes → Szene erstellen/aktualisieren."""
        r = self._client.post("/harmony/scenes", json=scene)
        r.raise_for_status()
        return cast(bool, r.json().get("success", False))

    def harmony_start_scene(self, name: str) -> dict[str, Any]:
        """POST /harmony/scene/start → Szene starten."""
        r = self._client.post(
            "/harmony/scene/start",
            json={"name": name},
        )
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    def harmony_delete_scene(self, name: str) -> bool:
        """DELETE /harmony/scene/{name} → Szene löschen."""
        r = self._client.delete(f"/harmony/scene/{name}")
        r.raise_for_status()
        return cast(bool, r.json().get("success", False))

    def harmony_power_off(self) -> bool:
        """POST /harmony/off"""
        r = self._client.post("/harmony/off")
        r.raise_for_status()
        return cast(bool, r.json().get("success", False))

    # --- System ---

    def update_rpi(self) -> ApiResponse:
        """RPi5 aktualisieren: git pull + pip install + systemctl restart."""
        r = self._client.post("/system/update", timeout=120.0)
        r.raise_for_status()
        return ApiResponse(**r.json())
