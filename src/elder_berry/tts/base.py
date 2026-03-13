"""Abstrakte Basisklasse für Text-to-Speech Engines."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VoiceInfo:
    """Informationen über eine verfügbare TTS-Stimme."""
    id: str
    name: str
    language: str


class TTSEngine(ABC):
    """
    Einheitliche Schnittstelle für Text-to-Speech.

    Plattformspezifische Implementierungen erben von dieser Klasse.
    Aktuell: WindowsTTSEngine (pyttsx3/SAPI5).
    Später möglich: LinuxTTSEngine (espeak), NeuralTTSEngine (Phase 3).
    """

    @abstractmethod
    def speak(self, text: str) -> None:
        """Spricht den Text laut aus (blockierend)."""
        ...

    @abstractmethod
    def get_rate(self) -> int:
        """Gibt die aktuelle Sprechgeschwindigkeit zurück (Wörter/Min)."""
        ...

    @abstractmethod
    def set_rate(self, rate: int) -> None:
        """
        Setzt die Sprechgeschwindigkeit.

        Args:
            rate: Wörter pro Minute (typisch: 100–300, Standard ~200).
        """
        ...

    @abstractmethod
    def get_volume(self) -> float:
        """Gibt die TTS-Lautstärke zurück (0.0–1.0)."""
        ...

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        """
        Setzt die TTS-Lautstärke.

        Args:
            volume: Wert zwischen 0.0 (stumm) und 1.0 (max).

        Raises:
            ValueError: Wenn volume nicht im Bereich 0.0–1.0 liegt.
        """
        ...

    @abstractmethod
    def get_voices(self) -> list[VoiceInfo]:
        """Gibt alle verfügbaren Stimmen zurück."""
        ...

    @abstractmethod
    def set_voice(self, voice_id: str) -> None:
        """
        Setzt die aktive Stimme.

        Args:
            voice_id: ID der Stimme (aus VoiceInfo.id).

        Raises:
            ValueError: Wenn voice_id nicht gefunden wird.
        """
        ...
