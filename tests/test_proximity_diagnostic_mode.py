"""Tests fuer ProximityDiagnosticMode (Phase 111, E3, M5). pygame dummy."""

from __future__ import annotations

import logging
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from elder_berry.avatar.proximity_attention_provider import (  # noqa: E402
    ProximityAttentionProvider,
    ProximityThresholds,
)
from elder_berry.room_display.oriented_display import OrientedDisplay  # noqa: E402
from elder_berry.room_display.proximity_diagnostic_mode import (  # noqa: E402
    ProximityDiagnosticMode,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Sensor:
    def __init__(self):
        self.value = 128
        self.fail = False

    def read_proximity(self):
        if self.fail:
            raise OSError(121, "Remote I/O error")
        return self.value


@pytest.fixture
def display():
    pygame.display.init()
    screen = pygame.display.set_mode((720, 1280))
    yield OrientedDisplay(screen, 90)
    pygame.display.quit()


@pytest.fixture
def setup(display):
    clock, sensor = Clock(), Sensor()
    provider = ProximityAttentionProvider(sensor, ProximityThresholds(), clock=clock)
    mode = ProximityDiagnosticMode(provider)
    mode.on_enter(display)
    return mode, provider, sensor, clock


def _tick(mode, display, clock, dt=0.1):
    clock.now += dt
    if mode.update(clock.now):
        mode.render(display)


def test_renders_only_on_change(setup, display):
    mode, _, sensor, clock = setup
    for _ in range(20):  # konstanter Wert
        _tick(mode, display, clock)
    assert mode.render_count == 1
    sensor.value = 140  # neuer Wert + PRESENT
    _tick(mode, display, clock)
    assert mode.render_count == 2
    for _ in range(5):
        _tick(mode, display, clock)
    assert mode.render_count == 2


def test_logs_min_mean_max_once_per_second(setup, display, caplog):
    caplog.set_level(logging.INFO)
    mode, _, sensor, clock = setup
    values = [128, 130, 126, 140, 128, 129, 131, 127, 128, 128, 135, 128]
    for value in values:
        sensor.value = value
        _tick(mode, display, clock, dt=0.1)
    lines = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("PDATA")
    ]
    assert len(lines) == 1
    assert "min 126" in lines[0] and "max 140" in lines[0]
    assert "Zustand" in lines[0]


def test_logs_thresholds_absolute_on_enter(display, caplog):
    caplog.set_level(logging.INFO)
    provider = ProximityAttentionProvider(Sensor(), ProximityThresholds(baseline=100))
    ProximityDiagnosticMode(provider).on_enter(display)
    assert (
        "Grundwert 100, AWAY < 110, PRESENT >= 112, FOCUSED ein >= 130 / aus < 115"
        in caplog.text
    )


def test_shows_fault_and_errors(setup, display):
    mode, provider, sensor, clock = setup
    sensor.fail = True
    _tick(mode, display, clock)
    assert provider.error_count == 1
    sensor.fail = False
    sensor.value = 128
    _tick(mode, display, clock)
    assert mode.render_count >= 2


def test_without_sensor_shows_hint_once(display, caplog):
    caplog.set_level(logging.WARNING)
    mode = ProximityDiagnosticMode(None)
    mode.on_enter(display)
    assert "kein Sensor" in caplog.text
    renders = 0
    for t in range(10):
        if mode.update(float(t)):
            mode.render(display)
            renders += 1
    assert renders == 1
    assert not mode.is_animating()
    assert not mode.wants_exit()
