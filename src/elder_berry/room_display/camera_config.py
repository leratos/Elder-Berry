"""Kamera- und Gesichts-Sektionen der frame_config (Phase 111, E4).

* ``camera``: Aufloesung, Ausrichtung, Autofokus, Warmhalten, Burst,
  JPEG-Qualitaet und Zielgroesse (§4.4 CAPTURE).
* ``face``: Gesichtspruefung ``haar`` | ``none`` (D2), Kaskade, Pruefbreite.

Ungueltige Werte brechen mit ``FrameConfigError`` ab (Muster E2/E3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elder_berry.room_display.config_values import (
    FrameConfigError,
    boolean,
    int_in_range,
    number_in_range,
    section,
)
from elder_berry.room_display.portrait.face_detector import DETECTOR_KINDS


@dataclass(frozen=True)
class CameraConfig:
    enabled: bool
    resolution: tuple[int, int]
    rotation: int
    hflip: bool
    vflip: bool
    autofocus: bool
    af_timeout_s: float
    keep_warm: bool
    burst: int
    burst_interval_s: float
    jpeg_quality: int
    target_edge: int
    diagnostic_interval_s: float


@dataclass(frozen=True)
class FaceConfig:
    detector: str
    cascade: Path | None
    detect_width: int


def _resolution(value: object, where: str) -> tuple[int, int]:
    if (
        not isinstance(value, list | tuple)
        or len(value) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        raise FrameConfigError(f"{where} muss [Breite, Hoehe] sein (war: {value!r})")
    width = int_in_range(value[0], f"{where}[0]", 320, 4608)
    height = int_in_range(value[1], f"{where}[1]", 240, 2592)
    return (width, height)


def parse_camera(data: Mapping[str, Any], source: str) -> CameraConfig:
    c = section(data, "camera", source)
    w = f"{source}: camera"
    rotation = c.get("rotation")
    if rotation not in (0, 90, 180, 270) or isinstance(rotation, bool):
        raise FrameConfigError(
            f"{w}.rotation muss 0, 90, 180 oder 270 sein (war: {rotation!r})"
        )
    return CameraConfig(
        enabled=boolean(c.get("enabled", True), f"{w}.enabled"),
        resolution=_resolution(c.get("resolution"), f"{w}.resolution"),
        rotation=int(rotation),
        hflip=boolean(c.get("hflip"), f"{w}.hflip"),
        vflip=boolean(c.get("vflip"), f"{w}.vflip"),
        autofocus=boolean(c.get("autofocus"), f"{w}.autofocus"),
        af_timeout_s=number_in_range(
            c.get("af_timeout_s"), f"{w}.af_timeout_s", 0.1, 10
        ),
        keep_warm=boolean(c.get("keep_warm"), f"{w}.keep_warm"),
        burst=int_in_range(c.get("burst"), f"{w}.burst", 1, 10),
        burst_interval_s=number_in_range(
            c.get("burst_interval_s"), f"{w}.burst_interval_s", 0, 5
        ),
        jpeg_quality=int_in_range(c.get("jpeg_quality"), f"{w}.jpeg_quality", 1, 95),
        target_edge=int_in_range(c.get("target_edge"), f"{w}.target_edge", 256, 4096),
        diagnostic_interval_s=number_in_range(
            c.get("diagnostic_interval_s"), f"{w}.diagnostic_interval_s", 0.5, 60
        ),
    )


def parse_face(data: Mapping[str, Any], source: str) -> FaceConfig:
    f = section(data, "face", source)
    w = f"{source}: face"
    detector = f.get("detector")
    if detector not in DETECTOR_KINDS:
        raise FrameConfigError(
            f"{w}.detector muss eins von {list(DETECTOR_KINDS)} sein (war: {detector!r})"
        )
    cascade = f.get("cascade")
    if cascade is not None and (not isinstance(cascade, str) or not cascade.strip()):
        raise FrameConfigError(f"{w}.cascade muss ein Pfad oder null sein")
    return FaceConfig(
        detector=str(detector),
        cascade=Path(cascade).expanduser() if isinstance(cascade, str) else None,
        detect_width=int_in_range(
            f.get("detect_width"), f"{w}.detect_width", 160, 1920
        ),
    )
