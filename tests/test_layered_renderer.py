"""Tests für LayeredSpriteRenderer – PyGame gemockt."""

import time
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.character.base import Emotion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pygame():
    """Mockt das pygame-Modul für LayeredSpriteRenderer."""
    with patch("elder_berry.avatar.layered_renderer.pygame") as mock_pg:
        mock_pg.QUIT = 256
        mock_screen = MagicMock()
        mock_pg.display.set_mode.return_value = mock_screen
        mock_clock = MagicMock()
        mock_pg.time.Clock.return_value = mock_clock
        mock_pg.get_init.return_value = True

        mock_surface = MagicMock()
        mock_surface.get_size.return_value = (512, 1024)
        mock_surface.convert_alpha.return_value = mock_surface
        mock_pg.image.load.return_value = mock_surface
        mock_pg.transform.smoothscale.return_value = mock_surface

        mock_pg.event.get.return_value = []

        yield {
            "pygame": mock_pg,
            "screen": mock_screen,
            "clock": mock_clock,
            "surface": mock_surface,
        }


@pytest.fixture
def layered_assets(tmp_path, monkeypatch):
    """Erstellt temporäre Asset-Ordner mit Dummy-PNGs.

    Isoliert zusaetzlich vom realen ``~/.elder-berry/avatar_config.yaml``
    und dem getrackten Repo-Default -- Renderer-Tests sollen das
    hardcoded-Fallback-Verhalten testen, nicht den Live-Repo-Config-
    Stand. Seit dem User-Override-Pattern resolvt der Loader ohne
    expliziten Pfad und wuerde sonst die echte Datei laden.
    """
    from elder_berry.avatar import avatar_config_loader as acl

    monkeypatch.setattr(
        acl, "DEFAULT_CONFIG_PATH", tmp_path / "_nonexistent_default.yaml"
    )
    monkeypatch.setattr(acl, "USER_CONFIG_PATH", tmp_path / "_nonexistent_user.yaml")
    for subdir, names in [
        (
            "body",
            [
                "idle",
                "angry",
                "thinking",
                "relaxed",
                "shy",
                "welcome",
                "confident",
                "tired",
            ],
        ),
        (
            "eye",
            [
                "eye_left_open",
                "eye_left_close",
                "eye_left_angry_open",
                "eye_left_sad_open",
                "eye_left_surprise_open",
                "eye_left_side_open",
                "eye_left_cheerful_open",
                "eye_left_shy_open",
                "eye_left_tired_open",
                "eye_left_confident_open",
                "eye_left_welcome_open",
                "eye_right_open",
                "eye_right_close",
                "eye_right_angry_open",
                "eye_right_sad_open",
                "eye_right_surprise_open",
                "eye_right_side_open",
                "eye_right_cheerful_open",
                "eye_right_shy_open",
                "eye_right_tired_open",
                "eye_right_confident_open",
                "eye_right_welcome_open",
            ],
        ),
        (
            "mouth",
            [
                "mouth_neutral_close",
                "mouth_idle_close",
                "mouth_think_close",
                "mouth_halfopen",
                "mouth_open",
                "mouth_angry_open",
                "mouth_friendly_open",
                "mouth_smirk_open",
                "mouth_grin",
                "mouth_shy_close",
                "mouth_pout",
                "mouth_tired_close",
                "mouth_tiny",
                "mouth_wide",
                "mouth_confident_halfopen",
            ],
        ),
    ]:
        d = tmp_path / subdir
        d.mkdir()
        for name in names:
            (d / f"{name}.png").write_bytes(b"\x89PNG" + b"\x00" * 40)
    return tmp_path


