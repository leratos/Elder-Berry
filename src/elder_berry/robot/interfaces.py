"""Hardware-Abstraktions-ABCs für den :mod:`elder_berry.robot.server`.

Phase 106 (Modul-Entflechtung): aus ``robot/server.py`` ausgelagert. Die ABCs
werden vom Simulator (Windows) und der echten RPi5-Hardware implementiert und
in ``server.py`` re-exportiert, sodass bestehende Importe
(``from elder_berry.robot.server import AvatarDisplay`` etc.) und der
Typ-Checker stabil bleiben. Reiner Symbol-Umzug, keine Verhaltensänderung.

Plattformhinweis: reine Schnittstellen-Definitionen, plattformunabhängig.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from elder_berry.core.audio_analyzer import AmplitudeTrack
from elder_berry.robot.protocol import BatteryStatus


class MotorController(ABC):
    """ABC für Motorsteuerung."""

    @abstractmethod
    def drive(self, direction: str, speed: float) -> None:
        """Fährt in die angegebene Richtung."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stoppt alle Motoren."""
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Gibt aktuellen Motor-Zustand zurück."""
        pass


class AvatarDisplay(ABC):
    """ABC für Avatar-Anzeige auf dem RPi5-Display."""

    @abstractmethod
    def set_emotion(
        self, emotion: str, confidence: float = 1.0, intensity: float = 1.0
    ) -> None:
        """Setzt die angezeigte Emotion.

        Args:
            emotion: Emotion-Key (String). Unbekannt → Implementierung wählt
                einen Fallback (i. d. R. ``neutral``).
            confidence: Phase 108 – Confidence der Bot-seitigen
                ``EmotionDecision`` (0.0–1.0), über die REST-Grenze
                durchgereicht. Eine unsichere Emotion (< Gate-Schwelle) hält die
                etablierte Mimik, statt sie umzuschalten. Default ``1.0``
                (Legacy-/String-only-Pfad) → immer umschalten.
            intensity: Phase 110 – Anzeige-Tiefe (0.0–1.0). ``< 1.0`` blendet die
                Emotion Richtung neutral (mildere Mimik); ``1.0`` = voll/opak
                (Default, Legacy-Verhalten). Implementierungen ohne Blend
                (Simulator) dürfen den Wert ignorieren.
        """
        pass

    @abstractmethod
    def set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        """Aktiviert/deaktiviert Lip-Sync.

        Args:
            is_speaking: ``True`` während einer Sprech-Sitzung.
            audio_meta: Phase 83.4 – optionales Amplitude-Profil für den
                AmplitudeLipSyncDriver (nur Playback-Modus). ``None`` →
                RandomLipSyncDriver-Fallback (§4.4). Implementierungen ohne
                Lip-Sync (z.B. Simulator) ignorieren den Parameter.
        """
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Gibt aktuellen Avatar-Zustand zurück."""
        pass


class SensorManager(ABC):
    """ABC für Sensor-Abfragen."""

    @abstractmethod
    def get_battery(self) -> BatteryStatus:
        """Liest Akku-Status."""
        pass

    @abstractmethod
    def get_all(self) -> dict[str, Any]:
        """Liest alle Sensoren."""
        pass
