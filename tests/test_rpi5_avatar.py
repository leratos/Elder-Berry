"""Tests für RPi5AvatarDisplay – PyGame gemockt."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pygame():
    """Mockt pygame im layered_renderer Modul."""
    with patch("elder_berry.avatar.layered_renderer.pygame") as mock_pg:
        mock_pg.QUIT = 256
        mock_pg.FULLSCREEN = 0x80000000
        mock_pg.NOFRAME = 0x00000020
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
        mock_pg.Surface.return_value = mock_surface
        mock_pg.event.get.return_value = []

        yield {
            "pygame": mock_pg,
            "screen": mock_screen,
            "clock": mock_clock,
            "surface": mock_surface,
        }


@pytest.fixture
def layered_assets(tmp_path):
    """Erstellt temporäre Layered-Assets (body, eye, mouth Ordner)."""
    for subdir in ("body", "eye", "mouth"):
        d = tmp_path / subdir
        d.mkdir()
    # Mindest-Assets für NEUTRAL
    for name in [
        "body/idle.png",
        "body/angry.png",
        "body/thinking.png",
        "eye/eye_left_open.png",
        "eye/eye_right_open.png",
        "eye/eye_left_close.png",
        "eye/eye_right_close.png",
        "eye/eye_left_angry_open.png",
        "eye/eye_right_angry_open.png",
        "eye/eye_left_side_open.png",
        "eye/eye_right_side_open.png",
        "eye/eye_left_sad_open.png",
        "eye/eye_right_sad_open.png",
        "eye/eye_left_surprise_open.png",
        "eye/eye_right_surprise_open.png",
        "mouth/mouth_neutral_close.png",
        "mouth/mouth_halfopen.png",
        "mouth/mouth_open.png",
        "mouth/mouth_idle_close.png",
        "mouth/mouth_angry_open.png",
        "mouth/mouth_think_close.png",
    ]:
        (tmp_path / name).write_bytes(b"\x89PNG" + b"\x00" * 40)
    return tmp_path


@pytest.fixture
def avatar_display(mock_pygame, layered_assets):
    """Erstellt ein RPi5AvatarDisplay (nicht gestartet)."""
    from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

    return RPi5AvatarDisplay(
        width=720,
        height=1280,
        fullscreen=False,
        assets_dir=layered_assets,
    )


# ---------------------------------------------------------------------------
# Init + State
# ---------------------------------------------------------------------------


class TestRPi5AvatarInit:
    def test_initial_emotion_is_neutral(self, avatar_display):
        state = avatar_display.get_state()
        assert state["emotion"] == "neutral"

    def test_initial_speaking_is_false(self, avatar_display):
        state = avatar_display.get_state()
        assert state["speaking"] is False

    def test_initial_not_running(self, avatar_display):
        state = avatar_display.get_state()
        assert state["running"] is False

    def test_is_avatar_display(self, avatar_display):
        from elder_berry.robot.server import AvatarDisplay

        assert isinstance(avatar_display, AvatarDisplay)


# ---------------------------------------------------------------------------
# set_emotion / set_speaking (thread-safe)
# ---------------------------------------------------------------------------


class TestStateChanges:
    def test_set_emotion(self, avatar_display):
        avatar_display.set_emotion("cheerful")
        assert avatar_display.get_state()["emotion"] == "cheerful"

    def test_set_speaking_true(self, avatar_display):
        avatar_display.set_speaking(True)
        assert avatar_display.get_state()["speaking"] is True

    def test_set_speaking_false(self, avatar_display):
        avatar_display.set_speaking(True)
        avatar_display.set_speaking(False)
        assert avatar_display.get_state()["speaking"] is False

    def test_set_emotion_multiple(self, avatar_display):
        for e in ["angry", "sad", "neutral", "cheerful"]:
            avatar_display.set_emotion(e)
            assert avatar_display.get_state()["emotion"] == e

    def test_concurrent_set_emotion(self, avatar_display):
        """Viele Threads setzen gleichzeitig Emotionen → kein Crash."""
        errors = []

        def set_emotions(name: str):
            try:
                for _ in range(100):
                    avatar_display.set_emotion(name)
                    avatar_display.get_state()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=set_emotions, args=(e,))
            for e in ["angry", "cheerful", "neutral", "sad"]
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == []


# ---------------------------------------------------------------------------
# Render-Loop (Start / Stop)
# ---------------------------------------------------------------------------


class TestRenderLoop:
    def test_start_creates_thread(self, avatar_display, mock_pygame):
        # Renderer soll nach 1 Frame stoppen
        mock_pygame["pygame"].event.get.return_value = [
            MagicMock(type=256),  # QUIT
        ]
        avatar_display.start()
        time.sleep(0.3)
        avatar_display.stop()

    def test_stop_without_start(self, avatar_display):
        """Stop ohne Start → kein Crash."""
        avatar_display.stop()

    def test_double_start_warns(self, avatar_display, mock_pygame):
        """Doppelter Start → Warning statt zweiter Thread."""
        mock_pygame["pygame"].event.get.return_value = []
        avatar_display.start()
        time.sleep(0.1)
        avatar_display.start()  # Sollte warnen, nicht crashen
        avatar_display._stop_event.set()
        time.sleep(0.3)
        avatar_display.stop()

    def test_state_reflects_emotion_during_loop(self, avatar_display, mock_pygame):
        """Emotion-Änderungen sind sofort im State sichtbar."""
        avatar_display.set_emotion("angry")
        assert avatar_display.get_state()["emotion"] == "angry"
        avatar_display.set_emotion("cheerful")
        assert avatar_display.get_state()["emotion"] == "cheerful"


# ---------------------------------------------------------------------------
# Fullscreen
# ---------------------------------------------------------------------------


class TestFullscreen:
    def test_fullscreen_default_true(self, mock_pygame, layered_assets):
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

        avatar = RPi5AvatarDisplay(assets_dir=layered_assets)
        assert avatar._fullscreen is True

    def test_windowed_mode(self, mock_pygame, layered_assets):
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

        avatar = RPi5AvatarDisplay(fullscreen=False, assets_dir=layered_assets)
        assert avatar._fullscreen is False


# ---------------------------------------------------------------------------
# LayeredSpriteRenderer Fullscreen-Flag
# ---------------------------------------------------------------------------


class TestLayeredRendererFullscreen:
    def test_fullscreen_flag_sets_mode(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280, fullscreen=True)

        flags = mock_pygame["pygame"].FULLSCREEN | mock_pygame["pygame"].NOFRAME
        mock_pygame["pygame"].display.set_mode.assert_called_once_with(
            (720, 1280),
            flags,
        )
        mock_pygame["pygame"].mouse.set_visible.assert_called_once_with(False)

    def test_windowed_no_flags(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280, fullscreen=False)

        mock_pygame["pygame"].display.set_mode.assert_called_once_with(
            (720, 1280),
        )
        mock_pygame["pygame"].mouse.set_visible.assert_not_called()

    def test_resolution_720x1280(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)
        assert r._width == 720
        assert r._height == 1280


# ---------------------------------------------------------------------------
# Lip-Sync Fix
# ---------------------------------------------------------------------------


class TestLipSyncFix:
    def test_show_speaking_no_reset_when_already_speaking(
        self, mock_pygame, layered_assets
    ):
        """show_speaking(True) darf lip_sync_mouth nicht resetten wenn schon True."""
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)

        r.show_speaking(True)
        r._lip_sync_mouth = "mouth_open"  # Simuliere Fortschritt
        last_switch = r._last_lip_switch
        r.show_speaking(True)  # Erneuter Aufruf mit True
        assert r._lip_sync_mouth == "mouth_open"  # Darf nicht zurückgesetzt werden
        assert r._last_lip_switch == last_switch

    def test_show_speaking_resets_on_transition(self, mock_pygame, layered_assets):
        """show_speaking(True) resettet beim Übergang von False → True."""
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)

        r.show_speaking(True)
        r._lip_sync_mouth = "mouth_open"
        r.show_speaking(False)
        r.show_speaking(True)  # Übergang False → True
        # Reset: mouth auf ersten Key der lip_sync_keys
        assert r._lip_sync_mouth == r._lip_sync_keys[0]


# ---------------------------------------------------------------------------
# Idle-Animationen
# ---------------------------------------------------------------------------


class TestIdleAnimations:
    def test_idle_state_initial(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)
        assert r._idle_active is False
        assert r._idle_eye_left is None

    def test_idle_triggers_after_interval(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
        import time as _time

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)

        # Forciere nächste Idle sofort
        r._next_idle_time = _time.monotonic() - 1.0
        r._update_idle(_time.monotonic())
        assert r._idle_active is True

    def test_idle_ends_after_duration(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
        import time as _time

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)

        # Starte und beende Idle
        r._next_idle_time = _time.monotonic() - 1.0
        r._update_idle(_time.monotonic())
        assert r._idle_active is True

        r._idle_end_time = _time.monotonic() - 1.0  # Force Ende
        r._update_idle(_time.monotonic())
        assert r._idle_active is False

    def test_idle_disabled_while_speaking(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer
        import time as _time

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)

        r.show_speaking(True)
        r._next_idle_time = _time.monotonic() - 1.0
        # update() prueft is_speaking -> kein idle_update
        r.update()
        assert r._idle_active is False


# ---------------------------------------------------------------------------
# Display-Rotation (Bugfix: RPi5 ignoriert display_lcd_rotate=)
# ---------------------------------------------------------------------------


class TestDisplayRotation:
    """Tests fuer Display-Rotation in pygame (RPi5 KMS-Workaround)."""

    def test_default_rotation_is_zero_in_renderer(self, mock_pygame, layered_assets):
        """LayeredSpriteRenderer hat ohne Argument rotation=0 (neutral)."""
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280)
        assert r._rotation == 0

    def test_rotation_180_stored(self, mock_pygame, layered_assets):
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280, rotation=180)
        assert r._rotation == 180

    def test_rotation_invalid_raises(self, mock_pygame, layered_assets):
        """90 und 270 sind nicht implementiert -> ValueError."""
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        with pytest.raises(ValueError, match="rotation muss 0 oder 180"):
            r.initialize(720, 1280, rotation=90)
        with pytest.raises(ValueError, match="rotation muss 0 oder 180"):
            r.initialize(720, 1280, rotation=270)
        with pytest.raises(ValueError, match="rotation muss 0 oder 180"):
            r.initialize(720, 1280, rotation=45)

    def test_update_calls_flip_when_rotation_180(self, mock_pygame, layered_assets):
        """Bei rotation=180 wird pygame.transform.flip(screen, True, True) aufgerufen."""
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280, rotation=180)
        r.update()

        # flip wurde mit (screen, True, True) aufgerufen
        mock_pygame["pygame"].transform.flip.assert_called_with(
            mock_pygame["screen"],
            True,
            True,
        )

    def test_update_no_flip_when_rotation_zero(self, mock_pygame, layered_assets):
        """Bei rotation=0 wird transform.flip NICHT aufgerufen (Render-Performance)."""
        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        r = LayeredSpriteRenderer(assets_dir=layered_assets)
        r.initialize(720, 1280, rotation=0)
        r.update()

        mock_pygame["pygame"].transform.flip.assert_not_called()

    def test_rpi5_default_rotation_is_180(self, mock_pygame, layered_assets):
        """RPi5AvatarDisplay nutzt 180° als Default (Saleria steht baulich auf Kopf)."""
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

        avatar = RPi5AvatarDisplay(assets_dir=layered_assets)
        assert avatar._rotation == 180

    def test_rpi5_rotation_override(self, mock_pygame, layered_assets):
        """rotation kann beim Konstruieren ueberschrieben werden."""
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

        avatar = RPi5AvatarDisplay(assets_dir=layered_assets, rotation=0)
        assert avatar._rotation == 0

    def test_rpi5_rotation_passed_to_renderer(self, mock_pygame, layered_assets):
        """RPi5AvatarDisplay reicht rotation an LayeredSpriteRenderer.initialize()."""
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

        # Renderer-Klasse patchen, um initialize-Call abzufangen
        with patch(
            "elder_berry.robot.rpi5_avatar.LayeredSpriteRenderer"
        ) as MockRenderer:
            mock_inst = MagicMock()
            mock_inst.is_running.return_value = False  # sofort raus aus Loop
            MockRenderer.return_value = mock_inst

            avatar = RPi5AvatarDisplay(
                assets_dir=layered_assets,
                fullscreen=False,
                rotation=180,
            )
            avatar.start()
            time.sleep(0.3)
            avatar.stop()

            # initialize wurde mit rotation=180 aufgerufen
            mock_inst.initialize.assert_called_once()
            kwargs = mock_inst.initialize.call_args.kwargs
            assert kwargs.get("rotation") == 180

    def test_rpi5_rotation_zero_passed_to_renderer(self, mock_pygame, layered_assets):
        """RPi5AvatarDisplay mit rotation=0 reicht 0 an Renderer durch."""
        from elder_berry.robot.rpi5_avatar import RPi5AvatarDisplay

        with patch(
            "elder_berry.robot.rpi5_avatar.LayeredSpriteRenderer"
        ) as MockRenderer:
            mock_inst = MagicMock()
            mock_inst.is_running.return_value = False
            MockRenderer.return_value = mock_inst

            avatar = RPi5AvatarDisplay(
                assets_dir=layered_assets,
                fullscreen=False,
                rotation=0,
            )
            avatar.start()
            time.sleep(0.3)
            avatar.stop()

            kwargs = mock_inst.initialize.call_args.kwargs
            assert kwargs.get("rotation") == 0

    def test_sprite_renderer_rejects_rotation(self, layered_assets):
        """SpriteRenderer (Legacy) lehnt rotation != 0 ab -- nicht implementiert."""
        with patch("elder_berry.avatar.sprite_renderer.pygame") as mock_pg:
            mock_pg.display.set_mode.return_value = MagicMock()
            mock_pg.time.Clock.return_value = MagicMock()
            mock_pg.event.get.return_value = []

            from elder_berry.avatar.sprite_renderer import SpriteRenderer

            r = SpriteRenderer(assets_dir=layered_assets)
            with pytest.raises(
                ValueError, match="SpriteRenderer unterstuetzt keine Rotation"
            ):
                r.initialize(rotation=180)
