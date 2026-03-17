"""Avatar-Renderer – Layered Component System mit Blink und Lip-Sync."""
import logging
import random
import time
from dataclasses import dataclass
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
BG_COLOR = (0, 0, 0)  # Schwarz für Pepper's Ghost
FPS = 30

# Blink-Timing
BLINK_MIN_INTERVAL = 2.0  # Sekunden
BLINK_MAX_INTERVAL = 6.0
BLINK_DURATION = 0.15  # Sekunden

# Lip-Sync-Timing
LIP_SYNC_INTERVAL = 0.18  # Sekunden zwischen Mundwechsel

# Idle-Animationen
IDLE_MIN_INTERVAL = 5.0   # Sekunden zwischen Idle-Aktionen
IDLE_MAX_INTERVAL = 15.0
IDLE_ACTION_DURATION = 2.0  # Sekunden die eine Idle-Aktion dauert


@dataclass(frozen=True)
class EmotionLayers:
    """Definiert welche Komponenten für eine Emotion verwendet werden."""
    body: str
    eye_left: str
    eye_right: str
    mouth: str
    can_blink: bool


# Mapping: Emotion → Komponenten-Dateinamen (ohne Ordner-Prefix)
EMOTION_MAP: dict[Emotion, EmotionLayers] = {
    Emotion.NEUTRAL: EmotionLayers(
        body="idle", eye_left="eye_left_open", eye_right="eye_right_open",
        mouth="mouth_neutral_close", can_blink=True,
    ),
    Emotion.CHEERFUL: EmotionLayers(
        body="idle", eye_left="eye_left_open", eye_right="eye_right_open",
        mouth="mouth_halfopen", can_blink=True,
    ),
    Emotion.ANGRY: EmotionLayers(
        body="angry", eye_left="eye_left_angry_open", eye_right="eye_right_angry_open",
        mouth="mouth_angry_open", can_blink=False,
    ),
    Emotion.SARCASTIC: EmotionLayers(
        body="idle", eye_left="eye_left_side_open", eye_right="eye_right_side_open",
        mouth="mouth_halfopen", can_blink=False,
    ),
    Emotion.MOTIVATED: EmotionLayers(
        body="idle", eye_left="eye_left_open", eye_right="eye_right_open",
        mouth="mouth_open", can_blink=True,
    ),
    Emotion.THOUGHTFUL: EmotionLayers(
        body="thinking", eye_left="eye_left_side_open", eye_right="eye_right_side_open",
        mouth="mouth_think_close", can_blink=False,
    ),
    Emotion.WHISPER: EmotionLayers(
        body="idle", eye_left="eye_left_open", eye_right="eye_right_open",
        mouth="mouth_halfopen", can_blink=True,
    ),
    Emotion.SHY: EmotionLayers(
        body="idle", eye_left="eye_left_close", eye_right="eye_right_close",
        mouth="mouth_neutral_close", can_blink=False,
    ),
    Emotion.DEPRESSED: EmotionLayers(
        body="idle", eye_left="eye_left_close", eye_right="eye_right_close",
        mouth="mouth_idle_close", can_blink=False,
    ),
    Emotion.SAD: EmotionLayers(
        body="idle", eye_left="eye_left_sad_open", eye_right="eye_right_sad_open",
        mouth="mouth_idle_close", can_blink=False,
    ),
}

# Lip-Sync: Mund-Zustände die beim Sprechen durchrotiert werden
LIP_SYNC_MOUTHS = ["mouth_neutral_close", "mouth_halfopen", "mouth_open", "mouth_halfopen"]


