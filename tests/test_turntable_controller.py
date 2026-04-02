"""Tests fuer TurntableController ABC + SimulatedTurntable + Hilfsfunktionen."""
import math
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from elder_berry.robot.turntable_controller import (
    HALF_STEP_SEQ,
    HOMING_STEP_LIMIT,
    MAX_DEGREES,
    STEPS_PER_REV,
    degrees_to_steps,
    steps_to_degrees,
)
from elder_berry.robot.simulator import SimulatedTurntable


class TestHelperFunctions:
    """Tests fuer degrees_to_steps / steps_to_degrees."""

    def test_degrees_to_steps_90(self):
        assert degrees_to_steps(90) == 1024

    def test_steps_to_degrees_2048(self):
        assert steps_to_degrees(2048) == pytest.approx(180.0)

    def test_degrees_to_steps_roundtrip(self):
        for deg in [0, 45, 90, 135, 180, -90, -180]:
            steps = degrees_to_steps(deg)
            back = steps_to_degrees(steps)
            assert back == pytest.approx(deg, abs=0.1)


class TestSimulatedTurntable:
    """Tests fuer SimulatedTurntable."""

    def test_home(self):
        t = SimulatedTurntable()
        t.home()
        assert t.is_homed is True
        assert t.get_position() == pytest.approx(0.0)

    def test_rotate_to(self):
        t = SimulatedTurntable()
        t.home()
        t.rotate_to(90)
        assert t.get_position() == pytest.approx(90.0, abs=0.1)

    def test_rotate_by(self):
        t = SimulatedTurntable()
        t.home()
        t.rotate_by(45)
        t.rotate_by(-30)
        assert t.get_position() == pytest.approx(15.0, abs=0.2)

    def test_clamp_positive(self):
        t = SimulatedTurntable()
        t.home()
        t.rotate_to(200)
        assert t.get_position() == pytest.approx(180.0, abs=0.1)

    def test_clamp_negative(self):
        t = SimulatedTurntable()
        t.home()
        t.rotate_to(-200)
        assert t.get_position() == pytest.approx(-180.0, abs=0.1)

    def test_rotate_by_clamp(self):
        t = SimulatedTurntable()
        t.home()
        t.rotate_to(170)
        t.rotate_by(30)
        assert t.get_position() == pytest.approx(180.0, abs=0.1)

    def test_not_homed_error(self):
        t = SimulatedTurntable()
        with pytest.raises(RuntimeError, match="gehomed"):
            t.rotate_to(90)

    def test_get_position_nan(self):
        t = SimulatedTurntable()
        assert math.isnan(t.get_position())

    def test_close(self):
        t = SimulatedTurntable()
        t.close()  # Should not raise


# ---------------------------------------------------------------------------
# Helpers for RPi5TurntableController tests
# ---------------------------------------------------------------------------

def _make_lgpio_mock() -> MagicMock:
    """Create a minimal lgpio mock with necessary constants."""
    lgpio_mock = MagicMock()
    lgpio_mock.SET_PULL_UP = 1
    lgpio_mock.gpiochip_open.return_value = 42  # chip handle
    lgpio_mock.gpio_read.return_value = 1  # Hall sensor HIGH (no magnet) by default
    return lgpio_mock


def _make_rpi5_turntable(lgpio_mock: MagicMock):
    """Create RPi5TurntableController with mocked lgpio."""
    from elder_berry.robot.turntable_controller import RPi5TurntableController

    with patch.dict("sys.modules", {"lgpio": lgpio_mock}):
        ctrl = RPi5TurntableController.__new__(RPi5TurntableController)
        ctrl._step_delay_ms = 0.001  # super fast for tests
        ctrl._position_steps = 0
        ctrl._is_homed = False
        ctrl._is_moving = False
        ctrl._stop_requested = False
        ctrl._lock = threading.Lock()
        ctrl._worker = None
        ctrl._lgpio = lgpio_mock
        ctrl._chip = 42

    return ctrl


# ---------------------------------------------------------------------------
# RPi5TurntableController – unit tests with mocked lgpio
# ---------------------------------------------------------------------------

