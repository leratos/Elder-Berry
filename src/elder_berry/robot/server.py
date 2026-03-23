"""RobotServer – FastAPI-Server für den RPi5 (oder Simulator).

Stellt REST-Endpoints bereit über die der Tower den Roboter steuert:
- Avatar (Emotion, Lip-Sync)
- Motoren (Fahrbefehle, Stopp)
- Sensoren (Akku, Temperatur)
- Health (Heartbeat)

Plattformhinweis: Läuft auf RPi5 (Linux) und Windows (Simulator).
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel

from elder_berry.robot.camera_controller import CameraController
from elder_berry.robot.turntable_controller import TurntableController
from elder_berry.robot.protocol import (
    ApiResponse,
    BatteryStatus,
    HealthResponse,
    RobotStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Models (für FastAPI Request-Validierung)
# ---------------------------------------------------------------------------

class AvatarRequest(BaseModel):
    """Request: Emotion und/oder Sprechzustand setzen."""
    emotion: str | None = None
    is_speaking: bool | None = None


class DriveRequest(BaseModel):
    """Request: Fahrbefehl."""
    direction: str
    speed: float = 0.5
    duration: float | None = None


class StopRequest(BaseModel):
    """Request: Notfall-Stopp."""
    reason: str = "manual"


class TurntableRotateRequest(BaseModel):
    """Request: Drehteller rotieren."""
    target_degrees: float | None = None    # Absolute Position
    relative_degrees: float | None = None  # Relative Rotation


# ---------------------------------------------------------------------------
# Hardware-Abstraktionen (werden vom Simulator oder echten RPi implementiert)
# ---------------------------------------------------------------------------

class MotorController(ABC):
    """ABC für Motorsteuerung."""

    @abstractmethod
    def drive(self, direction: str, speed: float) -> None:
        """Fährt in die angegebene Richtung."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stoppt alle Motoren."""
        ...

    @abstractmethod
    def get_state(self) -> dict:
        """Gibt aktuellen Motor-Zustand zurück."""
        ...


class AvatarDisplay(ABC):
    """ABC für Avatar-Anzeige auf dem RPi5-Display."""

    @abstractmethod
    def set_emotion(self, emotion: str) -> None:
        """Setzt die angezeigte Emotion."""
        ...

    @abstractmethod
    def set_speaking(self, is_speaking: bool) -> None:
        """Aktiviert/deaktiviert Lip-Sync."""
        ...

    @abstractmethod
    def get_state(self) -> dict:
        """Gibt aktuellen Avatar-Zustand zurück."""
        ...


class SensorManager(ABC):
    """ABC für Sensor-Abfragen."""

    @abstractmethod
    def get_battery(self) -> BatteryStatus:
        """Liest Akku-Status."""
        ...

    @abstractmethod
    def get_all(self) -> dict:
        """Liest alle Sensoren."""
        ...


# ---------------------------------------------------------------------------
# Server-Klasse
# ---------------------------------------------------------------------------

