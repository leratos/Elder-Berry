"""frame_camera -- Kamera-Wiring fuer das Profil "frame" (Phase 111, E4).

Baut aus der frame_config die ``RPi5Camera`` (ausgerichtet, Autofokus,
optional warm gestartet), den FaceDetector und die PhotoPipeline. Fehlende
Hardware ist kein Startfehler: einmal WARNING, weiter ohne Kamera.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from elder_berry.robot.camera_controller import RPi5Camera
from elder_berry.room_display.camera_config import CameraConfig, FaceConfig
from elder_berry.room_display.portrait.face_detector import build_face_detector
from elder_berry.room_display.portrait.photo_pipeline import PhotoPipeline

logger = logging.getLogger(__name__)


def build_camera(
    config: CameraConfig,
    *,
    start_now: bool | None = None,
    picamera2_factory: Callable[[], Any] | None = None,
) -> RPi5Camera | None:
    """Kamera bauen und (bei keep_warm bzw. ``start_now``) sofort starten.

    ``start_now`` ueberschreibt ``keep_warm`` (die Diagnoseansicht startet
    immer sofort, damit ein Kamerafehler beim Start auffaellt und nicht
    mitten in der Render-Schleife). ``None`` wenn aus oder nicht startbar.
    """
    if not config.enabled:
        logger.info("Kamera in der Konfiguration abgeschaltet.")
        return None
    camera = RPi5Camera(
        config.resolution,
        rotation=config.rotation,
        hflip=config.hflip,
        vflip=config.vflip,
        autofocus=config.autofocus,
        af_timeout_s=config.af_timeout_s,
        picamera2_factory=picamera2_factory,
    )
    if config.keep_warm if start_now is None else start_now:
        try:
            camera.start()
        except RuntimeError as exc:
            logger.warning("Kamera nicht verfuegbar: %s", exc)
            return None
    return camera


def build_pipeline(
    camera: RPi5Camera,
    camera_config: CameraConfig,
    face_config: FaceConfig,
    *,
    preview_without_face: bool = False,
) -> PhotoPipeline:
    detector = build_face_detector(
        face_config.detector,
        cascade_path=face_config.cascade,
        detect_width=face_config.detect_width,
    )
    return PhotoPipeline(
        camera,
        detector,
        burst=camera_config.burst,
        interval_s=camera_config.burst_interval_s,
        target_edge=camera_config.target_edge,
        jpeg_quality=camera_config.jpeg_quality,
        preview_without_face=preview_without_face,
    )


def af_status(camera: RPi5Camera) -> str:
    """Anzeige-Text fuer den Autofokus der letzten Aufnahme."""
    if not camera.has_autofocus:
        return "nein (Kamera ohne AfMode)"
    if camera.last_af_ok is None:
        return "ja (noch kein Zyklus)"
    return "ja (scharf)" if camera.last_af_ok else "ja (NICHT scharf/Timeout)"
