"""TurntableController -- Drehteller-Steuerung (28BYJ-48 + A3144 Hall-Sensor).

ABC + RPi5-Implementierung. Folgt dem etablierten Pattern:
ABC + echte Implementierung + Simulator + DI.

Plattformhinweis: RPi5TurntableController nur auf RPi5 (Linux mit lgpio) lauffaehig.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Hardware-Konstanten
STEPS_PER_REV = 4096           # Half-Steps pro volle Umdrehung
STEP_DELAY_MS = 2.0            # Millisekunden zwischen Steps (28BYJ-48 safe minimum)
MAX_DEGREES = 180.0            # +/-180 Grad Rotationslimit
HOMING_STEP_LIMIT = 4200       # Sicherheitslimit Homing (~369 Grad)

# GPIO Pins (BCM)
STEPPER_PINS = (17, 27, 22, 23)  # IN1, IN2, IN3, IN4
HALL_PIN = 24                     # A3144 Output

# Half-Step Sequenz
HALF_STEP_SEQ = [
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (0, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 0),
    (0, 0, 1, 1),
    (0, 0, 0, 1),
    (1, 0, 0, 1),
]


def degrees_to_steps(degrees: float) -> int:
    """Konvertiert Grad in Half-Steps (gerundet)."""
    return round(degrees / 360.0 * STEPS_PER_REV)


def steps_to_degrees(steps: int) -> float:
    """Konvertiert Half-Steps in Grad."""
    return steps / STEPS_PER_REV * 360.0


class TurntableController(ABC):
    """ABC fuer Drehteller-Steuerung."""

    @abstractmethod
    def home(self) -> None:
        """Homing-Sequenz: dreht bis Hall-Sensor ausloest -> Position 0 Grad.

        Raises:
            RuntimeError: Wenn Homing fehlschlaegt (Sensor defekt, Magnet fehlt).
            RuntimeError: Wenn bereits eine Rotation laeuft.
        """
        ...

    @abstractmethod
    def rotate_to(self, degrees: float) -> None:
        """Dreht auf absolute Position (relativ zu Home).

        Args:
            degrees: Zielposition in Grad (wird auf +/-180 Grad geclampt).

        Raises:
            RuntimeError: Wenn nicht gehomed.
            RuntimeError: Wenn bereits eine Rotation laeuft.
        """
        ...

    @abstractmethod
    def rotate_by(self, degrees: float) -> None:
        """Dreht relativ zur aktuellen Position.

        Args:
            degrees: Rotation in Grad (positiv = CW/rechts, negativ = CCW/links).
                     Ergebnis wird auf +/-180 Grad geclampt.

        Raises:
            RuntimeError: Wenn nicht gehomed.
            RuntimeError: Wenn bereits eine Rotation laeuft.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Bricht die aktuelle Rotation ab. No-op wenn keine Rotation laeuft."""
        ...

    @abstractmethod
    def get_position(self) -> float:
        """Gibt aktuelle Position in Grad zurueck. NaN wenn nicht gehomed."""
        ...

    @property
    @abstractmethod
    def is_homed(self) -> bool:
        """True wenn Homing erfolgreich durchgefuehrt wurde."""
        ...

    @property
    @abstractmethod
    def is_moving(self) -> bool:
        """True wenn eine Rotation laeuft."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Ressourcen freigeben (GPIO, Threads)."""
        ...


