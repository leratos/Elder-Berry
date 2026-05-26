"""AvatarConfigLoader – Lädt und validiert die Avatar-Konfiguration aus YAML.

Liest avatar_config.yaml und erzeugt daraus die Datenstrukturen die der
LayeredSpriteRenderer benötigt (EMOTION_MAP, LIP_SYNC_WEIGHTS, etc.).

Pfad-Aufloesung (User-Override-Pattern):
- ``USER_CONFIG_PATH`` (~/.elder-berry/avatar_config.yaml) gewinnt, wenn
  vorhanden -- gitignored, vom Avatar-Editor beschreibbar, vom
  ``update alles``-Pull nicht angefasst.
- ``DEFAULT_CONFIG_PATH`` (src/.../assets/avatar_config.yaml) ist das
  getrackte Default-Template, das mit dem Code ausgeliefert wird.

Fallback: Wenn weder USER noch DEFAULT existieren oder die Datei
invalide ist, werden die hardcoded Defaults aus layered_renderer.py
verwendet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from elder_berry.character.base import Emotion

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "assets" / "avatar_config.yaml"
"""Getrackte Default-Config -- liefert das Template aus dem Repo aus."""

USER_CONFIG_PATH = Path.home() / ".elder-berry" / "avatar_config.yaml"
"""User-Override-Config -- Avatar-Editor schreibt hierhin, der git-Pull
faesst sie nicht an (gitignored). Konvention analog FactStore (facts.db
im gleichen Verzeichnis)."""


def resolve_active_config_path() -> Path:
    """Liefert den aktiven Config-Pfad: USER wenn vorhanden, sonst DEFAULT.

    Bei jedem Aufruf neu ausgewertet, damit Tests und der Avatar-Editor
    nach dem ersten Save sofort die User-Datei sehen.
    """
    if USER_CONFIG_PATH.exists():
        return USER_CONFIG_PATH
    return DEFAULT_CONFIG_PATH


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
        path: Expliziter Pfad zur YAML-Datei. Wenn gesetzt, wird nur
            dieser Pfad probiert -- keine USER/DEFAULT-Resolution.
            Wenn ``None``: Lookup-Chain ``USER → DEFAULT`` mit
            Fallback auf DEFAULT, falls USER zwar existiert aber
            unbrauchbar ist (korruptes YAML, fehlende Felder).

    Returns:
        AvatarConfig oder ``None`` wenn weder USER noch DEFAULT eine
        valide Config liefern.
    """
    if path is not None:
        return _load_one(path)

    # Lookup-Chain mit Recovery: ein kaputtes USER-File darf den
    # Avatar nicht still auf hardcoded Defaults zurueckwerfen, solange
    # eine valide DEFAULT-Config im Repo liegt.
    if USER_CONFIG_PATH.exists():
        config = _load_one(USER_CONFIG_PATH)
        if config is not None:
            return config
        logger.warning(
            "USER-Override Avatar-Config unbrauchbar (%s) -- Fallback auf DEFAULT.",
            USER_CONFIG_PATH,
        )

    return _load_one(DEFAULT_CONFIG_PATH)


def _load_one(config_path: Path) -> AvatarConfig | None:
    """Lädt und parst eine einzelne YAML-Datei. ``None`` bei jedem Fehler."""
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
