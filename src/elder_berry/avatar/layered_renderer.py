"""Avatar-Renderer – Layered Component System mit Blink, Lip-Sync und Breathing."""
import logging
import math
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

# Lip-Sync: gewichtete Mund-Zustände (Mouth-Key → Gewicht)
LIP_SYNC_WEIGHTS: dict[str, float] = {
    "mouth_neutral_close": 0.15,
    "mouth_tiny": 0.15,
    "mouth_halfopen": 0.30,
    "mouth_open": 0.25,
    "mouth_wide": 0.15,
}
LIP_SYNC_INTERVAL = 0.18   # Sekunden zwischen Mundwechsel (Basis)
LIP_SYNC_JITTER = 0.03     # ±Jitter auf das Intervall

# Breathing-Animation
BREATH_SPEED = 1.2       # Frequenz (Zyklen/Sekunde)
BREATH_AMPLITUDE = 2.0   # Pixel Auslenkung (±)

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
    effect: str | None = None


# Mapping: Emotion → Komponenten-Dateinamen (ohne Ordner-Prefix)
EMOTION_MAP: dict[Emotion, EmotionLayers] = {
    Emotion.NEUTRAL: EmotionLayers(
        body="relaxed", eye_left="eye_left_open", eye_right="eye_right_open",
        mouth="mouth_neutral_close", can_blink=True,
    ),
    Emotion.CHEERFUL: EmotionLayers(
        body="welcome", eye_left="eye_left_cheerful_open", eye_right="eye_right_cheerful_open",
        mouth="mouth_friendly_open", can_blink=True,
    ),
    Emotion.ANGRY: EmotionLayers(
        body="angry", eye_left="eye_left_angry_open", eye_right="eye_right_angry_open",
        mouth="mouth_angry_open", can_blink=False,
    ),
    Emotion.SARCASTIC: EmotionLayers(
        body="idle", eye_left="eye_left_side_open", eye_right="eye_right_side_open",
        mouth="mouth_smirk_open", can_blink=False,
    ),
    Emotion.MOTIVATED: EmotionLayers(
        body="confident", eye_left="eye_left_confident_open", eye_right="eye_right_confident_open",
        mouth="mouth_grin", can_blink=True,
    ),
    Emotion.THOUGHTFUL: EmotionLayers(
        body="thinking", eye_left="eye_left_side_open", eye_right="eye_right_side_open",
        mouth="mouth_think_close", can_blink=False,
    ),
    Emotion.WHISPER: EmotionLayers(
        body="relaxed", eye_left="eye_left_tired_open", eye_right="eye_right_tired_open",
        mouth="mouth_halfopen", can_blink=True,
    ),
    Emotion.SHY: EmotionLayers(
        body="shy", eye_left="eye_left_shy_open", eye_right="eye_right_shy_open",
        mouth="mouth_shy_close", can_blink=False,
    ),
    Emotion.DEPRESSED: EmotionLayers(
        body="tired", eye_left="eye_left_tired_open", eye_right="eye_right_tired_open",
        mouth="mouth_pout", can_blink=False,
    ),
    Emotion.SAD: EmotionLayers(
        body="shy", eye_left="eye_left_sad_open", eye_right="eye_right_sad_open",
        mouth="mouth_pout", can_blink=False,
    ),
}

