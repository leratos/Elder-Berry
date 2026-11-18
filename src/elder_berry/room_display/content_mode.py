"""ContentMode -- ein Inhaltsmodus des Raumdisplays (Phase 111, Konzept §4.2).

Bewusst klein, damit spaeter weitere Modi (z.B. Rezepte) andocken koennen.
:class:`~elder_berry.room_display.room_display_app.RoomDisplayApp` hostet
genau einen Modus und ruft ihn so auf::

    on_enter(display)          einmal; Bilder vorbereiten (drehen beim Laden)
    loop:
        update(now) -> bool    True = es muss neu gezeichnet werden
        render(display)        nur wenn noetig
    on_exit()                  einmal, auch bei Abbruch

``is_animating()`` meldet laufende Ueberblendungen (dann rendert die App mit
voller Bildrate und loggt FPS). ``wants_exit()`` erlaubt einem Modus, das
Programm zu beenden (z.B. der Diagnosemodus nach der Messung).

Abweichung von der Skizze in §4.2: ``on_enter`` bekommt das Display, weil
ein Modus seine Standbilder beim Eintritt vorbereiten muss.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pygame nur fuer Typen; der Import bleibt leicht
    from elder_berry.room_display.oriented_display import OrientedDisplay


class ContentMode(ABC):
    """Basisklasse fuer Inhaltsmodi."""

    def on_enter(self, display: OrientedDisplay) -> None:  # noqa: B027
        """Einmal vor der ersten Aktualisierung. Default: nichts."""

    @abstractmethod
    def update(self, now: float) -> bool:
        """Zustand fortschreiben. True, wenn neu gezeichnet werden muss."""

    @abstractmethod
    def render(self, display: OrientedDisplay) -> None:
        """Aktuellen Zustand zeichnen (ohne ``present``; das macht die App)."""

    def on_exit(self) -> None:  # noqa: B027
        """Einmal beim Beenden, auch bei Abbruch. Default: nichts."""

    def is_animating(self) -> bool:
        """True waehrend einer Ueberblendung."""
        return False

    def wants_exit(self) -> bool:
        """True, wenn der Modus das Programm beenden moechte."""
        return False
