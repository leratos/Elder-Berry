"""DiagnosticMode -- Messmodus fuer M3 und M4' (Phase 111, E2, §7).

Kein Partyinhalt. Zwei Ansichten:

* ``testbild`` (M3, Ausrichtung): "OBEN LINKS" in der logischen Ecke oben
  links, Kreis in der Mitte, Pfeil nach oben, dazu erkannte physische
  Displaygroesse (``pygame.display.get_desktop_sizes``) und Rotation als
  Text. Statisch: einmal vorbereitet, danach kein Neuzeichnen.
* ``ueberblendung`` (M4', Bildrate): zwei erzeugte 1280x720-Bilder
  (Farbverlauf, Gitter), ``transitions`` Ueberblendungen hintereinander mit
  FPS-Log. Danach Zusammenfassung mit Auswertung nach §7 und Ende.

Die physische Groesse geht beim Start auch ins Log.
"""

from __future__ import annotations

import logging

import pygame

from elder_berry.room_display.content_mode import ContentMode
from elder_berry.room_display.crossfade import Crossfade
from elder_berry.room_display.frame_rate_meter import FrameRateMeter, FrameStats
from elder_berry.room_display.oriented_display import OrientedDisplay

logger = logging.getLogger(__name__)

VIEW_TESTBILD = "testbild"
VIEW_UEBERBLENDUNG = "ueberblendung"

_WHITE = (255, 255, 255)
_RED = (230, 40, 40)
_YELLOW = (250, 220, 40)


def evaluate_m4(stats: FrameStats) -> str:
    """Auswertungsregel M4' (§7) auf die mittlere FPS angewandt."""
    if stats.mean_fps >= 24:
        return ">= 24 FPS: Uebergaenge wie geplant"
    if stats.mean_fps >= 10:
        return "10-24 FPS: Ueberblendungen verkuerzen (<= 0,5 s), Stufe 1 als Risiko melden"
    return "< 10 FPS: Stufe 0 mit harten Schnitten, Stufe 1 entfaellt"


