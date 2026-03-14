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
        hostname: str = "elder-berry-rpi",
    ) -> None:
        self._motors = motors
        self._avatar = avatar
        self._sensors = sensors
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