class LayeredSpriteRenderer(AvatarRenderer):
    """
    PyGame-basierter Avatar-Renderer mit Component Layering.

    Setzt Body + Augen (L+R) + Mund zur Laufzeit zusammen.
    Unterstützt Blink-Animation und Lip-Sync beim Sprechen.

    Optimiert für Pepper's Ghost: schwarzer Hintergrund,
    nur helle Pixel werden im Acrylglas reflektiert.

    Plattformhinweis: Läuft auf Windows und Linux.
    """

    def __init__(self, assets_dir: Path | None = None) -> None:
        if pygame is None:
            raise ImportError(
                "pygame nicht installiert. Installiere mit: pip install pygame"
            )

        self._assets_dir = assets_dir or DEFAULT_ASSETS_DIR
        self._components: dict[str, pygame.Surface] = {}
        self._screen: pygame.Surface | None = None
        self._clock: pygame.time.Clock | None = None
        self._current_emotion = Emotion.NEUTRAL
        self._is_speaking = False
        self._running = False
        self._width = 512
        self._height = 1024

        # Blink-State
        self._blink_active = False
        self._next_blink_time = 0.0
        self._blink_end_time = 0.0

        # Lip-Sync-State
        self._lip_sync_index = 0
        self._last_lip_switch = 0.0

    def _load_components(self) -> None:
        """Lädt alle Komponenten-PNGs aus den Unterordnern."""
        subdirs = {"body": "body", "eye": "eye", "mouth": "mouth"}
        total = 0

        for subdir_name, subdir_key in subdirs.items():
            subdir = self._assets_dir / subdir_name
            if not subdir.exists():
                logger.warning("Assets-Unterordner nicht gefunden: %s", subdir)
                continue

            for png_path in sorted(subdir.glob("*.png")):
                key = png_path.stem  # Dateiname ohne .png
                surface = pygame.image.load(str(png_path)).convert_alpha()
                self._components[key] = surface
                total += 1
                logger.debug("Komponente geladen: %s/%s", subdir_name, key)

        logger.info("%d Komponenten geladen", total)

    def _scale_components(self) -> None:
        """Skaliert alle Komponenten auf Fenstergröße."""
        for key, surface in self._components.items():
            sw, sh = surface.get_size()
            scale = min(self._width / sw, self._height / sh)
            new_w = int(sw * scale)
            new_h = int(sh * scale)
            if (new_w, new_h) != (sw, sh):
                self._components[key] = pygame.transform.smoothscale(
                    surface, (new_w, new_h)
                )

    def initialize(
        self,
        width: int = 512,
        height: int = 1024,
        fullscreen: bool = False,
    ) -> None:
        self._width = width
        self._height = height

        pygame.init()

        if fullscreen:
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            self._screen = pygame.display.set_mode((width, height), flags)
            pygame.mouse.set_visible(False)
        else:
            self._screen = pygame.display.set_mode((width, height))

        pygame.display.set_caption(WINDOW_TITLE)
        self._clock = pygame.time.Clock()
        self._running = True

        self._load_components()
        self._scale_components()
        self._schedule_next_blink()

        logger.info(
            "LayeredSpriteRenderer initialisiert: %dx%d%s, %d Komponenten",
            width, height,
            " (fullscreen)" if fullscreen else "",
            len(self._components),
        )

    def show_emotion(self, emotion: Emotion) -> None:
        if emotion != self._current_emotion:
            logger.debug(
                "Emotion: %s → %s",
                self._current_emotion.value, emotion.value,
            )
            self._current_emotion = emotion

    def show_speaking(self, is_speaking: bool) -> None:
        if is_speaking == self._is_speaking:
            return  # Kein Zustandswechsel → kein Reset
        self._is_speaking = is_speaking
        if is_speaking:
            self._lip_sync_index = 0
            self._last_lip_switch = time.monotonic()

    def update(self) -> None:
        if not self._running or self._screen is None:
            return

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return

        now = time.monotonic()
        layers = EMOTION_MAP.get(self._current_emotion)
        if layers is None:
            layers = EMOTION_MAP[Emotion.NEUTRAL]

        self._screen.fill(BG_COLOR)

        # Layer 1: Body
        self._blit_centered(layers.body)

        # Layer 2: Augen (mit Blink-Logic)
        eye_left = layers.eye_left
        eye_right = layers.eye_right

        if layers.can_blink:
            self._update_blink(now)
            if self._blink_active:
                eye_left = "eye_left_close"
                eye_right = "eye_right_close"

        self._blit_centered(eye_left)
        self._blit_centered(eye_right)

        # Layer 3: Mund (mit Lip-Sync)
        if self._is_speaking:
            mouth_key = self._get_lip_sync_mouth(now)
        else:
            mouth_key = layers.mouth

        self._blit_centered(mouth_key)

        pygame.display.flip()
        self._clock.tick(FPS)

    def _blit_centered(self, component_key: str) -> None:
        """Zeichnet eine Komponente zentriert auf den Screen."""
        surface = self._components.get(component_key)
        if surface is None:
            return

        sw, sh = surface.get_size()
        x = (self._width - sw) // 2
        y = (self._height - sh) // 2
        self._screen.blit(surface, (x, y))

    def _schedule_next_blink(self) -> None:
        """Plant den nächsten Blink-Zeitpunkt."""
        delay = random.uniform(BLINK_MIN_INTERVAL, BLINK_MAX_INTERVAL)
        self._next_blink_time = time.monotonic() + delay

    def _update_blink(self, now: float) -> None:
        """Aktualisiert den Blink-Zustand."""
        if self._blink_active:
            if now >= self._blink_end_time:
                self._blink_active = False
                self._schedule_next_blink()
        elif now >= self._next_blink_time:
            self._blink_active = True
            self._blink_end_time = now + BLINK_DURATION

    def _get_lip_sync_mouth(self, now: float) -> str:
        """Gibt den aktuellen Lip-Sync-Mund zurück."""
        if now - self._last_lip_switch >= LIP_SYNC_INTERVAL:
            self._lip_sync_index = (self._lip_sync_index + 1) % len(LIP_SYNC_MOUTHS)
            self._last_lip_switch = now
        return LIP_SYNC_MOUTHS[self._lip_sync_index]

    def render_to_file(
        self, output_path: Path, emotion: Emotion = Emotion.NEUTRAL,
    ) -> Path:
        """Rendert Avatar mit gegebener Emotion als PNG (headless, kein Fenster).

        Lädt Komponenten bei Bedarf ohne Display-Fenster.
        Erstellt einen offscreen-Surface, composited die Layer und
        speichert das Ergebnis als PNG.
        """
        self._ensure_components_loaded()

        layers = EMOTION_MAP.get(emotion, EMOTION_MAP[Emotion.NEUTRAL])

        # Offscreen-Surface erstellen
        surface = pygame.Surface((self._width, self._height))
        surface.fill(BG_COLOR)

        # Layers compositen (Body → Eyes → Mouth)
        self._blit_to(surface, layers.body)
        self._blit_to(surface, layers.eye_left)
        self._blit_to(surface, layers.eye_right)
        self._blit_to(surface, layers.mouth)

        pygame.image.save(surface, str(output_path))
        logger.debug("Avatar gerendert: %s (emotion=%s)", output_path, emotion.value)
        return output_path

    def _ensure_components_loaded(self) -> None:
        """Stellt sicher dass Komponenten geladen sind (headless-kompatibel)."""
        if self._components:
            return

        if not pygame.get_init():
            pygame.init()

        # Komponenten laden ohne convert_alpha (braucht kein Display)
        subdirs = ("body", "eye", "mouth")
        total = 0
        for subdir_name in subdirs:
            subdir = self._assets_dir / subdir_name
            if not subdir.exists():
                continue
            for png_path in sorted(subdir.glob("*.png")):
                key = png_path.stem
                self._components[key] = pygame.image.load(str(png_path))
                total += 1

        self._scale_components()
        logger.info("%d Komponenten geladen (headless)", total)

    def _blit_to(self, target: "pygame.Surface", component_key: str) -> None:
        """Zeichnet eine Komponente zentriert auf eine beliebige Surface."""
        surface = self._components.get(component_key)
        if surface is None:
            return
        sw, sh = surface.get_size()
        x = (self._width - sw) // 2
        y = (self._height - sh) // 2
        target.blit(surface, (x, y))

    def shutdown(self) -> None:
        self._running = False
        if pygame.get_init():
            pygame.quit()
        logger.info("LayeredSpriteRenderer beendet")

    def is_running(self) -> bool:
        return self._running
