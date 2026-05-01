"""STTRouter – Wählt STT-Engine basierend auf Verfügbarkeit.

Primär:   Groq Whisper API (Cloud)
Fallback: FasterWhisper via TowerAgent (lokal auf Tower)

Implementiert STTEngine, damit AudioPipeline den Router transparent nutzen kann.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.stt.base import STTEngine, TranscriptionResult

if TYPE_CHECKING:
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.tools.cloud_stt_client import CloudSTTClient

logger = logging.getLogger(__name__)


class STTUnavailableError(Exception):
    """Kein STT-Backend verfügbar (weder Cloud noch Tower)."""


class STTRouter(STTEngine):
    """Router der Cloud-STT (Groq) bevorzugt und Tower als Fallback nutzt.

    Implementiert das STTEngine-Interface, damit AudioPipeline ihn als
    Drop-in-Replacement für FasterWhisperEngine nutzen kann.

    Args:
        cloud_stt: CloudSTTClient für Groq Whisper API.
        tower: TowerAgent für FasterWhisper Fallback (optional).
        event_loop: Optionaler Event-Loop für synchrone Aufrufe.
    """

    def __init__(
        self,
        cloud_stt: CloudSTTClient,
        tower: TowerAgent | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._cloud = cloud_stt
        self._tower = tower
        self._loop = event_loop
        self._loaded = True  # Cloud-STT braucht kein explizites Laden

    def _run_async[T](self, coro: Coroutine[Any, Any, T]) -> T:
        """Führt eine Coroutine synchron aus (für STTEngine-Interface).

        AudioPipeline ruft transcribe() in einem ThreadPoolExecutor.
        Wir müssen async-Aufrufe aus dem synchronen Kontext heraus aufrufen.
        """
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=120)
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=120)
        except RuntimeError:
            return asyncio.run(coro)

    async def transcribe_async(
        self,
        audio_bytes: bytes,
        filename: str = "audio.ogg",
    ) -> TranscriptionResult:
        """Transkribiert Audio-Bytes (async).

        Versucht Cloud-STT, fällt auf Tower zurück.

        Args:
            audio_bytes: Audio-Daten.
            filename: Dateiname für MIME-Type-Erkennung.

        Returns:
            TranscriptionResult mit erkanntem Text.

        Raises:
            STTUnavailableError: Wenn kein Backend verfügbar ist.
        """
        # Primär: Cloud-STT (Groq)
        try:
            text = await self._cloud.transcribe(audio_bytes, filename=filename)
            logger.info("STT via Cloud/Groq: '%s'", text[:60])
            return TranscriptionResult(text=text, language="de")
        except Exception as e:
            logger.warning("Cloud-STT fehlgeschlagen: %s", e)

        # Fallback: Tower (FasterWhisper)
        if self._tower and self._tower.is_online:
            try:
                text = await self._tower.stt(audio_bytes)
                logger.info("STT via Tower-Fallback: '%s'", text[:60])
                return TranscriptionResult(text=text)
            except Exception as e:
                logger.warning("Tower STT Fallback fehlgeschlagen: %s", e)

        raise STTUnavailableError("Kein STT verfügbar (Cloud + Tower down)")

    # -- STTEngine Interface --------------------------------------------------

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """Transkribiert eine Audio-Datei via Cloud oder Tower-Fallback.

        Liest die Datei ein und sendet die Bytes an die Cloud-API.

        Args:
            audio_path: Pfad zur Audio-Datei.

        Returns:
            TranscriptionResult mit erkanntem Text.
        """
        audio_bytes = audio_path.read_bytes()
        filename = audio_path.name
        return self._run_async(self.transcribe_async(audio_bytes, filename=filename))

    def transcribe_bytes(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """Transkribiert rohe Audio-Bytes (PCM).

        Für Cloud-STT müssen die rohen PCM-Bytes in ein Container-Format
        konvertiert werden. Wir schreiben sie als WAV-Datei.

        Args:
            audio_data: PCM-Audio als Bytes (int16, mono).
            sample_rate: Sample-Rate in Hz.

        Returns:
            TranscriptionResult mit erkanntem Text.
        """
        import wave

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data)

        try:
            return self.transcribe(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def is_available(self) -> bool:
        """Cloud-STT ist immer verfügbar (API-Key vorhanden)."""
        return True

    def load(self) -> None:
        """Cloud-STT braucht kein explizites Laden."""
        self._loaded = True

    def unload(self) -> None:
        """Cloud-STT braucht kein Entladen."""
        self._loaded = False
