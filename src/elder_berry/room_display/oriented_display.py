"""OrientedDisplay -- logisches Querbild auf beliebig montiertem Panel (§4.3).

Phase 111, E2. Das Panel des Rahmens ist nativ 720x1280 (hochkant), die
Gemaelde sind 16:9 quer. Die Inhalte arbeiten immer auf einer LOGISCHEN
Flaeche von 1280x720; ``OrientedDisplay`` bildet sie auf die PHYSISCHE
Flaeche ab:

* ``rotation`` (0/90/180/270, Grad gegen den Uhrzeigersinn, wie
  ``pygame.transform.rotate``) dreht das logische Bild aufs Panel.
* Standbilder werden mit :meth:`prepare` EINMAL beim Laden skaliert
  (Seitenverhaeltnis bleibt, Rest schwarz) und gedreht. :meth:`show` und
  :meth:`blend` drehen nichts mehr -- eine Ueberblendung kostet pro Frame
  damit nicht mehr als ohne Drehung (§4.3, Zweig M3-B).
* Nur dynamischer Inhalt (:meth:`show_dynamic`) wird pro Frame gedreht.

Ob Zweig M3-A (KMS liefert schon 1280x720, Rotation 0) oder M3-B
(Rotation 90/270) gilt, entscheidet die Messung M3 mit dem Testbild des
Diagnosemodus. Die Code-Struktur ist in beiden Zweigen gleich.

Plattformhinweis: pygame(-ce) ist Pflicht; auf dem Rahmen-Pi pygame-ce
(Extra ``[frame]``).
"""

from __future__ import annotations

import logging

import pygame

logger = logging.getLogger(__name__)

LOGICAL_SIZE = (1280, 720)
ALLOWED_ROTATIONS = (0, 90, 180, 270)
_BLACK = (0, 0, 0)


def fit_into(image: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    """Skaliert ``image`` mit gleichem Seitenverhaeltnis in ``size`` und
    zentriert es auf Schwarz. Liefert immer eine neue Flaeche der Groesse
    ``size``."""
    canvas = pygame.Surface(size)
    canvas.fill(_BLACK)
    src_w, src_h = image.get_size()
    if src_w == 0 or src_h == 0:
        return canvas
    scale = min(size[0] / src_w, size[1] / src_h)
    new_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    if new_size != (src_w, src_h):
        if image.get_bitsize() not in (24, 32):
            converted = pygame.Surface((src_w, src_h), 0, 32)
            converted.blit(image, (0, 0))
            image = converted
        image = pygame.transform.smoothscale(image, new_size)
    canvas.blit(image, ((size[0] - new_size[0]) // 2, (size[1] - new_size[1]) // 2))
    return canvas


class OrientedDisplay:
    """Bildet die logische Querflaeche auf die physische Anzeige ab.

    Args:
        screen: Physische Anzeigeflaeche (``pygame.display.set_mode``).
        rotation: 0, 90, 180 oder 270 Grad gegen den Uhrzeigersinn.
        logical_size: Logische Flaeche, Default 1280x720.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        rotation: int,
        *,
        logical_size: tuple[int, int] = LOGICAL_SIZE,
    ) -> None:
        if rotation not in ALLOWED_ROTATIONS:
            raise ValueError(
                f"rotation muss eins von {ALLOWED_ROTATIONS} sein (war: {rotation})"
            )
        self._screen = screen
        self._rotation = rotation
        self._logical_size = logical_size
        width, height = screen.get_size()
        rotated_portrait = rotation in (90, 270)
        if rotated_portrait == (width > height) and width != height:
            logger.warning(
                "Rotation %d passt nicht zur physischen Groesse %dx%d -- das Bild "
                "wird verkleinert (Balken). Rotation pruefen (M3).",
                rotation,
                width,
                height,
            )

    @property
    def rotation(self) -> int:
        return self._rotation

    @property
    def logical_size(self) -> tuple[int, int]:
        return self._logical_size

    @property
    def physical_size(self) -> tuple[int, int]:
        width, height = self._screen.get_size()
        return (width, height)

    def new_canvas(self) -> pygame.Surface:
        """Leere schwarze Flaeche in logischer Groesse."""
        canvas = pygame.Surface(self._logical_size)
        canvas.fill(_BLACK)
        return canvas

    def _orient(self, image: pygame.Surface) -> pygame.Surface:
        """Logisch skalieren, drehen, auf physische Groesse bringen."""
        logical = fit_into(image, self._logical_size)
        rotated = (
            pygame.transform.rotate(logical, self._rotation)
            if self._rotation
            else logical
        )
        if rotated.get_size() != self.physical_size:
            rotated = fit_into(rotated, self.physical_size)
        return rotated

    def prepare(self, image: pygame.Surface) -> pygame.Surface:
        """Standbild EINMAL fuer die Anzeige vorbereiten (skalieren + drehen).

        Das Ergebnis hat physische Groesse und kann mit :meth:`show` und
        :meth:`blend` ohne weitere Drehung gezeichnet werden.
        """
        prepared = self._orient(image)
        if pygame.display.get_surface() is not None:
            # Pixelformat der Anzeige: schnelleres Blitten in jedem Frame.
            prepared = prepared.convert()
        return prepared

    def show(self, prepared: pygame.Surface) -> None:
        """Vorbereitetes Bild zeichnen (keine Drehung)."""
        self._screen.blit(prepared, (0, 0))

    def blend(
        self, source: pygame.Surface, target: pygame.Surface, progress: float
    ) -> None:
        """Ueberblendung zweier vorbereiteter Bilder, ``progress`` in [0, 1]."""
        alpha = round(255 * min(1.0, max(0.0, progress)))
        self._screen.blit(source, (0, 0))
        target.set_alpha(alpha)
        try:
            self._screen.blit(target, (0, 0))
        finally:
            target.set_alpha(None)

    def show_dynamic(self, logical: pygame.Surface) -> None:
        """Dynamischen Inhalt zeichnen; wird bei jedem Aufruf gedreht."""
        self._screen.blit(self._orient(logical), (0, 0))

    def present(self) -> None:
        """Gezeichnetes auf das Panel bringen."""
        pygame.display.flip()
