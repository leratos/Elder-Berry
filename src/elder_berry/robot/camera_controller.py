"""CameraController – Kamera-Steuerung für RPi Camera Module 3 (IMX708)."""

from __future__ import annotations

import io
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Pillow nur fuer Typen; Import bleibt lazy
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)

ALLOWED_ROTATIONS = (0, 90, 180, 270)
#: libcamera AfModeEnum.Auto (Picamera2-Handbuch §5.3.1), falls libcamera
#: selbst nicht importierbar ist (Tests).
_AF_MODE_AUTO_FALLBACK = 1


def orient_image(
    image: PILImage, *, rotation: int = 0, hflip: bool = False, vflip: bool = False
) -> PILImage:
    """Spiegeln, dann drehen (Grad gegen den Uhrzeigersinn) -- per Pillow.

    Phase 111 (#1473 F5): Der libcamera-Transform kann nur spiegeln und 180
    Grad; eine Montage um 90 Grad braucht die Drehung nach der Aufnahme.
    """
    from PIL import Image

    if rotation not in ALLOWED_ROTATIONS:
        raise ValueError(f"rotation muss eins von {ALLOWED_ROTATIONS} sein")
    if hflip:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if vflip:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if rotation == 90:
        image = image.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 180:
        image = image.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        image = image.transpose(Image.Transpose.ROTATE_270)
    return image


def _default_picamera2_factory() -> Any:
    from picamera2 import Picamera2

    return Picamera2()


class CameraController(ABC):
    """ABC für Kamera-Steuerung auf dem RPi5."""

    @abstractmethod
    def is_available(self) -> bool:
        """Prüft ob die Kamera verfügbar und bereit ist."""
        pass

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
        pass

    @abstractmethod
    def get_resolution(self) -> tuple[int, int]:
        """Gibt die aktuelle Auflösung zurück (width, height)."""
        pass


class RPi5Camera(CameraController):
    """Echte Kamera-Implementierung für RPi Camera Module 3 (picamera2).

    Verwendet picamera2 (libcamera-basiert, Standard auf Bookworm).
    Die Kamera wird lazy initialisiert beim ersten Capture.

    Phase 111 (E4, Ae10): Erweiterungen fuer den Rahmen, alle per Default AUS,
    damit der Stamm-Pfad (``capture_jpeg``, Lazy-Init) unveraendert bleibt:
    ``capture_image`` (PIL-Bild im RAM, ausgerichtet), Ausrichtung
    (``rotation``/``hflip``/``vflip``), Autofokus-Zyklus vor der Aufnahme
    (``autofocus=True``, nur wenn die Kamera ``AfMode`` kennt) und
    :meth:`start` zum Warmhalten.

    Plattformhinweis: Nur auf RPi5 (Linux mit libcamera) lauffähig.
    """

    def __init__(
        self,
        resolution: tuple[int, int] = (1920, 1080),
        *,
        rotation: int = 0,
        hflip: bool = False,
        vflip: bool = False,
        autofocus: bool = False,
        af_timeout_s: float = 2.0,
        picamera2_factory: Callable[[], Any] | None = None,
    ) -> None:
        if rotation not in ALLOWED_ROTATIONS:
            raise ValueError(f"rotation muss eins von {ALLOWED_ROTATIONS} sein")
        self._resolution = resolution
        self._camera: Any = None  # picamera2.Picamera2 (lazy, untyped)
        self._initialized = False
        self._rotation = rotation
        self._hflip = hflip
        self._vflip = vflip
        self._autofocus = autofocus
        self._af_timeout_s = af_timeout_s
        self._factory = picamera2_factory or _default_picamera2_factory
        self.has_autofocus = False
        self.last_capture_s: float | None = None
        self.last_af_ok: bool | None = None

    def _ensure_initialized(self) -> None:
        """Lazy-Init: Kamera erst beim ersten Aufruf starten."""
        if self._initialized:
            return

        try:
            self._camera = self._factory()
            config = self._camera.create_still_configuration(
                main={"size": self._resolution, "format": "RGB888"},
            )
            self._camera.configure(config)
            self._camera.start()
            self._initialized = True
            logger.info(
                "RPi5Camera initialisiert: %dx%d",
                self._resolution[0],
                self._resolution[1],
            )
            if self._autofocus:
                self._setup_autofocus()
        except ImportError:
            raise RuntimeError(
                "picamera2 nicht installiert. "
                "Installiere es mit: sudo apt install python3-picamera2"
            ) from None
        except Exception as e:
            raise RuntimeError(f"Kamera-Initialisierung fehlgeschlagen: {e}") from e

    def _setup_autofocus(self) -> None:
        """AfMode=Auto setzen, falls die Kamera Autofokus kennt (§5.3.1)."""
        controls = getattr(self._camera, "camera_controls", {}) or {}
        self.has_autofocus = "AfMode" in controls
        if not self.has_autofocus:
            logger.info(
                "Kamera ohne Autofokus (kein AfMode) -- Aufnahme ohne AF-Zyklus."
            )
            return
        try:
            from libcamera import controls as libcamera_controls

            auto: object = libcamera_controls.AfModeEnum.Auto
        except ImportError:
            auto = _AF_MODE_AUTO_FALLBACK
        self._camera.set_controls({"AfMode": auto})

    def start(self) -> None:
        """Kamera sofort oeffnen und laufen lassen (Warmhalten, §4.4 CAPTURE).

        Loggt einmal die Faehigkeiten.

        Raises:
            RuntimeError: picamera2 fehlt oder Kamera nicht startbar.
        """
        self._ensure_initialized()
        logger.info(
            "Kamera warm: %dx%d, Autofokus %s, Rotation %d, hflip %s, vflip %s",
            self._resolution[0],
            self._resolution[1],
            "ja" if self.has_autofocus else "nein",
            self._rotation,
            self._hflip,
            self._vflip,
        )

    def _autofocus_cycle(self) -> None:
        """AF-Zyklus mit Timeout (Handbuch §5.3.4: autofocus_cycle(wait=False))."""
        self.last_af_ok = None
        if not (self._autofocus and self.has_autofocus):
            return
        try:
            job = self._camera.autofocus_cycle(wait=False)
            try:
                result = self._camera.wait(job, timeout=self._af_timeout_s)
            except TypeError:  # aeltere picamera2 ohne timeout-Parameter
                result = self._camera.wait(job)
            self.last_af_ok = bool(result)
        except (TimeoutError, RuntimeError) as exc:
            self.last_af_ok = False
            logger.warning(
                "Autofokus-Zyklus abgebrochen (%s) -- Aufnahme trotzdem.", exc
            )

    def capture_image(self) -> PILImage:
        """Ein Bild als PIL-Image (RGB), ausgerichtet, nur im RAM.

        Mit ``autofocus=True`` und AF-faehiger Kamera vorher ein AF-Zyklus.
        """
        self._ensure_initialized()
        from PIL import Image

        started = time.monotonic()
        self._autofocus_cycle()
        # picamera2 capture_array liefert bei "RGB888" tatsaechlich BGR
        # (libcamera-Konvention, #1473 F5) -> Kanaele umdrehen.
        array = self._camera.capture_array()
        image = Image.fromarray(array[:, :, ::-1])
        del array
        image = orient_image(
            image, rotation=self._rotation, hflip=self._hflip, vflip=self._vflip
        )
        self.last_capture_s = time.monotonic() - started
        logger.debug(
            "capture_image: %.0f ms, AF %s",
            self.last_capture_s * 1000,
            self.last_af_ok,
        )
        return image

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
