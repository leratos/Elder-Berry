"""AvatarStateMachine – hält den semantischen Avatar-Zustand (Phase 83.2).

Die Zustandsmaschine ist der Layer zwischen „Bot entscheidet eine Emotion/
Speaking" und „Renderer zeichnet ein Frame". Sie ersetzt **noch nicht** die
Frame-Erzeugung des ``LayeredSpriteRenderer`` (Idle, Blink, Lip-Sync und
Crossfade bleiben in 83.2 im Renderer); sie wird hier eingeführt und getestet
und in 83.3 (Crossfade) / 83.6 (Idle-Migration) zur autoritativen Frame-Quelle.

Kernpunkte:

- ``speaking_count`` ist ein **Zähler statt Boolean** (Race-Fix §2.3 #9):
  überlappende ``speech_increment``-Aufrufe heben den Avatar erst nach ebenso
  vielen ``speech_decrement`` aus dem Sprech-Zustand.
- ``direct_cut_pairs`` ist in 83.2 **nur Default-Datensatz**. Umgeschaltet wird
  immer hart (Crossfade ist 83.3); die Paare markieren, welche Übergänge auch
  später hart bleiben.

Die Zustandsmaschine ist **nicht** thread-safe; die Serialisierung übernimmt der
:class:`AvatarController` über einen gemeinsamen Lock (§0.6 / §6.5).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from elder_berry.avatar.render_plan import LayerSource, RenderPlan
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision

logger = logging.getLogger(__name__)

# Default-Frames für den Crossfade (8 @ 30 FPS ≈ 266 ms). In 83.2 nur als
# Konfigurationswert gehalten; das Blending kommt in 83.3.
DEFAULT_CROSSFADE_FRAMES = 8

# Emotionspaare, die sprunghaft wirken und daher auch mit Crossfade (83.3) hart
# umgeschaltet werden sollen ("Schmiergesicht"-Vermeidung, §3.3). In 83.2 reiner
# Datensatz – es wird ohnehin immer hart umgeschaltet.
DEFAULT_DIRECT_CUT_PAIRS: frozenset[tuple[Emotion, Emotion]] = frozenset(
    {
        (Emotion.NEUTRAL, Emotion.ANGRY),
        (Emotion.CHEERFUL, Emotion.ANGRY),
        (Emotion.MOTIVATED, Emotion.ANGRY),
        (Emotion.NEUTRAL, Emotion.SAD),
        (Emotion.SHY, Emotion.ANGRY),
    }
)


@dataclass
class AvatarState:
    """Aktueller semantischer Zustand des Avatars.

    Attributes:
        emotion: Aktuell angezeigte Emotion.
        speaking_count: Anzahl offener Sprech-Sitzungen (>= 0). > 0 = spricht.
        last_change: ``time.monotonic``-Zeitstempel des letzten Emotionswechsels
            (Basis für die Crossfade-Dauer ab 83.3).
    """

    emotion: Emotion = Emotion.NEUTRAL
    speaking_count: int = 0
    last_change: float = 0.0


@dataclass
class AvatarStateMachine:
    """Verwaltet Emotion + Sprech-Zähler und liefert den Layer-Plan eines Frames.

    Args:
        emotion_map: Emotion → Default-Layer-Quelle (dieselbe Instanz, die der
            Renderer aus YAML/Hardcode geladen hat). Nötig, damit
            :meth:`current_layers` Emotionen in Komponenten-Keys auflöst.
        crossfade_frames: Crossfade-Länge in Frames (83.3; in 83.2 nur gehalten).
        direct_cut_pairs: Übergänge, die hart geschnitten werden (83.3; in 83.2
            reiner Datensatz).
    """

    emotion_map: Mapping[Emotion, LayerSource]
    crossfade_frames: int = DEFAULT_CROSSFADE_FRAMES
    direct_cut_pairs: frozenset[tuple[Emotion, Emotion]] = field(
        default_factory=lambda: DEFAULT_DIRECT_CUT_PAIRS
    )
    _state: AvatarState = field(default_factory=AvatarState, init=False)

    @property
    def state(self) -> AvatarState:
        """Der aktuelle (veränderliche) Zustand. Nur unter Lock lesen/mutieren."""
        return self._state

    def request_emotion(self, decision: EmotionDecision) -> None:
        """Übernimmt die Emotion aus einer ``EmotionDecision`` (harter Switch).

        Idempotent: Bei gleicher Emotion passiert nichts (kein ``last_change``-
        Update). In 83.2 wird immer hart umgeschaltet; ``direct_cut_pairs`` und
        ``crossfade_frames`` werden noch nicht ausgewertet (Crossfade = 83.3).

        Args:
            decision: Aggregiertes Emotions-Ergebnis (aus dem EmotionResolver
                oder – im Legacy-Pfad – vom Controller synthetisiert).
        """
        if decision.emotion is self._state.emotion:
            return
        logger.debug(
            "Emotion: %s → %s (conf=%.2f, src=%s)",
            self._state.emotion.value,
            decision.emotion.value,
            decision.confidence,
            decision.source,
        )
        self._state.emotion = decision.emotion
        self._state.last_change = time.monotonic()

    def speech_increment(self) -> None:
        """Erhöht den Sprech-Zähler (Beginn einer Sprech-Sitzung)."""
        self._state.speaking_count += 1

    def speech_decrement(self) -> None:
        """Verringert den Sprech-Zähler, geklemmt auf >= 0 (Ende einer Sitzung)."""
        if self._state.speaking_count > 0:
            self._state.speaking_count -= 1
        else:
            logger.debug("speech_decrement bei speaking_count=0 ignoriert")

    def is_speaking(self) -> bool:
        """``True``, solange mindestens eine Sprech-Sitzung offen ist."""
        return self._state.speaking_count > 0

    def current_layers(self, now: float) -> RenderPlan:
        """Liefert den Layer-Plan für den aktuellen Zustand.

        In 83.2 ist das der **Ruhe-Basis-Plan** der aktuellen Emotion: Idle,
        Blink, Lip-Sync und Crossfade liegen noch im Renderer, daher fließen sie
        hier nicht ein. ``now`` ist für die Crossfade-Zeitrechnung ab 83.3
        reserviert.

        Args:
            now: ``time.monotonic``-Zeitpunkt des Frames (83.2: ungenutzt).

        Returns:
            Ein :class:`RenderPlan` mit den Emotion-Default-Layern.
        """
        del now  # 83.2: kein Crossfade → Frame-Zeit noch nicht nötig.
        base = self.emotion_map.get(self._state.emotion)
        if base is None:
            base = self.emotion_map[Emotion.NEUTRAL]
        return RenderPlan.compose(base)
