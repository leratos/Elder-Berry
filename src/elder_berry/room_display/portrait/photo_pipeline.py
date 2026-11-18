"""PhotoPipeline -- Aufnahme, Auswahl und Aufbereitung des Gaestefotos (E4).

Phase 111, Konzept §4.2/§4.4 (CAPTURE)/§4.7 (Loeschregel):

1. ``burst`` Aufnahmen (Default 3) im Abstand ``interval_s`` (Default 0,4 s)
   ueber ein schmales Kamera-Protocol (Ae10: nur ``capture_image``).
2. Jede Aufnahme wird auf Gesichter geprueft. Gewaehlt wird die Aufnahme
   mit dem groessten Gesicht. Gibt es keins: Ergebnis "kein Gesicht"
   (``has_face=False``) -- dann KEINE Generierung (§4.4 FALLBACK).
   Beim NullFaceDetector (nicht geprueft) gilt die letzte Aufnahme als
   gewaehlt und ``has_face`` als True.
3. Die gewaehlte Aufnahme wird auf ``target_edge`` (1024 px) lange Kante
   verkleinert und als JPEG im RAM kodiert.

Datenschutz per Konstruktion: Nichts wird auf einen Datentraeger
geschrieben, nichts von den Bilddaten geloggt. Nicht gewaehlte Aufnahmen
werden im ``finally`` verworfen, das Ergebnis per :meth:`PhotoResult.release`
bzw. als Context-Manager.
"""

from __future__ import annotations

import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Protocol

from elder_berry.room_display.portrait.face_detector import (
    FaceBox,
    FaceDetection,
    FaceDetector,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)


class ImageCamera(Protocol):
    """Schmales Kamera-Protocol (Ae10)."""

    def capture_image(self) -> PILImage: ...


@dataclass
class PhotoResult:
    """Ergebnis eines Bursts. Bilddaten nicht im ``repr``.

    Attributes:
        has_face: True, wenn ein Gesicht gefunden wurde (oder nicht geprueft).
        checked: False beim NullFaceDetector.
        jpeg: JPEG des gewaehlten Bildes (lange Kante ``target_edge``), sonst None.
        preview: Gewaehltes Bild verkleinert (fuer Diagnose), sonst None.
        faces: Gesichter des gewaehlten Bildes, in Koordinaten von ``preview``.
        chosen_index: Index der gewaehlten Aufnahme im Burst.
        capture_s / detect_s: Dauer je Aufnahme bzw. Pruefung.
    """

    has_face: bool
    checked: bool
    chosen_index: int | None
    jpeg: bytes | None = field(default=None, repr=False)
    preview: PILImage | None = field(default=None, repr=False)
    faces: tuple[FaceBox, ...] = ()
    capture_s: tuple[float, ...] = ()
    detect_s: tuple[float, ...] = ()

    def release(self) -> None:
        """Alle Bilddaten verwerfen (idempotent)."""
        self.jpeg = None
        self.preview = None

    def __enter__(self) -> PhotoResult:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def _scale_box(box: FaceBox, factor: float) -> FaceBox:
    return FaceBox(
        x=round(box.x * factor),
        y=round(box.y * factor),
        width=round(box.width * factor),
        height=round(box.height * factor),
    )


class PhotoPipeline:
    """Burst -> Auswahl -> Verkleinern -> JPEG, nur im RAM.

    Args:
        camera: Liefert PIL-Bilder (``RPi5Camera`` oder Fake).
        detector: Gesichtspruefung.
        burst: Anzahl Aufnahmen.
        interval_s: Abstand zwischen zwei Aufnahmen.
        target_edge: Lange Kante des Ergebnisses.
        jpeg_quality: JPEG-Qualitaet 1-95.
        preview_without_face: Nur Diagnose (M6): auch ohne Gesicht die letzte
            Aufnahme verkleinert als ``preview`` liefern (nie als JPEG).
        sleep: Wartefunktion (Tests: no-op).
        clock: Monotone Zeitquelle.
    """

    def __init__(
        self,
        camera: ImageCamera,
        detector: FaceDetector,
        *,
        burst: int = 3,
        interval_s: float = 0.4,
        target_edge: int = 1024,
        jpeg_quality: int = 85,
        preview_without_face: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if burst < 1:
            raise ValueError("burst muss >= 1 sein")
        if not 1 <= jpeg_quality <= 95:
            raise ValueError("jpeg_quality muss zwischen 1 und 95 liegen")
        self._camera = camera
        self._detector = detector
        self._burst = burst
        self._interval = interval_s
        self._target_edge = target_edge
        self._quality = jpeg_quality
        self._preview_without_face = preview_without_face
        self._sleep = sleep
        self._clock = clock

    @property
    def detector_name(self) -> str:
        return self._detector.name

    def capture(self) -> PhotoResult:
        """Einen Burst aufnehmen und auswerten. Das Ergebnis freigeben!"""
        shots: list[PILImage] = []
        detections: list[FaceDetection] = []
        capture_s: list[float] = []
        try:
            for index in range(self._burst):
                if index:
                    self._sleep(self._interval)
                started = self._clock()
                shots.append(self._camera.capture_image())
                capture_s.append(self._clock() - started)
                detections.append(self._detector.detect(shots[-1]))
            return self._build(shots, detections, capture_s)
        finally:
            # Loeschregel §4.7: nicht gewaehlte (und die Original-) Aufnahmen
            # verwerfen, egal wie der Burst endet.
            shots.clear()
            detections.clear()

    def _build(
        self,
        shots: list[PILImage],
        detections: list[FaceDetection],
        capture_s: list[float],
    ) -> PhotoResult:
        detect_s = tuple(d.duration_s for d in detections)
        checked = all(d.performed for d in detections)
        if checked:
            candidates = [
                (d.largest.area, i) for i, d in enumerate(detections) if d.largest
            ]
            if not candidates:
                preview = (
                    self._resize(shots[-1])[0] if self._preview_without_face else None
                )
                return PhotoResult(
                    has_face=False,
                    checked=True,
                    chosen_index=None,
                    preview=preview,
                    capture_s=tuple(capture_s),
                    detect_s=detect_s,
                )
            chosen = max(candidates)[1]
        else:
            chosen = len(shots) - 1
        resized, factor = self._resize(shots[chosen])
        buffer = io.BytesIO()
        resized.convert("RGB").save(buffer, format="JPEG", quality=self._quality)
        faces = tuple(_scale_box(box, factor) for box in detections[chosen].faces)
        return PhotoResult(
            has_face=True,
            checked=checked,
            chosen_index=chosen,
            jpeg=buffer.getvalue(),
            preview=resized,
            faces=faces,
            capture_s=tuple(capture_s),
            detect_s=detect_s,
        )

    def _resize(self, image: PILImage) -> tuple[PILImage, float]:
        """Lange Kante auf ``target_edge`` (nie vergroessern); immer eine Kopie."""
        factor = min(1.0, self._target_edge / max(image.size))
        size = (
            max(1, round(image.width * factor)),
            max(1, round(image.height * factor)),
        )
        return (image.resize(size) if factor < 1.0 else image.copy()), factor
