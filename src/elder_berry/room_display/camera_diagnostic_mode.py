"""CameraDiagnosticMode -- Kamera-Ansicht fuer M6 und die D2-Messung (E4).

Phase 111, ``--frame-view kamera``. Reiner Messmodus, kein Partyinhalt:

* Alle ``interval_s`` (Default 2 s) ein Burst ueber die PhotoPipeline --
  zeitgesteuert, NICHT ueber FOCUSED: M6 und die Pruefdauer fuer D2 sollen
  unabhaengig davon messbar sein, ob der APDS schon kalibriert (M5) oder
  angeschlossen ist.
* Angezeigt: gewaehltes Bild verkleinert mit Gesichtsrahmen, Anzahl
  Gesichter, Aufnahme- und Pruefdauer, Detector, Autofokus. Dazu der
  Hinweis "Diagnose - keine Speicherung".
* Pro Burst eine INFO-Zeile mit diesen Zahlen (D2: Pruefdauer mittel/max).
* Danach wird das Ergebnis sofort freigegeben (§4.7). Es gibt KEINE
  Speicher-Option; die angezeigte Flaeche lebt nur bis zum naechsten Burst.

Der Burst laeuft synchron in ``update`` (ca. burst x interval, Default
~1 s). Die Anzeige steht so lange; fuer eine Diagnose genuegt das, und es
gibt keinen zweiten Thread, der Bilddaten haelt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from statistics import mean

import pygame

from elder_berry.room_display.content_mode import ContentMode
from elder_berry.room_display.oriented_display import OrientedDisplay, fit_into
from elder_berry.room_display.portrait.photo_pipeline import PhotoPipeline, PhotoResult

logger = logging.getLogger(__name__)

_WHITE = (255, 255, 255)
_GREY = (150, 150, 150)
_GREEN = (60, 220, 90)
_RED = (230, 60, 60)
_IMAGE_AREA = pygame.Rect(20, 80, 800, 450)  # 16:9 im logischen 1280x720

AfStatus = Callable[[], str]


def _ms(values: tuple[float, ...]) -> str:
    if not values:
        return "-"
    return f"mittel {mean(values) * 1000:.0f} ms, max {max(values) * 1000:.0f} ms"


class CameraDiagnosticMode(ContentMode):
    """M6/D2-Werkzeug: Bursts mit Gesichtspruefung anzeigen und loggen.

    Args:
        pipeline: PhotoPipeline (mit ``preview_without_face=True``) oder
            ``None``, wenn keine Kamera verfuegbar ist (dann Hinweisbild).
        interval_s: Abstand zwischen zwei Bursts.
        af_status: Liefert "ja"/"nein"/"ja (unscharf)" fuer die Anzeige.
    """

    def __init__(
        self,
        pipeline: PhotoPipeline | None,
        *,
        interval_s: float = 2.0,
        af_status: AfStatus | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._interval = interval_s
        self._af_status = af_status or (lambda: "?")
        self._next_due: float | None = None
        self._surface: pygame.Surface | None = None
        self._lines: list[tuple[str, tuple[int, int, int]]] = []
        self._dirty = True
        self._font: pygame.font.Font | None = None
        self.bursts = 0
        self.render_count = 0

    def on_enter(self, display: OrientedDisplay) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        self._font = pygame.font.Font(None, 36)
        if self._pipeline is None:
            logger.warning("Kamera-Ansicht: keine Kamera -- nur Hinweis.")
            self._lines = [
                ("Kamera nicht verfuegbar", _RED),
                ("python3-picamera2 per apt? venv mit --system-site-packages?", _GREY),
                ("Kabel/Anschluss? (Log)", _GREY),
            ]

    def update(self, now: float) -> bool:
        if self._pipeline is None:
            dirty, self._dirty = self._dirty, False
            return dirty
        if self._next_due is not None and now < self._next_due:
            return False
        result = self._pipeline.capture()
        try:
            self._show(result)
        finally:
            result.release()  # §4.7: Bilddaten sofort verwerfen
        self.bursts += 1
        self._next_due = now + self._interval
        return True

    def _show(self, result: PhotoResult) -> None:
        assert self._pipeline is not None
        faces = result.faces
        largest = max(faces, key=lambda b: b.area, default=None)
        af = self._af_status()
        detector = self._pipeline.detector_name
        self._surface = None
        if result.preview is not None:
            preview = result.preview.convert("RGB")
            surface = pygame.image.frombytes(preview.tobytes(), preview.size, "RGB")
            for box in faces:
                pygame.draw.rect(
                    surface,
                    _GREEN,
                    pygame.Rect(box.x, box.y, box.width, box.height),
                    max(2, preview.size[0] // 300),
                )
            self._surface = surface
            del preview
        if not result.checked:
            verdict, color = "nicht geprueft (detector none)", _GREY
        elif result.has_face:
            verdict, color = f"Gesichter: {len(faces)}", _GREEN
        else:
            verdict, color = "KEIN GESICHT", _RED
        size = f"{largest.width}x{largest.height} px" if largest else "-"
        self._lines = [
            (verdict, color),
            (f"groesstes: {size} (im {self._pipeline_edge(result)}er Bild)", _WHITE),
            (f"gewaehlt: #{result.chosen_index} von {len(result.capture_s)}", _WHITE),
            (f"Aufnahme: {_ms(result.capture_s)}", _WHITE),
            (f"Pruefung [{detector}]: {_ms(result.detect_s)}", _WHITE),
            (f"Autofokus: {af}", _WHITE),
        ]
        logger.info(
            "Kamera-Burst %d: %s, groesstes %s, gewaehlt #%s/%d, Aufnahme %s, "
            "Pruefung [%s] %s, AF %s",
            self.bursts + 1,
            verdict,
            size,
            result.chosen_index,
            len(result.capture_s),
            _ms(result.capture_s),
            detector,
            _ms(result.detect_s),
            af,
        )

    @staticmethod
    def _pipeline_edge(result: PhotoResult) -> int:
        return max(result.preview.size) if result.preview is not None else 0

    def render(self, display: OrientedDisplay) -> None:
        self.render_count += 1
        assert self._font is not None
        canvas = display.new_canvas()
        canvas.blit(
            self._font.render("Diagnose - keine Speicherung", True, _RED), (20, 20)
        )
        pygame.draw.rect(canvas, _GREY, _IMAGE_AREA, 2)
        if self._surface is not None:
            fitted = fit_into(self._surface, _IMAGE_AREA.size)
            canvas.blit(fitted, _IMAGE_AREA.topleft)
        for index, (text, color) in enumerate(self._lines):
            canvas.blit(self._font.render(text, True, color), (840, 100 + index * 50))
        display.show_dynamic(canvas)
