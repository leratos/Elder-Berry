"""Tests für den Crossfade-FPS-Stopwatch (Phase 83.3, §6.1 / §0.6).

Der Großteil läuft gegen ein **gemocktes** pygame (wie die übrigen Avatar-Tests)
– damit der echte Kompositions-Codepfad und die Mess-Mathematik auch in CI
**ohne installiertes pygame** abgedeckt sind. Die wall-clock-Messung wird über
eine injizierte Zeitquelle deterministisch geprüft (kein Flackern).

Zusätzlich validiert :class:`TestRealComposite` gegen **echte** pygame-Software-
Surfaces die SDL2-Operationen (``BLEND_RGBA_MULT``-Fade, ``transform.flip``), die
ein Mock nicht abdecken kann – dieser Teil wird übersprungen, wenn pygame fehlt.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.avatar.crossfade_benchmark import (
    FRAME_BUDGET_MS,
    CrossfadeBenchmarkResult,
    format_result,
    measure_crossfade_fps,
    sweep_crossfade_fps,
)
from elder_berry.avatar.layered_renderer import CrossfadeScope

# Headless für den optionalen Real-Surface-Teil: vor pygame-Display-Init setzen.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def _fixed_clock(values):
    """Eine Zeitquelle, die nacheinander ``values`` zurückgibt."""
    it = iter(values)
    return lambda: next(it)


@pytest.fixture
def mock_pg():
    """Mockt pygame im Benchmark UND im Renderer → läuft ohne echtes pygame.

    Patcht beide Modul-Globals auf denselben MagicMock, sodass Screen- und
    Offscreen-Surfaces konsistent sind und der echte Kompositionspfad
    (``_composite_full`` / ``_composite_mouth_only``) gegen Mocks durchläuft.
    """
    surface = MagicMock()
    surface.get_size.return_value = (64, 64)
    with (
        patch("elder_berry.avatar.crossfade_benchmark.pygame") as bench_pg,
        patch("elder_berry.avatar.layered_renderer.pygame") as rend_pg,
    ):
        for pg in (bench_pg, rend_pg):
            pg.Surface.return_value = surface
            pg.get_init.return_value = True
        yield {"bench": bench_pg, "rend": rend_pg, "surface": surface}


# ---------------------------------------------------------------------------
# Deterministische Mess-Mathematik (injizierte Zeitquelle, gemocktes pygame)
# ---------------------------------------------------------------------------


class TestDeterministicTiming:
    def test_mean_and_max_from_injected_clock(self, mock_pg):
        # 3 Frames, 2 clock()-Aufrufe je Frame (start, ende):
        # f1: 0→0.010 = 10 ms, f2: 0.010→0.030 = 20 ms, f3: 0.030→0.050 = 20 ms.
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.030, 0.030, 0.050])
        result = measure_crossfade_fps(width=64, height=64, frames=3, clock=clock)
        assert result.frames == 3
        assert result.max_ms == pytest.approx(20.0)
        assert result.mean_ms == pytest.approx((10.0 + 20.0 + 20.0) / 3)
        assert result.holds_30fps is True  # max 20 ms <= 33.33 ms

    def test_holds_30fps_false_when_over_budget(self, mock_pg):
        clock = _fixed_clock([0.0, 0.050, 0.050, 0.100])  # 2x 50 ms > Budget
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        assert result.max_ms == pytest.approx(50.0)
        assert result.holds_30fps is False

    def test_effective_fps_matches_mean(self, mock_pg):
        clock = _fixed_clock([0.0, 0.020, 0.020, 0.040])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        assert result.effective_fps == pytest.approx(50.0)  # mean 20 ms → 50 FPS


# ---------------------------------------------------------------------------
# Struktur / Validierung (gemocktes pygame)
# ---------------------------------------------------------------------------


class TestBenchmarkStructure:
    def test_returns_result_dataclass(self, mock_pg):
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        assert isinstance(result, CrossfadeBenchmarkResult)
        assert result.budget_ms == pytest.approx(FRAME_BUDGET_MS)
        assert result.width == 64 and result.height == 64

    def test_frames_below_one_raises(self, mock_pg):
        with pytest.raises(ValueError):
            measure_crossfade_fps(frames=0)

    def test_initializes_pygame_when_not_yet_init(self, mock_pg):
        mock_pg["bench"].get_init.return_value = False
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        mock_pg["bench"].init.assert_called_once()

    def test_mouth_only_scope_runs(self, mock_pg):
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        result = measure_crossfade_fps(
            width=64, height=64, frames=2, scope=CrossfadeScope.MOUTH_ONLY, clock=clock
        )
        assert result.scope is CrossfadeScope.MOUTH_ONLY

    def test_default_component_size_full_screen(self, mock_pg):
        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        result = measure_crossfade_fps(
            width=120, height=200, frames=2, rotation=180, clock=clock
        )
        assert result.rotation == 180
        assert result.frames == 2

    def test_format_result_under_budget_verdict(self, mock_pg):
        clock = _fixed_clock([0.0, 0.005, 0.005, 0.010])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        text = format_result(result)
        assert "FPS" in text
        assert "64x64" in text
        assert "HOLDS" in text

    def test_format_result_over_budget_verdict(self, mock_pg):
        clock = _fixed_clock([0.0, 0.050, 0.050, 0.100])
        result = measure_crossfade_fps(width=64, height=64, frames=2, clock=clock)
        assert "UNTER 30 FPS" in format_result(result)


# ---------------------------------------------------------------------------
# Scope-Pfad: jeder Modus misst seinen EIGENEN Kompositionspfad (Codex P2 #2)
# ---------------------------------------------------------------------------


class TestBenchmarkScopePath:
    def test_mouth_only_benchmark_uses_mouth_only_composite(self, mock_pg):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        with (
            patch.object(
                LayeredSpriteRenderer,
                "_composite_mouth_only",
                autospec=True,
                side_effect=LayeredSpriteRenderer._composite_mouth_only,
            ) as spy_mouth,
            patch.object(
                LayeredSpriteRenderer,
                "_composite_full",
                autospec=True,
                side_effect=LayeredSpriteRenderer._composite_full,
            ) as spy_full,
        ):
            measure_crossfade_fps(
                width=64,
                height=64,
                frames=2,
                scope=CrossfadeScope.MOUTH_ONLY,
                clock=clock,
            )
        assert spy_mouth.called
        assert not spy_full.called

    def test_full_benchmark_uses_full_composite(self, mock_pg):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        clock = _fixed_clock([0.0, 0.010, 0.010, 0.020])
        with (
            patch.object(
                LayeredSpriteRenderer,
                "_composite_full",
                autospec=True,
                side_effect=LayeredSpriteRenderer._composite_full,
            ) as spy_full,
            patch.object(
                LayeredSpriteRenderer,
                "_composite_mouth_only",
                autospec=True,
                side_effect=LayeredSpriteRenderer._composite_mouth_only,
            ) as spy_mouth,
        ):
            measure_crossfade_fps(
                width=64, height=64, frames=2, scope=CrossfadeScope.FULL, clock=clock
            )
        assert spy_full.called
        assert not spy_mouth.called


# ---------------------------------------------------------------------------
# pygame fehlt → klarer RuntimeError statt obskurer Folgefehler
# ---------------------------------------------------------------------------


class TestPygameMissing:
    def test_raises_runtime_error_without_pygame(self):
        with patch("elder_berry.avatar.crossfade_benchmark.pygame", None):
            with pytest.raises(RuntimeError, match="pygame"):
                measure_crossfade_fps(width=64, height=64, frames=2)


# ---------------------------------------------------------------------------
# Sweep: FULL/MOUTH_ONLY x nativ/Fallback in einem Lauf (RPi5-Entscheidung)
# ---------------------------------------------------------------------------


class TestSweep:
    def test_covers_four_variants(self, mock_pg):
        results = sweep_crossfade_fps(width=720, height=1280, frames=2)
        assert len(results) == 4
        combos = {(r.scope, r.width, r.height) for r in results}
        assert (CrossfadeScope.FULL, 720, 1280) in combos
        assert (CrossfadeScope.MOUTH_ONLY, 720, 1280) in combos
        assert (CrossfadeScope.FULL, 540, 960) in combos
        assert (CrossfadeScope.MOUTH_ONLY, 540, 960) in combos

    def test_dedupes_when_native_equals_fallback(self, mock_pg):
        # Native == Fallback (540x960) → nur die zwei Scopes, keine Duplikate.
        results = sweep_crossfade_fps(width=540, height=960, frames=2)
        assert len(results) == 2
        assert {r.scope for r in results} == {
            CrossfadeScope.FULL,
            CrossfadeScope.MOUTH_ONLY,
        }


# ---------------------------------------------------------------------------
# Echte Komposition bei 720x1280 rotation=180 (§0.6) – nur mit echtem pygame
# ---------------------------------------------------------------------------


class TestRealComposite:
    """Validiert die echten SDL2-Operationen; übersprungen ohne pygame."""

    def test_720x1280_rotation180_composites(self):
        pytest.importorskip("pygame")
        # Loser Guard gegen katastrophale O(Pixel)-Regressionen – NICHT der
        # verbindliche 30-FPS-Beweis (der kommt vom RPi5-Lauf).
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
        assert result.mean_ms < 150.0  # machine-tolerant

    def test_mouth_only_real_composite_runs(self):
        pytest.importorskip("pygame")
        result = measure_crossfade_fps(
            width=320,
            height=480,
            rotation=180,
            frames=4,
            scope=CrossfadeScope.MOUTH_ONLY,
        )
        assert result.frames == 4
        assert result.scope is CrossfadeScope.MOUTH_ONLY
