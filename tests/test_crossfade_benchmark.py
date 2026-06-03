"""Tests für den Crossfade-FPS-Stopwatch (Phase 83.3, §6.1 / §0.6).

Läuft gegen **echte** pygame-Software-Surfaces (kein Mock) – validiert damit
genau die SDL2-Operationen (``BLEND_RGBA_MULT``-Fade, ``transform.flip``), die
ein Mock nicht abdecken kann. Headless via ``SDL_VIDEODRIVER=dummy``; wird
übersprungen, wenn pygame fehlt.

Die wall-clock-Messung wird mit einer injizierten Zeitquelle **deterministisch**
geprüft (kein CI-Flackern). Zusätzlich ein loser Regressions-Guard bei
720x1280 rotation=180 – die **verbindliche** ≥30-FPS-Zahl liefert der RPi5-Lauf.
"""

from __future__ import annotations

import os

# Headless: vor dem ersten pygame-Display-Init setzen.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

pytest.importorskip("pygame")

from elder_berry.avatar.crossfade_benchmark import (  # noqa: E402
    FRAME_BUDGET_MS,
    CrossfadeBenchmarkResult,
    format_result,
    measure_crossfade_fps,
)
from elder_berry.avatar.layered_renderer import CrossfadeScope  # noqa: E402


def _fixed_clock(values):
    """Eine Zeitquelle, die nacheinander ``values`` zurückgibt."""
    it = iter(values)
    return lambda: next(it)


# ---------------------------------------------------------------------------
# Deterministische Mess-Mathematik (injizierte Zeitquelle, kein Flackern)
# ---------------------------------------------------------------------------


class TestDeterministicTiming:
    def test_mean_and_max_from_injected_clock(self):
        # 3 Frames, 2 clock()-Aufrufe je Frame (start, ende):
        # f1: 0→0.010 = 10 ms, f2: 0.010→0.030 = 20 ms, f3: 0.030→0.050 = 20 ms.
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.030, 0.030, 0.050])
        result = measure_crossfade_fps(width=64, height=64, frames=3, clock=clock)
        assert result.frames == 3
        assert result.max_ms == pytest.approx(20.0)
        assert result.mean_ms == pytest.approx((10.0 + 20.0 + 20.0) / 3)
        assert result.holds_30fps is True  # max 20 ms <= 33.33 ms

    def test_holds_30fps_false_when_over_budget(self):
        # 2 Frames à 50 ms > 33.33 ms Budget.
        clock = _fixed_clock([0.0, 0.050, 0.050, 0.100])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        assert result.max_ms == pytest.approx(50.0)
        assert result.holds_30fps is False

    def test_effective_fps_matches_mean(self):
        clock = _fixed_clock([0.0, 0.020, 0.020, 0.040])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        # mean 20 ms → 50 FPS.
        assert result.effective_fps == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Struktur / Validierung
# ---------------------------------------------------------------------------


class TestBenchmarkStructure:
    def test_returns_result_dataclass(self):
        result = measure_crossfade_fps(width=64, height=64, frames=2)
        assert isinstance(result, CrossfadeBenchmarkResult)
        assert result.budget_ms == pytest.approx(FRAME_BUDGET_MS)

    def test_frames_below_one_raises(self):
        with pytest.raises(ValueError):
            measure_crossfade_fps(frames=0)

    def test_mouth_only_scope_runs(self):
        result = measure_crossfade_fps(
            width=64, height=64, frames=2, scope=CrossfadeScope.MOUTH_ONLY
        )
        assert result.scope is CrossfadeScope.MOUTH_ONLY

    def test_format_result_is_human_readable(self):
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        text = format_result(result)
        assert "FPS" in text
        assert "64x64" in text


# ---------------------------------------------------------------------------
# Echte Komposition bei 720x1280 rotation=180 (§0.6) – loser Regressions-Guard
# ---------------------------------------------------------------------------


class TestRealComposite:
    def test_720x1280_rotation180_composites(self):
        """Echter Render-Pfad bei RPi5-Auflösung MIT rotation=180.

        Loser Guard gegen katastrophale O(Pixel)-Regressionen – **nicht** der
        verbindliche 30-FPS-Beweis (der kommt vom RPi5-Lauf via
        ``start_rpi5.py --benchmark-crossfade``).
        """
        result = measure_crossfade_fps(
            width=720,
            height=1280,
            rotation=180,
            frames=8,
            component_size=(420, 700),
        )
        assert result.frames == 8
        assert result.rotation == 180
        assert result.effective_fps > 0
        assert result.mean_ms < 150.0  # nur Katastrophen-Guard, machine-tolerant

    def test_full_screen_components_worst_case_runs(self):
        """Default component_size = Vollbild (konservativer Worst-Case) läuft."""
        result = measure_crossfade_fps(width=320, height=480, rotation=180, frames=4)
        assert result.frames == 4
        assert result.max_ms >= 0.0
