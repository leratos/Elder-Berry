"""Crossfade -- Zeitachse einer Ueberblendung (Phase 111, E2).

Reine Logik ohne pygame: Fortschritt 0..1 aus Start und Dauer. Das
Zeichnen uebernimmt :meth:`OrientedDisplay.blend`.
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class Crossfade(Generic[T]):
    """Ueberblendung von ``source`` nach ``target``.

    Args:
        source: Ausgangsbild (vorbereitet).
        target: Zielbild (vorbereitet).
        start: Startzeit (monotone Sekunden).
        duration: Dauer in Sekunden, > 0.
    """

    def __init__(self, source: T, target: T, start: float, duration: float) -> None:
        if duration <= 0:
            raise ValueError("duration muss > 0 sein.")
        self.source = source
        self.target = target
        self._start = start
        self._duration = duration

    def progress(self, now: float) -> float:
        """Fortschritt in [0, 1]."""
        return min(1.0, max(0.0, (now - self._start) / self._duration))

    def done(self, now: float) -> bool:
        return now - self._start >= self._duration
