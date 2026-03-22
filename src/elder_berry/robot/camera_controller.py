"""CameraController – Kamera-Steuerung für RPi Camera Module 3 (IMX708)."""
from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CameraController(ABC):
    """ABC für Kamera-Steuerung auf dem RPi5."""

    @abstractmethod
    def is_available(self) -> bool:
        """Prüft ob die Kamera verfügbar und bereit ist."""
        ...

    @abstractmethod
    def capture_jpeg(self, quality: int = 85) -> bytes:
        """Nimmt ein Bild auf und gibt es als JPEG-Bytes zurück.

        Args:
            quality: JPEG-Qualität (1-100, Default 85).

        Returns:
            JPEG-kodierte Bilddaten als bytes.

        Raises:
            RuntimeError: Wenn Kamera nicht verfügbar oder Capture fehlschlägt.
        """
        ...

    @abstractmethod
    def get_resolution(self) -> tuple[int, int]:
        """Gibt die aktuelle Auflösung zurück (width, height)."""
        ...


class RPi5Camera(CameraController):
    """Echte Kamera-Implementierung für RPi Camera Module 3 (picamera2).

    Verwendet picamera2 (libcamera-basiert, Standard auf Bookworm).
    Die Kamera wird lazy initialisiert beim ersten Capture.

    Plattformhinweis: Nur auf RPi5 (Linux mit libcamera) lauffähig.
    """

    def __init__(
        self,
        resolution: tuple[int, int] = (1920, 1080),
    ) -> None:
        self._resolution = resolution
        self._camera = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-Init: Kamera erst beim ersten Aufruf starten."""
        if self._initialized:
            return

        try:
            from picamera2 import Picamera2

            self._camera = Picamera2()
            config = self._camera.create_still_configuration(
                main={"size": self._resolution, "format": "RGB888"},
            )
            self._camera.configure(config)
            self._camera.start()
            self._initialized = True
            logger.info(
                "RPi5Camera initialisiert: %dx%d",
                self._resolution[0], self._resolution[1],
            )
        except ImportError:
            raise RuntimeError(
                "picamera2 nicht installiert. "
                "Installiere es mit: sudo apt install python3-picamera2"
            )
        except Exception as e:
            raise RuntimeError(f"Kamera-Initialisierung fehlgeschlagen: {e}")

    def is_available(self) -> bool:
        """Prüft ob picamera2 importierbar und Kamera erkannt."""
        try:
            from picamera2 import Picamera2
            cameras = Picamera2.global_camera_info()
            return len(cameras) > 0
        except Exception:
            return False

    def capture_jpeg(self, quality: int = 85) -> bytes:
        """Nimmt ein JPEG-Bild auf."""
        self._ensure_initialized()

        from PIL import Image

        # picamera2 capture_array liefert bei "RGB888" tatsächlich BGR
        # (libcamera-Konvention: RGB888 = BGR in Speicherreihenfolge)
        array = self._camera.capture_array()
        image = Image.fromarray(array[:, :, ::-1])

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        jpeg_bytes = buffer.getvalue()

        logger.info("Capture: %d bytes JPEG", len(jpeg_bytes))
        return jpeg_bytes

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution

    def close(self) -> None:
        """Kamera-Ressourcen freigeben."""
        if self._camera and self._initialized:
            self._camera.stop()
            self._camera.close()
            self._initialized = False
            logger.info("RPi5Camera geschlossen")
