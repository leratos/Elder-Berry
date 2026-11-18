"""RoomDisplayApp -- Render-Schleife des Raumdisplays (Phase 111, §4.2).

Hostet genau einen :class:`ContentMode` auf einem :class:`OrientedDisplay`.

* Alle Eingabe-Events (Touch, Maus, Tastatur, ...) werden gelesen und
  verworfen (R12: Gaeste fassen das Display an). Es gibt keine Geste zum
  Beenden. Nur ``QUIT`` (vom System) und :meth:`request_stop` (SIGTERM,
  verdrahtet in ``frame_profile``) beenden die Schleife.
* Der Cursor ist aus.
* Gerendert wird nur, wenn der Modus eine Aenderung meldet oder eine
  Ueberblendung laeuft. Im Standbild wird nicht dauerhaft neu gezeichnet;
  die Schleife pollt dann nur mit ``idle_fps`` Events.
* Waehrend Ueberblendungen laeuft die Ziel-Bildrate ``fps``, und der
  :class:`FrameRateMeter` loggt hoechstens einmal pro Sekunde die FPS.

``pygame.display`` initialisiert und beendet ``frame_profile``, nicht die
App (wer initialisiert, raeumt auf).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import pygame

from elder_berry.room_display.content_mode import ContentMode
from elder_berry.room_display.frame_rate_meter import FrameRateMeter
from elder_berry.room_display.oriented_display import OrientedDisplay

logger = logging.getLogger(__name__)

DEFAULT_IDLE_FPS = 10


class RoomDisplayApp:
    """Render-Schleife fuer genau einen Inhaltsmodus.

    Args:
        display: Ausgerichtete Anzeige.
        mode: Der gehostete Modus.
        fps: Ziel-Bildrate waehrend Ueberblendungen.
        idle_fps: Poll-Rate im Standbild (Events, Zustandswechsel).
        meter: FPS-Messung; Default ein eigener Meter.
        clock: Monotone Zeitquelle (Tests).
    """

    def __init__(
        self,
        display: OrientedDisplay,
        mode: ContentMode,
        *,
        fps: int = 30,
        idle_fps: int = DEFAULT_IDLE_FPS,
        meter: FrameRateMeter | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if fps < 1 or idle_fps < 1:
            raise ValueError("fps und idle_fps muessen >= 1 sein.")
        self._display = display
        self._mode = mode
        self._fps = fps
        self._idle_fps = min(idle_fps, fps)
        self._meter = meter if meter is not None else FrameRateMeter()
        self._clock = clock
        self._stop = threading.Event()
        self.render_count = 0
        self.ignored_events = 0

    def request_stop(self) -> None:
        """Beendet die Schleife beim naechsten Durchlauf (signal-sicher)."""
        self._stop.set()

    def run(self) -> int:
        """Laeuft bis QUIT, :meth:`request_stop` oder ``mode.wants_exit()``.

        Returns:
            Exit-Code 0.
        """
        pygame.mouse.set_visible(False)
        tick = pygame.time.Clock()
        self._mode.on_enter(self._display)
        needs_render = True
        try:
            while not self._stop.is_set():
                self._drain_events()
                if self._stop.is_set():
                    break
                now = self._clock()
                if self._mode.update(now):
                    needs_render = True
                animating = self._mode.is_animating()
                if needs_render:
                    self._mode.render(self._display)
                    self._display.present()
                    self.render_count += 1
                    needs_render = False
                    if animating:
                        self._meter.frame(now)
                if not animating:
                    self._meter.pause()
                if self._mode.wants_exit():
                    logger.info("Modus meldet Ende -- Raumdisplay beendet sich.")
                    break
                tick.tick(self._fps if animating else self._idle_fps)
        finally:
            self._meter.pause()
            self._mode.on_exit()
        return 0

    def _drain_events(self) -> None:
        """Alle Events lesen; ausser QUIT wird alles verworfen."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                logger.info("QUIT empfangen -- Raumdisplay beendet sich.")
                self._stop.set()
            else:
                self.ignored_events += 1
