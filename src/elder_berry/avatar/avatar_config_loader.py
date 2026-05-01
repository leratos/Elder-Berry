"""AvatarConfigLoader – Lädt und validiert die Avatar-Konfiguration aus YAML.

Liest avatar_config.yaml und erzeugt daraus die Datenstrukturen die der
LayeredSpriteRenderer benötigt (EMOTION_MAP, LIP_SYNC_WEIGHTS, etc.).

Fallback: Wenn die YAML-Datei fehlt oder invalide ist, werden die
hardcoded Defaults aus layered_renderer.py verwendet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from elder_berry.character.base import Emotion

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "assets" / "avatar_config.yaml"


@dataclass(frozen=True)
class EmotionLayers:
    """Definiert welche Komponenten für eine Emotion verwendet werden."""

    body: str
    eye_left: str
    eye_right: str
    mouth: str
    can_blink: bool
    effect: str | None = None


@dataclass(frozen=True)
class IdleAction:
    """Eine Idle-Animation."""

    name: str
    eye_left: str | None
    eye_right: str | None
    mouth: str | None
    duration: float


@dataclass
class AvatarConfig:
    """Gesamte Avatar-Konfiguration."""

    emotions: dict[Emotion, EmotionLayers]
    lip_sync_weights: dict[str, float]
    lip_sync_interval: float
    lip_sync_jitter: float
    breathing_enabled: bool
    breathing_speed: float
    breathing_amplitude: float
    idle_actions: list[IdleAction]


# Emotion-Name (YAML) → Enum Mapping
_EMOTION_NAMES: dict[str, Emotion] = {e.value: e for e in Emotion}


def load_avatar_config(path: Path | None = None) -> AvatarConfig | None:
    """Lädt die Avatar-Konfiguration aus einer YAML-Datei.

    Args:
        path: Pfad zur YAML-Datei. Default: assets/avatar_config.yaml.

    Returns:
        AvatarConfig oder None wenn die Datei fehlt oder invalide ist.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        logger.warning("Avatar-Config nicht gefunden: %s", config_path)
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        logger.exception("Fehler beim Lesen der Avatar-Config: %s", config_path)
        return None

    if not isinstance(data, dict):
        logger.error("Avatar-Config ist kein gültiges YAML-Dict: %s", config_path)
        return None

    try:
        return _parse_config(data)
    except Exception:
        logger.exception("Fehler beim Parsen der Avatar-Config")
        return None


def _parse_config(data: dict) -> AvatarConfig:
    """Parst das YAML-Dict in ein AvatarConfig-Objekt."""
    # Emotions
    emotions: dict[Emotion, EmotionLayers] = {}
    for name, layers_data in data.get("emotions", {}).items():
        emotion = _EMOTION_NAMES.get(name)
        if emotion is None:
            logger.warning("Unbekannte Emotion in Config: %s", name)
            continue
        emotions[emotion] = EmotionLayers(
            body=layers_data["body"],
            eye_left=layers_data["eye_left"],
            eye_right=layers_data["eye_right"],
            mouth=layers_data["mouth"],
            can_blink=layers_data.get("can_blink", True),
            effect=layers_data.get("effect"),
        )

    # Lip-Sync
    lip_sync = data.get("lip_sync", {})
    lip_sync_weights = lip_sync.get("frames", {})
    lip_sync_interval = lip_sync.get("interval", 0.18)
    lip_sync_jitter = lip_sync.get("jitter", 0.03)

    # Breathing
    breathing = data.get("breathing", {})
    breathing_enabled = breathing.get("enabled", True)
    breathing_speed = breathing.get("speed", 1.2)
    breathing_amplitude = breathing.get("amplitude", 2.0)

    # Idle Actions
    idle_actions: list[IdleAction] = []
    for action_data in data.get("idle_actions", []):
        idle_actions.append(
            IdleAction(
                name=action_data["name"],
                eye_left=action_data.get("eye_left"),
                eye_right=action_data.get("eye_right"),
                mouth=action_data.get("mouth"),
                duration=action_data.get("duration", 2.0),
            )
        )

    return AvatarConfig(
        emotions=emotions,
        lip_sync_weights=lip_sync_weights,
        lip_sync_interval=lip_sync_interval,
        lip_sync_jitter=lip_sync_jitter,
        breathing_enabled=breathing_enabled,
        breathing_speed=breathing_speed,
        breathing_amplitude=breathing_amplitude,
        idle_actions=idle_actions,
    )
