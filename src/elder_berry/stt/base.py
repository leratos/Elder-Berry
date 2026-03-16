"""Abstrakte Basisklassen und DTOs für Speech-to-Text."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TranscriptionSegment:
    """Ein einzelnes Segment einer Transkription mit Zeitstempeln."""
    start: float    # Sekunden
    end: float      # Sekunden
    text: str


@dataclass
class TranscriptionResult:
    """
    Ergebnis einer STT-Transkription.

    Attributes:
        text:       Vollständiger transkribierter Text (alle Segmente zusammen).
        language:   Erkannte Sprache (ISO-Code, z.B. "de", "en") oder None.
        confidence: Durchschnittliche Konfidenz 0.0–1.0 oder None wenn nicht verfügbar.
        segments:   Einzelne Segmente mit Zeitstempeln (optional).
    """
    text: str
    language: str | None = None
    confidence: float | None = None
    segments: list[TranscriptionSegment] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.text.strip()


class STTEngine(ABC):
    """
    Abstrakte Schnittstelle für Speech-to-Text-Engines.

    Implementierungen:
        FasterWhisperEngine – faster-whisper (GPU-beschleunigt, lokal)
    """

    @abstractmethod
    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """
        Transkribiert eine Audio-Datei.

        Args:
            audio_path: Pfad zur Audio-Datei (WAV, MP3, FLAC, etc.).

        Returns:
            TranscriptionResult mit erkanntem Text.

        Raises:
            RuntimeError: Wenn Transkription fehlschlägt.
        """
        ...

    @abstractmethod
    def transcribe_bytes(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """
        Transkribiert rohe Audio-Bytes (PCM int16, mono).

        Args:
            audio_data:  PCM-Audio als Bytes (int16, mono).
            sample_rate: Sample-Rate in Hz (Standard: 16000).

        Returns:
            TranscriptionResult mit erkanntem Text.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Prüft ob die STT-Engine verfügbar ist (Paket installiert, Modell geladen)."""
        ...

    @abstractmethod
    def load(self) -> None:
        """Lädt das Modell in den Speicher (explizit, sonst Lazy-Load bei erster Nutzung)."""
        ...

    @abstractmethod
    def unload(self) -> None:
        """Entlädt das Modell aus dem Speicher (VRAM freigeben)."""
        ...
