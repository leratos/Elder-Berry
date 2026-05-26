"""Tests: avatar_config_loader -- Pfad-Resolution USER vs. DEFAULT.

Stellt sicher, dass der Loader den USER-Override-Pfad
(`~/.elder-berry/avatar_config.yaml`) vor dem getrackten DEFAULT-Template
priorisiert. Vermeidet den Bug aus dem 2026-05-20-Live-Test, wo
``update alles`` am dirty DEFAULT-File scheiterte.
"""

from __future__ import annotations

import yaml
import pytest

from elder_berry.avatar import avatar_config_loader as acl
from elder_berry.avatar.avatar_config_loader import (
    load_avatar_config,
    resolve_active_config_path,
)
from elder_berry.character.base import Emotion


_MINIMAL_CONFIG = {
    "emotions": {
        "neutral": {
            "body": "relaxed",
            "eye_left": "eye_left_open",
            "eye_right": "eye_right_open",
            "mouth": "mouth_neutral_close",
            "can_blink": True,
        }
    },
    "lip_sync": {"frames": {}, "interval": 0.18, "jitter": 0.03},
    "breathing": {"enabled": True, "speed": 1.0, "amplitude": 1.0},
    "idle_actions": [],
}


def _user_config_with_body(body_value: str) -> dict:
    """Variante von _MINIMAL_CONFIG mit anderem Body-Wert (Marker fuer den
    USER-Override-Pfad in Tests)."""
    return {
        **_MINIMAL_CONFIG,
        "emotions": {
            "neutral": {
                **_MINIMAL_CONFIG["emotions"]["neutral"],
                "body": body_value,
            }
        },
    }


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    """Patcht DEFAULT_CONFIG_PATH + USER_CONFIG_PATH auf tmp_path.

    DEFAULT existiert mit _MINIMAL_CONFIG; USER existiert anfangs NICHT
    (jeder Test kann ihn explizit anlegen).
    """
    default = tmp_path / "default.yaml"
    user = tmp_path / "user.yaml"
    with open(default, "w", encoding="utf-8") as f:
        yaml.dump(_MINIMAL_CONFIG, f)
    monkeypatch.setattr(acl, "DEFAULT_CONFIG_PATH", default)
    monkeypatch.setattr(acl, "USER_CONFIG_PATH", user)
    return default, user


class TestResolveActiveConfigPath:
    def test_returns_default_when_user_missing(self, patched_paths):
        default, user = patched_paths
        assert not user.exists()
        assert resolve_active_config_path() == default

    def test_returns_user_when_present(self, patched_paths):
        _, user = patched_paths
        with open(user, "w", encoding="utf-8") as f:
            yaml.dump(_MINIMAL_CONFIG, f)
        assert resolve_active_config_path() == user

    def test_reevaluates_on_each_call(self, patched_paths):
        """Nach dem ersten Editor-Save sieht der naechste Aufruf sofort
        USER -- es darf kein Cache im Modul haengen."""
        default, user = patched_paths
        assert resolve_active_config_path() == default

        with open(user, "w", encoding="utf-8") as f:
            yaml.dump(_MINIMAL_CONFIG, f)
        assert resolve_active_config_path() == user


class TestLoadAvatarConfigResolution:
    def test_no_arg_uses_user_when_present(self, patched_paths):
        _, user = patched_paths
        with open(user, "w", encoding="utf-8") as f:
            yaml.dump(_user_config_with_body("user_body"), f)

        cfg = load_avatar_config()
        assert cfg is not None
        assert cfg.emotions[Emotion.NEUTRAL].body == "user_body"

    def test_no_arg_falls_back_to_default(self, patched_paths):
        _, user = patched_paths
        assert not user.exists()
        cfg = load_avatar_config()
        assert cfg is not None
        assert cfg.emotions[Emotion.NEUTRAL].body == "relaxed"

    def test_explicit_path_overrides_resolution(self, patched_paths):
        """Backward-Compat: ein expliziter Pfad ignoriert die Resolution
        komplett -- USER existiert, aber wir lesen trotzdem DEFAULT."""
        default, user = patched_paths
        with open(user, "w", encoding="utf-8") as f:
            yaml.dump(_user_config_with_body("user_body"), f)

        cfg = load_avatar_config(default)
        assert cfg is not None
        assert cfg.emotions[Emotion.NEUTRAL].body == "relaxed"

    def test_returns_none_when_both_missing(self, tmp_path, monkeypatch):
        missing_default = tmp_path / "nonexistent_default.yaml"
        missing_user = tmp_path / "nonexistent_user.yaml"
        monkeypatch.setattr(acl, "DEFAULT_CONFIG_PATH", missing_default)
        monkeypatch.setattr(acl, "USER_CONFIG_PATH", missing_user)
        assert load_avatar_config() is None
