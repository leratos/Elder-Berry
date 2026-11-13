"""Headless-Render von LayeredSpriteRenderer.render_to_file (elder-berry#1462).

Zwei Ebenen:

* ``TestHeadlessRenderReal`` rendert mit **echtem** pygame(-ce) und den
  getrackten Repo-Assets – genau der Weg des Selfie-Commands auf dem
  Rootserver. Ohne pygame (z.B. in der CI, die weder ``[avatar]`` noch
  ``[server]`` installiert) wird die Klasse per ``importorskip``
  uebersprungen.
* ``TestHeadlessNoInit`` prueft mit gemocktem pygame, dass der headless-Pfad
  kein ``pygame.init()`` aufruft (sonst startet der Mixer und ALSA meldet auf
  dem Server ohne Soundkarte Fehler).
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.character.base import Emotion


def _png_size(path: Path) -> tuple[int, int]:
    """Liest Breite/Hoehe aus dem IHDR-Chunk einer PNG-Datei."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", "keine PNG-Signatur"
    width, height = struct.unpack(">II", header[16:24])
    return width, height


class TestHeadlessRenderReal:
    """Echter Render ohne Display mit den Repo-Assets."""

    @pytest.fixture(autouse=True)
    def _require_pygame(self) -> None:
        pytest.importorskip("pygame")

    def test_render_to_file_writes_png_512x1024_with_content(
        self, tmp_path: Path
    ) -> None:
        import pygame

        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        out = tmp_path / "selfie.png"
        renderer = LayeredSpriteRenderer()
        result = renderer.render_to_file(out, Emotion.CHEERFUL)

        assert result == out
        assert out.exists()
        assert _png_size(out) == (512, 1024)

        # Nicht nur Schwarz: mindestens ein Teil der Pixel traegt Saleria.
        surface = pygame.image.load(str(out))
        width, height = surface.get_size()
        lit = 0
        for y in range(0, height, 16):
            for x in range(0, width, 16):
                r, g, b, *_ = surface.get_at((x, y))
                if r or g or b:
                    lit += 1
        assert lit > 0, "Render ist komplett schwarz"

    def test_render_does_not_start_mixer(self, tmp_path: Path) -> None:
        """Kein Audio-Init im headless-Pfad (ALSA-Lograuschen, #1462)."""
        import pygame

        from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

        if pygame.mixer.get_init():
            pytest.skip("Mixer bereits von einem anderen Test initialisiert")

        LayeredSpriteRenderer().render_to_file(tmp_path / "a.png")

        assert pygame.mixer.get_init() is None


class TestHeadlessNoInit:
    """Gemocktes pygame: render_to_file ruft kein pygame.init()."""

    def test_no_pygame_init_in_headless_path(self, tmp_path: Path) -> None:
        with patch("elder_berry.avatar.layered_renderer.pygame") as mock_pg:
            surface = MagicMock()
            surface.get_size.return_value = (512, 1024)
            mock_pg.image.load.return_value = surface
            mock_pg.Surface.return_value = MagicMock()
            mock_pg.get_init.return_value = False

            from elder_berry.avatar.layered_renderer import LayeredSpriteRenderer

            renderer = LayeredSpriteRenderer()
            renderer.render_to_file(tmp_path / "x.png")

            mock_pg.init.assert_not_called()
            mock_pg.image.save.assert_called_once()
