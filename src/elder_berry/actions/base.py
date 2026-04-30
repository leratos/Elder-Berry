"""Abstrakte Basisklasse für PC-Steuerung."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class WindowInfo:
    """Informationen über ein Fenster."""

    title: str
    handle: int


class ActionController(ABC):
    """
    Einheitliche Schnittstelle für PC-Steuerung.

    Plattformspezifische Implementierungen erben von dieser Klasse.
    Aktuell: WindowsActionController.
    """

    # ------------------------------------------------------------------
    # Tastatur
    # ------------------------------------------------------------------

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Drückt eine einzelne Taste (z.B. 'enter', 'space', 'a')."""
        ...

    @abstractmethod
    def type_text(self, text: str, interval: float = 0.02) -> None:
        """Tippt einen Text zeichenweise."""
        ...

    @abstractmethod
    def hotkey(self, *keys: str) -> None:
        """Drückt eine Tastenkombination (z.B. hotkey('ctrl', 'c'))."""
        ...

    # ------------------------------------------------------------------
    # Maus
    # ------------------------------------------------------------------

    @abstractmethod
    def move_mouse(self, x: int, y: int, duration: float = 0.25) -> None:
        """Bewegt die Maus zu einer absoluten Position."""
        ...

    @abstractmethod
    def click(
        self, x: int | None = None, y: int | None = None, button: str = "left"
    ) -> None:
        """Klickt an der angegebenen Position (oder aktuelle Position)."""
        ...

    # ------------------------------------------------------------------
    # Fenster
    # ------------------------------------------------------------------

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        """Gibt alle sichtbaren Fenster zurück."""
        ...

    @abstractmethod
    def focus_window(self, title: str) -> bool:
        """
        Bringt ein Fenster mit dem angegebenen Titel in den Vordergrund.

        Args:
            title: Teilstring des Fenstertitels (case-insensitive).

        Returns:
            True wenn ein Fenster gefunden und fokussiert wurde.
        """
        ...

    @abstractmethod
    def minimize_window(self, title: str) -> bool:
        """Minimiert ein Fenster. Gibt True zurück bei Erfolg."""
        ...

    @abstractmethod
    def maximize_window(self, title: str) -> bool:
        """Maximiert ein Fenster. Gibt True zurück bei Erfolg."""
        ...

    # ------------------------------------------------------------------
    # Lautstärke
    # ------------------------------------------------------------------

    @abstractmethod
    def get_volume(self) -> float:
        """Gibt die aktuelle System-Lautstärke zurück (0.0 – 1.0)."""
        ...

    @abstractmethod
    def set_volume(self, level: float) -> None:
        """
        Setzt die System-Lautstärke.

        Args:
            level: Wert zwischen 0.0 (stumm) und 1.0 (max).

        Raises:
            ValueError: Wenn level nicht im Bereich 0.0–1.0 liegt.
        """
        ...

    @abstractmethod
    def mute(self, state: bool = True) -> None:
        """Schaltet Stummschaltung ein (True) oder aus (False)."""
        ...