class TestRPi5TurntableInit:
    def test_init_claims_gpio(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        from elder_berry.robot.turntable_controller import (
            RPi5TurntableController,
            STEPPER_PINS,
            HALL_PIN,
        )

        with patch.dict("sys.modules", {"lgpio": lgpio_mock}):
            ctrl = RPi5TurntableController(step_delay_ms=0.001)

        lgpio_mock.gpiochip_open.assert_called_once_with(0)
        for pin in STEPPER_PINS:
            lgpio_mock.gpio_claim_output.assert_any_call(42, pin, 0)
        lgpio_mock.gpio_claim_input.assert_called_once()

    def test_init_no_lgpio_raises(self) -> None:
        with patch.dict("sys.modules", {"lgpio": None}):
            from elder_berry.robot.turntable_controller import RPi5TurntableController
            with pytest.raises((ImportError, TypeError)):
                RPi5TurntableController()


class TestRPi5ReadHall:
    def test_read_hall_magnet_detected(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 0  # LOW = magnet
        ctrl = _make_rpi5_turntable(lgpio_mock)
        assert ctrl._read_hall() is True

    def test_read_hall_no_magnet(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 1  # HIGH = no magnet
        ctrl = _make_rpi5_turntable(lgpio_mock)
        assert ctrl._read_hall() is False


class TestRPi5StepMotor:
    def test_step_motor_positive(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        executed = ctrl._step_motor(8)
        assert executed == 8

    def test_step_motor_negative(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        executed = ctrl._step_motor(-8)
        assert executed == -8

    def test_step_motor_stop_requested(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0
        ctrl._stop_requested = True

        executed = ctrl._step_motor(100)
        assert executed == 0


class TestRPi5StepUntilHall:
    def test_hall_triggers_immediately(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 0  # magnet always detected
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        result = ctrl._step_until_hall(100)
        assert result == -1  # stopped after 1 step

    def test_hall_triggers_after_some_steps(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        # First 4 reads = no magnet, then magnet
        lgpio_mock.gpio_read.side_effect = [1, 1, 1, 0] + [0] * 100
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        result = ctrl._step_until_hall(50)
        assert result == -4

    def test_hall_timeout_raises(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 1  # never triggers
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        with pytest.raises(RuntimeError, match="Homing fehlgeschlagen"):
            ctrl._step_until_hall(5)

    def test_stop_requested_during_homing(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 1  # no magnet
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0
        ctrl._stop_requested = True

        with pytest.raises(RuntimeError, match="abgebrochen"):
            ctrl._step_until_hall(10)


class TestRPi5RunHome:
    def test_run_home_already_on_home(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 0  # Hall immediately active
        ctrl = _make_rpi5_turntable(lgpio_mock)

        ctrl._run_home()

        assert ctrl._is_homed is True
        assert ctrl._position_steps == 0
        assert ctrl._is_moving is False

    def test_run_home_normal(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        # First read (check if already on home) = no magnet, then magnet on step 3
        lgpio_mock.gpio_read.side_effect = [1, 1, 1, 0] + [0] * 100
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        ctrl._run_home()

        assert ctrl._is_homed is True
        assert ctrl._position_steps == 0
        assert ctrl._is_moving is False

    def test_run_home_failure_clears_homed(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 1  # never finds home
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        # Use a small limit to trigger error quickly
        with patch(
            "elder_berry.robot.turntable_controller.HOMING_STEP_LIMIT", 3
        ):
            ctrl._run_home()

        assert ctrl._is_homed is False
        assert ctrl._is_moving is False


class TestRPi5RunRotate:
    def test_run_rotate_moves_to_target(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0
        ctrl._is_homed = True

        target = degrees_to_steps(90)
        ctrl._run_rotate(target)

        assert ctrl._position_steps == target
        assert ctrl._is_moving is False

    def test_run_rotate_no_movement_needed(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._is_homed = True
        ctrl._position_steps = 100

        ctrl._run_rotate(100)  # already at target
        assert ctrl._position_steps == 100

    def test_run_rotate_stop_mid_movement(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0
        ctrl._is_homed = True
        ctrl._stop_requested = True  # pre-set stop

        ctrl._run_rotate(degrees_to_steps(180))
        # Position didn't change since stop was already set
        assert ctrl._is_moving is False


class TestRPi5StartWorker:
    def test_start_worker_already_moving_raises(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._is_moving = True

        with pytest.raises(RuntimeError, match="Rotation laeuft bereits"):
            ctrl._start_worker(lambda: None)


class TestRPi5PublicMethods:
    def test_home_starts_worker(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        lgpio_mock.gpio_read.return_value = 0  # immediate home
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._step_delay_ms = 0.0

        ctrl.home()
        if ctrl._worker:
            ctrl._worker.join(timeout=1.0)

        assert ctrl._is_homed is True

    def test_rotate_to_not_homed_raises(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        with pytest.raises(RuntimeError, match="gehomed"):
            ctrl.rotate_to(90)

    def test_rotate_to_clamped(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._is_homed = True
        ctrl._step_delay_ms = 0.0

        ctrl.rotate_to(270)  # > MAX_DEGREES
        if ctrl._worker:
            ctrl._worker.join(timeout=1.0)

        assert ctrl.get_position() == pytest.approx(MAX_DEGREES, abs=0.2)

    def test_rotate_by_not_homed_raises(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        with pytest.raises(RuntimeError, match="gehomed"):
            ctrl.rotate_by(45)

    def test_rotate_by_clamped(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._is_homed = True
        ctrl._position_steps = degrees_to_steps(160)
        ctrl._step_delay_ms = 0.0

        ctrl.rotate_by(50)  # 160+50=210 > MAX_DEGREES
        if ctrl._worker:
            ctrl._worker.join(timeout=1.0)

        assert ctrl.get_position() == pytest.approx(MAX_DEGREES, abs=0.2)

    def test_get_position_not_homed_is_nan(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        assert math.isnan(ctrl.get_position())

    def test_get_position_homed(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        ctrl._is_homed = True
        ctrl._position_steps = degrees_to_steps(45)
        assert ctrl.get_position() == pytest.approx(45.0, abs=0.1)

    def test_is_homed_property(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        assert ctrl.is_homed is False
        ctrl._is_homed = True
        assert ctrl.is_homed is True

    def test_is_moving_property(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        assert ctrl.is_moving is False
        ctrl._is_moving = True
        assert ctrl.is_moving is True

    def test_stop_no_op_when_not_moving(self) -> None:
        ctrl = _make_rpi5_turntable(_make_lgpio_mock())
        ctrl.stop()  # should not raise

    def test_stop_sets_stop_requested(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        ctrl._is_moving = True
        ctrl._worker = MagicMock()
        ctrl._worker.is_alive.return_value = False

        ctrl.stop()
        assert ctrl._stop_requested is True

    def test_close_frees_gpio(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)

        ctrl.close()

        lgpio_mock.gpiochip_close.assert_called_once_with(42)

    def test_close_without_chip_attr(self) -> None:
        lgpio_mock = _make_lgpio_mock()
        ctrl = _make_rpi5_turntable(lgpio_mock)
        del ctrl._chip  # simulate no chip

        ctrl.close()  # should not raise
