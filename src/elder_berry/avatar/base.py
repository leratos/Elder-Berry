"""Abstrakte Basisklasse für Avatar-Renderer."""

from abc import ABC, abstractmethod
from pathlib import Path

from elder_berry.character.base import Emotion


class AvatarRenderer(ABC):
    """
    Einheitliche Schnittstelle für die Avatar-Darstellung.

    Konkrete Implementierungen rendern den Avatar auf unterschiedlichen
    Ausgabegeräten (z.B. PyGame-Fenster, Holodisplay).
    """

    @abstractmethod
    def initialize(
        self,
        width: int = 512,
        height: int = 512,
        fullscreen: bool = False,
        rotation: int = 0,
    ) -> None:
        """
        Initialisiert das Render-Fenster / die Ausgabe.

        Args:
            width: Fensterbreite in Pixeln.
            height: Fensterhöhe in Pixeln.
            fullscreen: Vollbildmodus (ohne Rahmen, Maus versteckt).
            rotation: Display-Rotation in Grad. Erlaubt: 0 oder 180.
                90/270 sind nicht implementiert (würden Buffer-Refactor
                und Tausch von width/height erfordern).

        Raises:
            ValueError: bei rotation nicht in {0, 180}.
        """
        pass

    @abstractmethod
    def show_emotion(self, emotion: Emotion) -> None:
        """
        Zeigt den Avatar mit der gegebenen Emotion an.

        Args:
            emotion: Darzustellende Emotion.
        """
        pass

    @abstractmethod
    def show_speaking(self, is_speaking: bool) -> None:
        """
        Aktiviert/deaktiviert die Sprech-Animation.

        Args:
            is_speaking: True wenn der Avatar gerade spricht.
        """
        pass

    @abstractmethod
    def update(self) -> None:
        """Aktualisiert die Anzeige (ein Frame)."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Beendet den Renderer und schließt das Fenster."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Gibt True zurück wenn das Render-Fenster noch offen ist."""
        pass

    def render_to_file(
        self,
        output_path: Path,
        emotion: Emotion = Emotion.NEUTRAL,
    ) -> Path:
        """Rendert den Avatar mit gegebener Emotion als PNG-Datei.

        Headless-Rendering: benötigt kein Fenster / Display.
        Standardimplementierung wirft NotImplementedError.

        Args:
            output_path: Zielpfad für die PNG-Datei.
            emotion: Darzustellende Emotion (default: NEUTRAL).

        Returns:
            Pfad zur erzeugten PNG-Datei.
        """
        raise NotImplementedError("render_to_file nicht implementiert")
