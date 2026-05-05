"""Abstrakte Basisklasse für Text-to-Speech Engines."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


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
    Aktuell: WindowsTTSEngine (pyttsx3/SAPI5), CoquiTTSEngine (XTTS v2).
    """

    @abstractmethod
    def speak(self, text: str, emotion: str | None = None) -> None:
        """
        Spricht den Text laut aus (blockierend).

        Args:
            text: Auszusprechender Text.
            emotion: Optionaler Emotions-Name (z.B. "cheerful", "angry").
                     Engines die Emotionen unterstützen (z.B. CoquiTTSEngine)
                     wählen damit das passende Voice-Sample.
                     Engines ohne Emotions-Support ignorieren den Parameter.
        """
        pass

    def load(self) -> None:  # noqa: B027
        """Lädt das TTS-Modell in den Speicher (GPU/RAM).

        Standard-Implementierung: No-Op. Wird von Engines überschrieben
        die explizites VRAM-Management benötigen (z.B. CoquiTTSEngine).
        """

    def unload(self) -> None:  # noqa: B027
        """Entlädt das TTS-Modell aus dem Speicher.

        Standard-Implementierung: No-Op. Wird von Engines überschrieben
        die explizites VRAM-Management benötigen (z.B. CoquiTTSEngine).
        """

    def generate_audio(
        self, text: str, output_path: Path, emotion: str | None = None
    ) -> Path:
        """
        Generiert Audio-Datei ohne sie abzuspielen.

        Standard-Implementierung: nicht verfügbar, wirft NotImplementedError.
        Engines mit Dateigenerierung (z.B. CoquiTTSEngine) überschreiben dies.

        Args:
            text: Zu synthetisierender Text.
            output_path: Ziel-Pfad für die Audio-Datei.
            emotion: Optionaler Emotions-Name.

        Returns:
            Pfad zur generierten Audio-Datei.
        """
        raise NotImplementedError(
            f"{type(self).__name__} unterstützt keine Audio-Dateigenerierung."
        )

    @abstractmethod
    def get_rate(self) -> int:
        """Gibt die aktuelle Sprechgeschwindigkeit zurück (Wörter/Min)."""
        pass

    @abstractmethod
    def set_rate(self, rate: int) -> None:
        """
        Setzt die Sprechgeschwindigkeit.

        Args:
            rate: Wörter pro Minute (typisch: 100–300, Standard ~200).
        """
        pass

    @abstractmethod
    def get_volume(self) -> float:
        """Gibt die TTS-Lautstärke zurück (0.0–1.0)."""
        pass

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        """
        Setzt die TTS-Lautstärke.

        Args:
            volume: Wert zwischen 0.0 (stumm) und 1.0 (max).

        Raises:
            ValueError: Wenn volume nicht im Bereich 0.0–1.0 liegt.
        """
        pass

    @abstractmethod
    def get_voices(self) -> list[VoiceInfo]:
        """Gibt alle verfügbaren Stimmen zurück."""
        pass

    @abstractmethod
    def set_voice(self, voice_id: str) -> None:
        """
        Setzt die aktive Stimme.

        Args:
            voice_id: ID der Stimme (aus VoiceInfo.id).

        Raises:
            ValueError: Wenn voice_id nicht gefunden wird.
        """
        pass
