"""Tests fuer RoomDisplayApp (Phase 111, E2, §4.2). pygame dummy."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from elder_berry.room_display.content_mode import ContentMode  # noqa: E402
from elder_berry.room_display.frame_rate_meter import FrameRateMeter  # noqa: E402
from elder_berry.room_display.oriented_display import OrientedDisplay  # noqa: E402
from elder_berry.room_display.room_display_app import RoomDisplayApp  # noqa: E402

FAST = {"fps": 500, "idle_fps": 500}


class ScriptedMode(ContentMode):
    """Modus, dessen Verhalten pro Tick vorgegeben wird."""

    def __init__(
        self, *, changes_at=(), animate_ticks=0, stop_after=None, on_tick=None
    ):
        self.ticks = 0
        self.renders = 0
        self.entered = False
        self.exited = False
        self._changes_at = set(changes_at)
        self._animate_ticks = animate_ticks
        self._stop_after = stop_after
        self._on_tick = on_tick

    def on_enter(self, display):
        self.entered = True

    def update(self, now):
        self.ticks += 1
        if self._on_tick is not None:
            self._on_tick(self.ticks)
        return self.ticks in self._changes_at or self.is_animating()

    def render(self, display):
        self.renders += 1

    def on_exit(self):
        self.exited = True

    def is_animating(self):
        return 0 < self.ticks <= self._animate_ticks

    def wants_exit(self):
        return self._stop_after is not None and self.ticks >= self._stop_after


@pytest.fixture
def display():
    pygame.display.init()
    screen = pygame.display.set_mode((720, 1280))
    yield OrientedDisplay(screen, 90)
    pygame.display.quit()


def test_static_image_renders_once(display):
    mode = ScriptedMode(stop_after=50)
    app = RoomDisplayApp(display, mode, **FAST)
    assert app.run() == 0
    assert mode.ticks == 50
    assert app.render_count == 1  # nur das erste Bild, kein Dauerrendern
    assert mode.entered and mode.exited


def test_change_triggers_single_render(display):
    mode = ScriptedMode(changes_at=(10, 20), stop_after=30)
    app = RoomDisplayApp(display, mode, **FAST)
    app.run()
    assert app.render_count == 3


def test_animation_renders_every_tick_and_feeds_meter(display):
    meter = FrameRateMeter()
    mode = ScriptedMode(animate_ticks=20, stop_after=40)
    app = RoomDisplayApp(display, mode, meter=meter, **FAST)
    app.run()
    assert app.render_count == 20
    stats = meter.summary()
    assert stats is not None and stats.frames == 19


def test_input_events_are_ignored(display):
    def post_inputs(tick):
        if tick == 2:
            for event in (
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 10)),
                pygame.event.Event(
                    pygame.MOUSEMOTION, pos=(20, 20), rel=(1, 1), buttons=(0, 0, 0)
                ),
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0),
                pygame.event.Event(
                    pygame.KEYDOWN, key=pygame.K_q, mod=pygame.KMOD_CTRL
                ),
                pygame.event.Event(
                    pygame.FINGERDOWN, x=0.5, y=0.5, finger_id=0, touch_id=0
                ),
                pygame.event.Event(pygame.MULTIGESTURE, touch_id=0, x=0.5, y=0.5),
            ):
                pygame.event.post(event)

    mode = ScriptedMode(stop_after=20, on_tick=post_inputs)
    app = RoomDisplayApp(display, mode, **FAST)
    assert app.run() == 0
    assert mode.ticks == 20  # nicht vorzeitig beendet
    assert app.ignored_events >= 6
    assert app.render_count == 1  # Eingaben loesen kein Neuzeichnen aus


def test_quit_event_ends_cleanly(display):
    mode = ScriptedMode(
        on_tick=lambda t: t == 3 and pygame.event.post(pygame.event.Event(pygame.QUIT))
    )
    app = RoomDisplayApp(display, mode, **FAST)
    assert app.run() == 0
    assert mode.ticks == 3
    assert mode.exited


def test_request_stop_ends_cleanly(display):
    holder = {}
    mode = ScriptedMode(on_tick=lambda t: t == 5 and holder["app"].request_stop())
    app = RoomDisplayApp(display, mode, **FAST)
    holder["app"] = app
    assert app.run() == 0
    assert mode.ticks == 5
    assert mode.exited


def test_on_exit_runs_on_exception(display):
    class Boom(ScriptedMode):
        def render(self, display):
            raise RuntimeError("kaputt")

    mode = Boom(stop_after=3)
    with pytest.raises(RuntimeError):
        RoomDisplayApp(display, mode, **FAST).run()
    assert mode.exited


def test_cursor_hidden(display):
    pygame.mouse.set_visible(True)
    RoomDisplayApp(display, ScriptedMode(stop_after=1), **FAST).run()
    assert pygame.mouse.get_visible() is False


def test_invalid_fps(display):
    with pytest.raises(ValueError):
        RoomDisplayApp(display, ScriptedMode(), fps=0)
