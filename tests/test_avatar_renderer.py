"""Tests für AvatarRenderer ABC und SpriteRenderer – PyGame gemockt."""
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.character.base import Emotion


# ---------------------------------------------------------------------------
# ABC-Tests
# ---------------------------------------------------------------------------

class TestAvatarRendererABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AvatarRenderer()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pygame():
    """Mockt das pygame-Modul."""
    with patch("elder_berry.avatar.sprite_renderer.pygame") as mock_pg:
        mock_pg.QUIT = 256  # pygame.QUIT Konstante
        mock_screen = MagicMock()
        mock_pg.display.set_mode.return_value = mock_screen
        mock_clock = MagicMock()
        mock_pg.time.Clock.return_value = mock_clock
        mock_pg.get_init.return_value = True

        # Simuliere Sprite-Loading: gibt Mock-Surface zurück
        mock_surface = MagicMock()
        mock_surface.get_size.return_value = (512, 512)
        mock_surface.convert_alpha.return_value = mock_surface
        mock_pg.image.load.return_value = mock_surface
        mock_pg.transform.smoothscale.return_value = mock_surface

        # Keine Events standardmäßig
        mock_pg.event.get.return_value = []

        yield {
            "pygame": mock_pg,
            "screen": mock_screen,
            "clock": mock_clock,
            "surface": mock_surface,
        }


@pytest.fixture
def sprite_dir(tmp_path):
    """Erstellt ein temporäres Assets-Verzeichnis mit Dummy-Sprites."""
    for emotion in Emotion:
        sprite_path = tmp_path / f"saleria-{emotion.value}.png"
        sprite_path.write_bytes(b"\x89PNG" + b"\x00" * 40)
    return tmp_path


@pytest.fixture
def renderer(mock_pygame, sprite_dir):
    """Erstellt einen initialisierten SpriteRenderer."""
    from elder_berry.avatar.sprite_renderer import SpriteRenderer
    r = SpriteRenderer(assets_dir=sprite_dir)
    r.initialize(512, 512)
    return r


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

class TestSpriteRendererInit:
    def test_is_avatar_renderer(self, renderer):
        assert isinstance(renderer, AvatarRenderer)

    def test_is_running_after_init(self, renderer):
        assert renderer.is_running()

    def test_default_emotion_is_neutral(self, renderer):
        assert renderer._current_emotion is Emotion.NEUTRAL

    def test_import_error_without_pygame(self):
        with patch("elder_berry.avatar.sprite_renderer.pygame", None):
            from elder_berry.avatar.sprite_renderer import SpriteRenderer
            with pytest.raises(ImportError, match="pygame"):
                SpriteRenderer()

    def test_initializes_pygame(self, mock_pygame, sprite_dir):
        from elder_berry.avatar.sprite_renderer import SpriteRenderer
        r = SpriteRenderer(assets_dir=sprite_dir)
        r.initialize(800, 600)
        mock_pygame["pygame"].init.assert_called_once()
        mock_pygame["pygame"].display.set_mode.assert_called_once_with((800, 600))

    def test_loads_all_sprites(self, renderer, mock_pygame):
        assert mock_pygame["pygame"].image.load.call_count == len(Emotion)


# ---------------------------------------------------------------------------
# Emotion
# ---------------------------------------------------------------------------

class TestEmotionDisplay:
    def test_show_emotion_changes_state(self, renderer):
        renderer.show_emotion(Emotion.ANGRY)
        assert renderer._current_emotion is Emotion.ANGRY

    def test_show_emotion_same_no_change(self, renderer):
        renderer.show_emotion(Emotion.NEUTRAL)
        assert renderer._current_emotion is Emotion.NEUTRAL

    def test_show_all_emotions(self, renderer):
        for emotion in Emotion:
            renderer.show_emotion(emotion)
            assert renderer._current_emotion is emotion


# ---------------------------------------------------------------------------
# Speaking Indicator
# ---------------------------------------------------------------------------

class TestSpeakingIndicator:
    def test_speaking_default_false(self, renderer):
        assert not renderer._is_speaking

    def test_show_speaking_true(self, renderer):
        renderer.show_speaking(True)
        assert renderer._is_speaking

    def test_show_speaking_false(self, renderer):
        renderer.show_speaking(True)
        renderer.show_speaking(False)
        assert not renderer._is_speaking


# ---------------------------------------------------------------------------
# Update (Render Loop)
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_update_fills_background(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["screen"].fill.assert_called()

    def test_update_blits_sprite(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["screen"].blit.assert_called()

    def test_update_flips_display(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["pygame"].display.flip.assert_called()

    def test_update_ticks_clock(self, renderer, mock_pygame):
        renderer.update()
        mock_pygame["clock"].tick.assert_called_with(30)

    def test_update_draws_speaking_indicator(self, renderer, mock_pygame):
        renderer.show_speaking(True)
        renderer.update()
        mock_pygame["pygame"].draw.circle.assert_called()

    def test_update_no_indicator_when_silent(self, renderer, mock_pygame):
        renderer.show_speaking(False)
        renderer.update()
        mock_pygame["pygame"].draw.circle.assert_not_called()

    def test_quit_event_stops_renderer(self, renderer, mock_pygame):
        quit_event = MagicMock()
        quit_event.type = 256  # pygame.QUIT
        mock_pygame["pygame"].event.get.return_value = [quit_event]
        renderer.update()
        assert not renderer.is_running()


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

    def test_update_after_shutdown_does_nothing(self, renderer, mock_pygame):
        renderer.shutdown()
        mock_pygame["screen"].fill.reset_mock()
        renderer.update()
        mock_pygame["screen"].fill.assert_not_called()
