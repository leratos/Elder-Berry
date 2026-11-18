"""Tests fuer CameraDiagnosticMode und frame_camera (Phase 111, E4, M6/D2)."""

from __future__ import annotations

import builtins
import logging
import os
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")
pytest.importorskip("PIL")
np = pytest.importorskip("numpy")

from PIL import Image  # noqa: E402

from elder_berry.room_display.camera_diagnostic_mode import (  # noqa: E402
    CameraDiagnosticMode,
)
from elder_berry.room_display.frame_camera import (  # noqa: E402
    af_status,
    build_camera,
    build_pipeline,
)
from elder_berry.room_display.frame_config import load_frame_config  # noqa: E402
from elder_berry.room_display.oriented_display import OrientedDisplay  # noqa: E402
from elder_berry.room_display.portrait.face_detector import (  # noqa: E402
    FaceBox,
    FaceDetection,
    FaceDetector,
)
from elder_berry.room_display.portrait.photo_pipeline import PhotoPipeline  # noqa: E402


class Camera:
    def capture_image(self):
        return Image.new("RGB", (2304, 1296), (100, 100, 100))


class OneFace(FaceDetector):
    name = "fake"

    def detect(self, image):
        return FaceDetection(faces=(FaceBox(800, 300, 400, 400),), duration_s=0.08)


@pytest.fixture
def display():
    pygame.display.init()
    screen = pygame.display.set_mode((720, 1280))
    yield OrientedDisplay(screen, 90)
    pygame.display.quit()


def _mode(detector=None, **kw):
    pipeline = PhotoPipeline(
        Camera(), detector or OneFace(), sleep=lambda s: None, preview_without_face=True
    )
    return CameraDiagnosticMode(
        pipeline, interval_s=2.0, af_status=lambda: "ja (scharf)", **kw
    )


def test_burst_every_interval_and_render(display):
    mode = _mode()
    mode.on_enter(display)
    assert mode.update(0.0) is True
    mode.render(display)
    assert mode.update(1.0) is False
    assert mode.update(1.9) is False
    assert mode.update(2.0) is True
    mode.render(display)
    assert mode.bursts == 2
    assert mode.render_count == 2


def test_one_log_line_per_burst(display, caplog):
    caplog.set_level(logging.INFO)
    mode = _mode()
    mode.on_enter(display)
    for t in (0.0, 0.5, 2.0, 2.5, 4.0):
        if mode.update(t):
            mode.render(display)
    lines = [r.getMessage() for r in caplog.records if "Kamera-Burst" in r.getMessage()]
    assert len(lines) == 3
    assert "Gesichter: 1" in lines[0]
    assert "Pruefung [fake] mittel 80 ms, max 80 ms" in lines[0]
    assert "AF ja (scharf)" in lines[0]


def test_no_face_is_shown_and_logged(display, caplog):
    caplog.set_level(logging.INFO)

    class NoFace(FaceDetector):
        name = "fake"

        def detect(self, image):
            return FaceDetection(duration_s=0.05)

    mode = _mode(NoFace())
    mode.on_enter(display)
    mode.update(0.0)
    mode.render(display)
    assert "KEIN GESICHT" in caplog.text


