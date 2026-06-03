"""RenderPlan – DTO für genau einen Avatar-Frame (Phase 83.2/83.3).

Ein ``RenderPlan`` beschreibt vollständig, welche Komponenten-PNGs ein Renderer
für ein Frame zusammensetzt: Body, Augen (links/rechts), Mund und optionaler
Effekt, plus ``y_offset`` (Breathing) und ``alpha`` (Deckkraft beim Crossfade,
ab 83.3 aktiv genutzt).

Die **Layer-Priorität** lebt ausschließlich in :meth:`RenderPlan.compose`, damit
es genau eine Quelle der Wahrheit gibt: sowohl der ``LayeredSpriteRenderer``
(``update`` baut intern einen Plan) als auch die ``AvatarStateMachine``
(``current_layers``) nutzen denselben Aufbau.

- **Augen:** ``blink`` > ``idle`` > Emotion-Default.
- **Mund:**  ``speaking`` (Lip-Sync) > ``idle`` > Emotion-Default.

``render_plan`` importiert bewusst **keine** konkrete ``EmotionLayers`` (es gibt
zwei strukturgleiche – im Renderer und im Config-Loader). Stattdessen genügt das
:class:`LayerSource`-Protocol; das vermeidet einen Zirkular-Import.

Ein :class:`RenderPlan` erfüllt selbst das :class:`LayerSource`-Protocol (er hat
``body``/``eye_left``/``eye_right``/``mouth``/``effect``). Dadurch kann der
Renderer im Crossfade (83.3) seine dynamischen Overrides per
:meth:`RenderPlan.compose` direkt auf die von der StateMachine gelieferten
Basis-Pläne in :class:`TransitionState` legen, ohne die StateMachine zu kennen.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

# Volle Deckkraft (opak). Pläne mit ``alpha >= OPAQUE_ALPHA`` rendert der
# Renderer byte-identisch zum opaken Bestandspfad (kein Alpha-Blend).
OPAQUE_ALPHA = 255


def lerp_alpha(progress: float) -> int:
    """Bildet einen Crossfade-Fortschritt 0.0–1.0 auf einen Alpha-Wert 0–255 ab.

    ``progress`` wird auf ``[0.0, 1.0]`` geklemmt. ``0.0`` → ``0`` (voll
    transparent, der einlaufende Plan ist unsichtbar), ``1.0`` →
    :data:`OPAQUE_ALPHA` (voll deckend).

    Args:
        progress: Fortschritt der Transition (``frame / crossfade_frames``).

    Returns:
        Ganzzahliger Alpha-Wert im Bereich ``0..255``.
    """
    clamped = min(1.0, max(0.0, progress))
    return round(OPAQUE_ALPHA * clamped)


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
        alpha: Deckkraft 0–255 (255 = opak). Ab 83.3 für den Crossfade aktiv:
            ``< 255`` lässt den Renderer diesen Plan über den darunterliegenden
            (opaken) Plan blenden.
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

    def with_alpha(self, alpha: int) -> RenderPlan:
        """Liefert eine Kopie des Plans mit anderer Deckkraft.

        Args:
            alpha: Neue Deckkraft 0–255.

        Returns:
            Ein neuer :class:`RenderPlan`; das Original bleibt unverändert.
        """
        return replace(self, alpha=alpha)


@dataclass(frozen=True)
class TransitionState:
    """Blend-Beschreibung für genau ein Crossfade-Frame (Phase 83.3).

    Von :meth:`AvatarStateMachine.transition_at` erzeugt und vom Renderer
    konsumiert. Trägt die **bloßen Emotion-Basis-Pläne** (ohne dynamische
    Overrides) der alten und der neuen Emotion. Der Renderer legt seine
    Overrides (Idle/Blink/Lip-Sync/Breathing) deckungsgleich auf **beide**
    Basen und blendet ``current`` (alpha < 255) über ``previous`` (opak).

    Außerhalb einer Transition ist ``in_transition`` ``False`` und ``current``
    der einzige relevante Plan (``progress == 1.0``); ``previous`` zeigt dann
    dieselbe Emotion und wird vom Renderer ignoriert.

    Attributes:
        in_transition: ``True``, solange ein Crossfade läuft.
        progress: Fortschritt ``0.0..1.0`` (``frame / crossfade_frames``).
        previous: Basis-Plan der **alten** Emotion (opak, ``alpha == 255``).
        current: Basis-Plan der **neuen** Emotion; ``alpha`` = lerp(progress).
    """

    in_transition: bool
    progress: float
    previous: RenderPlan
    current: RenderPlan
