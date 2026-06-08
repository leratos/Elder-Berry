"""Avatar-Renderer – Layered Component System mit Blink, Lip-Sync und Breathing."""

import logging
import math
import random
import time
from collections.abc import Collection
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

try:
    import pygame
except ImportError:
    pygame = None  # type: ignore[assignment]

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.idle_policy import IdleBlinkOverrides
from elder_berry.avatar.render_plan import (
    OPAQUE_ALPHA,
    RenderPlan,
    TransitionState,
)
from elder_berry.character.base import Emotion

logger = logging.getLogger(__name__)


class CrossfadeScope(Enum):
    """Welche Layer beim Emotion-Crossfade geblendet werden (Performance-Weiche).

    ``FULL`` blendet alle Layer (Default). ``MOUTH_ONLY`` ist der §5/§6.1-
    Fallback, falls der volle Crossfade auf dem RPi5 unter 30 FPS drückt: nur der
    Mund crossfadet, Body/Augen/Effekt schneiden hart auf die neue Emotion.
    """

    FULL = "full"
    MOUTH_ONLY = "mouth_only"


@dataclass(frozen=True)
class _FrameOverrides:
    """Die einmal pro Frame aufgelösten dynamischen Overrides (Idle/Blink/Lip-Sync).

    Wird im Crossfade (83.3) deckungsgleich auf den alten **und** den neuen
    Basis-Plan gelegt, damit beide Gesichter registriert bleiben.
    """

    blink_eyes: tuple[str, str] | None
    idle_eyes: tuple[str, str] | None
    speaking_mouth: str | None
    idle_mouth: str | None
    breath_y: int

DEFAULT_ASSETS_DIR = Path(__file__).parent / "assets"
WINDOW_TITLE = "Elder-Berry – Saleria Berry"
BG_COLOR = (0, 0, 0)  # Schwarz für Pepper's Ghost
FPS = 30

# Lip-Sync: gewichtete Mund-Zustände (Mouth-Key → Gewicht)
LIP_SYNC_WEIGHTS: dict[str, float] = {
    "mouth_neutral_close": 0.15,
    "mouth_tiny": 0.15,
    "mouth_halfopen": 0.30,
    "mouth_open": 0.25,
    "mouth_wide": 0.15,
}
LIP_SYNC_INTERVAL = 0.18  # Sekunden zwischen Mundwechsel (Basis)
LIP_SYNC_JITTER = 0.03  # ±Jitter auf das Intervall

# Breathing-Animation
BREATH_SPEED = 1.2  # Frequenz (Zyklen/Sekunde)
BREATH_AMPLITUDE = 2.0  # Pixel Auslenkung (±)

