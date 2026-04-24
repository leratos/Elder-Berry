"""TTS-Engine – Coqui XTTS v2 mit Voice Cloning und Emotions-Support."""
import logging
import re
import tempfile
import wave
from pathlib import Path

try:
    import torch
    from TTS.api import TTS
except ImportError:
    torch = None  # type: ignore[assignment]
    TTS = None  # type: ignore[assignment,misc]

try:
    import sounddevice as sd
    import numpy as np
except (ImportError, OSError):
    # OSError: PortAudio-Library nicht vorhanden (z.B. CI ohne Audio-Hardware)
    sd = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]

from elder_berry.tts.base import TTSEngine, VoiceInfo

logger = logging.getLogger(__name__)

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

# Anti-Hallucination Inference-Parameter für XTTS v2.
# Das multilingual-Modell driftet ohne diese Einschränkungen in andere
# Sprachen ab (Language Bleed, z.B. japanische Phoneme am Satzende).
# temperature: Niedrigere Werte → deterministischere Token-Wahl (Default: 0.75)
# top_p/top_k: Einschränkung des Token-Pools (Defaults: 0.85 / 50)
# repetition_penalty: Verhindert Token-Wiederholungen/Loops (Default: 10.0)
XTTS_TEMPERATURE = 0.7
XTTS_TOP_P = 0.7
XTTS_TOP_K = 40
XTTS_REPETITION_PENALTY = 10.0

# Regex: Emojis und andere Non-Text-Zeichen entfernen
# Umfasst Emoji-Blöcke, Dingbats, Symbole, etc.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbole & Piktogramme
    "\U0001F680-\U0001F6FF"  # Transport & Karten
    "\U0001F1E0-\U0001F1FF"  # Flaggen
    "\U0001FA00-\U0001FA6F"  # Erweiterte Symbole
    "\U0001FA70-\U0001FAFF"  # Erweiterte Symbole
    "\U00002702-\U000027B0"  # Dingbats
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "\U0000200D"             # Zero Width Joiner
    "\U000020E3"             # Combining Enclosing Keycap
    "\U00002600-\U000026FF"  # Misc Symbols
    "\U00002300-\U000023FF"  # Misc Technical
    "]+",
    flags=re.UNICODE,
)


def _clean_text_for_tts(text: str) -> str:
    """Entfernt Emojis und bereinigt Text für TTS-Synthese.

    XTTS v2 kann mit Emojis nicht umgehen – es versucht sie als Phoneme
    zu interpretieren und driftet in andere Sprachen ab.
    Trailing Whitespace nach Satzzeichen löst nachweislich
    Halluzinationen aus (Language Bleed, z.B. japanische Phoneme).
    """
    cleaned = _EMOJI_PATTERN.sub("", text)
    # Mehrfache Leerzeichen und Whitespace bereinigen
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Trailing Whitespace nach Satzzeichen entfernen (Hallucination-Trigger)
    cleaned = re.sub(r"([.!?…])\s+$", r"\1", cleaned)
    return cleaned


def _split_sentences(text: str, max_chars: int = 250) -> list[str]:
    """Splittet Text an Satzgrenzen (. ! ? …) für satzweise TTS-Generierung.

    Kurze Fragmente (<15 Zeichen) werden an den vorherigen Satz angehängt,
    um XTTS-Drift bei zu kurzen Segmenten zu vermeiden.

    Segmente über max_chars werden zusätzlich an Komma/Semikolon/Doppelpunkt
    aufgespalten (XTTS-Limit: 253 Zeichen für Deutsch).
    """
    # Split an Satzzeichen, behalte das Satzzeichen am Ende
    raw = re.split(r"(?<=[.!?…])\s+", text.strip())
    raw = [s.strip() for s in raw if s.strip()]

    if not raw:
        return [text]

    # Kurze Fragmente an vorherigen Satz anhängen
    merged: list[str] = []
    for part in raw:
        if merged and len(part) < 15:
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)

    if not merged:
        return [text]

    # Lange Segmente an Komma/Semikolon/Doppelpunkt/Gedankenstrich aufbrechen
    final: list[str] = []
    for segment in merged:
        if len(segment) <= max_chars:
            final.append(segment)
            continue
        # Subsplit an ,;:–-
        parts = re.split(r"(?<=[,;:–\-])\s+", segment)
        chunk = ""
        for part in parts:
            if chunk and len(chunk) + 1 + len(part) > max_chars:
                final.append(chunk.strip())
                chunk = part
            else:
                chunk = chunk + " " + part if chunk else part
        if chunk.strip():
            final.append(chunk.strip())

    return final


