"""Tests fuer FrameConfig (Phase 111, E2; Ae13)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from elder_berry.room_display.frame_config import (
    DEFAULT_CONFIG_PATH,
    FrameConfigError,
    apply_overrides,
    load_frame_config,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


class TestDefault:
    def test_default_values(self, tmp_path):
        config = load_frame_config(user_path=tmp_path / "fehlt.yaml")
        assert config.display.rotation == 90
        assert config.display.fps == 30
        assert config.display.transition_s == 1.0
        assert config.display.video_driver == "kmsdrm"
        assert config.display.fullscreen is True
        assert config.mode == "diagnostic"
        assert config.diagnostic.view == "testbild"
        assert config.diagnostic.transitions == 10
        assert config.diagnostic.hold_s == 1.0
        assert config.source == str(DEFAULT_CONFIG_PATH)

    def test_no_generation_settings_in_frame_config(self):
        """Modell/provider stehen in scenes.yaml (#1477 A1), nicht hier."""
        text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
        assert "gpt-image" not in text
        assert "data_collection" not in text


class TestUserOverride:
    def test_override_merges_per_key(self, tmp_path):
        user = _write(tmp_path / "frame_config.yaml", "display:\n  rotation: 270\n")
        config = load_frame_config(user_path=user)
        assert config.display.rotation == 270
        assert config.display.fps == 30  # aus dem Default
        assert config.diagnostic.view == "testbild"
        assert str(user) in config.source

    def test_nested_override(self, tmp_path):
        user = _write(
            tmp_path / "u.yaml",
            "mode:\n  diagnostic:\n    view: ueberblendung\n",
        )
        config = load_frame_config(user_path=user)
        assert config.diagnostic.view == "ueberblendung"
        assert config.diagnostic.transitions == 10

    def test_empty_override_is_ok(self, tmp_path):
        user = _write(tmp_path / "u.yaml", "")
        assert load_frame_config(user_path=user).display.rotation == 90

    def test_explicit_path_skips_user_file(self, tmp_path, monkeypatch):
        user = _write(tmp_path / "user.yaml", "display:\n  rotation: 270\n")
        explicit = _write(tmp_path / "explicit.yaml", "display:\n  fps: 25\n")
        config = load_frame_config(explicit, user_path=user)
        assert config.display.fps == 25
        assert config.display.rotation == 90

    def test_invalid_rotation_is_clear_error(self, tmp_path):
        user = _write(tmp_path / "u.yaml", "display:\n  rotation: 45\n")
        with pytest.raises(
            FrameConfigError, match=r"display\.rotation.*0, 90, 180, 270"
        ):
            load_frame_config(user_path=user)

    def test_invalid_override_does_not_fall_back_silently(self, tmp_path):
        user = _write(tmp_path / "u.yaml", "display:\n  fps: 0\n")
        with pytest.raises(FrameConfigError, match="fps"):
            load_frame_config(user_path=user)

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("display: [1, 2]\n", "display"),
            ("display:\n  rotation: true\n", "rotation"),
            ("display:\n  fps: 500\n", "fps"),
            ("display:\n  transition_s: 0\n", "transition_s"),
            ("display:\n  video_driver: ''\n", "video_driver"),
            ("display:\n  fullscreen: 'ja'\n", "fullscreen"),
            ("mode:\n  name: portrait\n", "mode.name"),
            ("mode:\n  diagnostic:\n    view: bunt\n", "view"),
            ("mode:\n  diagnostic:\n    transitions: 0\n", "transitions"),
            ("mode:\n  diagnostic:\n    hold_s: -1\n", "hold_s"),
            ("- a\n", "kein Mapping"),
            ("display: {rotation: [\n", "kein gueltiges YAML"),
        ],
    )
    def test_invalid_values(self, tmp_path, text, match):
        user = _write(tmp_path / "u.yaml", text)
        with pytest.raises(FrameConfigError, match=match):
            load_frame_config(user_path=user)

    def test_video_driver_null(self, tmp_path):
        user = _write(tmp_path / "u.yaml", "display:\n  video_driver: null\n")
        assert load_frame_config(user_path=user).display.video_driver is None

    def test_unreadable_explicit_path(self, tmp_path):
        with pytest.raises(FrameConfigError, match="nicht lesbar"):
            load_frame_config(tmp_path / "fehlt.yaml")


class TestOverrides:
    def _base(self, tmp_path):
        return load_frame_config(user_path=tmp_path / "fehlt.yaml")

    def test_none_keeps_values(self, tmp_path):
        base = self._base(tmp_path)
        assert apply_overrides(base) == base

    def test_overrides_apply(self, tmp_path):
        config = apply_overrides(
            self._base(tmp_path),
            rotation=270,
            fps=60,
            video_driver="dummy",
            view="ueberblendung",
        )
        assert config.display.rotation == 270
        assert config.display.fps == 60
        assert config.display.video_driver == "dummy"
        assert config.diagnostic.view == "ueberblendung"

    def test_invalid_override(self, tmp_path):
        with pytest.raises(FrameConfigError, match="--frame-rotation"):
            apply_overrides(self._base(tmp_path), rotation=45)
        with pytest.raises(FrameConfigError, match="--frame-view"):
            apply_overrides(self._base(tmp_path), view="bunt")