class RobotServer:
    """
    FastAPI-basierter Server für die Tower ↔ RPi5 Kommunikation.

    Alle Hardware-Abhängigkeiten werden per DI übergeben (Konstruktor).
    Im Simulator: Mock-Implementierungen.
    Auf dem RPi5: Echte Hardware-Klassen.
    """

    def __init__(
        self,
        motors: MotorController,
        avatar: AvatarDisplay,
        sensors: SensorManager,
        camera: CameraController | None = None,
        turntable: TurntableController | None = None,
        hostname: str = "elder-berry-rpi",
    ) -> None:
        self._motors = motors
        self._avatar = avatar
        self._sensors = sensors
        self._camera = camera
        self._turntable = turntable
        self._hostname = hostname
        self._start_time = time.monotonic()

        self.app = FastAPI(title="Elder-Berry Robot API", version="0.1.0")
        self._register_routes()

        logger.info("RobotServer initialisiert: %s", hostname)

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
            motor_state = self._motors.get_state()
            avatar_state = self._avatar.get_state()
            battery = self._sensors.get_battery()

            robot_status = RobotStatus(
                online=True,
                battery=battery,
                motors_active=motor_state.get("active", False),
                current_direction=motor_state.get("direction", "stop"),
                current_speed=motor_state.get("speed", 0.0),
                avatar_emotion=avatar_state.get("emotion", "neutral"),
                avatar_speaking=avatar_state.get("speaking", False),
                sensors=self._sensors.get_all(),
            )
            return asdict(robot_status)

        @self.app.post("/avatar/emotion")
        def set_avatar(request: AvatarRequest) -> dict:
            if request.emotion is not None:
                self._avatar.set_emotion(request.emotion)
                logger.info("Avatar Emotion: %s", request.emotion)

            if request.is_speaking is not None:
                self._avatar.set_speaking(request.is_speaking)
                logger.info("Avatar Speaking: %s", request.is_speaking)

            resp = ApiResponse(success=True, message="Avatar aktualisiert")
            return asdict(resp)

        @self.app.post("/motor/drive")
        def drive(request: DriveRequest) -> dict:
            self._motors.drive(request.direction, request.speed)
            logger.info(
                "Motor: %s @ %.0f%%", request.direction, request.speed * 100,
            )
            resp = ApiResponse(
                success=True,
                message=f"Fahre {request.direction}",
            )
            return asdict(resp)

        @self.app.post("/motor/stop")
        def stop(request: StopRequest | None = None) -> dict:
            reason = request.reason if request else "manual"
            self._motors.stop()
            logger.info("Motor STOP: %s", reason)
            resp = ApiResponse(success=True, message=f"Gestoppt: {reason}")
            return asdict(resp)

        @self.app.get("/sensor/battery")
        def battery() -> dict:
            return asdict(self._sensors.get_battery())

        @self.app.get("/sensor/all")
        def sensors() -> dict:
            return self._sensors.get_all()

        # --- Kamera ---

        @self.app.get("/camera/capture")
        def camera_capture(quality: int = 85) -> dict:
            """Nimmt ein Bild auf und gibt JPEG als Base64 zurück."""
            if not self._camera:
                return asdict(ApiResponse(
                    success=False,
                    message="Keine Kamera verfügbar",
                ))
            if not self._camera.is_available():
                return asdict(ApiResponse(
                    success=False,
                    message="Kamera nicht erkannt",
                ))
            try:
                import base64
                jpeg_bytes = self._camera.capture_jpeg(quality=quality)
                b64 = base64.b64encode(jpeg_bytes).decode("ascii")
                width, height = self._camera.get_resolution()
                return {
                    "success": True,
                    "image_base64": b64,
                    "format": "jpeg",
                    "width": width,
                    "height": height,
                    "size_bytes": len(jpeg_bytes),
                }
            except Exception as e:
                logger.error("Kamera-Capture fehlgeschlagen: %s", e)
                return asdict(ApiResponse(
                    success=False,
                    message=f"Capture fehlgeschlagen: {e}",
                ))

        @self.app.get("/camera/status")
        def camera_status() -> dict:
            """Gibt den Kamera-Status zurück."""
            if not self._camera:
                return {"available": False, "reason": "Keine Kamera konfiguriert"}
            available = self._camera.is_available()
            resolution = self._camera.get_resolution() if available else None
            return {
                "available": available,
                "resolution": resolution,
            }

        # --- Drehteller ---

        @self.app.post("/turntable/rotate")
        def turntable_rotate(request: TurntableRotateRequest) -> dict:
            if not self._turntable:
                return asdict(ApiResponse(
                    success=False, message="Kein Drehteller",
                ))
            if request.target_degrees is None and request.relative_degrees is None:
                return asdict(ApiResponse(
                    success=False,
                    message="target_degrees oder relative_degrees erforderlich",
                ))
            try:
                if request.target_degrees is not None:
                    self._turntable.rotate_to(request.target_degrees)
                    msg = f"Rotation zu {request.target_degrees} Grad gestartet"
                else:
                    self._turntable.rotate_by(request.relative_degrees)
                    msg = f"Rotation um {request.relative_degrees} Grad gestartet"
                return asdict(ApiResponse(success=True, message=msg))
            except RuntimeError as e:
                return asdict(ApiResponse(success=False, message=str(e)))

        @self.app.post("/turntable/home")
        def turntable_home() -> dict:
            if not self._turntable:
                return asdict(ApiResponse(
                    success=False, message="Kein Drehteller",
                ))
            try:
                self._turntable.home()
                return asdict(ApiResponse(
                    success=True, message="Homing gestartet",
                ))
            except RuntimeError as e:
                return asdict(ApiResponse(success=False, message=str(e)))

        @self.app.post("/turntable/stop")
        def turntable_stop() -> dict:
            if not self._turntable:
                return asdict(ApiResponse(
                    success=False, message="Kein Drehteller",
                ))
            self._turntable.stop()
            return asdict(ApiResponse(
                success=True, message="Rotation gestoppt",
            ))

        @self.app.get("/turntable/status")
        def turntable_status() -> dict:
            if not self._turntable:
                return {
                    "available": False,
                    "reason": "Kein Drehteller konfiguriert",
                }
            return {
                "available": True,
                "is_homed": self._turntable.is_homed,
                "is_moving": self._turntable.is_moving,
                "position_degrees": self._turntable.get_position(),
            }
