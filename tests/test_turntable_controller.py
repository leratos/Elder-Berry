"""Tests fuer TurntableController ABC + SimulatedTurntable + Hilfsfunktionen."""
import math
import pytest

from elder_berry.robot.turntable_controller import (
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