def build_test_image(
    size: tuple[int, int], *, rotation: int, desktop_sizes: list[tuple[int, int]]
) -> pygame.Surface:
    """Testbild fuer M3 in logischer Groesse."""
    width, height = size
    image = pygame.Surface(size)
    image.fill((20, 20, 40))
    pygame.draw.rect(image, _WHITE, image.get_rect(), 4)
    pygame.draw.circle(image, _YELLOW, (width // 2, height // 2), min(size) // 4, 6)
    # Pfeil nach oben ueber dem Kreis
    tip = (width // 2, height // 2 - min(size) // 4 - 90)
    pygame.draw.polygon(
        image, _RED, [tip, (tip[0] - 40, tip[1] + 60), (tip[0] + 40, tip[1] + 60)]
    )
    pygame.draw.line(image, _RED, (tip[0], tip[1] + 60), (tip[0], tip[1] + 75), 12)
    # Markierung exakt in der logischen Ecke oben links
    pygame.draw.rect(image, _RED, pygame.Rect(0, 0, 24, 24))

    if not pygame.font.get_init():
        pygame.font.init()
    big = pygame.font.Font(None, 72)
    small = pygame.font.Font(None, 40)
    image.blit(big.render("OBEN LINKS", True, _WHITE), (32, 32))
    sizes = ", ".join(f"{w}x{h}" for w, h in desktop_sizes) or "unbekannt"
    lines = [
        f"Physisch (get_desktop_sizes): {sizes}",
        f"Rotation: {rotation} Grad | logisch {width}x{height}",
        "Kreis muss rund sein, Pfeil zeigt nach oben",
    ]
    for index, line in enumerate(lines):
        image.blit(small.render(line, True, _WHITE), (32, height - 150 + index * 44))
    return image


def build_gradient(size: tuple[int, int]) -> pygame.Surface:
    """Horizontaler Farbverlauf (Bild A fuer M4')."""
    width, height = size
    image = pygame.Surface(size)
    for x in range(width):
        ratio = x / max(1, width - 1)
        color = (
            int(40 + 200 * ratio),
            int(30 + 60 * (1 - ratio)),
            int(200 - 160 * ratio),
        )
        pygame.draw.line(image, color, (x, 0), (x, height - 1))
    return image


def build_grid(size: tuple[int, int], step: int = 80) -> pygame.Surface:
    """Gitter (Bild B fuer M4')."""
    width, height = size
    image = pygame.Surface(size)
    image.fill((10, 10, 10))
    for x in range(0, width, step):
        pygame.draw.line(image, (200, 200, 200), (x, 0), (x, height - 1), 2)
    for y in range(0, height, step):
        pygame.draw.line(image, (200, 200, 200), (0, y), (width - 1, y), 2)
    return image


class DiagnosticMode(ContentMode):
    """Testbild (M3) oder Ueberblend-Schleife (M4').

    Args:
        view: ``testbild`` oder ``ueberblendung``.
        desktop_sizes: Ergebnis von ``pygame.display.get_desktop_sizes()``.
        meter: Derselbe Meter wie in der App (fuer die Zusammenfassung).
        transition_s: Dauer einer Ueberblendung.
        hold_s: Standzeit zwischen Ueberblendungen.
        transitions: Anzahl Ueberblendungen bis zum Ende.
    """

    def __init__(
        self,
        view: str,
        *,
        desktop_sizes: list[tuple[int, int]],
        meter: FrameRateMeter,
        transition_s: float = 1.0,
        hold_s: float = 1.0,
        transitions: int = 10,
    ) -> None:
        if view not in (VIEW_TESTBILD, VIEW_UEBERBLENDUNG):
            raise ValueError(f"Unbekannte Ansicht: {view!r}")
        self._view = view
        self._desktop_sizes = list(desktop_sizes)
        self._meter = meter
        self._transition_s = transition_s
        self._hold_s = hold_s
        self._transitions = transitions
        self._images: list[pygame.Surface] = []
        self._current = 0
        self._fade: Crossfade[pygame.Surface] | None = None
        self._progress = 0.0  # Fortschritt der laufenden Ueberblendung
        self._next_start: float | None = None
        self._completed = 0
        self._dirty = True
        self._finished = False

    @property
    def completed_transitions(self) -> int:
        return self._completed

    def on_enter(self, display: OrientedDisplay) -> None:
        logger.info(
            "Diagnosemodus '%s': physisch %s (Fenster %dx%d), Rotation %d, logisch %dx%d",
            self._view,
            self._desktop_sizes,
            *display.physical_size,
            display.rotation,
            *display.logical_size,
        )
        if self._view == VIEW_TESTBILD:
            image = build_test_image(
                display.logical_size,
                rotation=display.rotation,
                desktop_sizes=self._desktop_sizes,
            )
            self._images = [display.prepare(image)]
        else:
            self._images = [
                display.prepare(build_gradient(display.logical_size)),
                display.prepare(build_grid(display.logical_size)),
            ]
        self._dirty = True

    def update(self, now: float) -> bool:
        if self._view == VIEW_TESTBILD:
            dirty, self._dirty = self._dirty, False
            return dirty
        return self._update_fades(now)

    def _update_fades(self, now: float) -> bool:
        if self._finished:
            return False
        if self._fade is not None:
            if not self._fade.done(now):
                self._progress = self._fade.progress(now)
                return True
            self._fade = None
            self._current = 1 - self._current
            self._completed += 1
            if self._completed >= self._transitions:
                self._finish()
            else:
                self._next_start = now + self._hold_s
            return True
        if self._next_start is None:
            self._next_start = now + self._hold_s
        if now >= self._next_start:
            self._fade = Crossfade(
                self._images[self._current],
                self._images[1 - self._current],
                now,
                self._transition_s,
            )
            self._progress = 0.0
            return True
        dirty, self._dirty = self._dirty, False
        return dirty

    def _finish(self) -> None:
        self._finished = True
        self._meter.pause()  # letztes Messfenster vor der Zusammenfassung loggen
        stats = self._meter.summary()
        if stats is None:
            logger.warning("M4': keine Frames gemessen.")
            return
        logger.info(
            "M4' Ergebnis nach %d Ueberblendungen: mittel %.1f FPS, min %.1f FPS, "
            "Frame mittel %.1f ms, max %.1f ms (n=%d)",
            self._completed,
            stats.mean_fps,
            stats.min_fps,
            stats.mean_frame_ms,
            stats.max_frame_ms,
            stats.frames,
        )
        logger.info("M4' Auswertung (mittlere FPS, §7): %s", evaluate_m4(stats))

    def render(self, display: OrientedDisplay) -> None:
        if self._fade is not None:
            # Fortschritt aus dem letzten update(); die App ruft render direkt
            # danach mit demselben Zeitpunkt.
            display.blend(self._fade.source, self._fade.target, self._progress)
        else:
            display.show(self._images[self._current])

    def is_animating(self) -> bool:
        return self._fade is not None

    def wants_exit(self) -> bool:
        return self._finished
