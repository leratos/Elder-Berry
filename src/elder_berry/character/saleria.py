"""SaleriaEngine – Konkrete CharacterEngine für Saleria Berry."""

import logging
import re
from pathlib import Path

import yaml

from elder_berry.character.base import (
    CharacterEngine,
    Emotion,
    MoodState,
    Personality,
)
from elder_berry.character.emotion_tracker import EmotionTracker

logger = logging.getLogger(__name__)

# Regex: findet [emotion]-Tags (case-insensitive)
_EMOTION_TAG_RE = re.compile(
    r"\[(" + "|".join(e.value for e in Emotion) + r")\]",
    re.IGNORECASE,
)


class SaleriaEngine(CharacterEngine):
    """
    CharacterEngine für Saleria Berry.

    Lädt Persönlichkeit und Emotion-Mappings aus einer YAML-Datei.
    Voice-Samples liegen in einem konfigurierbaren Verzeichnis.
    """

    DEFAULT_YAML = Path(__file__).parent / "saleria.yaml"
    DEFAULT_VOICES_DIR = Path(__file__).parent.parent / "tts" / "voices"

    def __init__(
        self,
        config_path: Path | None = None,
        voices_dir: Path | None = None,
        sprites_dir: Path | None = None,
    ) -> None:
        self._config_path = config_path or self.DEFAULT_YAML
        self._voices_dir = voices_dir or self.DEFAULT_VOICES_DIR
        self._sprites_dir = sprites_dir
        self._mood = MoodState()
        self._emotion_tracker = EmotionTracker()

        config = self._load_config()
        self._personality = self._parse_personality(config)
        self._voice_map = self._parse_voice_map(config)
        self._prompt_template = config.get("system_prompt_template", "")

        logger.info("SaleriaEngine geladen: %s", self._personality.name)

    def _load_config(self) -> dict:
        """Lädt die YAML-Konfiguration."""
        with open(self._config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def _parse_personality(config: dict) -> Personality:
        """Parst den personality-Block aus der Config."""
        p = config["personality"]
        return Personality(
            name=p["name"],
            title=p["title"],
            core_trait=p["core_trait"].strip(),
            speaking_style=p["speaking_style"].strip(),
            boundaries=p.get("boundaries", []),
        )

    def _parse_voice_map(self, config: dict) -> dict[Emotion, Path]:
        """Baut die Emotion→Voice-Sample Zuordnung."""
        samples = config.get("voice_samples", {})
        voice_map: dict[Emotion, Path] = {}
        for emotion in Emotion:
            filename = samples.get(emotion.value)
            if filename:
                path = self._voices_dir / filename
                if path.exists():
                    voice_map[emotion] = path
                else:
                    logger.warning("Voice-Sample nicht gefunden: %s", path)
        return voice_map

    def get_personality(self) -> Personality:
        return self._personality

    def get_mood(self) -> MoodState:
        return self._mood

    def set_mood(self, emotion: Emotion, intensity: float = 0.5) -> None:
        self._mood = MoodState(current_emotion=emotion, intensity=intensity)

    def build_system_prompt(
        self,
        available_actions: str = "",
        memory_context: str = "",
        remote_commands: str = "",
    ) -> str:
        emotions_list = ", ".join(f"[{e.value}]" for e in Emotion)
        return self._prompt_template.format(
            name=self._personality.name,
            core_trait=self._personality.core_trait,
            speaking_style=self._personality.speaking_style,
            emotions_list=emotions_list,
            action_list=available_actions,
            memory_context=memory_context,
            remote_commands=remote_commands,
        )

    def extract_emotion(self, llm_response: str) -> Emotion:
        match = _EMOTION_TAG_RE.search(llm_response)
        if match:
            tag_value = match.group(1).lower()
            try:
                emotion = Emotion(tag_value)
                self.set_mood(emotion)
                self._emotion_tracker.record(emotion)
                return emotion
            except ValueError:
                logger.warning("Unbekannter Emotions-Tag: %s", tag_value)
        return Emotion.NEUTRAL

    def clean_response(self, llm_response: str) -> str:
        return _EMOTION_TAG_RE.sub("", llm_response).strip()

    def get_mood_context(self) -> str | None:
        return self._emotion_tracker.get_mood_summary()

    def get_voice_sample(self, emotion: Emotion) -> Path | None:
        return self._voice_map.get(emotion)

    def get_sprite_asset(self, emotion: Emotion) -> Path | None:
        if self._sprites_dir is None:
            return None
        # Konvention: sprites_dir/saleria-{emotion.value}.png
        path = self._sprites_dir / f"saleria-{emotion.value}.png"
        return path if path.exists() else None
