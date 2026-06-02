"""RenderPlan – DTO für genau einen Avatar-Frame (Phase 83.2).

Ein ``RenderPlan`` beschreibt vollständig, welche Komponenten-PNGs ein Renderer
für ein Frame zusammensetzt: Body, Augen (links/rechts), Mund und optionaler
Effekt, plus ``y_offset`` (Breathing) und ``alpha`` (für den Crossfade in 83.3,
in 83.2 nur mitgeführt).

Die **Layer-Priorität** lebt ausschließlich in :meth:`RenderPlan.compose`, damit
es genau eine Quelle der Wahrheit gibt: sowohl der ``LayeredSpriteRenderer``
(``update`` baut intern einen Plan) als auch die ``AvatarStateMachine``
(``current_layers``) nutzen denselben Aufbau.

- **Augen:** ``blink`` > ``idle`` > Emotion-Default.
- **Mund:**  ``speaking`` (Lip-Sync) > ``idle`` > Emotion-Default.

``render_plan`` importiert bewusst **keine** konkrete ``EmotionLayers`` (es gibt
zwei strukturgleiche – im Renderer und im Config-Loader). Stattdessen genügt das
:class:`LayerSource`-Protocol; das vermeidet einen Zirkular-Import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LayerSource(Protocol):
    """Strukturelle Sicht auf eine Emotion: liefert die Default-Layer-Keys.

    Erfüllt von beiden ``EmotionLayers``-Varianten (``layered_renderer`` und
    ``avatar_config_loader``) – beide haben dieselben Felder.
    """

    body: str
    eye_left: str
    eye_right: str
    mouth: str
    effect: str | None


@dataclass(frozen=True)
class RenderPlan:
    """Vollständige Layer-Beschreibung für ein einzelnes Frame.

    Attributes:
        body: Body-Komponenten-Key.
        eye_left: Key für das linke Auge.
        eye_right: Key für das rechte Auge.
        mouth: Mund-Key.
        effect: Optionaler Effekt-Key (``None`` = kein Effekt-Layer).
        alpha: Deckkraft 0–255 (255 = opak). Für den Crossfade ab 83.3;
            in 83.2 immer 255 und vom Renderer nicht ausgewertet.
        y_offset: Vertikaler Versatz in Pixeln (Breathing-Animation).
    """

    body: str
    eye_left: str
    eye_right: str
    mouth: str
    effect: str | None = None
    alpha: int = 255
    y_offset: int = 0

    @classmethod
    def compose(
        cls,
        base: LayerSource,
        *,
        blink_eyes: tuple[str, str] | None = None,
        idle_eyes: tuple[str, str] | None = None,
        speaking_mouth: str | None = None,
        idle_mouth: str | None = None,
        alpha: int = 255,
        y_offset: int = 0,
    ) -> RenderPlan:
        """Baut einen Plan aus den Emotion-Defaults plus optionalen Overrides.

        Die Priorität ist über die Reihenfolge der Zuweisungen kodiert:

        - Augen: erst ``idle_eyes``, dann ``blink_eyes`` (Blink gewinnt).
        - Mund: erst ``idle_mouth``, dann ``speaking_mouth`` (Speaking gewinnt).

        Ein ``None``-Override lässt den jeweiligen Default unberührt.

        Args:
            base: Emotion-Defaults (Protocol :class:`LayerSource`).
            blink_eyes: Augen-Keys während eines Blinks (höchste Priorität).
            idle_eyes: Augen-Keys einer Idle-Aktion (mittlere Priorität).
            speaking_mouth: Mund-Key aus dem Lip-Sync (höchste Priorität).
            idle_mouth: Mund-Key einer Idle-Aktion (mittlere Priorität).
            alpha: Deckkraft des Plans (0–255).
            y_offset: Vertikaler Versatz (Breathing).

        Returns:
            Ein neuer, unveränderlicher :class:`RenderPlan`.
        """
        eye_left, eye_right = base.eye_left, base.eye_right
        if idle_eyes is not None:
            eye_left, eye_right = idle_eyes
        if blink_eyes is not None:
            eye_left, eye_right = blink_eyes

        mouth = base.mouth
        if idle_mouth is not None:
            mouth = idle_mouth
        if speaking_mouth is not None:
            mouth = speaking_mouth

        return cls(
            body=base.body,
            eye_left=eye_left,
            eye_right=eye_right,
            mouth=mouth,
            effect=base.effect,
            alpha=alpha,
            y_offset=y_offset,
        )