# Display-Rotation: erlaubte Werte (0 oder 180).
# Hintergrund: RPi5 ignoriert die Legacy-Firmware-Rotation
# (display_lcd_rotate=) im KMS-Modus. Rotation muss daher als
# Render-Operation geschehen. 180° nutzt pygame.transform.flip
# (kein Resampling, keine Dimensions-Änderung). 90/270 würden
# Buffer-Refactor + Width/Height-Tausch erfordern -- nicht
# implementiert.
ALLOWED_ROTATIONS = (0, 180)


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
        body="relaxed",
        eye_left="eye_left_open",
        eye_right="eye_right_open",
        mouth="mouth_neutral_close",
        can_blink=True,
    ),
    Emotion.CHEERFUL: EmotionLayers(
        body="welcome",
        eye_left="eye_left_cheerful_open",
        eye_right="eye_right_cheerful_open",
        mouth="mouth_friendly_open",
        can_blink=True,
    ),
    Emotion.ANGRY: EmotionLayers(
        body="angry",
        eye_left="eye_left_angry_open",
        eye_right="eye_right_angry_open",
        mouth="mouth_angry_open",
        can_blink=False,
    ),
    Emotion.SARCASTIC: EmotionLayers(
        body="idle",
        eye_left="eye_left_side_open",
        eye_right="eye_right_side_open",
        mouth="mouth_smirk_open",
        can_blink=False,
    ),
    Emotion.MOTIVATED: EmotionLayers(
        body="confident",
        eye_left="eye_left_confident_open",
        eye_right="eye_right_confident_open",
        mouth="mouth_grin",
        can_blink=True,
    ),
    Emotion.THOUGHTFUL: EmotionLayers(
        body="thinking",
        eye_left="eye_left_side_open",
        eye_right="eye_right_side_open",
        mouth="mouth_think_close",
        can_blink=False,
    ),
    Emotion.WHISPER: EmotionLayers(
        body="relaxed",
        eye_left="eye_left_tired_open",
        eye_right="eye_right_tired_open",
        mouth="mouth_halfopen",
        can_blink=True,
    ),
    Emotion.SHY: EmotionLayers(
        body="shy",
        eye_left="eye_left_shy_open",
        eye_right="eye_right_shy_open",
        mouth="mouth_shy_close",
        can_blink=False,
    ),
    Emotion.DEPRESSED: EmotionLayers(
        body="tired",
        eye_left="eye_left_tired_open",
        eye_right="eye_right_tired_open",
        mouth="mouth_pout",
        can_blink=False,
    ),
    Emotion.SAD: EmotionLayers(
        body="shy",
        eye_left="eye_left_sad_open",
        eye_right="eye_right_sad_open",
        mouth="mouth_pout",
        can_blink=False,
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

    def __init__(
        self,
        assets_dir: Path | None = None,
        crossfade_scope: CrossfadeScope = CrossfadeScope.FULL,
    ) -> None:
        if pygame is None:
            raise ImportError(
                "pygame nicht installiert. Installiere mit: pip install pygame"
            )

        self._assets_dir = assets_dir or DEFAULT_ASSETS_DIR
        # Crossfade-Reichweite (FULL = alle Layer; MOUTH_ONLY = §5/§6.1-Fallback).
        self._crossfade_scope = crossfade_scope
        # Wiederverwendeter opaker Scratch-Buffer für den Cross-Dissolve (statt
        # pro Frame/Ebene zu allokieren – §6.1-Performance auf dem RPi5).
        self._scratch: pygame.Surface | None = None
        self._components: dict[str, pygame.Surface] = {}
        self._screen: pygame.Surface | None = None
        self._clock: pygame.time.Clock | None = None
        self._current_emotion = Emotion.NEUTRAL
        self._is_speaking = False
        self._running = False
        self._width = 512
        self._height = 1024
        # Display-Rotation in Grad (0 oder 180). Wird in initialize() gesetzt.
        self._rotation = 0

        # YAML-Config laden (Fallback auf hardcoded Defaults)
        self._load_yaml_config()

        # Lip-Sync-State (gewichtete Zufallsauswahl) – bleibt im Renderer (83.6
        # zieht nur Idle/Blink in die IdleBehaviorPolicy; Random-Lip-Sync nicht).
        self._lip_sync_mouth: str = self._lip_sync_keys[0]
        self._last_lip_switch = 0.0
        self._next_lip_interval = self._lip_sync_interval

    def _load_yaml_config(self) -> None:
        """Lädt die Avatar-Config aus YAML, Fallback auf hardcoded Defaults.

        Pfad-Aufloesung in dieser Reihenfolge:
        1. ``assets_dir/avatar_config.yaml`` -- **nur** wenn der Pfad
           nicht auf das getrackte Default-File zeigt. Damit gewinnt
           eine Custom-Asset-Pack-Config (passt zu den Pack-Assets);
           USER-Overrides aus der Default-Pack-Welt werden bewusst
           ignoriert, sonst landen Emotion-/Lip-Sync-Keys aus einem
           anderen Mapping bei diesen Component-PNGs.
        2. Sonst die ``USER → DEFAULT``-Chain via ``load_avatar_config()``
           ohne expliziten Pfad. So sehen wir Editor-Aenderungen am
           Default-Pack ohne den getrackten Pfad anzufassen.
        """
        from elder_berry.avatar.avatar_config_loader import (
            DEFAULT_CONFIG_PATH,
            load_avatar_config,
        )

        local_config = self._assets_dir / "avatar_config.yaml"
        if (
            local_config.exists()
            and local_config.resolve() != DEFAULT_CONFIG_PATH.resolve()
        ):
            # Custom asset pack: pack-eigene Config ist authoritativ.
            config = load_avatar_config(local_config)
        else:
            # Default-Pack: USER-Override → DEFAULT-Chain.
            config = load_avatar_config()
        if config and config.emotions:
            self._emotion_map = config.emotions
            self._lip_sync_keys = list(config.lip_sync_weights.keys()) or _LIP_SYNC_KEYS
            self._lip_sync_probs = (
                list(config.lip_sync_weights.values()) or _LIP_SYNC_PROBS
            )
            self._lip_sync_interval = config.lip_sync_interval
            self._lip_sync_jitter = config.lip_sync_jitter
            self._breathing_enabled = config.breathing_enabled
            self._breathing_speed = config.breathing_speed
            self._breathing_amplitude = config.breathing_amplitude
            self._idle_actions_config = [
                (a.name, a.eye_left, a.eye_right, a.mouth) for a in config.idle_actions
            ]
            logger.info(
                "Avatar-Config aus YAML geladen (%d Emotionen)", len(self._emotion_map)
            )
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
        rotation: int = 0,
    ) -> None:
        if rotation not in ALLOWED_ROTATIONS:
            raise ValueError(
                f"rotation muss 0 oder 180 sein (war: {rotation}). "
                "90/270 sind nicht implementiert."
            )

        self._width = width
        self._height = height
        self._rotation = rotation

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

        logger.info(
            "LayeredSpriteRenderer initialisiert: %dx%d%s rotation=%d\u00b0, %d Komponenten",
            width,
            height,
            " (fullscreen)" if fullscreen else "",
            rotation,
            len(self._components),
        )

    def show_emotion(self, emotion: Emotion) -> None:
        if emotion != self._current_emotion:
            logger.debug(
                "Emotion: %s → %s",
                self._current_emotion.value,
                emotion.value,
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

    @property
    def emotion_map(self) -> dict[Emotion, EmotionLayers]:
        """Read-only Zugriff auf die aktive Emotion→Layer-Zuordnung.

        Quelle ist YAML (``avatar_config_loader``) oder der Hardcode-Fallback.
        Wird in 83.2 von der :class:`AvatarStateMachine` geteilt, damit deren
        ``current_layers`` dieselben Keys auflöst wie der Renderer.
        """
        return self._emotion_map

    @property
    def component_keys(self) -> Collection[str]:
        """Geladene Komponenten-Keys – Quelle für den Lip-Sync-Guard (§0.6).

        Der :class:`AvatarController` reicht diese an den
        ``AmplitudeLipSyncDriver`` weiter, damit ein nicht vorhandener Mund-Key
        (z.B. fehlendes ``mouth_wide``) auf einen Fallback statt auf einen
        leeren Blit fällt.
        """
        return self._components.keys()

    @property
    def idle_actions(self) -> list[tuple[str, str | None, str | None, str | None]]:
        """Geladene Idle-Action-Specs ``(name, eye_left, eye_right, mouth)``.

        Quelle für die :class:`~elder_berry.avatar.idle_policy.IdleBehaviorPolicy`
        (83.6). Stammt aus **derselben** geladenen Config wie :attr:`emotion_map`
        (YAML oder Hardcode-Fallback) – kein zweiter Lade-Pfad, damit Policy und
        Renderer nicht auseinanderlaufen (§2.3 #2).
        """
        return self._idle_actions_config

    def update(
        self,
        transition: TransitionState | None = None,
        speaking_mouth: str | None = None,
        idle_blink: IdleBlinkOverrides | None = None,
    ) -> None:
        """Rendert ein Frame: Event-Pump → (Crossfade oder Einzel-Plan).

        Args:
            transition: Optionale Blend-Info der StateMachine (83.3). Ist sie
                ``None`` oder ``not in_transition``, läuft der **byte-identische**
                Bestandspfad (``_build_plan`` + opakes :meth:`render`). Läuft ein
                Crossfade, werden die Overrides einmal aufgelöst und auf den alten
                **und** neuen Basis-Plan gelegt; :meth:`_render_crossfade`
                blendet beide.
            speaking_mouth: Optionaler Mund-Key vom ``LipSyncDriver`` (83.4,
                Amplitude). Ist er gesetzt **und** der Avatar spricht, gewinnt er
                über die renderer-interne Zufallsauswahl. ``None`` → byte-
                identischer Bestandspfad (Inline-Random-Lip-Sync bleibt im Renderer).
            idle_blink: Pro Frame von der ``IdleBehaviorPolicy`` aufgelöste Idle-/
                Blink-Overrides (83.6). ``None`` → keine Idle/Blink-Overrides (der
                Renderer treibt Idle/Blink nicht mehr selbst). Im Produktionspfad
                reicht der Render-Loop ``controller.current_idle_blink(now)`` durch.
        """
        if not self._running or self._screen is None:
            return

        if not self._pump_events():
            return

        now = time.monotonic()
        if transition is not None and transition.in_transition:
            old_plan, new_plan = self._build_transition_plans(
                now, transition, speaking_mouth, idle_blink
            )
            self._render_crossfade(old_plan, new_plan)
        else:
            plan = self._build_plan(now, speaking_mouth, idle_blink)
            self.render(plan)

    def _pump_events(self) -> bool:
        """Verarbeitet die PyGame-Event-Queue.

        Returns:
            ``False``, wenn ein ``QUIT``-Event den Renderer gestoppt hat
            (Caller bricht den Frame ab), sonst ``True``.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return False
        return True

    def _resolve_overrides(
        self,
        now: float,
        speaking_mouth: str | None = None,
        idle_blink: IdleBlinkOverrides | None = None,
    ) -> _FrameOverrides:
        """Löst die dynamischen Overrides genau einmal pro Frame auf.

        Idle und Blink kommen ab 83.6 fertig aufgelöst von der
        ``IdleBehaviorPolicy`` (über ``idle_blink`` – inkl. ``can_blink``-Gate und
        Idle-Unterdrückung beim Sprechen). Der Renderer wendet sie nur noch an.
        Breathing-Offset und der Inline-Random-Lip-Sync (Fallback, §4.4) bleiben
        renderer-intern.

        ``speaking_mouth`` ist der optionale Mund-Key vom ``LipSyncDriver``
        (83.4, Amplitude). Ist er gesetzt **und** der Avatar spricht, gewinnt er
        über die renderer-interne Zufallsauswahl (``_get_lip_sync_mouth`` wird
        dann **nicht** ausgewertet). ``idle_blink`` ``None`` → keine Idle/Blink-
        Overrides (Standalone/Tests).
        """
        ov = idle_blink if idle_blink is not None else IdleBlinkOverrides()

        # Breathing-Offset (subtile Y-Verschiebung, nur wenn nicht sprechend)
        breath_y = 0
        if not self._is_speaking and self._breathing_enabled:
            breath_y = int(
                math.sin(now * self._breathing_speed) * self._breathing_amplitude
            )

        # Mund: Lip-Sync (sprechend) schlägt Idle schlägt Emotion-Default.
        # Liefert der LipSyncDriver (83.4) einen Mund-Key, gewinnt er; sonst die
        # renderer-interne Zufallsauswahl (Fallback, §4.4).
        if self._is_speaking:
            mouth_override = (
                speaking_mouth
                if speaking_mouth is not None
                else self._get_lip_sync_mouth(now)
            )
        else:
            mouth_override = None

        return _FrameOverrides(
            blink_eyes=ov.blink_eyes,
            idle_eyes=ov.idle_eyes,
            speaking_mouth=mouth_override,
            idle_mouth=ov.idle_mouth,
            breath_y=breath_y,
        )

    def _build_plan(
        self,
        now: float,
        speaking_mouth: str | None = None,
        idle_blink: IdleBlinkOverrides | None = None,
    ) -> RenderPlan:
        """Löst Emotion + dynamische Overrides zu einem :class:`RenderPlan` auf.

        Nicht-Transition-Pfad. Prioritäten via :meth:`RenderPlan.compose`: Augen
        blink>idle>Emotion, Mund speaking>idle>Emotion. Idle/Blink stammen aus
        ``idle_blink`` (IdleBehaviorPolicy, 83.6).
        """
        layers = self._emotion_map.get(self._current_emotion)
        if layers is None:
            layers = self._emotion_map[Emotion.NEUTRAL]

        ov = self._resolve_overrides(now, speaking_mouth, idle_blink)
        return RenderPlan.compose(
            layers,
            blink_eyes=ov.blink_eyes,
            idle_eyes=ov.idle_eyes,
            speaking_mouth=ov.speaking_mouth,
            idle_mouth=ov.idle_mouth,
            y_offset=ov.breath_y,
        )

    def render(self, plan: RenderPlan) -> None:
        """Zeichnet genau einen :class:`RenderPlan` (fill → Layer → Flip).

        Reiner Blitter ohne Verhaltens-Logik. Ist ``plan.alpha >= 255`` (opak),
        läuft der **byte-identische** Bestandspfad (direkte zentrierte Blits).
        Bei ``plan.alpha < 255`` wird der Plan offscreen komponiert und als
        Einheit verblasst (Fade-from-Black) – die Basis des Crossfades (§5).
        """
        if self._screen is None:
            return

        self._screen.fill(BG_COLOR)

        if plan.alpha >= OPAQUE_ALPHA:
            # Opaker Bestandspfad (byte-identisch zu 83.2).
            self._blit_centered(plan.body, y_offset=plan.y_offset)
            self._blit_centered(plan.eye_left, y_offset=plan.y_offset)
            self._blit_centered(plan.eye_right, y_offset=plan.y_offset)
            self._blit_centered(plan.mouth, y_offset=plan.y_offset)
            if plan.effect:
                self._blit_centered(plan.effect, y_offset=plan.y_offset)
        else:
            surface = self._compose_plan_to_surface(plan)
            self._fade_surface(surface, plan.alpha)
            self._screen.blit(surface, (0, 0))

        self._finish_frame()

    def _finish_frame(self) -> None:
        """Display-Rotation (180°) + Present – Abschluss jedes Frames."""
        self._apply_rotation()
        self._present()

    def _apply_rotation(self) -> None:
        """Spiegelt den Screen-Inhalt um 180°, falls ``rotation == 180``.

        RPi5 ignoriert ``display_lcd_rotate=`` im KMS-Modus; die Drehung läuft als
        Vollbild-``flip(True, True)`` (kein Resampling) **vor** dem ``display.flip``.
        Teil der pro-Frame-Render-Kosten – die FPS-Messung (§0.6) schließt ihn ein.
        """
        if self._rotation == 180:
            rotated = pygame.transform.flip(self._screen, True, True)
            self._screen.blit(rotated, (0, 0))

    def _present(self) -> None:
        """Stellt den Frame dar (``display.flip``) und drosselt auf ``FPS``.

        ``clock.tick`` ist die vsync-/throttle-Stelle und wird in der FPS-Messung
        bewusst **ausgeschlossen** (sie verfälscht die reine Kompositionszeit).
        """
        pygame.display.flip()
        if self._clock is not None:
            self._clock.tick(FPS)

    # -- Crossfade (Phase 83.3) -----------------------------------------------

    def _build_transition_plans(
        self,
        now: float,
        transition: TransitionState,
        speaking_mouth: str | None = None,
        idle_blink: IdleBlinkOverrides | None = None,
    ) -> tuple[RenderPlan, RenderPlan]:
        """Legt die Frame-Overrides deckungsgleich auf alten + neuen Basis-Plan.

        Die Overrides (Idle/Blink/Lip-Sync/Breathing) werden **einmal** aufgelöst
        und auf beide Basen gelegt – gleiches ``y_offset``, gleicher Blink/Idle/
        Lip-Sync-Key –, damit beide Gesichter registriert bleiben. Idle/Blink
        kommen aus ``idle_blink`` (IdleBehaviorPolicy, 83.6); ``speaking_mouth``
        (83.4) wird – wie alle Overrides – deckungsgleich auf beide Basen gelegt.
        Die Crossfade-Reichweite (FULL vs. MOUTH_ONLY) entscheidet erst die
        Komposition (:meth:`_composite_crossfade_to_screen`), nicht das
        Plan-Bauen.
        """
        ov = self._resolve_overrides(now, speaking_mouth, idle_blink)

        old_plan = self._apply_overrides(transition.previous, ov, OPAQUE_ALPHA)
        new_plan = self._apply_overrides(
            transition.current, ov, transition.current.alpha
        )
        return old_plan, new_plan

    @staticmethod
    def _apply_overrides(
        base: RenderPlan, ov: _FrameOverrides, alpha: int
    ) -> RenderPlan:
        """``compose`` der Overrides auf einen Basis-Plan (LayerSource) mit Alpha."""
        return RenderPlan.compose(
            base,
            blink_eyes=ov.blink_eyes,
            idle_eyes=ov.idle_eyes,
            speaking_mouth=ov.speaking_mouth,
            idle_mouth=ov.idle_mouth,
            alpha=alpha,
            y_offset=ov.breath_y,
        )

    def _blit_plan_to(self, target: "pygame.Surface", plan: RenderPlan) -> None:
        """Blittet alle Layer eines Plans (Body→Augen→Mund→Effekt) auf ``target``.

        Auf einem **opaken** Ziel klopft das die per-Pixel-Alpha-Layer über den
        Hintergrund flach; auf einem SRCALPHA-Ziel bleibt die Transparenz erhalten.
        """
        self._blit_to(target, plan.body, y_offset=plan.y_offset)
        self._blit_to(target, plan.eye_left, y_offset=plan.y_offset)
        self._blit_to(target, plan.eye_right, y_offset=plan.y_offset)
        self._blit_to(target, plan.mouth, y_offset=plan.y_offset)
        if plan.effect:
            self._blit_to(target, plan.effect, y_offset=plan.y_offset)

    def _compose_plan_to_surface(self, plan: RenderPlan) -> "pygame.Surface":
        """Komponiert einen Plan auf einen transparenten Offscreen-Buffer (§5)."""
        surface = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
        self._blit_plan_to(surface, plan)
        return surface

    def _scratch_surface(self) -> "pygame.Surface":
        """Liefert den wiederverwendeten opaken Scratch-Buffer (lazy, größentreu).

        Allokiert nur beim ersten Aufruf bzw. bei geänderter Auflösung neu –
        spart auf dem RPi5 die teure Vollbild-Allokation pro Frame.
        """
        size = (self._width, self._height)
        if self._scratch is None or self._scratch.get_size() != size:
            self._scratch = pygame.Surface(size)
        return self._scratch

    def _blit_faded_component(
        self, component_key: str, alpha: int, y_offset: int
    ) -> None:
        """Blittet **eine** Komponente zentriert mit reduzierter Deckkraft.

        Fadet eine **Kopie** des (kleinen) Komponenten-Sprites statt eines
        Vollbild-Offscreens – deutlich billiger für den MOUTH_ONLY-Mund.
        """
        surface = self._components.get(component_key)
        if surface is None:
            return
        sw, sh = surface.get_size()  # Kopie hat dieselbe Größe wie das Original
        faded = surface.copy()
        self._fade_surface(faded, alpha)
        x = (self._width - sw) // 2
        y = (self._height - sh) // 2 + y_offset
        self._screen.blit(faded, (x, y))

    @staticmethod
    def _fade_surface(surface: "pygame.Surface", alpha: int) -> None:
        """Skaliert die per-Pixel-Deckkraft einer Surface auf ``alpha/255`` (§5).

        ``BLEND_RGBA_MULT`` multipliziert jeden Kanal mit ``color/255``: RGB
        bleiben (×255/255), der Alpha-Kanal wird auf ``alpha/255`` skaliert →
        formtreues Verblassen einer per-Pixel-Alpha-Komposition.
        """
        surface.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)

    @staticmethod
    def _mouth_only_layers(
        old_plan: RenderPlan, new_plan: RenderPlan
    ) -> tuple[RenderPlan, str]:
        """Zerlegt einen Crossfade in den MOUTH_ONLY-Fallback.

        Returns:
            ``(static_plan, fade_mouth_key)`` – ``static_plan`` trägt die **neue**
            Basis (Body/Augen/Effekt, hart geschnitten) plus den **alten** Mund
            darunter und ist opak; ``fade_mouth_key`` ist der **neue** Mund, der
            als einziger Layer einblendet. So wird Body/Augen/Effekt genau einmal
            gezeichnet (kein Doppel-Blend auf semi-transparenten Kanten).
        """
        static_plan = replace(new_plan, mouth=old_plan.mouth, alpha=OPAQUE_ALPHA)
        return static_plan, new_plan.mouth

    def _render_crossfade(self, old_plan: RenderPlan, new_plan: RenderPlan) -> None:
        """Komponiert das Crossfade-Frame und stellt es dar (§5)."""
        if self._screen is None:
            return
        self._composite_crossfade_to_screen(old_plan, new_plan)
        self._present()

    def _composite_crossfade_to_screen(
        self, old_plan: RenderPlan, new_plan: RenderPlan
    ) -> None:
        """Komponiert ein Crossfade-Frame (+ 180°-Rotation) – **ohne** Present.

        Genau diese Kosten misst der Crossfade-FPS-Stopwatch (§6.1/§0.6);
        ``display.flip``/``clock.tick`` bleiben außen vor. Die Reichweite
        (``self._crossfade_scope``) entscheidet hier – damit Renderer **und**
        Benchmark denselben Pfad für den jeweiligen Modus exerzieren.
        """
        if self._crossfade_scope is CrossfadeScope.MOUTH_ONLY:
            self._composite_mouth_only(old_plan, new_plan)
        else:
            self._composite_full(old_plan, new_plan)
        self._apply_rotation()

    def _composite_full(self, old_plan: RenderPlan, new_plan: RenderPlan) -> None:
        """Voller Crossfade als echter linearer Cross-Dissolve (§5).

        Ergebnis = ``alt*(1-t) + neu*t`` auf schwarzem BG. Beide Pläne werden
        **komplementär** gewichtet (``alt_gewicht = 255 - neu.alpha``), sodass:

        - **alt-only**-Pixel (Silhouetten-Differenz) verblassen mit ``(1-t)`` statt
          opak stehen zu bleiben und am Ende zu poppen (Codex P2 #3),
        - **geteilte** Pixel (z. B. ein Lip-Sync-Mund auf beiden Plänen) sich auf
          den vollen Wert summieren – kein Doppel-Blit-Flackern (Codex P2 #4),
        - nichts überstrahlt/clippt (Gewichte addieren sich zu 1).

        Pepper's Ghost zeigt nur helle Pixel auf Schwarz → additives Licht ist
        physikalisch korrekt. Kosten: zwei vorgewichtete Vollbild-Kompositionen
        pro Frame (in der RPi5-FPS-Messung zu prüfen; sonst MOUTH_ONLY/540x960).
        """
        self._screen.fill(BG_COLOR)
        old_weight = OPAQUE_ALPHA - new_plan.alpha
        self._add_weighted_plan(old_plan, old_weight)
        self._add_weighted_plan(new_plan, new_plan.alpha)

    def _add_weighted_plan(self, plan: RenderPlan, weight: int) -> None:
        """Addiert einen mit ``weight/255`` skalierten Plan additiv auf den Screen.

        Der Plan wird direkt auf den wiederverwendeten opaken Scratch über Schwarz
        „flachgeklopft" (per-Pixel-Alpha in die RGB einmultipliziert), per
        ``BLEND_RGB_MULT`` auf ``weight`` skaliert und per ``BLEND_RGB_ADD``
        aufaddiert – so trägt jeder Layer formtreu sein ``Licht * weight`` bei.
        ``weight <= 0`` ist ein No-op.
        """
        if weight <= 0:
            return

        scratch = self._scratch_surface()
        scratch.fill(BG_COLOR)
        self._blit_plan_to(scratch, plan)

        if weight < OPAQUE_ALPHA:
            scratch.fill(
                (weight, weight, weight), special_flags=pygame.BLEND_RGB_MULT
            )
        self._screen.blit(scratch, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _composite_mouth_only(
        self, old_plan: RenderPlan, new_plan: RenderPlan
    ) -> None:
        """MOUTH_ONLY-Fallback: Body/Augen/Effekt hart auf neu, nur Mund fadet.

        Die statische Basis (neue Emotion + **alter** Mund darunter) wird **einmal**
        opak direkt auf den Screen gezeichnet; nur der **neue** Mund blendet als
        kleines Komponenten-Sprite darüber ein (kein Vollbild-Offscreen). So gibt
        es kein Doppel-Zeichnen von Body/Augen/Effekt (Codex P2: saubere Kanten),
        und der Benchmark misst über denselben Pfad die echten Fallback-Kosten.
        """
        static_plan, fade_mouth_key = self._mouth_only_layers(old_plan, new_plan)

        self._screen.fill(BG_COLOR)
        self._blit_plan_to(self._screen, static_plan)

        if new_plan.alpha >= OPAQUE_ALPHA:
            self._blit_to(self._screen, fade_mouth_key, y_offset=new_plan.y_offset)
        else:
            self._blit_faded_component(
                fade_mouth_key, new_plan.alpha, new_plan.y_offset
            )

    def _blit_centered(self, component_key: str, y_offset: int = 0) -> None:
        """Zeichnet eine Komponente zentriert auf den Screen."""
        surface = self._components.get(component_key)
        if surface is None:
            return

        sw, sh = surface.get_size()
        x = (self._width - sw) // 2
        y = (self._height - sh) // 2 + y_offset
        self._screen.blit(surface, (x, y))

    def _get_lip_sync_mouth(self, now: float) -> str:
        """Gibt den aktuellen Lip-Sync-Mund zurück (gewichtete Zufallsauswahl)."""
        if now - self._last_lip_switch >= self._next_lip_interval:
            self._lip_sync_mouth = random.choices(
                self._lip_sync_keys,
                weights=self._lip_sync_probs,
                k=1,
            )[0]
            self._last_lip_switch = now
            # Jitter: nächstes Intervall leicht variieren
            self._next_lip_interval = self._lip_sync_interval + random.uniform(
                -self._lip_sync_jitter,
                self._lip_sync_jitter,
            )
        return self._lip_sync_mouth

    # -- Idle-Aktionen (Config-Fallback) ---------------------------------------

    # Hardcoded Idle-Aktionen-Fallback: ``(name, eye_left, eye_right, mouth)``;
    # ``None`` = behalte Emotion-Default. Wird in ``_load_yaml_config`` genutzt,
    # wenn keine YAML-Config vorliegt, und über :attr:`idle_actions` an die
    # ``IdleBehaviorPolicy`` gereicht (83.6 – die Idle-Logik selbst lebt dort).
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

    def render_to_file(
        self,
        output_path: Path,
        emotion: Emotion = Emotion.NEUTRAL,
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

    def _blit_to(
        self, target: "pygame.Surface", component_key: str, y_offset: int = 0
    ) -> None:
        """Zeichnet eine Komponente zentriert auf eine beliebige Surface.

        ``y_offset`` (Default 0) verschiebt vertikal – nötig, damit der
        Crossfade-Offscreen-Buffer denselben Breathing-Versatz trägt wie der
        opake Pfad. ``render_to_file`` ruft ohne Offset (Verhalten unverändert).
        """
        surface = self._components.get(component_key)
        if surface is None:
            return
        sw, sh = surface.get_size()
        x = (self._width - sw) // 2
        y = (self._height - sh) // 2 + y_offset
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
