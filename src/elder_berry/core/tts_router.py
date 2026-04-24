"""TTSRouter – Wählt TTS-Engine basierend auf Verfügbarkeit.

Primär:    ElevenLabs API (Cloud, MP3-Output)
Fallback1: XTTS v2 via TowerAgent (Tower, WAV-Output)
Fallback2: Lokale TTSEngine (CoquiTTS/WindowsTTS, wenn verfügbar)

Implementiert TTSEngine, damit Assistant den Router transparent nutzen kann.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.tts.base import TTSEngine, VoiceInfo

if TYPE_CHECKING:
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.tools.elevenlabs_client import ElevenLabsClient

logger = logging.getLogger(__name__)


class TTSUnavailableError(Exception):
    """Kein TTS-Backend verfügbar (weder ElevenLabs noch Tower)."""


class TTSRouter(TTSEngine):
    """Router der ElevenLabs (Cloud) bevorzugt und bei Fehler zurückfällt.

    Fallback-Kette: ElevenLabs → Tower (XTTS v2) → lokale TTSEngine.

    Implementiert das TTSEngine-Interface, damit Assistant ihn als
    Drop-in-Replacement für CoquiTTSEngine nutzen kann.

    Args:
        elevenlabs: ElevenLabsClient für Cloud-TTS.
        tower: TowerAgent für XTTS v2 Fallback (optional).
        local_tts: Lokale TTSEngine als letzter Fallback (optional).
        event_loop: Optionaler Event-Loop für synchrone Aufrufe aus
            Assistant.process() heraus.
    """

    def __init__(
        self,
        elevenlabs: ElevenLabsClient,
        tower: TowerAgent | None = None,
        local_tts: TTSEngine | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._elevenlabs = elevenlabs
        self._tower = tower
        self._local_tts = local_tts
        self._loop = event_loop
        self._rate = 200
        self._volume = 1.0

    def _run_async(self, coro):
        """Führt eine Coroutine synchron aus (für TTSEngine-Interface).

        Assistant.process() läuft in einem ThreadPoolExecutor. Wir müssen
        async-Aufrufe aus dem synchronen Kontext heraus aufrufen.
        """
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=60)
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=60)
        except RuntimeError:
            return asyncio.run(coro)

    async def synthesize(self, text: str, emotion: str | None = None) -> bytes:
        """Synthetisiert Text zu Audio-Bytes (async).

        Versucht ElevenLabs, fällt auf Tower zurück.

        Args:
            text: Zu synthetisierender Text.
            emotion: Optionaler Emotions-Name (nur für Tower-Fallback relevant).

        Returns:
            Audio-Bytes (MP3 von ElevenLabs, WAV von Tower).

        Raises:
            TTSUnavailableError: Wenn kein Backend verfügbar ist.
        """
        # Primär: ElevenLabs
        try:
            audio = await self._elevenlabs.synthesize(text)
            logger.info("TTS via ElevenLabs (%d bytes)", len(audio))
            return audio
        except Exception as e:
            logger.warning("ElevenLabs TTS fehlgeschlagen: %s", e)

        # Fallback 1: Tower (XTTS v2)
        if self._tower and self._tower.is_online:
            try:
                audio = await self._tower.tts(text, emotion)
                logger.info("TTS via Tower-Fallback (%d bytes)", len(audio))
                return audio
            except Exception as e:
                logger.warning("Tower TTS Fallback fehlgeschlagen: %s", e)

        raise TTSUnavailableError("Kein TTS verfügbar (ElevenLabs + Tower down)")

    # -- TTSEngine Interface --------------------------------------------------

    def speak(self, text: str, emotion: str | None = None) -> None:
        """Spricht Text – delegiert an lokale Engine wenn vorhanden.

        Auf dem Server gibt es keine Soundkarte, daher No-Op wenn kein
        lokaler Fallback konfiguriert ist.
        """
        if self._local_tts is not None:
            self._local_tts.speak(text, emotion=emotion)
        else:
            logger.debug("TTSRouter.speak() – kein lokales Audio verfügbar")

    def generate_audio(
        self, text: str, output_path: Path, emotion: str | None = None,
    ) -> Path:
        """Generiert Audio-Datei via ElevenLabs, Tower oder lokaler Engine.

        Fallback-Kette:
        1. ElevenLabs (MP3) → 2. Tower XTTS v2 (WAV) → 3. Lokale Engine (WAV)

        Args:
            text: Zu synthetisierender Text.
            output_path: Ziel-Pfad für die Audio-Datei.
            emotion: Optionaler Emotions-Name.

        Returns:
            Pfad zur generierten Audio-Datei (MP3 oder WAV).
        """
        # Versuche Cloud/Tower (async)
        try:
            audio_bytes = self._run_async(self.synthesize(text, emotion))

            # Suffix anpassen: ElevenLabs liefert MP3
            # AudioConverter.to_ogg_opus() kann beides (MP3/WAV) verarbeiten
            actual_path = output_path.with_suffix(".mp3")
            actual_path.write_bytes(audio_bytes)

            logger.debug(
                "TTS-Audio geschrieben: %s (%d bytes)",
                actual_path.name, len(audio_bytes),
            )
            return actual_path

        except (TTSUnavailableError, Exception) as e:
            if self._local_tts is None:
                raise

            # Fallback 2: Lokale TTSEngine (CoquiTTS/WindowsTTS)
            logger.info("TTS lokaler Fallback: %s", type(self._local_tts).__name__)
            return self._local_tts.generate_audio(text, output_path, emotion=emotion)

    def get_rate(self) -> int:
        """Sprechgeschwindigkeit – nicht steuerbar bei Cloud-TTS."""
        return self._rate

    def set_rate(self, rate: int) -> None:
        """Sprechgeschwindigkeit – nicht steuerbar bei Cloud-TTS."""
        self._rate = rate

    def get_volume(self) -> float:
        """Lautstärke – nicht steuerbar bei Cloud-TTS."""
        return self._volume

    def set_volume(self, volume: float) -> None:
        """Lautstärke – nicht steuerbar bei Cloud-TTS."""
        if not 0.0 <= volume <= 1.0:
            raise ValueError("Volume muss zwischen 0.0 und 1.0 liegen")
        self._volume = volume

    def get_voices(self) -> list[VoiceInfo]:
        """Verfügbare Stimmen – ElevenLabs Voice ist fest konfiguriert."""
        return [VoiceInfo(id="elevenlabs", name="ElevenLabs", language="de")]

    def set_voice(self, voice_id: str) -> None:
        """Stimme setzen – bei ElevenLabs über Voice-ID im Constructor."""
        logger.debug("set_voice('%s') ignoriert – Voice über ElevenLabs config", voice_id)