class CoquiTTSEngine(TTSEngine):
    """
    Text-to-Speech via Coqui XTTS v2 mit Voice Cloning.

    Wählt das Speaker-WAV anhand der übergebenen Emotion.
    Unterstützt explizites load()/unload() für VRAM-Management
    (sequentieller Betrieb mit Ollama auf 8GB VRAM).

    Plattformhinweis: Läuft auf Windows und Linux.
    GPU wird bevorzugt, CPU als Fallback.
    """

    def __init__(
        self,
        voice_map: dict[str, Path] | None = None,
        default_speaker_wav: Path | None = None,
        language: str = "de",
        model_name: str = XTTS_MODEL,
    ) -> None:
        """
        Args:
            voice_map: Emotion-Name → Pfad zum Speaker-WAV.
            default_speaker_wav: Fallback-WAV wenn Emotion nicht gemappt.
            language: Sprache für XTTS (Standard: "de").
            model_name: Coqui TTS Modellname.
        """
        if TTS is None:
            raise ImportError(
                "Coqui TTS nicht installiert. "
                "Installiere mit: pip install TTS sounddevice numpy"
            )

        self._voice_map = voice_map or {}
        self._default_speaker_wav = default_speaker_wav
        self._language = language
        self._model_name = model_name
        self._tts: TTS | None = None
        self._device: str = ""
        self._volume: float = 1.0
        self._rate: int = 200  # Nicht direkt steuerbar bei XTTS, Platzhalter

        logger.info(
            "CoquiTTSEngine konfiguriert: model=%s, language=%s, "
            "voice_map=%d Emotionen",
            model_name, language, len(self._voice_map),
        )

    @property
    def is_loaded(self) -> bool:
        """Ob das Modell aktuell geladen ist."""
        return self._tts is not None

    def load(self) -> None:
        """Lädt das XTTS-Modell auf GPU (oder CPU als Fallback)."""
        if self._tts is not None:
            logger.debug("Modell bereits geladen")
            return

        self._device = "cuda" if torch and torch.cuda.is_available() else "cpu"
        logger.info("Lade XTTS-Modell auf %s...", self._device)

        self._tts = TTS(model_name=self._model_name).to(self._device)
        logger.info("XTTS-Modell geladen auf %s", self._device)

    def unload(self) -> None:
        """Entlädt das XTTS-Modell und gibt VRAM/RAM frei."""
        if self._tts is None:
            return

        del self._tts
        self._tts = None

        if torch and torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info("XTTS-Modell entladen, Speicher freigegeben")

    def speak(self, text: str, emotion: str | None = None) -> None:
        """
        Generiert Audio via XTTS und spielt es ab (blockierend).

        Args:
            text: Auszusprechender Text.
            emotion: Emotions-Name → wählt das passende Speaker-WAV.
        """
        if not text.strip():
            logger.warning("speak() mit leerem Text aufgerufen")
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            output_path = Path(tmp.name)

        try:
            self.generate_audio(text, output_path, emotion)
            self._play_audio(output_path)
        finally:
            if output_path.exists():
                output_path.unlink()

    def generate_audio(self, text: str, output_path: Path,
                       emotion: str | None = None) -> Path:
        """
        Generiert eine WAV-Datei via XTTS Voice Cloning.

        Args:
            text: Zu synthetisierender Text.
            output_path: Ziel-Pfad für die WAV-Datei.
            emotion: Emotions-Name → wählt das passende Speaker-WAV.

        Returns:
            Pfad zur generierten WAV-Datei.
        """
        if not self.is_loaded:
            self.load()

        # Emojis entfernen – XTTS kann damit nicht umgehen und driftet
        # in andere Sprachen ab (z.B. 🌙 → japanische Phoneme)
        clean = _clean_text_for_tts(text)
        if not clean:
            logger.warning("Text nach Emoji-Bereinigung leer, überspringe TTS")
            return output_path

        speaker_wav = self._resolve_speaker_wav(emotion)
        if speaker_wav is None:
            raise ValueError(
                "Kein Speaker-WAV verfügbar. Setze default_speaker_wav "
                "oder konfiguriere voice_map."
            )

        logger.debug(
            "Generiere Audio: %d Zeichen, emotion=%s, speaker=%s",
            len(clean), emotion, speaker_wav.name,
        )

        # Eigenes Satz-Splitting + WAV-Concatenation.
        # XTTS v2 driftet bei kurzem internem Splitting in andere Sprachen.
        # Wir splitten selbst an Satzzeichen, generieren pro Satz einzeln
        # (jedes Mal mit vollem Speaker-Referenz-Kontext) und fügen zusammen.
        sentences = _split_sentences(clean)

        if len(sentences) <= 1:
            # Einzelner Satz: direkt generieren
            self._tts.tts_to_file(
                text=clean,
                speaker_wav=str(speaker_wav),
                language=self._language,
                file_path=str(output_path),
                split_sentences=False,
                temperature=XTTS_TEMPERATURE,
                top_p=XTTS_TOP_P,
                top_k=XTTS_TOP_K,
                repetition_penalty=XTTS_REPETITION_PENALTY,
            )
        else:
            # Mehrere Sätze: einzeln generieren + zusammenfügen
            self._generate_and_concat(sentences, speaker_wav, output_path)

        logger.debug("Audio generiert: %s", output_path)
        return output_path

    def _generate_and_concat(
        self, sentences: list[str], speaker_wav: Path, output_path: Path,
    ) -> None:
        """Generiert pro Satz ein WAV und fügt sie zusammen."""
        import wave

        parts: list[Path] = []
        try:
            for i, sentence in enumerate(sentences):
                part_path = output_path.with_suffix(f".part{i}.wav")
                self._tts.tts_to_file(
                    text=sentence,
                    speaker_wav=str(speaker_wav),
                    language=self._language,
                    file_path=str(part_path),
                    split_sentences=False,
                    temperature=XTTS_TEMPERATURE,
                    top_p=XTTS_TOP_P,
                    top_k=XTTS_TOP_K,
                    repetition_penalty=XTTS_REPETITION_PENALTY,
                )
                parts.append(part_path)

            # WAVs zusammenfügen (alle haben gleiches Format von XTTS)
            if not parts:
                return

            with wave.open(str(parts[0]), "rb") as first:
                params = first.getparams()
                all_frames = first.readframes(first.getnframes())

            for part in parts[1:]:
                with wave.open(str(part), "rb") as wf:
                    all_frames += wf.readframes(wf.getnframes())

            with wave.open(str(output_path), "wb") as out:
                out.setparams(params)
                out.writeframes(all_frames)

        finally:
            for part in parts:
                part.unlink(missing_ok=True)

    def _resolve_speaker_wav(self, emotion: str | None) -> Path | None:
        """Bestimmt das Speaker-WAV: emotion-spezifisch oder default."""
        if emotion and emotion in self._voice_map:
            return self._voice_map[emotion]
        return self._default_speaker_wav

    def _play_audio(self, audio_path: Path) -> None:
        """Spielt eine WAV-Datei ab (blockierend)."""
        if sd is None:
            raise ImportError(
                "sounddevice nicht installiert. "
                "Installiere mit: pip install sounddevice numpy"
            )

        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            n_frames = wf.getnframes()
            raw_data = wf.readframes(n_frames)

        audio_data = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)
        audio_data /= 32768.0  # Normalisieren auf [-1.0, 1.0]

        if n_channels > 1:
            audio_data = audio_data.reshape(-1, n_channels)

        audio_data *= self._volume

        sd.play(audio_data, samplerate=sample_rate)
        sd.wait()

    def get_rate(self) -> int:
        return self._rate

    def set_rate(self, rate: int) -> None:
        logger.info("set_rate: %d (Hinweis: XTTS Geschwindigkeit nicht direkt steuerbar)", rate)
        self._rate = rate

    def get_volume(self) -> float:
        return self._volume

    def set_volume(self, volume: float) -> None:
        if not 0.0 <= volume <= 1.0:
            raise ValueError(
                f"Volume muss zwischen 0.0 und 1.0 liegen, war: {volume}"
            )
        logger.info("set_volume: %.2f", volume)
        self._volume = volume

    def get_voices(self) -> list[VoiceInfo]:
        """Gibt verfügbare Voice-Samples als VoiceInfo zurück."""
        voices = []
        for emotion_name, _path in sorted(self._voice_map.items()):
            voices.append(VoiceInfo(
                id=emotion_name,
                name=f"Saleria ({emotion_name})",
                language=self._language,
            ))
        return voices

    def set_voice(self, voice_id: str) -> None:
        """Setzt das Default-Speaker-WAV auf die angegebene Emotion."""
        if voice_id not in self._voice_map:
            available = list(self._voice_map.keys())
            raise ValueError(
                f"Voice '{voice_id}' nicht gefunden. Verfügbar: {available}"
            )
        self._default_speaker_wav = self._voice_map[voice_id]
        logger.info("Default-Voice gesetzt: %s", voice_id)