# Lip-Sync: vorberechnete Listen für random.choices()
_LIP_SYNC_KEYS = list(LIP_SYNC_WEIGHTS.keys())
_LIP_SYNC_PROBS = list(LIP_SYNC_WEIGHTS.values())


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

        # YAML-Config laden (Fallback auf hardcoded Defaults)
        self._load_yaml_config()

        # Blink-State
        self._blink_active = False
        self._next_blink_time = 0.0
        self._blink_end_time = 0.0

        # Lip-Sync-State (gewichtete Zufallsauswahl)
        self._lip_sync_mouth: str = self._lip_sync_keys[0]
        self._last_lip_switch = 0.0
        self._next_lip_interval = self._lip_sync_interval

        # Idle-Animation-State
        self._idle_active = False
        self._idle_action: str | None = None
        self._idle_eye_left: str | None = None
        self._idle_eye_right: str | None = None
        self._idle_mouth: str | None = None
        self._next_idle_time = 0.0
        self._idle_end_time = 0.0

    def _load_yaml_config(self) -> None:
        """Lädt die Avatar-Config aus YAML, Fallback auf hardcoded Defaults."""
        from elder_berry.avatar.avatar_config_loader import load_avatar_config

        config = load_avatar_config(self._assets_dir / "avatar_config.yaml")
        if config and config.emotions:
            self._emotion_map = config.emotions
            self._lip_sync_keys = list(config.lip_sync_weights.keys()) or _LIP_SYNC_KEYS
            self._lip_sync_probs = list(config.lip_sync_weights.values()) or _LIP_SYNC_PROBS
            self._lip_sync_interval = config.lip_sync_interval
            self._lip_sync_jitter = config.lip_sync_jitter
            self._breathing_enabled = config.breathing_enabled
            self._breathing_speed = config.breathing_speed
            self._breathing_amplitude = config.breathing_amplitude
            self._idle_actions_config = [
                (a.name, a.eye_left, a.eye_right, a.mouth)
                for a in config.idle_actions
            ]
            logger.info("Avatar-Config aus YAML geladen (%d Emotionen)",
                        len(self._emotion_map))
        else:
            self._emotion_map = EMOTION_MAP
            self._lip_sync_keys = _LIP_SYNC_KEYS
            self._lip_sync_probs = _LIP_SYNC_PROBS
            self._lip_sync_interval = LIP_SYNC_INTERVAL
            self._lip_sync_jitter = LIP_SYNC_JITTER
            self._breathing_enabled = True
            self._breathing_speed = BREATH_SPEED
            self._breathing_amplitude = BREATH_AMPLITUDE
            self._idle_actions_config = self._IDLE_ACTIONS
            logger.info("Avatar-Config: hardcoded Defaults (YAML nicht verfügbar)")

    def _load_components(self) -> None:
        """Lädt alle Komponenten-PNGs aus den Unterordnern."""
        subdirs = {"body": "body", "eye": "eye", "mouth": "mouth", "effect": "effect"}
        total = 0

        for subdir_name, _subdir_key in subdirs.items():
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
        self._schedule_next_idle()

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
            self._lip_sync_mouth = self._lip_sync_keys[0]
            self._last_lip_switch = time.monotonic()
            self._next_lip_interval = self._lip_sync_interval

    def update(self) -> None:
        if not self._running or self._screen is None:
            return

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return

        now = time.monotonic()
        layers = self._emotion_map.get(self._current_emotion)
        if layers is None:
            layers = self._emotion_map[Emotion.NEUTRAL]

        # Idle-Animation updaten (nur wenn nicht sprechend)
        if not self._is_speaking:
            self._update_idle(now)

        self._screen.fill(BG_COLOR)

        # Breathing-Offset (subtile Y-Verschiebung, nur wenn nicht sprechend)
        breath_y = 0
        if not self._is_speaking and self._breathing_enabled:
            breath_y = int(math.sin(now * self._breathing_speed) * self._breathing_amplitude)

        # Layer 1: Body
        self._blit_centered(layers.body, y_offset=breath_y)

        # Layer 2: Augen (mit Blink → Idle → Emotion Priorität)
        eye_left = layers.eye_left
        eye_right = layers.eye_right

        # Idle-Override (wenn aktiv und nicht blinkend)
        if self._idle_active and self._idle_eye_left:
            eye_left = self._idle_eye_left
            eye_right = self._idle_eye_right

        if layers.can_blink:
            self._update_blink(now)
            if self._blink_active:
                eye_left = "eye_left_close"
                eye_right = "eye_right_close"

        self._blit_centered(eye_left, y_offset=breath_y)
        self._blit_centered(eye_right, y_offset=breath_y)

        # Layer 3: Mund (Lip-Sync → Idle → Emotion Priorität)
        if self._is_speaking:
            mouth_key = self._get_lip_sync_mouth(now)
        elif self._idle_active and self._idle_mouth:
            mouth_key = self._idle_mouth
        else:
            mouth_key = layers.mouth

        self._blit_centered(mouth_key, y_offset=breath_y)

        # Layer 4: Effekt (optional)
        if layers.effect:
            self._blit_centered(layers.effect, y_offset=breath_y)

        pygame.display.flip()
        self._clock.tick(FPS)

    def _blit_centered(self, component_key: str, y_offset: int = 0) -> None:
        """Zeichnet eine Komponente zentriert auf den Screen."""
        surface = self._components.get(component_key)
        if surface is None:
            return

        sw, sh = surface.get_size()
        x = (self._width - sw) // 2
        y = (self._height - sh) // 2 + y_offset
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
        """Gibt den aktuellen Lip-Sync-Mund zurück (gewichtete Zufallsauswahl)."""
        if now - self._last_lip_switch >= self._next_lip_interval:
            self._lip_sync_mouth = random.choices(
                self._lip_sync_keys, weights=self._lip_sync_probs, k=1,
            )[0]
            self._last_lip_switch = now
            # Jitter: nächstes Intervall leicht variieren
            self._next_lip_interval = self._lip_sync_interval + random.uniform(
                -self._lip_sync_jitter, self._lip_sync_jitter,
            )
        return self._lip_sync_mouth

    # -- Idle-Animationen ------------------------------------------------------

    # Verfügbare Idle-Aktionen: (eye_left, eye_right, mouth)
    # None = behalte Emotion-Default
    _IDLE_ACTIONS = [
        # Zur Seite schauen
        ("glance_left", "eye_left_side_open", "eye_right_side_open", None),
        ("glance_right", "eye_left_side_open", "eye_right_side_open", None),
        # Kurz lächeln
        ("smile", None, None, "mouth_halfopen"),
        # Kurz Augen schließen (nachdenklich)
        ("soft_close", "eye_left_close", "eye_right_close", None),
        # Kurz überrascht schauen
        ("surprise", "eye_left_surprise_open", "eye_right_surprise_open", "mouth_open"),
    ]

    def _schedule_next_idle(self) -> None:
        """Plant die nächste Idle-Aktion."""
        delay = random.uniform(IDLE_MIN_INTERVAL, IDLE_MAX_INTERVAL)
        self._next_idle_time = time.monotonic() + delay

    def _update_idle(self, now: float) -> None:
        """Aktualisiert den Idle-Animations-Zustand."""
        if self._idle_active:
            if now >= self._idle_end_time:
                self._idle_active = False
                self._idle_eye_left = None
                self._idle_eye_right = None
                self._idle_mouth = None
                self._schedule_next_idle()
        elif now >= self._next_idle_time:
            self._start_idle_action()

    def _start_idle_action(self) -> None:
        """Startet eine zufällige Idle-Aktion."""
        action_name, eye_l, eye_r, mouth = random.choice(self._idle_actions_config)

        # Prüfe ob die benötigten Komponenten existieren
        if eye_l and eye_l not in self._components:
            self._schedule_next_idle()
            return
        if mouth and mouth not in self._components:
            self._schedule_next_idle()
            return

        self._idle_active = True
        self._idle_action = action_name
        self._idle_eye_left = eye_l
        self._idle_eye_right = eye_r
        self._idle_mouth = mouth
        self._idle_end_time = time.monotonic() + IDLE_ACTION_DURATION

    def render_to_file(
        self, output_path: Path, emotion: Emotion = Emotion.NEUTRAL,
    ) -> Path:
        """Rendert Avatar mit gegebener Emotion als PNG (headless, kein Fenster).

        Lädt Komponenten bei Bedarf ohne Display-Fenster.
        Erstellt einen offscreen-Surface, composited die Layer und
        speichert das Ergebnis als PNG.
        """
        self._ensure_components_loaded()

        layers = self._emotion_map.get(emotion, self._emotion_map[Emotion.NEUTRAL])

        # Offscreen-Surface erstellen
        surface = pygame.Surface((self._width, self._height))
        surface.fill(BG_COLOR)

        # Layers compositen (Body → Eyes → Mouth → Effect)
        self._blit_to(surface, layers.body)
        self._blit_to(surface, layers.eye_left)
        self._blit_to(surface, layers.eye_right)
        self._blit_to(surface, layers.mouth)
        if layers.effect:
            self._blit_to(surface, layers.effect)

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
        subdirs = ("body", "eye", "mouth", "effect")
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

    def reload_config(self) -> bool:
        """Lädt die YAML-Config neu (Hot-Reload).

        Returns:
            True wenn die Config erfolgreich geladen wurde, False bei Fehler.
        """
        try:
            self._load_yaml_config()
            logger.info("Avatar-Config hot-reloaded")
            return True
        except Exception:
            logger.exception("Fehler beim Hot-Reload der Avatar-Config")
            return False

    def shutdown(self) -> None:
        self._running = False
        if pygame.get_init():
            pygame.quit()
        logger.info("LayeredSpriteRenderer beendet")

    def is_running(self) -> bool:
        return self._running
