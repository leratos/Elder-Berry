"""Tests fuer PhotoPipeline (Phase 111, E4, §4.4 CAPTURE, §4.7 Loeschregel)."""

from __future__ import annotations

import builtins
import gc
import io
import logging
import weakref
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from elder_berry.room_display.portrait.face_detector import (  # noqa: E402
    FaceBox,
    FaceDetection,
    FaceDetector,
    NullFaceDetector,
)
from elder_berry.room_display.portrait.photo_pipeline import PhotoPipeline  # noqa: E402


class FakeCamera:
    def __init__(self, size=(2304, 1296)):
        self.size = size
        self.shots: list[weakref.ref] = []

    def capture_image(self):
        image = Image.new("RGB", self.size, (len(self.shots) * 40, 80, 120))
        self.shots.append(weakref.ref(image))
        return image


class ScriptedDetector(FaceDetector):
    """Liefert pro Aufruf die vorgegebenen Boxen (Koordinaten im Eingabebild)."""

    name = "fake"

    def __init__(self, per_shot):
        self.per_shot = list(per_shot)
        self.calls = 0

    def detect(self, image):
        faces = self.per_shot[self.calls]
        self.calls += 1
        return FaceDetection(faces=tuple(faces), performed=True, duration_s=0.05)


def _pipeline(camera, detector, **kw):
    return PhotoPipeline(camera, detector, sleep=lambda s: None, **kw)


def test_chooses_shot_with_largest_face():
    camera = FakeCamera()
    detector = ScriptedDetector(
        [
            [FaceBox(0, 0, 100, 100)],
            [FaceBox(500, 300, 400, 400)],
            [FaceBox(0, 0, 200, 200)],
        ]
    )
    with _pipeline(camera, detector).capture() as result:
        assert result.has_face and result.checked
        assert result.chosen_index == 1
        assert result.detect_s == (0.05, 0.05, 0.05)
        assert len(result.capture_s) == 3
        # Box auf das 1024er-Bild umgerechnet (Faktor 1024/2304)
        box = result.faces[0]
        assert (box.width, box.height) == (178, 178)


def test_no_face_gives_no_face_result_without_image():
    camera = FakeCamera()
    with _pipeline(camera, ScriptedDetector([[], [], []])).capture() as result:
        assert result.has_face is False
        assert result.checked is True
        assert result.jpeg is None
        assert result.preview is None
        assert result.chosen_index is None


def test_preview_without_face_only_for_diagnosis():
    camera = FakeCamera()
    pipeline = _pipeline(
        camera, ScriptedDetector([[], [], []]), preview_without_face=True
    )
    with pipeline.capture() as result:
        assert result.has_face is False
        assert result.jpeg is None  # nie ein JPEG ohne Gesicht
        assert result.preview is not None and max(result.preview.size) == 1024


def test_output_is_jpeg_with_long_edge_1024():
    camera = FakeCamera()
    with _pipeline(
        camera, ScriptedDetector([[FaceBox(0, 0, 50, 50)]] * 3)
    ).capture() as result:
        assert result.jpeg is not None and result.jpeg[:2] == b"\xff\xd8"
        with Image.open(io.BytesIO(result.jpeg)) as decoded:
            assert decoded.format == "JPEG"
            assert max(decoded.size) == 1024
            assert decoded.size == (1024, 576)


def test_small_images_are_not_enlarged():
    camera = FakeCamera(size=(640, 360))
    with _pipeline(
        camera, ScriptedDetector([[FaceBox(0, 0, 50, 50)]] * 3)
    ).capture() as result:
        assert result.preview.size == (640, 360)


def test_null_detector_takes_last_shot_unchecked():
    camera = FakeCamera()
    with _pipeline(camera, NullFaceDetector()).capture() as result:
        assert result.has_face is True
        assert result.checked is False
        assert result.chosen_index == 2
        assert result.faces == ()


def test_burst_count_and_interval():
    camera = FakeCamera()
    sleeps = []
    pipeline = PhotoPipeline(
        camera, NullFaceDetector(), burst=4, interval_s=0.25, sleep=sleeps.append
    )
    pipeline.capture().release()
    assert len(camera.shots) == 4
    assert sleeps == [0.25, 0.25, 0.25]


def test_release_drops_all_buffers_including_unchosen_shots():
    camera = FakeCamera()
    detector = ScriptedDetector([[FaceBox(0, 0, 10, 10)], [FaceBox(0, 0, 90, 90)], []])
    result = _pipeline(camera, detector).capture()
    preview_ref = weakref.ref(result.preview)
    gc.collect()
    # Original-Aufnahmen (gewaehlte und nicht gewaehlte) sind schon weg
    assert [ref() for ref in camera.shots] == [None, None, None]
    result.release()
    gc.collect()
    assert preview_ref() is None
    assert result.jpeg is None and result.preview is None


def test_buffers_dropped_when_detector_fails():
    camera = FakeCamera()

    class Boom(FaceDetector):
        name = "boom"

        def detect(self, image):
            raise RuntimeError("kaputt")

    with pytest.raises(RuntimeError):
        _pipeline(camera, Boom()).capture()
    gc.collect()
    assert [ref() for ref in camera.shots] == [None]


def test_no_file_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    writes = []
    real_open = builtins.open

    def watched_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            writes.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watched_open)
    monkeypatch.setattr(
        Path, "write_bytes", lambda self, data: writes.append(str(self))
    )
    camera = FakeCamera()
    detector = ScriptedDetector([[FaceBox(0, 0, 50, 50)]] * 3)
    _pipeline(camera, detector).capture().release()
    _pipeline(
        camera, ScriptedDetector([[], [], []]), preview_without_face=True
    ).capture().release()
    assert writes == []
    assert list(tmp_path.iterdir()) == []


def test_no_image_data_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    camera = FakeCamera()
    with _pipeline(
        camera, ScriptedDetector([[FaceBox(0, 0, 50, 50)]] * 3)
    ).capture() as result:
        jpeg = result.jpeg
    text = "\n".join(r.getMessage() + repr(r.args) for r in caplog.records)
    for marker in ("data:image", "base64,", "\\xff\\xd8", "JFIF"):
        assert marker not in text
    assert jpeg is not None
    assert "jpeg" not in repr(result).lower() or "jpeg=" not in repr(result)


def test_result_repr_hides_image_data():
    camera = FakeCamera()
    with _pipeline(camera, NullFaceDetector()).capture() as result:
        text = repr(result)
    assert "jpeg=" not in text and "preview=" not in text


@pytest.mark.parametrize(
    "kwargs", [{"burst": 0}, {"jpeg_quality": 0}, {"jpeg_quality": 100}]
)
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        PhotoPipeline(FakeCamera(), NullFaceDetector(), **kwargs)
