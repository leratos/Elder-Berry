"""Tests fuer DiagnosticMode (Phase 111, E2; M3/M4'). pygame dummy."""

from __future__ import annotations

import logging
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from elder_berry.room_display.diagnostic_mode import (  # noqa: E402
    DiagnosticMode,
    build_grid,
    build_gradient,
    build_test_image,
    evaluate_m4,
)
from elder_berry.room_display.frame_rate_meter import (  # noqa: E402
    FrameRateMeter,
    FrameStats,
)
from elder_berry.room_display.oriented_display import OrientedDisplay  # noqa: E402


@pytest.fixture
def display():
    pygame.display.init()
    screen = pygame.display.set_mode((720, 1280))
    yield OrientedDisplay(screen, 90)
    pygame.display.quit()


def _stats(mean_fps: float) -> FrameStats:
    return FrameStats(
        frames=10, mean_fps=mean_fps, min_fps=mean_fps, mean_frame_ms=1, max_frame_ms=1
    )


@pytest.mark.parametrize(
    ("fps", "expected"),
    [(30, ">= 24"), (24, ">= 24"), (23.9, "10-24"), (10, "10-24"), (9.9, "< 10")],
)
def test_evaluate_m4_thresholds(fps, expected):
    assert evaluate_m4(_stats(fps)).startswith(expected)


def test_test_image_has_marker_top_left_and_logical_size():
    pygame.display.init()
    try:
        image = build_test_image((1280, 720), rotation=90, desktop_sizes=[(720, 1280)])
        assert image.get_size() == (1280, 720)
        assert tuple(image.get_at((5, 5)))[:3] == (230, 40, 40)
    finally:
        pygame.display.quit()


def test_generated_images_differ():
    gradient = build_gradient((1280, 720))
    grid = build_grid((1280, 720))
    assert gradient.get_size() == grid.get_size() == (1280, 720)
    assert gradient.get_at((640, 300)) != grid.get_at((640, 300))


def test_testbild_renders_once_and_logs_size(display, caplog):
    caplog.set_level(logging.INFO)
    mode = DiagnosticMode(
        "testbild", desktop_sizes=[(720, 1280)], meter=FrameRateMeter()
    )
    mode.on_enter(display)
    assert "physisch [(720, 1280)]" in caplog.text
    assert mode.update(0.0) is True
    assert [mode.update(t) for t in (0.1, 5.0, 100.0)] == [False, False, False]
    assert not mode.is_animating()
    assert not mode.wants_exit()
    mode.render(display)


def test_ueberblendung_runs_n_transitions_then_exits(display, caplog):
    caplog.set_level(logging.INFO)
    meter = FrameRateMeter()
    mode = DiagnosticMode(
        "ueberblendung",
        desktop_sizes=[(720, 1280)],
        meter=meter,
        transition_s=0.5,
        hold_s=0.2,
        transitions=3,
    )
    mode.on_enter(display)
    t = 0.0
    animating_ticks = 0
    while not mode.wants_exit() and t < 10:
        if mode.update(t):
            mode.render(display)
        if mode.is_animating():
            animating_ticks += 1
            meter.frame(t)
        else:
            meter.pause()
        t += 1 / 40
    assert mode.wants_exit()
    assert mode.completed_transitions == 3
    assert animating_ticks >= 3 * 0.5 * 40 - 3
    assert "M4' Ergebnis nach 3 Ueberblendungen" in caplog.text
    assert "M4' Auswertung" in caplog.text
    # nach dem Ende keine weiteren Aenderungen
    assert mode.update(t + 1) is False


def test_ueberblendung_holds_between_fades(display):
    mode = DiagnosticMode(
        "ueberblendung",
        desktop_sizes=[],
        meter=FrameRateMeter(),
        transition_s=1.0,
        hold_s=2.0,
        transitions=5,
    )
    mode.on_enter(display)
    mode.update(0.0)
    assert not mode.is_animating()  # erst Standzeit
    mode.update(1.9)
    assert not mode.is_animating()
    mode.update(2.0)
    assert mode.is_animating()
    mode.update(2.5)
    mode.render(display)  # Blend-Pfad
    mode.update(3.0)
    assert not mode.is_animating()
    assert mode.completed_transitions == 1


def test_unknown_view():
    with pytest.raises(ValueError):
        DiagnosticMode("bunt", desktop_sizes=[], meter=FrameRateMeter())
