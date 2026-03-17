"""Avatar-Renderer – PyGame-basierte Sprite-Darstellung mit Emotionswechsel."""
import logging
from pathlib import Path

try:
    import pygame
except ImportError:
    pygame = None  # type: ignore[assignment]

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.character.base import Emotion

logger = logging.getLogger(__name__)

DEFAULT_ASSETS_DIR = Path(__file__).parent / "assets"
WINDOW_TITLE = "Elder-Berry – Saleria Berry"
BG_COLOR = (20, 20, 30)
SPEAKING_INDICATOR_COLOR = (80, 200, 120)
SPEAKING_INDICATOR_RADIUS = 8


class SpriteRenderer(AvatarRenderer):
    """
    PyGame-basierter Avatar-Renderer.

    Zeigt Sprites pro Emotion an. Unterstützt Sprech-Indikator
    und ist als Vorschau für späteres Holodisplay konzipiert.

    Plattformhinweis: Läuft auf Windows und Linux (überall wo PyGame läuft).
    """

    def __init__(
        self,
        assets_dir: Path | None = None,
        sprite_prefix: str = "saleria",
    ) -> None:
        """
        Args:
            assets_dir: Verzeichnis mit Sprite-PNGs.
            sprite_prefix: Dateiname-Präfix (z.B. "saleria" → "saleria-neutral.png").
        """
        if pygame is None:
            raise ImportError(
                "pygame nicht installiert. Installiere mit: pip install pygame"
            )

        self._assets_dir = assets_dir or DEFAULT_ASSETS_DIR
        self._sprite_prefix = sprite_prefix
        self._sprites: dict[Emotion, pygame.Surface] = {}
        self._screen: pygame.Surface | None = None
        self._clock: pygame.time.Clock | None = None
        self._current_emotion = Emotion.NEUTRAL
        self._is_speaking = False
        self._running = False
        self._width = 512
        self._height = 512

    def _load_sprites(self) -> None:
        """Lädt alle verfügbaren Sprites aus dem Assets-Verzeichnis."""
        for emotion in Emotion:
            path = self._assets_dir / f"{self._sprite_prefix}-{emotion.value}.png"
            if path.exists():
                sprite = pygame.image.load(str(path)).convert_alpha()
                self._sprites[emotion] = sprite
                logger.debug("Sprite geladen: %s", path.name)
            else:
                logger.warning("Sprite nicht gefunden: %s", path)

        logger.info("%d/%d Sprites geladen", len(self._sprites), len(Emotion))

    def initialize(self, width: int = 512, height: int = 512, fullscreen: bool = False) -> None:
        self._width = width
        self._height = height

        pygame.init()
        self._screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(WINDOW_TITLE)
        self._clock = pygame.time.Clock()
        self._running = True

        self._load_sprites()
        self._scale_sprites()

        logger.info("SpriteRenderer initialisiert: %dx%d", width, height)

    def _scale_sprites(self) -> None:
        """Skaliert Sprites auf Fenstergröße (Seitenverhältnis beibehalten)."""
        for emotion, sprite in self._sprites.items():
            sw, sh = sprite.get_size()
            scale = min(self._width / sw, self._height / sh)
            new_w = int(sw * scale)
            new_h = int(sh * scale)
            self._sprites[emotion] = pygame.transform.smoothscale(sprite, (new_w, new_h))

    def show_emotion(self, emotion: Emotion) -> None:
        if emotion != self._current_emotion:
            logger.debug("Emotion: %s → %s", self._current_emotion.value, emotion.value)
            self._current_emotion = emotion

    def show_speaking(self, is_speaking: bool) -> None:
        self._is_speaking = is_speaking

    def update(self) -> None:
        if not self._running or self._screen is None:
            return

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return

        self._screen.fill(BG_COLOR)

        # Sprite zeichnen (zentriert)
        sprite = self._sprites.get(self._current_emotion)
        if sprite is not None:
            sw, sh = sprite.get_size()
            x = (self._width - sw) // 2
            y = (self._height - sh) // 2
            self._screen.blit(sprite, (x, y))

        # Sprech-Indikator (grüner Punkt unten rechts)
        if self._is_speaking:
            pos = (self._width - 25, self._height - 25)
            pygame.draw.circle(
                self._screen, SPEAKING_INDICATOR_COLOR,
                pos, SPEAKING_INDICATOR_RADIUS,
            )

        pygame.display.flip()
        self._clock.tick(30)  # 30 FPS

    def shutdown(self) -> None:
        self._running = False
        if pygame.get_init():
            pygame.quit()
        logger.info("SpriteRenderer beendet")

    def is_running(self) -> bool:
        return self._running