class RPi5TurntableController(TurntableController):
    """Echte Drehteller-Implementierung fuer RPi5 (lgpio).

    Plattformhinweis: Nur auf RPi5 (Linux mit lgpio) lauffaehig.
    """

    def __init__(
        self,
        step_delay_ms: float = STEP_DELAY_MS,
        auto_home: bool = False,
    ) -> None:
        self._step_delay_ms = step_delay_ms
        self._position_steps: int = 0
        self._is_homed: bool = False
        self._is_moving: bool = False
        self._stop_requested: bool = False
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

        # GPIO initialisieren
        import lgpio
        self._lgpio = lgpio
        self._chip = lgpio.gpiochip_open(0)
        for pin in STEPPER_PINS:
            lgpio.gpio_claim_output(self._chip, pin, 0)
        lgpio.gpio_claim_input(self._chip, HALL_PIN, lgpio.SET_PULL_UP)

        logger.info(
            "RPi5TurntableController initialisiert: Stepper=%s, Hall=GPIO%d",
            STEPPER_PINS, HALL_PIN,
        )
        if auto_home:
            self.home()

    def _read_hall(self) -> bool:
        """Liest Hall-Sensor. Returns True wenn Magnet erkannt (LOW)."""
        return self._lgpio.gpio_read(self._chip, HALL_PIN) == 0

    def _step_motor(self, steps: int) -> int:
        """Bewegt Motor um N Half-Steps. Prueft _stop_requested pro Step.

        Returns: Tatsaechlich ausgefuehrte Steps (mit Vorzeichen).
        """
        direction = 1 if steps > 0 else -1
        seq = HALF_STEP_SEQ if direction == 1 else HALF_STEP_SEQ[::-1]
        delay_s = self._step_delay_ms / 1000.0
        executed = 0
        for i in range(abs(steps)):
            if self._stop_requested:
                break
            pattern = seq[i % len(seq)]
            for pin_idx, pin in enumerate(STEPPER_PINS):
                self._lgpio.gpio_write(self._chip, pin, pattern[pin_idx])
            time.sleep(delay_s)
            executed += 1
        # Spulen stromlos
        for pin in STEPPER_PINS:
            self._lgpio.gpio_write(self._chip, pin, 0)
        return executed * direction

    def _step_until_hall(self, max_steps: int) -> int:
        """Dreht CCW bis Hall-Sensor ausloest. Fuer Homing.

        Returns: Ausgefuehrte Steps (negativ, da CCW).
        Raises: RuntimeError wenn max_steps erreicht.
        """
        seq_reversed = HALF_STEP_SEQ[::-1]
        delay_s = self._step_delay_ms / 1000.0
        executed = 0
        for i in range(max_steps):
            if self._stop_requested:
                for pin in STEPPER_PINS:
                    self._lgpio.gpio_write(self._chip, pin, 0)
                raise RuntimeError("Homing abgebrochen (stop() aufgerufen)")
            pattern = seq_reversed[i % len(seq_reversed)]
            for pin_idx, pin in enumerate(STEPPER_PINS):
                self._lgpio.gpio_write(self._chip, pin, pattern[pin_idx])
            time.sleep(delay_s)
            executed += 1
            if self._read_hall():
                for pin in STEPPER_PINS:
                    self._lgpio.gpio_write(self._chip, pin, 0)
                return -executed
        for pin in STEPPER_PINS:
            self._lgpio.gpio_write(self._chip, pin, 0)
        raise RuntimeError(
            f"Homing fehlgeschlagen: Hall-Sensor nach {max_steps} Steps "
            f"(~{steps_to_degrees(max_steps):.0f}) nicht ausgeloest. "
            f"Sensor defekt oder Magnet fehlt?"
        )

    def _run_home(self) -> None:
        """Worker-Thread fuer Homing."""
        try:
            self._is_moving = True
            self._stop_requested = False
            if self._read_hall():
                self._position_steps = 0
                self._is_homed = True
                logger.info("Homing: bereits auf Home-Position")
                return
            steps = self._step_until_hall(HOMING_STEP_LIMIT)
            self._position_steps = 0
            self._is_homed = True
            logger.info("Homing erfolgreich: %d Steps gedreht", abs(steps))
        except RuntimeError as e:
            logger.error("Homing fehlgeschlagen: %s", e)
            self._is_homed = False
        finally:
            self._is_moving = False

    def _run_rotate(self, target_steps: int) -> None:
        """Worker-Thread fuer Rotation."""
        try:
            self._is_moving = True
            self._stop_requested = False
            delta = target_steps - self._position_steps
            if delta == 0:
                return
            executed = self._step_motor(delta)
            self._position_steps += executed
            if self._stop_requested:
                logger.info(
                    "Rotation abgebrochen bei %.1f Grad",
                    steps_to_degrees(self._position_steps),
                )
            else:
                logger.info(
                    "Rotation abgeschlossen: %.1f Grad",
                    steps_to_degrees(self._position_steps),
                )
        finally:
            self._is_moving = False

    def _start_worker(self, target: callable) -> None:
        """Startet Worker-Thread. Raises RuntimeError wenn bereits Rotation laeuft."""
        if self._is_moving:
            raise RuntimeError("Rotation laeuft bereits -- erst stop() aufrufen")
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def home(self) -> None:
        self._start_worker(self._run_home)

    def rotate_to(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed -- erst home() aufrufen")
        clamped = max(-MAX_DEGREES, min(MAX_DEGREES, degrees))
        if clamped != degrees:
            logger.warning("rotate_to(%.1f) geclampt auf %.1f", degrees, clamped)
        target_steps = degrees_to_steps(clamped)
        self._start_worker(lambda: self._run_rotate(target_steps))

    def rotate_by(self, degrees: float) -> None:
        if not self._is_homed:
            raise RuntimeError("Nicht gehomed -- erst home() aufrufen")
        current_deg = steps_to_degrees(self._position_steps)
        target_deg = current_deg + degrees
        clamped = max(-MAX_DEGREES, min(MAX_DEGREES, target_deg))
        if clamped != target_deg:
            logger.warning(
                "rotate_by(%.1f) -> Ziel %.1f geclampt auf %.1f",
                degrees, target_deg, clamped,
            )
        target_steps = degrees_to_steps(clamped)
        self._start_worker(lambda: self._run_rotate(target_steps))

    def stop(self) -> None:
        if self._is_moving:
            self._stop_requested = True
            if self._worker and self._worker.is_alive():
                self._worker.join(timeout=5.0)

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
        self.stop()
        if hasattr(self, "_chip"):
            for pin in STEPPER_PINS:
                self._lgpio.gpio_write(self._chip, pin, 0)
            self._lgpio.gpiochip_close(self._chip)
            logger.info("RPi5TurntableController: GPIO freigegeben")
