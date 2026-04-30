"""Kommunikationsprotokoll Tower ↔ RPi5 – gemeinsame Nachrichtentypen."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DriveDirection(str, Enum):
    """Fahrtrichtungen für Mecanum-Antrieb."""

    FORWARD = "forward"
    BACKWARD = "backward"
    LEFT = "left"
    RIGHT = "right"
    ROTATE_LEFT = "rotate_left"
    ROTATE_RIGHT = "rotate_right"
    STOP = "stop"


class SensorType(str, Enum):
    """Verfügbare Sensor-Typen auf dem RPi5."""

    BATTERY = "battery"
    TEMPERATURE = "temperature"
    CAMERA = "camera"
    IR = "ir"


# ---------------------------------------------------------------------------
# Tower → RPi5: Befehle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AvatarCommand:
    """Setzt Emotion und/oder Sprechzustand auf dem RPi5-Display."""

    emotion: str | None = None
    is_speaking: bool | None = None


@dataclass(frozen=True)
class DriveCommand:
    """Fahrbefehl an den Mecanum-Antrieb."""

    direction: str
    speed: float = 0.5
    duration: float | None = None


@dataclass(frozen=True)
class MotorStopCommand:
    """Notfall-Stopp aller Motoren."""

    reason: str = "manual"


# ---------------------------------------------------------------------------
# RPi5 → Tower: Status / Sensor-Daten
# ---------------------------------------------------------------------------


@dataclass
class BatteryStatus:
    """Akku-Zustand (vom Pico 2W via RPi5)."""

    voltage: float = 0.0
    percentage: int = 0
    is_charging: bool = False
    is_low: bool = False


@dataclass
class SensorReading:
    """Einzelne Sensor-Messung."""

    sensor_type: str
    value: Any
    unit: str = ""
    timestamp: float = 0.0


@dataclass
class RobotStatus:
    """Gesamtstatus des Roboters."""

    online: bool = True
    battery: BatteryStatus = field(default_factory=BatteryStatus)
    motors_active: bool = False
    current_direction: str = "stop"
    current_speed: float = 0.0
    avatar_emotion: str = "neutral"
    avatar_speaking: bool = False
    sensors: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Health / Heartbeat
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthResponse:
    """Heartbeat-Antwort vom RPi5."""

    status: str = "ok"
    hostname: str = ""
    uptime: float = 0.0
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# API Response Wrapper
# ---------------------------------------------------------------------------


@dataclass
class ApiResponse:
    """Einheitliche API-Antwort."""

    success: bool
    message: str = ""
    data: dict[str, Any] | None = None
