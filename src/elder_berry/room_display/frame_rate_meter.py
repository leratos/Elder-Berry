"""FrameRateMeter -- FPS-Messung waehrend Ueberblendungen (Phase 111, E2).

Grundlage fuer M4' (§7): Waehrend einer Ueberblendung zaehlt die App jeden
gerenderten Frame. Hoechstens einmal pro ``log_interval_s`` schreibt der
Meter eine INFO-Zeile mit mittlerer und minimaler FPS sowie mittlerer und
maximaler Frame-Dauer. Ausserhalb von Ueberblendungen wird nichts gemessen
(:meth:`pause`), damit Standzeiten die Werte nicht verfaelschen.

Reine Logik, Zeit kommt von aussen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameStats:
    """Kennzahlen einer Menge von Frame-Dauern."""

    frames: int
    mean_fps: float
    min_fps: float
    mean_frame_ms: float
    max_frame_ms: float


def _stats(durations: list[float]) -> FrameStats | None:
    if not durations:
        return None
    total = sum(durations)
    worst = max(durations)
    return FrameStats(
        frames=len(durations),
        mean_fps=len(durations) / total if total > 0 else float("inf"),
        min_fps=1.0 / worst if worst > 0 else float("inf"),
        mean_frame_ms=1000.0 * total / len(durations),
        max_frame_ms=1000.0 * worst,
    )


class FrameRateMeter:
    """Misst Frame-Abstaende und loggt sie gedrosselt."""

    def __init__(self, *, log_interval_s: float = 1.0) -> None:
        self._interval = log_interval_s
        self._last_frame: float | None = None
        self._window: list[float] = []
        self._window_start: float | None = None
        self._all: list[float] = []

    def frame(self, now: float) -> None:
        """Einen gerenderten Frame waehrend einer Ueberblendung melden."""
        if self._last_frame is not None:
            delta = now - self._last_frame
            self._window.append(delta)
            self._all.append(delta)
        if self._window_start is None:
            self._window_start = now
        self._last_frame = now
        if now - self._window_start >= self._interval:
            self._flush()
            self._window_start = now

    def pause(self) -> None:
        """Ueberblendung vorbei: offenes Fenster loggen, Abstand zuruecksetzen."""
        if self._last_frame is None:
            return
        self._flush()
        self._last_frame = None
        self._window_start = None

    def summary(self) -> FrameStats | None:
        """Kennzahlen ueber alle bisher gemessenen Frames."""
        return _stats(self._all)

    def _flush(self) -> None:
        stats = _stats(self._window)
        self._window = []
        if stats is None:
            return
        logger.info(
            "FPS (Ueberblendung): mittel %.1f, min %.1f | Frame mittel %.1f ms, "
            "max %.1f ms (n=%d)",
            stats.mean_fps,
            stats.min_fps,
            stats.mean_frame_ms,
            stats.max_frame_ms,
            stats.frames,
        )
