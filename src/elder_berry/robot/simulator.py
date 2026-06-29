"""RPi5-Simulator – Mock-Implementierungen für lokale Entwicklung.

Simuliert den RPi5 auf dem Tower:
- Mock-Motoren (loggen statt fahren)
- Mock-Sensoren (feste Werte, simulierter Akkuverbrauch)
- Mock-Avatar-Display (State-Tracking)

Verwendung:
    python -m elder_berry.robot.simulator
    → Startet den RobotServer auf localhost:8000
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from elder_berry.core.audio_analyzer import AmplitudeTrack
from elder_berry.robot.camera_controller import CameraController
from elder_berry.robot.protocol import BatteryStatus
from elder_berry.robot.server import (
    AvatarDisplay,
    MotorController,
    RobotServer,
    SensorManager,
)
from elder_berry.robot.turntable_controller import (
    MAX_DEGREES,
    TurntableController,
    degrees_to_steps,
    steps_to_degrees,
)

logger = logging.getLogger(__name__)


class SimulatedMotors(MotorController):
    """Simulierte Mecanum-Motoren (loggen statt fahren)."""

    def __init__(self) -> None:
        self._active = False
        self._direction = "stop"
        self._speed = 0.0

    def drive(self, direction: str, speed: float) -> None:
        self._direction = direction
        self._speed = max(0.0, min(1.0, speed))
        self._active = True
        logger.info(
            "[SIM] Motor: %s @ %.0f%%",
            direction,
            self._speed * 100,
        )

    def stop(self) -> None:
        self._direction = "stop"
        self._speed = 0.0
        self._active = False
        logger.info("[SIM] Motor: STOP")

    def get_state(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "direction": self._direction,
            "speed": self._speed,
        }


class SimulatedAvatar(AvatarDisplay):
    """Simuliertes Avatar-Display (State-Tracking)."""

    def __init__(self) -> None:
        self._emotion = "neutral"
        self._speaking = False
        self._confidence = 1.0

    def set_emotion(self, emotion: str, confidence: float = 1.0) -> None:
        # confidence (Phase 108): der Simulator hat kein Confidence-Gate, hält
        # den Wert aber für get_state/Tests fest.
        self._emotion = emotion
        self._confidence = confidence
        logger.info("[SIM] Avatar Emotion: %s (conf=%.2f)", emotion, confidence)

    def set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        # audio_meta (83.4): der Simulator hat keinen Lip-Sync → ignoriert.
        del audio_meta
        self._speaking = is_speaking
        logger.info("[SIM] Avatar Speaking: %s", is_speaking)

    def get_state(self) -> dict[str, Any]:
        return {
            "emotion": self._emotion,
            "speaking": self._speaking,
            "confidence": self._confidence,
        }


class SimulatedSensors(SensorManager):
    """Simulierte Sensoren mit realistischen Fake-Werten."""

    def __init__(self) -> None:
        self._start_time = time.monotonic()
        self._battery_pct = 85

    def get_battery(self) -> BatteryStatus:
        # Simuliert langsamen Akkuverbrauch (1% pro 5 Minuten)
        elapsed_min = (time.monotonic() - self._start_time) / 60
        pct = max(0, self._battery_pct - int(elapsed_min / 5))

        # Spannung: 7.4V voll → 6.0V leer (linear)
        voltage = 6.0 + (pct / 100) * 1.4

        return BatteryStatus(
            voltage=round(voltage, 2),
            percentage=pct,
            is_charging=False,
            is_low=pct < 20,
        )

    def get_all(self) -> dict[str, Any]:
        battery = self.get_battery()
        return {
            "battery": {
                "voltage": battery.voltage,
                "percentage": battery.percentage,
                "is_charging": battery.is_charging,
                "is_low": battery.is_low,
            },
            "temperature": {
                "cpu": round(45.0 + random.uniform(-2, 5), 1),
                "ambient": round(22.0 + random.uniform(-1, 1), 1),
                "unit": "celsius",
            },
            "ir": {
                "obstacle_front": random.random() > 0.8,
                "distance_cm": round(random.uniform(10, 200), 1),
            },
        }


class SimulatedTurntable(TurntableController):
    """Simulierter Drehteller fuer Tower-Tests ohne Hardware."""

    def __init__(self) -> None:
        self._position_steps: int = 0
        self._is_homed: bool = False
        self._is_moving: bool = False

    def home(self) -> None:
        self._position_steps = 0
        self._is_homed = True
        logger.info("[SIM] Turntable: Homed")

    def rotate_to(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed -- erst home() aufrufen")
        clamped = max(-MAX_DEGREES, min(MAX_DEGREES, degrees))
        self._position_steps = degrees_to_steps(clamped)
        logger.info("[SIM] Turntable: rotate_to(%.1f)", clamped)

    def rotate_by(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed -- erst home() aufrufen")
        current = steps_to_degrees(self._position_steps)
        target = max(-MAX_DEGREES, min(MAX_DEGREES, current + degrees))
        self._position_steps = degrees_to_steps(target)
        logger.info("[SIM] Turntable: rotate_by(%.1f) -> %.1f", degrees, target)

    def stop(self) -> None:
        self._is_moving = False
        logger.info("[SIM] Turntable: Stop")

    def get_position(self) -> float:
        if not self._is_homed:
            return float("nan")
        return steps_to_degrees(self._position_steps)

    @property
    def is_homed(self) -> bool:
        return self._is_homed

    @property
    def is_moving(self) -> bool:
        return self._is_moving

    def close(self) -> None:
        pass


class SimulatedCamera(CameraController):
    """Simulierte Kamera für lokale Entwicklung."""

    def __init__(self, resolution: tuple[int, int] = (1920, 1080)) -> None:
        self._resolution = resolution

    def is_available(self) -> bool:
        return True

    def capture_jpeg(self, quality: int = 85) -> bytes:
        """Generiert ein minimales JPEG-Testbild (320x240, dunkelgrau)."""
        from PIL import Image
        import io

        img = Image.new("RGB", (320, 240), color=(40, 40, 40))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        logger.info("[SIM] Camera: Simulated capture")
        return buffer.getvalue()

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution


def create_simulator(
    host: str = "127.0.0.1",
    port: int = 8000,
    robot_token: str | None = None,
) -> RobotServer:
    """Erstellt einen RobotServer mit simulierter Hardware.

    Phase 64 (H-2): Default-Host auf ``127.0.0.1`` geaendert. Der
    Simulator laeuft per Default OHNE Robot-Token-Auth, also darf er
    nicht auf allen Interfaces binden.

    Phase 103 (S1): ``robot_token`` wird jetzt an den ``RobotServer``
    durchgereicht (vorher landete die RobotTokenMiddleware dauerhaft im
    Bypass). Mit gesetztem Token darf der Simulator bewusst auch auf
    ``0.0.0.0`` laufen; ohne Token erzwingt der ``__main__``-Guard
    Loopback (siehe :func:`elder_berry.core.bind_policy.enforce_token_policy`).
    """
    server = RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        turntable=SimulatedTurntable(),
        hostname="elder-berry-simulator",
        robot_token=robot_token,
    )
    logger.info("Simulator bereit auf %s:%d", host, port)
    return server


if __name__ == "__main__":  # pragma: no cover - Script-Entrypoint (uvicorn.run)
    import argparse
    import os

    import uvicorn

    from elder_berry.core.bind_policy import enforce_token_policy

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Elder-Berry Robot-Simulator (FastAPI)",
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Bind-Host (default: 127.0.0.1 = Loopback). "
        "Fuer LAN-Zugriff ELDER_BERRY_ROBOT_TOKEN setzen und explizit "
        "'--bind 0.0.0.0' angeben -- ohne Token verweigert der Start einen "
        "Nicht-Loopback-Bind.",
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Phase 103 (S1): fail-closed. Ohne ELDER_BERRY_ROBOT_TOKEN darf der
    # Simulator nur auf Loopback binden; ein Nicht-Loopback-Bind ohne Token
    # bricht mit Exit 2 ab (statt nur zu warnen). Mit Token ist 0.0.0.0
    # bewusst erlaubt -- das Token wird an den RobotServer durchgereicht.
    _env_token = os.environ.get("ELDER_BERRY_ROBOT_TOKEN")
    _robot_token = _env_token.strip() if _env_token and _env_token.strip() else None
    enforce_token_policy(
        _robot_token,
        args.bind,
        token_env_name="ELDER_BERRY_ROBOT_TOKEN",
        server_label="Robot-Simulator",
        logger=logger,
    )

    sim = create_simulator(
        host=args.bind, port=args.port, robot_token=_robot_token
    )
    uvicorn.run(sim.app, host=args.bind, port=args.port)
