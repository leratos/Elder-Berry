"""Tests für LayeredSpriteRenderer – PyGame gemockt."""
import time
from pathlib import Path
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
def layered_assets(tmp_path):
    """Erstellt temporäre Asset-Ordner mit Dummy-PNGs."""
    for subdir, names in [
        ("body", ["idle", "angry", "thinking"]),
        ("eye", [
            "eye_left_open", "eye_left_close", "eye_left_angry_open",
            "eye_left_sad_open", "eye_left_surprise_open", "eye_left_side_open",
            "eye_right_open", "eye_right_close", "eye_right_angry_open",
            "eye_right_sad_open", "eye_right_surprise_open", "eye_right_side_open",
        ]),
        ("mouth", [
            "mouth_neutral_close", "mouth_idle_close", "mouth_think_close",
            "mouth_halfopen", "mouth_open", "mouth_angry_open",
        ]),
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
        # 3 body + 12 eye + 6 mouth = 21
        assert len(renderer._components) == 21

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

    def test_neutral_can_blink(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP
        assert EMOTION_MAP[Emotion.NEUTRAL].can_blink is True

    def test_sad_cannot_blink(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP
        assert EMOTION_MAP[Emotion.SAD].can_blink is False

    def test_shy_uses_closed_eyes(self):
        from elder_berry.avatar.layered_renderer import EMOTION_MAP
        layers = EMOTION_MAP[Emotion.SHY]
        assert layers.eye_left == "eye_left_close"
        assert layers.eye_right == "eye_right_close"


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
        renderer._lip_sync_index = 3
        renderer.show_speaking(True)
        assert renderer._lip_sync_index == 0

    def test_lip_sync_cycles_mouths(self, renderer):
        from elder_berry.avatar.layered_renderer import LIP_SYNC_MOUTHS
        renderer.show_speaking(True)
        mouths_seen = set()
        # Simuliere Zeit-Fortschritt
        for i in range(len(LIP_SYNC_MOUTHS)):
            renderer._last_lip_switch = 0  # Erzwinge Wechsel
            mouth = renderer._get_lip_sync_mouth(time.monotonic())
            mouths_seen.add(mouth)
        assert len(mouths_seen) >= 2  # Mindestens 2 verschiedene Mundformen


# ---------------------------------------------------------------------------
# Blink
# ---------------------------------------------------------------------------

class TestBlink:
    def test_blink_not_active_initially(self, renderer):
        assert not renderer._blink_active

    def test_blink_activates_after_interval(self, renderer):
        # Setze next_blink_time in die Vergangenheit
        renderer._next_blink_time = 0
        renderer._update_blink(time.monotonic())
        assert renderer._blink_active

    def test_blink_deactivates_after_duration(self, renderer):
        renderer._blink_active = True
        renderer._blink_end_time = 0  # In der Vergangenheit
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
        renderer._last_lip_switch = 0  # Erzwinge Mundwechsel
        renderer.update()
        # Sicherstellen dass blit aufgerufen wird (Lip-Sync aktiv)
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
