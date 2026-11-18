"""Tests fuer FrameRateMeter und Crossfade (Phase 111, E2)."""

from __future__ import annotations

import logging

import pytest

from elder_berry.room_display.crossfade import Crossfade
from elder_berry.room_display.frame_rate_meter import FrameRateMeter


class TestFrameRateMeter:
    def test_logs_at_most_once_per_interval(self, caplog):
        caplog.set_level(
            logging.INFO, logger="elder_berry.room_display.frame_rate_meter"
        )
        meter = FrameRateMeter(log_interval_s=1.0)
        t = 0.0
        for _ in range(90):  # 3 s bei 30 FPS
            meter.frame(t)
            t += 1 / 30
        lines = [r.getMessage() for r in caplog.records]
        assert 2 <= len(lines) <= 3
        assert all("mittel 30.0" in line for line in lines)

    def test_line_contains_mean_min_and_frame_times(self, caplog):
        caplog.set_level(
            logging.INFO, logger="elder_berry.room_display.frame_rate_meter"
        )
        meter = FrameRateMeter(log_interval_s=10.0)
        for t in (0.0, 0.02, 0.04, 0.14):  # ein langsamer Frame (100 ms)
            meter.frame(t)
        meter.pause()
        line = caplog.records[-1].getMessage()
        assert "min 10.0" in line
        assert "max 100.0 ms" in line
        assert "n=3" in line

    def test_pause_excludes_standing_time(self):
        meter = FrameRateMeter()
        meter.frame(0.0)
        meter.frame(0.033)
        meter.pause()
        meter.frame(5.0)  # nach 5 s Standbild: kein 5-s-Frame
        meter.frame(5.033)
        stats = meter.summary()
        assert stats is not None
        assert stats.frames == 2
        assert stats.max_frame_ms == pytest.approx(33.0)

    def test_summary_none_without_frames(self):
        assert FrameRateMeter().summary() is None
        meter = FrameRateMeter()
        meter.frame(1.0)
        assert meter.summary() is None  # ein Frame = noch kein Abstand

    def test_pause_without_frames_is_silent(self, caplog):
        caplog.set_level(logging.INFO)
        FrameRateMeter().pause()
        assert caplog.records == []


class TestCrossfade:
    def test_progress_and_done(self):
        fade = Crossfade("a", "b", start=10.0, duration=2.0)
        assert fade.progress(9.0) == 0.0
        assert fade.progress(11.0) == 0.5
        assert fade.progress(13.0) == 1.0
        assert not fade.done(11.9)
        assert fade.done(12.0)
        assert (fade.source, fade.target) == ("a", "b")

    def test_duration_must_be_positive(self):
        with pytest.raises(ValueError):
            Crossfade("a", "b", start=0.0, duration=0)
