"""Tests fuer FaceDetector, NullFaceDetector, HaarFaceDetector (Phase 111, E4, D2)."""

from __future__ import annotations

import builtins
import logging
from pathlib import Path

import pytest

from elder_berry.room_display.portrait.face_detector import (
    FaceBox,
    FaceDetection,
    NullFaceDetector,
    build_face_detector,
)


def test_face_box_area_and_largest():
    detection = FaceDetection(faces=(FaceBox(0, 0, 10, 10), FaceBox(5, 5, 30, 20)))
    assert detection.largest == FaceBox(5, 5, 30, 20)
    assert FaceDetection().largest is None


def test_null_detector_semantics():
    detection = NullFaceDetector().detect(object())  # Bild wird nicht angesehen
    assert detection.performed is False
    assert detection.faces == ()
    assert NullFaceDetector.name == "none"


def test_build_none():
    assert isinstance(build_face_detector("none"), NullFaceDetector)


def test_build_unknown_kind():
    with pytest.raises(ValueError):
        build_face_detector("dnn")


def test_missing_cv2_falls_back_once(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    real_import = builtins.__import__

    def no_cv2(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("No module named 'cv2'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cv2)
    detector = build_face_detector("haar")
    assert isinstance(detector, NullFaceDetector)
    assert caplog.text.count("nicht verfuegbar") == 1
    assert "python3-opencv" in caplog.text


def test_missing_cascade_raises_unavailable(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    from elder_berry.room_display.portrait import haar_face_detector as haar

    class FakeCv2:
        data = None

        def CascadeClassifier(self, path):  # noqa: N802 -- OpenCV-API
            raise AssertionError("darf nicht geladen werden")

    original = haar.APT_CASCADE_DIR
    haar.APT_CASCADE_DIR = tmp_path / "leer"
    try:
        with pytest.raises(haar.HaarUnavailableError, match="Kaskade nicht gefunden"):
            haar.HaarFaceDetector(
                cv2_module=FakeCv2(), cascade_path=tmp_path / "fehlt.xml"
            )
    finally:
        haar.APT_CASCADE_DIR = original


def test_opencv_without_cascade_classifier_falls_back():
    """OpenCV 5.x hat keinen CascadeClassifier mehr -> sauberer Rueckfall."""
    from elder_berry.room_display.portrait import haar_face_detector as haar

    class Cv2Five:
        __version__ = "5.1.0"

    with pytest.raises(haar.HaarUnavailableError, match="CascadeClassifier"):
        haar.HaarFaceDetector(cv2_module=Cv2Five())


def test_find_cascade_prefers_configured(tmp_path):
    from elder_berry.room_display.portrait.haar_face_detector import find_cascade

    configured = tmp_path / "mine.xml"
    configured.write_text("<x/>", encoding="utf-8")
    assert find_cascade(configured, object()) == configured


# ---------------------------------------------------------------------------
# Echte Haar-Kaskade (nur wenn cv2 + Kaskade vorhanden)
# ---------------------------------------------------------------------------


@pytest.fixture
def haar():
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from elder_berry.room_display.portrait.haar_face_detector import (
        HaarFaceDetector,
        HaarUnavailableError,
    )

    try:
        return HaarFaceDetector(detect_width=320, cv2_module=cv2)
    except HaarUnavailableError as exc:
        pytest.skip(f"Kaskade nicht vorhanden: {exc}")


def test_haar_synthetic_image_without_face(haar):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1280, 720), (90, 120, 150))
    draw = ImageDraw.Draw(image)
    for x in range(0, 1280, 80):
        draw.line([(x, 0), (x, 719)], fill=(200, 200, 200), width=3)
    detection = haar.detect(image)
    assert detection.performed is True
    assert detection.faces == ()
    assert detection.duration_s >= 0
    assert isinstance(haar.cascade_path, Path)


def test_haar_boxes_are_scaled_back(haar, monkeypatch):
    from PIL import Image

    class FixedClassifier:
        def detectMultiScale(self, array, **kwargs):  # noqa: N802 -- OpenCV-API
            assert array.shape == (180, 320)  # Pruefbreite 320
            return [(10, 20, 40, 40)]

    monkeypatch.setattr(haar, "_classifier", FixedClassifier())
    detection = haar.detect(Image.new("RGB", (1280, 720)))
    assert detection.faces == (FaceBox(40, 80, 160, 160),)
