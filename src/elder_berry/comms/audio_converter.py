"""AudioConverter – Konvertiert Audio-Dateien zu OGG/Opus für Matrix-Sprachnachrichten.

Element erwartet OGG/Opus mit dem ``org.matrix.msc3245.voice``-Flag für
die Waveform-Anzeige in Sprachnachrichten.

Phase 55: Diese Klasse rief bisher ``pydub.AudioSegment`` auf, das seit
Python 3.13 nicht mehr importierbar ist (pydub zieht unconditional das
entfernte ``audioop``-Stdlib-Modul). Da wir ohnehin nur zwei Operationen
brauchen – WAV→OGG/Opus-Konvertierung und Dauer-Bestimmung – nutzt der
Konverter jetzt direkt ``ffmpeg`` bzw. ``ffprobe`` als Subprozess.
``ffmpeg`` ist weiterhin Pflicht-Dependency des Projekts.

Verwendung:
    converter = AudioConverter()
    ogg_path, duration_ms = converter.to_ogg_opus(Path("input.wav"))
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioConverterError(Exception):
    """Fehler bei der Audio-Konvertierung."""


class AudioConverter:
    """Konvertiert Audio-Dateien (WAV, MP3, …) zu OGG/Opus via ffmpeg.

    Prüft bei Initialisierung, ob ``ffmpeg`` und ``ffprobe`` verfügbar
    sind, und gibt ``duration_ms`` für den Matrix-Event-Metadata-Payload
    zurück.
    """

    # Timeouts verhindern, dass ein hängender ffmpeg-Prozess die ganze
    # Matrix-Nachrichtenverarbeitung blockiert.
    FFMPEG_TIMEOUT_SECONDS = 60
    FFPROBE_TIMEOUT_SECONDS = 15

    def __init__(self) -> None:
        self._ffmpeg_available = shutil.which("ffmpeg") is not None
        self._ffprobe_available = shutil.which("ffprobe") is not None
        if not self._ffmpeg_available:
            logger.warning(
                "ffmpeg nicht gefunden! Audio-Konvertierung wird fehlschlagen. "
                "Installation: Windows: choco install ffmpeg | "
                "Linux: sudo apt install ffmpeg",
            )
        elif not self._ffprobe_available:
            logger.warning(
                "ffprobe nicht gefunden! Duration-Bestimmung wird fehlschlagen. "
                "ffprobe wird üblicherweise mit ffmpeg zusammen installiert.",
            )

    @property
    def ffmpeg_available(self) -> bool:
        """True wenn ffmpeg im System-PATH gefunden wurde."""
        return self._ffmpeg_available

    @property
    def ffprobe_available(self) -> bool:
        """True wenn ffprobe im System-PATH gefunden wurde."""
        return self._ffprobe_available

    def to_ogg_opus(
        self,
        input_path: Path,
        output_path: Path | None = None,
        bitrate: str = "64k",
    ) -> tuple[Path, int]:
        """Konvertiert eine Audio-Datei zu OGG/Opus.

        Args:
            input_path: Pfad zur Eingabe-Datei (WAV, MP3, FLAC, …).
            output_path: Optionaler Ausgabe-Pfad. Default: ``input_path``
                mit ``.ogg``-Endung.
            bitrate: Opus-Bitrate (Default: ``64k`` – gut für Sprache).

        Returns:
            Tuple aus (Pfad zur OGG-Datei, Duration in Millisekunden).

        Raises:
            AudioConverterError: Wenn ffmpeg/ffprobe fehlt oder der Aufruf
                fehlschlägt.
            FileNotFoundError: Wenn ``input_path`` nicht existiert.
        """
        if not self._ffmpeg_available:
            raise AudioConverterError(
                "ffmpeg nicht verfügbar. "
                "Installation: Windows: choco install ffmpeg | "
                "Linux: sudo apt install ffmpeg",
            )

        if not input_path.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {input_path}")

        if output_path is None:
            output_path = input_path.with_suffix(".ogg")

        cmd = [
            "ffmpeg",
            "-y",               # vorhandene Ziel-Datei überschreiben
            "-hide_banner",
            "-loglevel", "error",
            "-i", str(input_path),
            "-c:a", "libopus",
            "-b:a", bitrate,
            str(output_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.FFMPEG_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            # ffmpeg war bei shutil.which noch da, inzwischen nicht mehr
            raise AudioConverterError(
                "ffmpeg konnte nicht ausgeführt werden (FileNotFoundError).",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AudioConverterError(
                f"ffmpeg-Timeout nach {self.FFMPEG_TIMEOUT_SECONDS}s: {input_path}",
            ) from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip() or "(kein stderr)"
            raise AudioConverterError(
                f"Konvertierung fehlgeschlagen ({input_path} → {output_path}): "
                f"{stderr}",
            )

        duration_ms = self._probe_duration_ms(output_path)

        logger.debug(
            "Konvertiert: %s → %s (%d ms, %s)",
            input_path.name, output_path.name, duration_ms, bitrate,
        )
        return output_path, duration_ms

    def get_duration_ms(self, audio_path: Path) -> int:
        """Gibt die Duration einer Audio-Datei in Millisekunden zurück.

        Raises:
            AudioConverterError: Wenn ffmpeg/ffprobe fehlt oder die Datei
                nicht lesbar ist.
            FileNotFoundError: Wenn ``audio_path`` nicht existiert.
        """
        if not self._ffmpeg_available:
            raise AudioConverterError("ffmpeg nicht verfügbar")

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_path}")

        return self._probe_duration_ms(audio_path)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_duration_ms(self, path: Path) -> int:
        """Ermittelt die Dauer einer Audio-Datei in Millisekunden via ffprobe.

        Args:
            path: Existierende Audio-/Container-Datei.

        Raises:
            AudioConverterError: Wenn ffprobe fehlt, fehlschlägt oder die
                JSON-Antwort unerwartet ist.
        """
        if not self._ffprobe_available:
            raise AudioConverterError(
                "ffprobe nicht verfügbar (wird für Duration-Bestimmung benötigt).",
            )

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.FFPROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AudioConverterError(
                "ffprobe konnte nicht ausgeführt werden (FileNotFoundError).",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AudioConverterError(
                f"ffprobe-Timeout nach {self.FFPROBE_TIMEOUT_SECONDS}s: {path}",
            ) from exc

        if result.returncode != 0:
            stderr = (result.stderr or "").strip() or "(kein stderr)"
            raise AudioConverterError(
                f"Duration konnte nicht ermittelt werden: {path} → {stderr}",
            )

        try:
            data = json.loads(result.stdout)
            duration_s = float(data["format"]["duration"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AudioConverterError(
                f"ffprobe-Antwort unlesbar für {path}: {exc}",
            ) from exc

        return int(round(duration_s * 1000))
