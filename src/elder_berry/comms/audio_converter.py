"""AudioConverter – Konvertiert Audio-Dateien zu OGG/Opus für Matrix-Sprachnachrichten.

Element erwartet OGG/Opus mit dem org.matrix.msc3245.voice Flag für
Sprachnachrichten-Darstellung (Waveform-Player statt Download-Link).

Benötigt ffmpeg als System-Dependency (pydub nutzt es unter der Haube).

Verwendung:
    converter = AudioConverter()
    ogg_path, duration_ms = converter.to_ogg_opus(Path("input.wav"))
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioConverterError(Exception):
    """Fehler bei der Audio-Konvertierung."""


class AudioConverter:
    """Konvertiert Audio-Dateien (WAV, MP3, etc.) zu OGG/Opus.

    Prüft bei Initialisierung ob ffmpeg verfügbar ist.
    Gibt duration_ms zurück für Matrix-Event-Metadata.
    """

    def __init__(self) -> None:
        self._ffmpeg_available = shutil.which("ffmpeg") is not None
        if not self._ffmpeg_available:
            logger.warning(
                "ffmpeg nicht gefunden! Audio-Konvertierung wird fehlschlagen. "
                "Installation: Windows: choco install ffmpeg | "
                "Linux: sudo apt install ffmpeg"
            )

    @property
    def ffmpeg_available(self) -> bool:
        """True wenn ffmpeg im System-PATH gefunden wurde."""
        return self._ffmpeg_available

    def to_ogg_opus(
        self,
        input_path: Path,
        output_path: Path | None = None,
        bitrate: str = "64k",
    ) -> tuple[Path, int]:
        """Konvertiert eine Audio-Datei zu OGG/Opus.

        Args:
            input_path: Pfad zur Eingabe-Datei (WAV, MP3, FLAC, etc.).
            output_path: Optionaler Ausgabe-Pfad. Default: input_path mit .ogg Endung.
            bitrate: Opus-Bitrate (Default: 64k – gut für Sprache).

        Returns:
            Tuple aus (Pfad zur OGG-Datei, Duration in Millisekunden).

        Raises:
            AudioConverterError: Wenn ffmpeg fehlt oder Konvertierung fehlschlägt.
            FileNotFoundError: Wenn input_path nicht existiert.
        """
        if not self._ffmpeg_available:
            raise AudioConverterError(
                "ffmpeg nicht verfügbar. "
                "Installation: Windows: choco install ffmpeg | "
                "Linux: sudo apt install ffmpeg"
            )

        if not input_path.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {input_path}")

        if output_path is None:
            output_path = input_path.with_suffix(".ogg")

        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(input_path))
            duration_ms = len(audio)

            audio.export(
                str(output_path),
                format="ogg",
                codec="libopus",
                bitrate=bitrate,
            )

            logger.debug(
                "Konvertiert: %s → %s (%d ms, %s)",
                input_path.name, output_path.name, duration_ms, bitrate,
            )

            return output_path, duration_ms

        except Exception as e:
            raise AudioConverterError(
                f"Konvertierung fehlgeschlagen: {input_path} → {e}"
            ) from e

    def get_duration_ms(self, audio_path: Path) -> int:
        """Gibt die Duration einer Audio-Datei in Millisekunden zurück.

        Raises:
            AudioConverterError: Wenn ffmpeg fehlt oder Datei nicht lesbar.
            FileNotFoundError: Wenn audio_path nicht existiert.
        """
        if not self._ffmpeg_available:
            raise AudioConverterError("ffmpeg nicht verfügbar")

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_path}")

        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(audio_path))
            return len(audio)
        except Exception as e:
            raise AudioConverterError(
                f"Duration konnte nicht ermittelt werden: {audio_path} → {e}"
            ) from e
