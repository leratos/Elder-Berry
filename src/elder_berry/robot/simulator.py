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

from elder_berry.robot.protocol import BatteryStatus
from elder_berry.robot.server import (
    AvatarDisplay,
    MotorController,
    RobotServer,
    SensorManager,
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
            "[SIM] Motor: %s @ %.0f%%", direction, self._speed * 100,
        )

    def stop(self) -> None:
        self._direction = "stop"
        self._speed = 0.0
        self._active = False
        logger.info("[SIM] Motor: STOP")

    def get_state(self) -> dict:
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

    def set_emotion(self, emotion: str) -> None:
        self._emotion = emotion
        logger.info("[SIM] Avatar Emotion: %s", emotion)

    def set_speaking(self, is_speaking: bool) -> None:
        self._speaking = is_speaking
        logger.info("[SIM] Avatar Speaking: %s", is_speaking)

    def get_state(self) -> dict:
        return {
            "emotion": self._emotion,
            "speaking": self._speaking,
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

    def get_all(self) -> dict:
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


def create_simulator(
    host: str = "0.0.0.0",
    port: int = 8000,
) -> RobotServer:
    """Erstellt einen RobotServer mit simulierter Hardware."""
    server = RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        hostname="elder-berry-simulator",
    )
    logger.info("Simulator bereit auf %s:%d", host, port)
    return server


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    sim = create_simulator()
    uvicorn.run(sim.app, host="0.0.0.0", port=8000)