@pytest.fixture
def renderer(mock_pygame, layered_assets):
    """Erstellt einen initialisierten LayeredSpriteRenderer."""
    from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

    r = LayeredSpriteRenderer(assets_dir=layered_assets)
    r.initialize(512, 1024)
    return r


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestLayeredRendererInit:
    def test_is_avatar_renderer(self, renderer):
        assert isinstance(renderer, AvatarRenderer)

    def test_is_running_after_init(self, renderer):
        assert renderer.is_running()

    def test_default_emotion_is_neutral(self, renderer):
        assert renderer._current_emotion is Emotion.NEUTRAL

    def test_import_error_without_pygame(self):
        with patch("elder_berry.avatar.layered_renderer.pygame", None):
            from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

            with pytest.raises(ImportError, match="pygame"):
                LayeredSpriteRenderer()

    def test_initializes_pygame(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)
        mock_pygame["pygame"].init.assert_called_once()
        mock_pygame["pygame"].display.set_mode.assert_called_once_with((720, 1280))

    def test_loads_all_components(self, renderer):
        # 8 body + 22 eye + 15 mouth = 45
        assert len(renderer._components) == 45

    def test_default_height_1024(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize()
        mock_pygame["pygame"].display.set_mode.assert_called_with((512, 1024))


# ---------------------------------------------------------------------------
# Emotion
# ---------------------------------------------------------------------------


class TestEmotionDisplay:
    def test_show_emotion_changes_state(self, renderer):
        renderer.show_emotion(Emotion.ANGRY)
        assert renderer._current_emotion is Emotion.ANGRY

    def test_show_all_emotions(self, renderer):
        for emotion in Emotion:
            renderer.show_emotion(emotion)
            assert renderer._current_emotion is emotion


# ---------------------------------------------------------------------------
# Emotion Mapping
# ---------------------------------------------------------------------------


class TestEmotionMapping:
    def test_all_emotions_have_mapping(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        for emotion in Emotion:
            assert emotion in EMOTION_MAP, f"Emotion {emotion} fehlt im Mapping"

    def test_angry_uses_angry_body(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.ANGRY]
        assert layers.body == "angry"
        assert layers.can_blink is False

    def test_thoughtful_uses_thinking_body(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.THOUGHTFUL]
        assert layers.body == "thinking"

    def test_neutral_uses_relaxed_body(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        assert EMOTION_MAP[Emotion.NEUTRAL].body == "relaxed"

    def test_neutral_can_blink(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        assert EMOTION_MAP[Emotion.NEUTRAL].can_blink is True

    def test_sad_cannot_blink(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        assert EMOTION_MAP[Emotion.SAD].can_blink is False

    def test_shy_uses_shy_body_and_eyes(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.SHY]
        assert layers.body == "shy"
        assert layers.eye_left == "eye_left_shy_open"
        assert layers.eye_right == "eye_right_shy_open"

    def test_cheerful_uses_welcome_body(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.CHEERFUL]
        assert layers.body == "welcome"
        assert layers.mouth == "mouth_friendly_open"

    def test_motivated_uses_confident_body(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.MOTIVATED]
        assert layers.body == "confident"
        assert layers.mouth == "mouth_grin"

    def test_sarcastic_uses_smirk(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.SARCASTIC]
        assert layers.mouth == "mouth_smirk_open"

    def test_depressed_uses_tired_body(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        layers = EMOTION_MAP[Emotion.DEPRESSED]
        assert layers.body == "tired"
        assert layers.mouth == "mouth_pout"

    def test_each_emotion_has_distinct_combination(self):
        """Jede Emotion hat eine visuell unterscheidbare Kombination."""
        from elder_berry.avatar.layered_renderer import EMOTION_MAP

        combos = set()
        for emotion, layers in EMOTION_MAP.items():
            combo = (layers.body, layers.eye_left, layers.mouth)
            assert combo not in combos, (
                f"{emotion.value} hat gleiche Kombination wie eine andere Emotion"
            )
            combos.add(combo)


# ---------------------------------------------------------------------------
# Speaking / Lip-Sync
# ---------------------------------------------------------------------------


class TestSpeaking:
    def test_speaking_default_false(self, renderer):
        assert not renderer._is_speaking

    def test_show_speaking_true(self, renderer):
        renderer.show_speaking(True)
        assert renderer._is_speaking

    def test_show_speaking_false(self, renderer):
        renderer.show_speaking(True)
        renderer.show_speaking(False)
        assert not renderer._is_speaking

    def test_lip_sync_resets_on_speak_start(self, renderer):
        renderer._lip_sync_mouth = "mouth_open"
        renderer.show_speaking(True)
        assert renderer._lip_sync_mouth == renderer._lip_sync_keys[0]

    def test_lip_sync_produces_variety(self, renderer):
        """Lip-Sync verwendet gewichtete Zufallsauswahl → mehrere Mundformen."""
        renderer.show_speaking(True)
        mouths_seen = set()
        for _ in range(20):
            renderer._last_lip_switch = 0  # Erzwinge Wechsel
            mouth = renderer._get_lip_sync_mouth(time.monotonic())
            mouths_seen.add(mouth)
        assert len(mouths_seen) >= 2

    def test_lip_sync_jitter_varies_interval(self, renderer):
        """Lip-Sync Intervall variiert durch Jitter."""
        renderer.show_speaking(True)
        intervals = set()
        for _ in range(10):
            renderer._last_lip_switch = 0
            renderer._get_lip_sync_mouth(time.monotonic())
            intervals.add(round(renderer._next_lip_interval, 4))
        # Bei Jitter > 0 sollten verschiedene Intervalle entstehen
        assert len(intervals) >= 2


# ---------------------------------------------------------------------------
# Breathing
# ---------------------------------------------------------------------------


class TestBreathing:
    def test_breathing_enabled_by_default(self, renderer):
        assert renderer._breathing_enabled is True

    def test_breathing_offset_changes_over_time(self, renderer):
        """Breathing erzeugt unterschiedliche Y-Offsets."""
        import math

        offsets = set()
        for t in range(10):
            offset = int(
                math.sin(t * 0.5 * renderer._breathing_speed)
                * renderer._breathing_amplitude
            )
            offsets.add(offset)
        assert len(offsets) >= 2

    def test_breathing_disabled_no_offset(self, renderer, mock_pygame):
        """Wenn Breathing deaktiviert, kein Y-Offset."""
        renderer._breathing_enabled = False
        renderer.update()
        # Alle blit-Aufrufe sollten y_offset=0 haben (also Standard-Position)
        for call in mock_pygame["screen"].blit.call_args_list:
            _, pos = call[0]
            # Y-Position sollte exakt zentriert sein (keine Verschiebung)
            assert pos[1] == (1024 - 1024) // 2  # 0


# ---------------------------------------------------------------------------
# Blink
# ---------------------------------------------------------------------------


class TestBlink:
    def test_blink_not_active_initially(self, renderer):
        assert not renderer._blink_active

    def test_blink_activates_after_interval(self, renderer):
        renderer._next_blink_time = 0
        renderer._update_blink(time.monotonic())
        assert renderer._blink_active

    def test_blink_deactivates_after_duration(self, renderer):
        renderer._blink_active = True
        renderer._blink_end_time = 0
        renderer._update_blink(time.monotonic())
        assert not renderer._blink_active

    def test_blink_schedules_next(self, renderer):
        from elder_berry.avatar.layered_renderer import BLINK_MIN_INTERVAL

        renderer._blink_active = True
        renderer._blink_end_time = 0
        now = time.monotonic()
        renderer._update_blink(now)
        assert renderer._next_blink_time >= now + BLINK_MIN_INTERVAL


# ---------------------------------------------------------------------------
# Update (Render Loop)
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_fills_black_background(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["screen"].fill.assert_called_with((0, 0, 0))

    def test_update_blits_components(self, renderer, mock_pygame):
        renderer.update()
        # Mindestens 4 blits: body + eye_left + eye_right + mouth
        assert mock_pygame["screen"].blit.call_count >= 4

    def test_update_flips_display(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["pygame"].display.flip.assert_called()

    def test_update_ticks_clock(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["clock"].tick.assert_called_with(30)

    def test_quit_event_stops_renderer(self, renderer, mock_pygame):
        quit_event = MagicMock()
        quit_event.type = 256
        mock_pygame["pygame"].event.get.return_value = [quit_event]
        renderer.update()
        assert not renderer.is_running()

    def test_speaking_changes_mouth(self, renderer, mock_pygame):
        renderer.show_speaking(True)
        renderer._last_lip_switch = 0
        renderer.update()
        assert mock_pygame["screen"].blit.call_count >= 4


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_stops_running(self, renderer):
        renderer.shutdown()
        assert not renderer.is_running()

    def test_shutdown_quits_pygame(self, renderer, mock_pygame):
        renderer.shutdown()
        mock_pygame["pygame"].quit.assert_called_once()

    def test_update_after_shutdown_noop(self, renderer, mock_pygame):
        renderer.shutdown()
        mock_pygame["screen"].fill.reset_mock()
        renderer.update()
        mock_pygame["screen"].fill.assert_not_called()


# ---------------------------------------------------------------------------
# YAML Config Loading
# ---------------------------------------------------------------------------


class TestYAMLConfig:
    def test_loads_yaml_config_when_present(self, renderer):
        """Renderer lädt YAML-Config wenn vorhanden."""
        # Renderer hat _emotion_map von YAML oder hardcoded
        assert len(renderer._emotion_map) == 10

    def test_fallback_without_yaml(self, mock_pygame, tmp_path, monkeypatch):
        """Ohne YAML-Datei (weder USER noch DEFAULT): hardcoded Defaults."""
        for subdir in ["body", "eye", "mouth"]:
            d = tmp_path / subdir
            d.mkdir()
            (d / "dummy.png").write_bytes(b"\x89PNG" + b"\x00" * 40)

        # Loader-Pfade auf nicht-existente Sackgassen biegen. Seit dem
        # User-Override-Pattern entscheidet der Loader (nicht der
        # assets_dir-Parameter), welche Datei gelesen wird.
        from elder_berry.avatar import avatar_config_loader as acl

        monkeypatch.setattr(
            acl, "DEFAULT_CONFIG_PATH", tmp_path / "_nonexistent_default.yaml"
        )
        monkeypatch.setattr(
            acl, "USER_CONFIG_PATH", tmp_path / "_nonexistent_user.yaml"
        )

        from elder_berry.avatar.layered_renderer import (
            LayeredSpriteRenderer,
            EMOTION_MAP,
        )

        r = LayeredSpriteRenderer(assets_dir=tmp_path)
        # Kein avatar_config.yaml → Fallback
        assert r._emotion_map is EMOTION_MAP

    def test_breathing_config_from_yaml(self, renderer):
        assert renderer._breathing_speed > 0
        assert renderer._breathing_amplitude > 0

    def test_lip_sync_config_from_yaml(self, renderer):
        assert len(renderer._lip_sync_keys) >= 3
        assert len(renderer._lip_sync_probs) == len(renderer._lip_sync_keys)
        assert renderer._lip_sync_interval > 0


# ---------------------------------------------------------------------------
# AvatarConfigLoader
# ---------------------------------------------------------------------------


class TestAvatarConfigLoader:
    def test_load_valid_config(self):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        config = load_avatar_config()
        assert config is not None
        assert len(config.emotions) == 10
        assert Emotion.NEUTRAL in config.emotions
        assert Emotion.ANGRY in config.emotions

    def test_load_missing_file(self, tmp_path):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        result = load_avatar_config(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_load_invalid_yaml(self, tmp_path):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("not: [valid: yaml: {{", encoding="utf-8")
        result = load_avatar_config(bad_file)
        assert result is None

    def test_lip_sync_config(self):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        config = load_avatar_config()
        assert len(config.lip_sync_weights) >= 3
        assert config.lip_sync_interval > 0
        assert config.lip_sync_jitter >= 0

    def test_breathing_config(self):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        config = load_avatar_config()
        assert config.breathing_enabled is True
        assert config.breathing_speed > 0
        assert config.breathing_amplitude > 0

    def test_idle_actions_config(self):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        config = load_avatar_config()
        assert len(config.idle_actions) >= 3
        for action in config.idle_actions:
            assert action.name
            assert action.duration > 0

    def test_emotion_layers_fields(self):
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        config = load_avatar_config()
        neutral = config.emotions[Emotion.NEUTRAL]
        assert neutral.body == "relaxed"
        assert neutral.eye_left == "eye_left_open"
        assert neutral.can_blink is True


# ---------------------------------------------------------------------------
# Custom-Asset-Pack-Config (Codex P1)
# ---------------------------------------------------------------------------


class TestRendererAssetsDirConfig:
    """Renderer akzeptiert eine pack-eigene ``avatar_config.yaml`` neben
    den Pack-PNGs. Sonst koennten Component-Filenames aus dem Pack mit
    Emotion-/Lip-Sync-Keys aus dem USER-Override (anderes Mapping)
    kollidieren -- Codex P1 zum User-Override-Pattern.
    """

    def test_uses_assets_dir_local_config_when_present(
        self, mock_pygame, layered_assets
    ):
        """assets_dir-local avatar_config.yaml gewinnt gegen USER/DEFAULT."""
        import yaml

        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        custom_config = {
            "emotions": {
                "neutral": {
                    # Anderer Wert als der Hardcode-Default "relaxed"
                    # und als der Repo-Default-YAML -- erkennbarer Marker.
                    "body": "thinking",
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
        with open(layered_assets / "avatar_config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f)

        r = LayeredSpriteRenderer(assets_dir=layered_assets)

        assert r._emotion_map[Emotion.NEUTRAL].body == "thinking"

    def test_falls_through_to_user_when_no_local_config(
        self, mock_pygame, layered_assets, tmp_path, monkeypatch
    ):
        """Ohne assets_dir-local Config greift die USER→DEFAULT-Chain."""
        import yaml

        from elder_berry.avatar import avatar_config_loader as acl
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        # layered_assets hat KEIN avatar_config.yaml im assets_dir
        # und patched USER/DEFAULT auf nonexistent. Wir biegen USER
        # jetzt auf eine reale Datei mit Marker um.
        user_path = tmp_path / "real_user.yaml"
        user_config = {
            "emotions": {
                "neutral": {
                    "body": "shy",
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
        with open(user_path, "w", encoding="utf-8") as f:
            yaml.dump(user_config, f)
        monkeypatch.setattr(acl, "USER_CONFIG_PATH", user_path)

        r = LayeredSpriteRenderer(assets_dir=layered_assets)

        assert r._emotion_map[Emotion.NEUTRAL].body == "shy"
