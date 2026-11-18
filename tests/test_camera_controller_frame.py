"""Tests fuer die Rahmen-Erweiterung von RPi5Camera (Phase 111, E4, Ae10).

Fake-picamera2 statt Hardware. Prueft capture_image (RGB, BGR korrigiert),
Ausrichtung, Autofokus nur wenn vorhanden, Warmhalten, und dass der
Stamm-Pfad (capture_jpeg, Defaults) unveraendert bleibt.
"""

from __future__ import annotations

import io
import logging

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from elder_berry.robot.camera_controller import (  # noqa: E402
    RPi5Camera,
    orient_image,
)

RED = (255, 0, 0)
BLACK = (0, 0, 0)


class FakePicamera2:
    """Minimaler Ersatz: liefert BGR-Arrays wie picamera2 bei RGB888."""

    instances = 0

    def __init__(
        self, *, with_af=True, wait_result=True, wait_error=None, size=(64, 36)
    ):
        FakePicamera2.instances += 1
        self.camera_controls = {"AfMode": (0, 2, 0)} if with_af else {}
        self.wait_result = wait_result
        self.wait_error = wait_error
        self.size = size
        self.set_controls_calls = []
        self.af_cycles = 0
        self.started = False
        self.closed = False
        self.config = None

    def create_still_configuration(self, main):
        return {"main": main}

    def configure(self, config):
        self.config = config

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def set_controls(self, controls):
        self.set_controls_calls.append(controls)

    def autofocus_cycle(self, wait=True):
        assert wait is False
        self.af_cycles += 1
        return "job"

    def wait(self, job, timeout=None):
        assert job == "job"
        if self.wait_error is not None:
            raise self.wait_error
        return self.wait_result

    def capture_array(self):
        width, height = self.size
        bgr = np.zeros((height, width, 3), dtype=np.uint8)
        bgr[0:4, 0:4] = (0, 0, 255)  # BGR-Rot oben links
        return bgr


def _camera(fake, **kwargs):
    return RPi5Camera((64, 36), picamera2_factory=lambda: fake, **kwargs)


def _rgb(image, pos):
    return image.convert("RGB").getpixel(pos)


def test_capture_image_is_rgb_with_bgr_corrected():
    image = _camera(FakePicamera2()).capture_image()
    assert image.mode == "RGB"
    assert image.size == (64, 36)
    assert _rgb(image, (1, 1)) == RED  # nicht Blau
    assert _rgb(image, (40, 20)) == BLACK


@pytest.mark.parametrize(
    ("kwargs", "size", "corner"),
    [
        ({}, (64, 36), (1, 1)),
        ({"rotation": 90}, (36, 64), (1, 62)),
        ({"rotation": 180}, (64, 36), (62, 34)),
        ({"rotation": 270}, (36, 64), (34, 1)),
        ({"hflip": True}, (64, 36), (62, 1)),
        ({"vflip": True}, (64, 36), (1, 34)),
    ],
)
def test_orientation_moves_marker(kwargs, size, corner):
    image = _camera(FakePicamera2(), **kwargs).capture_image()
    assert image.size == size
    assert _rgb(image, corner) == RED


def test_orient_image_flips_before_rotation():
    base = Image.new("RGB", (10, 6))
    base.putpixel((0, 0), RED)
    image = orient_image(base, rotation=90, hflip=True)
    # hflip: Marke nach oben rechts; dann 90 Grad gg. Uhrzeigersinn: oben links
    assert image.getpixel((0, 0)) == RED


def test_invalid_rotation():
    with pytest.raises(ValueError):
        RPi5Camera(rotation=45)
    with pytest.raises(ValueError):
        orient_image(Image.new("RGB", (2, 2)), rotation=30)


def test_autofocus_cycle_when_available():
    fake = FakePicamera2(with_af=True)
    camera = _camera(fake, autofocus=True)
    camera.capture_image()
    camera.capture_image()
    assert camera.has_autofocus
    assert fake.af_cycles == 2
    assert camera.last_af_ok is True
    assert len(fake.set_controls_calls) == 1
    assert "AfMode" in fake.set_controls_calls[0]


def test_no_autofocus_logs_info_once(caplog):
    caplog.set_level(logging.INFO)
    fake = FakePicamera2(with_af=False)
    camera = _camera(fake, autofocus=True)
    for _ in range(3):
        camera.capture_image()
    assert fake.af_cycles == 0
    assert not camera.has_autofocus
    assert caplog.text.count("ohne Autofokus") == 1
    assert fake.set_controls_calls == []


def test_autofocus_timeout_warns_and_still_captures(caplog):
    caplog.set_level(logging.WARNING)
    fake = FakePicamera2(wait_error=TimeoutError("af"))
    camera = _camera(fake, autofocus=True)
    image = camera.capture_image()
    assert image.size == (64, 36)
    assert camera.last_af_ok is False
    assert "Autofokus-Zyklus abgebrochen" in caplog.text


def test_autofocus_unsharp_result():
    camera = _camera(FakePicamera2(wait_result=False), autofocus=True)
    camera.capture_image()
    assert camera.last_af_ok is False


def test_keep_warm_opens_once():
    FakePicamera2.instances = 0
    fake = FakePicamera2()
    calls = []

    def factory():
        calls.append(1)
        return fake

    camera = RPi5Camera((64, 36), picamera2_factory=factory)
    camera.start()
    assert fake.started
    for _ in range(3):
        camera.capture_image()
    assert len(calls) == 1
    assert camera.last_capture_s is not None


def test_start_without_picamera2_raises_runtime_error():
    def missing():
        raise ImportError("No module named 'picamera2'")

    with pytest.raises(RuntimeError, match="python3-picamera2"):
        RPi5Camera(picamera2_factory=missing).start()


def test_stamm_defaults_unchanged():
    """Stamm-Pfad: Defaults ohne AF/Drehung, capture_jpeg wie bisher."""
    fake = FakePicamera2(with_af=True)
    camera = RPi5Camera(picamera2_factory=lambda: fake)
    assert camera.get_resolution() == (1920, 1080)
    data = camera.capture_jpeg(quality=80)
    assert data[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(data)) as decoded:
        assert decoded.size == (64, 36)
    assert fake.af_cycles == 0
    assert fake.set_controls_calls == []
    assert fake.config == {"main": {"size": (1920, 1080), "format": "RGB888"}}


def test_close():
    fake = FakePicamera2()
    camera = _camera(fake)
    camera.start()
    camera.close()
    assert fake.closed