def test_no_file_written(display, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writes = []
    real_open = builtins.open

    def watched(file, mode="r", *a, **k):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            writes.append(str(file))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", watched)
    monkeypatch.setattr(
        pygame.image, "save", lambda *a, **k: writes.append("pygame.save")
    )
    mode = _mode()
    mode.on_enter(display)
    for t in (0.0, 2.0, 4.0):
        mode.update(t)
        mode.render(display)
    assert writes == []
    assert list(tmp_path.iterdir()) == []


def test_without_camera_shows_hint_once(display, caplog):
    caplog.set_level(logging.WARNING)
    mode = CameraDiagnosticMode(None)
    mode.on_enter(display)
    assert "keine Kamera" in caplog.text
    renders = sum(1 for t in range(5) if mode.update(float(t)))
    assert renders == 1
    mode.render(display)


# ---------------------------------------------------------------------------
# frame_camera + Konfiguration
# ---------------------------------------------------------------------------


class FakePicamera2:
    def __init__(self):
        self.camera_controls = {}
        self.started = False

    def create_still_configuration(self, main):
        return {"main": main}

    def configure(self, config):
        self.config = config

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        pass

    def capture_array(self):
        return np.zeros((36, 64, 3), dtype=np.uint8)


def _config(tmp_path, text=""):
    user = tmp_path / "frame_config.yaml"
    user.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_frame_config(user_path=user)


def test_camera_and_face_defaults(tmp_path):
    config = _config(tmp_path)
    c = config.camera
    assert c.resolution == (2304, 1296)
    assert (c.rotation, c.hflip, c.vflip) == (0, False, False)
    assert (c.autofocus, c.af_timeout_s, c.keep_warm) == (True, 2.0, True)
    assert (c.burst, c.burst_interval_s, c.jpeg_quality, c.target_edge) == (
        3,
        0.4,
        85,
        1024,
    )
    assert c.diagnostic_interval_s == 2.0
    assert (config.face.detector, config.face.cascade, config.face.detect_width) == (
        "haar",
        None,
        640,
    )


def test_camera_override(tmp_path):
    config = _config(
        tmp_path,
        """
        camera:
          rotation: 270
          hflip: true
          resolution: [1536, 864]
        face:
          detector: none
          cascade: ~/kaskade.xml
        """,
    )
    assert config.camera.rotation == 270 and config.camera.hflip
    assert config.camera.resolution == (1536, 864)
    assert config.camera.burst == 3
    assert config.face.detector == "none"
    assert config.face.cascade == Path("~/kaskade.xml").expanduser()


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("camera:\n  rotation: 45\n", "camera.rotation"),
        ("camera:\n  resolution: [100]\n", "resolution"),
        ("camera:\n  resolution: [99999, 1080]\n", "resolution"),
        ("camera:\n  burst: 0\n", "burst"),
        ("camera:\n  jpeg_quality: 100\n", "jpeg_quality"),
        ("camera:\n  hflip: 'ja'\n", "hflip"),
        ("camera:\n  af_timeout_s: 0\n", "af_timeout_s"),
        ("face:\n  detector: dnn\n", "face.detector"),
        ("face:\n  detect_width: 50\n", "detect_width"),
        ("face:\n  cascade: ''\n", "cascade"),
    ],
)
def test_invalid_camera_face_values(tmp_path, text, match):
    from elder_berry.room_display.frame_config import FrameConfigError

    with pytest.raises(FrameConfigError, match=match):
        _config(tmp_path, text)


def test_kamera_is_a_valid_view(tmp_path):
    config = _config(tmp_path, "mode:\n  diagnostic:\n    view: kamera\n")
    assert config.diagnostic.view == "kamera"


def test_build_camera_keep_warm_and_start_now(tmp_path):
    config = _config(tmp_path).camera
    fake = FakePicamera2()
    camera = build_camera(config, picamera2_factory=lambda: fake)
    assert camera is not None and fake.started  # keep_warm
    fake2 = FakePicamera2()
    lazy = build_camera(
        replace(config, keep_warm=False), picamera2_factory=lambda: fake2
    )
    assert lazy is not None and not fake2.started
    assert af_status(camera).startswith("nein")


def test_build_camera_unavailable(tmp_path, caplog):
    caplog.set_level(logging.WARNING)

    def missing():
        raise ImportError("No module named 'picamera2'")

    config = _config(tmp_path).camera
    assert build_camera(config, start_now=True, picamera2_factory=missing) is None
    assert "Kamera nicht verfuegbar" in caplog.text
    assert build_camera(replace(config, enabled=False)) is None


def test_build_pipeline_with_none_detector(tmp_path):
    config = _config(tmp_path, "face:\n  detector: none\n")
    camera = build_camera(config.camera, picamera2_factory=FakePicamera2)
    pipeline = build_pipeline(camera, config.camera, config.face)
    assert pipeline.detector_name == "none"
    with pipeline.capture() as result:
        assert result.has_face and not result.checked
