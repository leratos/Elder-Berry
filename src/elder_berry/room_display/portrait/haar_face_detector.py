"""HaarFaceDetector -- Gesichtspruefung mit OpenCV-Haar-Kaskade (Phase 111, E4, D2).

OpenCV kommt auf dem Pi NUR per apt (``python3-opencv``, Kaskaden in
``opencv-data``), nicht per pip -- Picamera2-Handbuch §2.6.1. ``cv2`` wird
deshalb lazy importiert; fehlt es, wirft der Konstruktor
:class:`HaarUnavailableError` und ``build_face_detector`` faellt auf
``none`` zurueck.

Kaskade: ``haarcascade_frontalface_default.xml``. Gesucht wird (in dieser
Reihenfolge) im konfigurierten Pfad, in ``cv2.data.haarcascades`` (pip-
Variante) und in ``/usr/share/opencv4/haarcascades`` (apt ``opencv-data``).

OpenCV 5.x (pip, z.B. 5.1) enthaelt KEIN ``CascadeClassifier`` mehr und
liefert keine Kaskaden mit (festgestellt in E4). Auch das fuehrt zum sauberen
Rueckfall statt zu einem AttributeError. Auf dem Pi kommt OpenCV aus apt
(4.x); ob dort ``CascadeClassifier`` und die Kaskaden da sind, prueft
M-E0-3.

Erkannt wird auf einer verkleinerten Graustufenkopie (``detect_width``,
Default 640 px). Die Boxen werden auf das Eingabebild zurueckgerechnet.
Die Dauer jeder Pruefung steht im Ergebnis (D2: < 300 ms auf dem Pi 5).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.room_display.portrait.face_detector import (
    FaceBox,
    FaceDetection,
    FaceDetector,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)

CASCADE_FILE = "haarcascade_frontalface_default.xml"
APT_CASCADE_DIR = Path("/usr/share/opencv4/haarcascades")


class HaarUnavailableError(RuntimeError):
    """cv2 oder die Kaskaden-Datei fehlt."""


def find_cascade(configured: Path | None, cv2_module: Any) -> Path:
    """Kaskaden-Datei suchen; wirft HaarUnavailableError, wenn keine da ist."""
    candidates: list[Path] = []
    if configured is not None:
        candidates.append(configured)
    data = getattr(cv2_module, "data", None)
    pip_dir = getattr(data, "haarcascades", None)
    if pip_dir:
        candidates.append(Path(pip_dir) / CASCADE_FILE)
    candidates.append(APT_CASCADE_DIR / CASCADE_FILE)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise HaarUnavailableError(
        "Kaskade nicht gefunden (gesucht: "
        + ", ".join(str(c) for c in candidates)
        + ")"
    )


class HaarFaceDetector(FaceDetector):
    """Frontale Gesichter per Haar-Kaskade.

    Args:
        cascade_path: Explizite Kaskaden-Datei (sonst Suche, siehe Modul).
        detect_width: Breite der Graustufenkopie fuer die Erkennung.
        scale_factor / min_neighbors: OpenCV-Parameter.
        min_face_ratio: Kleinstes Gesicht relativ zur Prueflaenge (Breite).
        cv2_module: Fuer Tests; Default ``import cv2``.

    Raises:
        HaarUnavailableError: cv2 fehlt oder Kaskade nicht ladbar.
    """

    name = "haar"

    def __init__(
        self,
        *,
        cascade_path: Path | None = None,
        detect_width: int = 640,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_face_ratio: float = 0.08,
        cv2_module: Any = None,
    ) -> None:
        if cv2_module is None:
            try:
                import cv2 as imported_cv2
            except ImportError as exc:
                raise HaarUnavailableError(f"cv2 nicht importierbar ({exc})") from exc
            cv2_module = imported_cv2
        self._cv2 = cv2_module
        if not hasattr(cv2_module, "CascadeClassifier"):
            version = getattr(cv2_module, "__version__", "?")
            raise HaarUnavailableError(
                f"OpenCV {version} hat keinen CascadeClassifier (ab OpenCV 5 entfernt)"
            )
        path = find_cascade(cascade_path, cv2_module)
        classifier = cv2_module.CascadeClassifier(str(path))
        if classifier.empty():
            raise HaarUnavailableError(f"Kaskade nicht ladbar: {path}")
        self._classifier = classifier
        self._detect_width = detect_width
        self._scale_factor = scale_factor
        self._min_neighbors = min_neighbors
        self._min_face_ratio = min_face_ratio
        self.cascade_path = path
        logger.info(
            "Gesichtspruefung 'haar' bereit: %s, Pruefbreite %d px", path, detect_width
        )

    def detect(self, image: PILImage) -> FaceDetection:
        import numpy as np

        started = time.monotonic()
        width, height = image.size
        scale = min(1.0, self._detect_width / width) if width else 1.0
        small_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        gray = image.convert("L").resize(small_size)
        array = np.asarray(gray)
        min_side = max(1, round(small_size[0] * self._min_face_ratio))
        found = self._classifier.detectMultiScale(
            array,
            scaleFactor=self._scale_factor,
            minNeighbors=self._min_neighbors,
            minSize=(min_side, min_side),
        )
        del array, gray
        boxes = tuple(
            FaceBox(
                x=round(x / scale),
                y=round(y / scale),
                width=round(w / scale),
                height=round(h / scale),
            )
            for (x, y, w, h) in (tuple(int(v) for v in row) for row in found)
        )
        return FaceDetection(
            faces=boxes, performed=True, duration_s=time.monotonic() - started
        )
