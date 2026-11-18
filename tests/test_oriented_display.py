"""Tests fuer OrientedDisplay (Phase 111, E2, §4.3). pygame dummy."""

from __future__ import annotations

import logging
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame = pytest.importorskip("pygame")

from elder_berry.room_display.oriented_display import (  # noqa: E402
    LOGICAL_SIZE,
    OrientedDisplay,
    fit_into,
)

RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)
BLACK = (0, 0, 0)


@pytest.fixture
def make_screen():
    pygame.display.init()

    def _make(size):
        return pygame.display.set_mode(size)

    yield _make
    pygame.display.quit()


def _marked_logical() -> pygame.Surface:
    """Logisches Bild: schwarz, roter Block in der Ecke oben links."""
    image = pygame.Surface(LOGICAL_SIZE)
    image.fill(BLACK)
    pygame.draw.rect(image, RED, pygame.Rect(0, 0, 40, 40))
    return image


def _rgb(surface, pos):
    return tuple(surface.get_at(pos))[:3]


# Rotation gegen den Uhrzeigersinn: wo landet die logische Ecke oben links?
@pytest.mark.parametrize(
    ("rotation", "physical", "corner"),
    [
        (0, (1280, 720), lambda w, h: (2, 2)),
        (90, (720, 1280), lambda w, h: (2, h - 3)),
        (180, (1280, 720), lambda w, h: (w - 3, h - 3)),
        (270, (720, 1280), lambda w, h: (w - 3, 2)),
    ],
)
def test_logical_top_left_lands_on_expected_physical_corner(
    make_screen, rotation, physical, corner
):
    screen = make_screen(physical)
    display = OrientedDisplay(screen, rotation)
    display.show(display.prepare(_marked_logical()))
    w, h = physical
    assert _rgb(screen, corner(w, h)) == RED
    # Gegenprobe: die diagonal gegenueberliegende Ecke ist nicht rot
    cx, cy = corner(w, h)
    assert _rgb(screen, (w - 1 - cx, h - 1 - cy)) == BLACK


def test_prepared_image_has_physical_size(make_screen):
    screen = make_screen((720, 1280))
    display = OrientedDisplay(screen, 90)
    assert display.prepare(_marked_logical()).get_size() == (720, 1280)
    assert display.physical_size == (720, 1280)
    assert display.logical_size == (1280, 720)


def test_scaling_keeps_aspect_ratio_with_black_bars(make_screen):
    screen = make_screen((1280, 720))
    display = OrientedDisplay(screen, 0)
    square = pygame.Surface((400, 400))
    square.fill(BLUE)
    display.show(display.prepare(square))
    # quadratisch -> 720x720 in der Mitte, links und rechts schwarz
    assert _rgb(screen, (100, 360)) == BLACK
    assert _rgb(screen, (1180, 360)) == BLACK
    assert _rgb(screen, (640, 360)) == BLUE
    assert _rgb(screen, (641, 5)) == BLUE  # volle Hoehe genutzt


def test_fit_into_handles_paletted_and_empty_surfaces():
    paletted = pygame.Surface((10, 10), 0, 8)
    assert fit_into(paletted, (40, 20)).get_size() == (40, 20)
    assert fit_into(pygame.Surface((0, 0)), (4, 4)).get_size() == (4, 4)


def test_rotation_only_when_loading(make_screen, monkeypatch):
    screen = make_screen((720, 1280))
    display = OrientedDisplay(screen, 90)
    calls = []
    original = pygame.transform.rotate

    def counting_rotate(surface, angle):
        calls.append(angle)
        return original(surface, angle)

    monkeypatch.setattr(pygame.transform, "rotate", counting_rotate)
    a = display.prepare(_marked_logical())
    b = display.prepare(_marked_logical())
    assert len(calls) == 2  # je einmal beim Laden
    calls.clear()
    for step in range(30):
        display.show(a)
        display.blend(a, b, step / 29)
        display.present()
    assert calls == []  # Render-Pfad dreht nicht


def test_show_dynamic_rotates_every_call(make_screen, monkeypatch):
    screen = make_screen((720, 1280))
    display = OrientedDisplay(screen, 90)
    calls = []
    original = pygame.transform.rotate
    monkeypatch.setattr(
        pygame.transform,
        "rotate",
        lambda s, a: calls.append(a) or original(s, a),
    )
    display.show_dynamic(_marked_logical())
    display.show_dynamic(_marked_logical())
    assert calls == [90, 90]


def test_no_rotation_call_at_zero(make_screen, monkeypatch):
    screen = make_screen((1280, 720))
    display = OrientedDisplay(screen, 0)
    monkeypatch.setattr(
        pygame.transform, "rotate", lambda *a: pytest.fail("rotate bei 0 Grad")
    )
    display.prepare(_marked_logical())


def test_blend_mixes_and_resets_alpha(make_screen):
    screen = make_screen((1280, 720))
    display = OrientedDisplay(screen, 0)
    red = pygame.Surface(LOGICAL_SIZE)
    red.fill(RED)
    green = pygame.Surface(LOGICAL_SIZE)
    green.fill(GREEN)
    a, b = display.prepare(red), display.prepare(green)

    display.blend(a, b, 0.0)
    assert _rgb(screen, (640, 360)) == RED
    display.blend(a, b, 1.0)
    assert _rgb(screen, (640, 360)) == GREEN
    display.blend(a, b, 0.5)
    r, g, _ = _rgb(screen, (640, 360))
    assert 100 < r < 160 and 100 < g < 160
    assert b.get_alpha() is None  # nicht dauerhaft halbtransparent


def test_mismatched_orientation_warns(make_screen, caplog):
    caplog.set_level(logging.WARNING)
    OrientedDisplay(make_screen((1280, 720)), 90)
    assert "passt nicht" in caplog.text
    caplog.clear()
    OrientedDisplay(make_screen((720, 1280)), 90)
    assert caplog.text == ""


def test_invalid_rotation(make_screen):
    with pytest.raises(ValueError):
        OrientedDisplay(make_screen((1280, 720)), 45)


def test_new_canvas_is_black_logical(make_screen):
    display = OrientedDisplay(make_screen((1280, 720)), 0)
    canvas = display.new_canvas()
    assert canvas.get_size() == LOGICAL_SIZE
    assert _rgb(canvas, (10, 10)) == BLACK
