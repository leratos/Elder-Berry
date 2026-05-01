"""Abstrakte Basisklasse für die CharacterEngine – steuert Persönlichkeit und Emotionen."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Emotion(Enum):
    """Verfügbare Emotionszustände eines Charakters."""

    NEUTRAL = "neutral"
    CHEERFUL = "cheerful"
    SARCASTIC = "sarcastic"
    MOTIVATED = "motivated"
    THOUGHTFUL = "thoughtful"
    WHISPER = "whisper"
    SHY = "shy"
    DEPRESSED = "depressed"
    SAD = "sad"
    ANGRY = "angry"


@dataclass(frozen=True)
class Personality:
    """Unveränderliche Persönlichkeitsdefinition eines Charakters."""

    name: str
    title: str
    core_trait: str
    speaking_style: str
    boundaries: list[str] = field(default_factory=list)


@dataclass
class EmotionMapping:
    """Zuordnung einer Emotion zu Voice-Sample und Sprite-Asset."""

    emotion: Emotion
    voice_sample: Path | None = None
    sprite_asset: Path | None = None


@dataclass
class MoodState:
    """Aktueller emotionaler Zustand des Charakters."""

    current_emotion: Emotion = Emotion.NEUTRAL
    intensity: float = 0.5  # 0.0 = schwach, 1.0 = stark

    def __post_init__(self) -> None:
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError(
                f"Intensity muss zwischen 0.0 und 1.0 liegen, war {self.intensity}"
            )


class CharacterEngine(ABC):
    """
    Steuert Persönlichkeit, Emotionen und System-Prompt eines Charakters.

    Plattformunabhängig. Konkrete Implementierungen definieren den
    spezifischen Charakter (z.B. SaleriaEngine).
    """

    @abstractmethod
    def get_personality(self) -> Personality:
        """Gibt die Persönlichkeitsdefinition zurück."""
        ...

    @abstractmethod
    def get_mood(self) -> MoodState:
        """Gibt den aktuellen emotionalen Zustand zurück."""
        ...

    @abstractmethod
    def set_mood(self, emotion: Emotion, intensity: float = 0.5) -> None:
        """
        Setzt den emotionalen Zustand.

        Args:
            emotion: Neue Emotion.
            intensity: Stärke der Emotion (0.0–1.0).
        """
        ...

    @abstractmethod
    def build_system_prompt(
        self,
        available_actions: str = "",
        memory_context: str = "",
        remote_commands: str = "",
    ) -> str:
        """
        Generiert den System-Prompt für das LLM basierend auf Persönlichkeit und Mood.

        Args:
            available_actions: Formatierte Liste verfügbarer Aktionen.
            memory_context:    Formatierter Memory-Kontext aus dem RAG-Gedächtnis.
            remote_commands:   Dynamische Command-Beschreibungen für remote_command.

        Returns:
            Vollständiger System-Prompt als String.
        """
        ...

    @abstractmethod
    def extract_emotion(self, llm_response: str) -> Emotion:
        """
        Extrahiert Emotions-Tags aus der LLM-Antwort.

        Sucht nach [emotion]-Tags im Text (z.B. [cheerful], [angry]).

        Args:
            llm_response: Rohe LLM-Antwort mit möglichen Emotions-Tags.

        Returns:
            Erkannte Emotion, oder NEUTRAL als Fallback.
        """
        ...

    @abstractmethod
    def clean_response(self, llm_response: str) -> str:
        """
        Entfernt Emotions-Tags aus dem Text für TTS/Display.

        Args:
            llm_response: Text mit möglichen [emotion]-Tags.

        Returns:
            Bereinigter Text ohne Tags.
        """
        ...

    def get_mood_context(self) -> str | None:
        """
        Gibt den emotionalen Kontext für den System-Prompt zurück.

        Basiert auf den letzten Emotionen (Kurzzeitgedächtnis).
        Default-Implementierung gibt None zurück (kein Tracking).

        Returns:
            Formatierter Kontext-String oder None.
        """
        return None

    @abstractmethod
    def get_voice_sample(self, emotion: Emotion) -> Path | None:
        """
        Gibt den Pfad zum Voice-Sample für die gegebene Emotion zurück.

        Args:
            emotion: Emotion für die das Sample benötigt wird.

        Returns:
            Pfad zum WAV-File, oder None wenn kein Sample vorhanden.
        """
        ...

    @abstractmethod
    def get_sprite_asset(self, emotion: Emotion) -> Path | None:
        """
        Gibt den Pfad zum Sprite-Asset für die gegebene Emotion zurück.

        Args:
            emotion: Emotion für die das Sprite benötigt wird.

        Returns:
            Pfad zum Bild, oder None wenn kein Asset vorhanden.
        """
        ...
