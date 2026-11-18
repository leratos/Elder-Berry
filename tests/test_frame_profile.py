"""Tests fuer frame_profile (Phase 111, E2, §4.1, Ae9). pygame dummy."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from elder_berry.room_display import frame_profile  # noqa: E402
from elder_berry.room_display.frame_config import (  # noqa: E402
    apply_overrides,
    load_frame_config,
)


def _args(**kwargs) -> argparse.Namespace:
    base = {
        "width": 720,
        "height": 1280,
        "rotation": 180,
        "frame_config": None,
        "frame_rotation": None,
        "frame_fps": None,
        "frame_video_driver": None,
        "frame_view": None,
        "frame_windowed": False,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def _short_config(tmp_path: Path, view: str = "ueberblendung") -> Path:
    path = tmp_path / "frame.yaml"
    path.write_text(
        "display:\n  transition_s: 0.1\n  fps: 120\n  video_driver: dummy\n"
        f"mode:\n  diagnostic:\n    view: {view}\n    hold_s: 0.0\n    transitions: 2\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _no_user_override(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "elder_berry.room_display.frame_config.USER_CONFIG_PATH",
        tmp_path / "keiner.yaml",
    )


def test_ueberblendung_runs_and_cleans_up(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    code = frame_profile.run_frame(_args(frame_config=_short_config(tmp_path)))
    assert code == 0
    assert "M4' Ergebnis nach 2 Ueberblendungen" in caplog.text
    assert "Physische Displaygroesse" in caplog.text
    assert not pygame.display.get_init()  # pygame.quit() gelaufen


def test_overrides_from_cli(tmp_path):
    config = frame_profile.config_from_args(
        _args(
            frame_config=_short_config(tmp_path),
            frame_rotation=270,
            frame_fps=25,
            frame_view="testbild",
            frame_video_driver="dummy",
        )
    )
    assert config.display.rotation == 270
    assert config.display.fps == 25
    assert config.diagnostic.view == "testbild"


def test_stamm_arguments_are_ignored_with_warning(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    config = frame_profile.config_from_args(
        _args(frame_config=_short_config(tmp_path), width=100, rotation=0)
    )
    assert config.display.rotation == 90  # nicht --rotation 0
    assert "--width gilt nur fuer das Profil stamm" in caplog.text
    assert "--rotation gilt nur fuer das Profil stamm" in caplog.text
    assert "--height" not in caplog.text


def test_invalid_config_returns_2(tmp_path, caplog):
    bad = tmp_path / "bad.yaml"
    bad.write_text("display:\n  rotation: 45\n", encoding="utf-8")
    assert frame_profile.run_frame(_args(frame_config=bad)) == 2
    assert "Konfiguration ungueltig" in caplog.text


def test_display_init_failure_returns_1(tmp_path, caplog):
    config = apply_overrides(
        load_frame_config(_short_config(tmp_path)), video_driver="gibt-es-nicht"
    )
    try:
        assert frame_profile.run_with_config(config) == 1
    finally:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    assert "Display-Init fehlgeschlagen" in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM-Zustellung nur POSIX")
def test_sigterm_ends_cleanly_with_exit_0(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    previous = signal.getsignal(signal.SIGTERM)
    timer = threading.Timer(0.5, signal.raise_signal, args=(signal.SIGTERM,))
    timer.start()
    try:
        code = frame_profile.run_frame(
            _args(frame_config=_short_config(tmp_path, view="testbild"))
        )
    finally:
        timer.cancel()
    assert code == 0
    assert "Signal 15 empfangen" in caplog.text
    assert not pygame.display.get_init()
    assert signal.getsignal(signal.SIGTERM) == previous  # Handler zurueckgesetzt


def test_windowed_flag_is_passed_through(tmp_path):
    seen = {}
    original = frame_profile.run_with_config

    def capture(config, *, windowed=False):
        seen["windowed"] = windowed
        return 0

    frame_profile.run_with_config = capture
    try:
        frame_profile.run_frame(
            _args(frame_config=_short_config(tmp_path), frame_windowed=True)
        )
    finally:
        frame_profile.run_with_config = original
    assert seen["windowed"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM-Zustellung nur POSIX")
def test_naeherung_without_sensor_and_thermal_thread_stops(tmp_path, caplog):
    """E3: Ansicht naeherung laeuft ohne I2C-Geraet; Thermal-Thread endet mit."""
    caplog.set_level(logging.INFO)
    timer = threading.Timer(0.5, signal.raise_signal, args=(signal.SIGTERM,))
    timer.start()
    try:
        code = frame_profile.run_frame(
            _args(frame_config=_short_config(tmp_path), frame_view="naeherung")
        )
    finally:
        timer.cancel()
    assert code == 0
    assert "Naeherungsansicht:" in caplog.text  # mit oder ohne Sensor gestartet
    assert "Temperatur: CPU" in caplog.text
    assert not any(t.name == "thermal-monitor" for t in threading.enumerate())


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM-Zustellung nur POSIX")
def test_kamera_view_without_camera_runs_and_stops(tmp_path, caplog, monkeypatch):
    """E4: Ansicht kamera laeuft ohne picamera2 mit Hinweis und endet sauber."""
    caplog.set_level(logging.INFO)

    def no_picamera2():
        raise ImportError("No module named 'picamera2'")

    monkeypatch.setattr(
        "elder_berry.robot.camera_controller._default_picamera2_factory", no_picamera2
    )
    timer = threading.Timer(0.5, signal.raise_signal, args=(signal.SIGTERM,))
    timer.start()
    try:
        code = frame_profile.run_frame(
            _args(frame_config=_short_config(tmp_path), frame_view="kamera")
        )
    finally:
        timer.cancel()
    assert code == 0
    assert "Kamera nicht verfuegbar" in caplog.text
    assert "Kamera-Ansicht: keine Kamera" in caplog.text
