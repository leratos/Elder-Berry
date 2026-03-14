"""TTS-Engine – Windows-Implementierung via pyttsx3 (SAPI5)."""
import logging
import platform

try:
    import pyttsx3
except (ImportError, OSError):
    # ImportError wenn Paket fehlt, OSError auf Linux ohne SAPI5.
    pyttsx3 = None  # type: ignore[assignment]

from .base import TTSEngine, VoiceInfo

logger = logging.getLogger(__name__)


def _check_platform() -> None:
    """Wirft RuntimeError wenn nicht auf Windows."""
    if platform.system() != "Windows":
        raise RuntimeError(
            f"WindowsTTSEngine ist nur unter Windows verfügbar "
            f"(aktuell: {platform.system()})."
        )


class WindowsTTSEngine(TTSEngine):
    """
    Text-to-Speech via pyttsx3 (nutzt Windows SAPI5).

    Offline-fähig, keine API-Keys nötig.
    """

    def __init__(self) -> None:
        _check_platform()
        self._engine = pyttsx3.init()
        logger.info("WindowsTTSEngine initialisiert")

    def speak(self, text: str, emotion: str | None = None) -> None:
        if not text.strip():
            logger.warning("speak() mit leerem Text aufgerufen")
            return
        logger.debug("speak: %s Zeichen", len(text))
        self._engine.say(text)
        self._engine.runAndWait()

    def get_rate(self) -> int:
        return int(self._engine.getProperty("rate"))

    def set_rate(self, rate: int) -> None:
        logger.info("set_rate: %d", rate)
        self._engine.setProperty("rate", rate)

    def get_volume(self) -> float:
        return float(self._engine.getProperty("volume"))

    def set_volume(self, volume: float) -> None:
        if not 0.0 <= volume <= 1.0:
            raise ValueError(
                f"Volume muss zwischen 0.0 und 1.0 liegen, war: {volume}"
            )
        logger.info("set_volume: %.2f", volume)
        self._engine.setProperty("volume", volume)

    def get_voices(self) -> list[VoiceInfo]:
        voices = self._engine.getProperty("voices")
        result = []
        for v in voices:
            # SAPI5 voices haben .id, .name und .languages
            lang = ""
            if v.languages:
                lang = str(v.languages[0])
            result.append(VoiceInfo(id=v.id, name=v.name, language=lang))
        return result

    def set_voice(self, voice_id: str) -> None:
        available = self.get_voices()
        ids = [v.id for v in available]
        if voice_id not in ids:
            raise ValueError(
                f"Stimme '{voice_id}' nicht gefunden. "
                f"Verfügbar: {[v.name for v in available]}"
            )
        logger.info("set_voice: %s", voice_id)
        self._engine.setProperty("voice", voice_id)
