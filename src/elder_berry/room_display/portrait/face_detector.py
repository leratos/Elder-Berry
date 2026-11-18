"""FaceDetector -- Gesichtspruefung vor der Generierung (Phase 111, E4, D2).

Zweck (#1449 Punkt 3, §4.4 CAPTURE): Ohne erkennbares Gesicht keine
kostenpflichtige Generierung (z.B. eine greifende Hand vor dem Sensor), und
aus einem Burst wird die Aufnahme mit dem groessten Gesicht gewaehlt.

* :class:`NullFaceDetector` prueft nichts. Semantik: ``performed=False`` und
  keine Boxen. Die PhotoPipeline wertet das als "nicht geprueft, Gesicht
  angenommen" und nimmt die letzte Aufnahme (Rueckfall bei D2 = nein).
* ``HaarFaceDetector`` (eigene Datei) nutzt OpenCV-Haar-Kaskaden.
* :func:`build_face_detector` waehlt nach Konfiguration (``haar`` | ``none``).
  Fehlt cv2 oder die Kaskade, gibt es EINMAL eine WARNING und den Rueckfall
  auf ``none``. Keine Umschaltung zur Laufzeit (D2 entscheidet Lera).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Pillow nur fuer Typen
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)

DETECTOR_KINDS = ("haar", "none")


@dataclass(frozen=True)
class FaceBox:
    """Gesicht in Pixelkoordinaten des geprueften Bildes."""

    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class FaceDetection:
    """Ergebnis einer Pruefung.

    Attributes:
        faces: Gefundene Gesichter (leer = keins).
        performed: False beim NullFaceDetector -- dann sagt ``faces`` nichts.
        duration_s: Dauer der Pruefung.
    """

    faces: tuple[FaceBox, ...] = field(default=())
    performed: bool = True
    duration_s: float = 0.0

    @property
    def largest(self) -> FaceBox | None:
        return max(self.faces, key=lambda box: box.area, default=None)


class FaceDetector(ABC):
    """Findet Gesichter in einem RGB-Bild."""

    name = "abstract"

    @abstractmethod
    def detect(self, image: PILImage) -> FaceDetection:
        """Gesichter im Bild suchen (Koordinaten im Eingabebild)."""


class NullFaceDetector(FaceDetector):
    """Prueft nicht (D2 = nein). ``performed=False``, keine Boxen."""

    name = "none"

    def detect(self, image: PILImage) -> FaceDetection:
        return FaceDetection(faces=(), performed=False, duration_s=0.0)


def build_face_detector(
    kind: str, *, cascade_path: Path | None = None, detect_width: int = 640
) -> FaceDetector:
    """Detector nach Konfiguration; bei fehlendem cv2/Kaskade Rueckfall auf none."""
    if kind == "none":
        return NullFaceDetector()
    if kind != "haar":
        raise ValueError(
            f"face.detector muss eins von {DETECTOR_KINDS} sein (war: {kind!r})"
        )
    from elder_berry.room_display.portrait.haar_face_detector import (
        HaarFaceDetector,
        HaarUnavailableError,
    )

    try:
        return HaarFaceDetector(cascade_path=cascade_path, detect_width=detect_width)
    except HaarUnavailableError as exc:
        logger.warning(
            "Gesichtspruefung 'haar' nicht verfuegbar (%s) -- Rueckfall auf 'none' "
            "(keine Pruefung). Pi: sudo apt install python3-opencv opencv-data",
            exc,
        )
        return NullFaceDetector()
