"""AvatarStateMachine – hält den semantischen Avatar-Zustand (Phase 83.2/83.3).

Die Zustandsmaschine ist der Layer zwischen „Bot entscheidet eine Emotion/
Speaking" und „Renderer zeichnet ein Frame". Idle, Blink und Lip-Sync bleiben
bis 83.6 im Renderer; **den Emotion-Crossfade besitzt ab 83.3 jedoch die
StateMachine** (Hybrid-Weiche, Journal #700): sie kennt die alte und neue
Emotion, rechnet den Fortschritt → Alpha aus und entscheidet harter Schnitt vs.
Crossfade. Der Renderer legt seine dynamischen Overrides nur noch auf die beiden
von hier gelieferten Basis-Pläne (:class:`TransitionState`).

Kernpunkte:

- ``speaking_count`` ist ein **Zähler statt Boolean** (Race-Fix §2.3 #9):
  überlappende ``speech_increment``-Aufrufe heben den Avatar erst nach ebenso
  vielen ``speech_decrement`` aus dem Sprech-Zustand.
- ``direct_cut_pairs`` ist **aktiv** (83.3): steht das geordnete Paar
  ``(alt, neu)`` darin, wird hart geschnitten statt crossgefadet
  („Schmiergesicht"-Vermeidung, §3.3). Alle anderen Wechsel crossfaden über
  ``crossfade_frames`` Frames.
- :meth:`transition_at` liefert pro Frame die Blend-Info (alt-Basis opak,
  neu-Basis mit Alpha = lerp(Fortschritt)); :meth:`current_layers` bleibt die
  Einzel-Plan-Sicht (neue Emotion, Alpha spiegelt den Fortschritt).

Die Zustandsmaschine ist **nicht** thread-safe; die Serialisierung übernimmt der
:class:`AvatarController` über einen gemeinsamen Lock (§0.6 / §6.5).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from elder_berry.avatar.render_plan import (
    LayerSource,
    RenderPlan,
    TransitionState,
    lerp_alpha,
)
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision

logger = logging.getLogger(__name__)

# Default-Frames für den Crossfade (8 @ 30 FPS ≈ 266 ms). Ab 83.3 ausgewertet.
DEFAULT_CROSSFADE_FRAMES = 8

# Frame-Rate, gegen die ``crossfade_frames`` in Sekunden umgerechnet wird.
# Muss zur Render-Loop-Rate (``layered_renderer.FPS``) passen; bewusst hier
# dupliziert, um einen Import-Zyklus Renderer↔StateMachine zu vermeiden.
DEFAULT_FPS = 30

# Phase 108 (Confidence-Gate): Mindest-Confidence einer EmotionDecision, damit
# sie die aktuell gezeigte Emotion überhaupt überschreiben darf. Der
# EmotionResolver liefert getaggte Turns mit ~0.7–0.9, einen nur aus dem
# Tracker-Trend abgeleiteten (untagged) Turn mit ≤0.2 (und 0.0 im Fallback).
# 0.35 trennt beide sauber: unsichere/untagged Turns halten die etablierte
# Mimik, statt sie hart umzuschalten. Der Legacy-/extract_emotion-Pfad
# synthetisiert ``confidence=1.0`` und passiert das Gate damit immer → Verhalten
# ohne Resolver unverändert.
DEFAULT_MIN_SWITCH_CONFIDENCE = 0.35

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
        emotion: Aktuell angezeigte (Ziel-)Emotion.
        previous_emotion: Emotion, von der ein laufender Crossfade ausgeht. Bei
            ``previous_emotion == emotion`` läuft **keine** Transition (frischer
            Zustand oder harter Schnitt).
        speaking_count: Anzahl offener Sprech-Sitzungen (>= 0). > 0 = spricht.
        last_change: ``time.monotonic``-Zeitstempel des letzten Emotionswechsels
            (Startzeit des Crossfade-Fortschritts).
        intensity: Anzeige-Tiefe der aktuellen Emotion (Phase 110, 0.0–1.0).
            ``1.0`` = voll/opak; ``< 1.0`` blendet im eingeschwungenen Zustand
            Richtung neutral (mildere Mimik).
    """

    emotion: Emotion = Emotion.NEUTRAL
    previous_emotion: Emotion = Emotion.NEUTRAL
    speaking_count: int = 0
    last_change: float = 0.0
    intensity: float = 1.0


@dataclass
class AvatarStateMachine:
    """Verwaltet Emotion + Sprech-Zähler und liefert den Layer-Plan eines Frames.

    Args:
        emotion_map: Emotion → Default-Layer-Quelle (dieselbe Instanz, die der
            Renderer aus YAML/Hardcode geladen hat). Nötig, damit
            :meth:`current_layers` Emotionen in Komponenten-Keys auflöst.
        crossfade_frames: Crossfade-Länge in Frames (aktiv ab 83.3).
        direct_cut_pairs: Übergänge, die hart geschnitten statt crossgefadet
            werden (aktiv ab 83.3).
        fps: Frame-Rate, gegen die ``crossfade_frames`` in Sekunden umgerechnet
            wird. Default :data:`DEFAULT_FPS` (= Render-Loop-Rate).
    """

    emotion_map: Mapping[Emotion, LayerSource]
    crossfade_frames: int = DEFAULT_CROSSFADE_FRAMES
    direct_cut_pairs: frozenset[tuple[Emotion, Emotion]] = field(
        default_factory=lambda: DEFAULT_DIRECT_CUT_PAIRS
    )
    fps: int = DEFAULT_FPS
    min_switch_confidence: float = DEFAULT_MIN_SWITCH_CONFIDENCE
    _state: AvatarState = field(default_factory=AvatarState, init=False)

    @property
    def state(self) -> AvatarState:
        """Der aktuelle (veränderliche) Zustand. Nur unter Lock lesen/mutieren."""
        return self._state

    def request_emotion(self, decision: EmotionDecision) -> bool:
        """Übernimmt die Emotion aus einer ``EmotionDecision``.

        - **Gleiche Emotion** → no-op (idempotent, kein ``last_change``-Update).
        - **Confidence < :attr:`min_switch_confidence`** → no-op (Phase 108):
          eine unsichere/untagged Decision hält die etablierte Emotion, statt
          sie umzuschalten. Der Legacy-Pfad (``confidence == 1.0``) passiert das
          Gate immer.
        - **(alt, neu) ∈ direct_cut_pairs** → harter Schnitt: ``previous_emotion``
          wird auf die neue Emotion gesetzt, sodass :meth:`transition_at` keine
          Transition meldet.
        - **sonst** → Crossfade starten: ``previous_emotion`` = alte Emotion,
          ``last_change`` = jetzt. Trifft eine neue Decision **während** eines
          laufenden Crossfades ein, startet eine frische Transition von der
          aktuellen Ziel-Emotion aus (leichter Pop wird in Kauf genommen).

        Args:
            decision: Aggregiertes Emotions-Ergebnis (aus dem EmotionResolver
                oder – im Legacy-Pfad – vom Controller synthetisiert).

        Returns:
            ``True``, wenn die angezeigte Emotion jetzt ``decision.emotion`` ist
            (frisch übernommen **oder** bereits aktiv); ``False``, wenn die
            Decision vom Confidence-Gate **verworfen** wurde und die alte Emotion
            gehalten wird. Der Controller zeigt die Emotion nur bei ``True`` an
            (Phase 108: verworfene Emotion darf den Renderer nicht umschalten).
        """
        new_emotion = decision.emotion
        old_emotion = self._state.emotion
        if new_emotion is old_emotion:
            # Gleiche Emotion: kein Wechsel, aber die Anzeige-Tiefe (Phase 110)
            # ggf. aktualisieren (z.B. angry:0.4 → angry:0.8 vertieft den Blend).
            # Nur bei vertrauenswürdiger (= das Gate passierender) Decision: ein
            # tag-loser Tracker-Turn (confidence ≤ Schwelle, intensity Default
            # 1.0) darf einen gehaltenen milden Blend NICHT auf voll hochziehen.
            if decision.confidence >= self.min_switch_confidence:
                self._state.intensity = decision.intensity
            return True  # bereits angezeigt → Renderer darf idempotent zeigen
        # Phase 108: Confidence-Gate. Eine unsichere Decision (typisch: untagged
        # Turn, nur Tracker-Trend) überschreibt die aktuell gezeigte Emotion
        # nicht hart, sondern lässt sie stehen (emotionale Trägheit). Die
        # Intensität einer verworfenen Decision wird NICHT übernommen.
        if decision.confidence < self.min_switch_confidence:
            logger.debug(
                "Emotion-Wechsel verworfen (conf=%.2f < %.2f, src=%s): %s behalten",
                decision.confidence,
                self.min_switch_confidence,
                decision.source,
                old_emotion.value,
            )
            return False
        is_direct_cut = (old_emotion, new_emotion) in self.direct_cut_pairs
        logger.debug(
            "Emotion: %s → %s (conf=%.2f, src=%s, %s)",
            old_emotion.value,
            new_emotion.value,
            decision.confidence,
            decision.source,
            "cut" if is_direct_cut else "crossfade",
        )
        self._state.emotion = new_emotion
        self._state.intensity = decision.intensity  # Phase 110: Anzeige-Tiefe
        # Bei hartem Schnitt previous == emotion ⇒ keine Transition; sonst die
        # alte Emotion als Fade-Quelle merken.
        self._state.previous_emotion = new_emotion if is_direct_cut else old_emotion
        self._state.last_change = time.monotonic()
        return True

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

    def _base_plan(self, emotion: Emotion) -> RenderPlan:
        """Bloßer Basis-Plan einer Emotion (ohne Overrides), NEUTRAL-Fallback."""
        base = self.emotion_map.get(emotion)
        if base is None:
            base = self.emotion_map[Emotion.NEUTRAL]
        return RenderPlan.compose(base)

    def _progress(self, now: float) -> float:
        """Crossfade-Fortschritt ``0.0..1.0`` seit ``last_change`` (geklemmt)."""
        if self.fps <= 0 or self.crossfade_frames <= 0:
            return 1.0
        duration = self.crossfade_frames / self.fps
        elapsed = now - self._state.last_change
        return min(1.0, max(0.0, elapsed / duration))

    def is_in_transition(self, now: float) -> bool:
        """``True``, solange ein Crossfade zwischen zwei Emotionen läuft."""
        if self._state.previous_emotion is self._state.emotion:
            return False
        return self._progress(now) < 1.0

    def transition_at(self, now: float) -> TransitionState:
        """Liefert die Blend-Info für genau ein Frame (Crossfade, 83.3).

        Reiner Lese-Zugriff (mutiert den Zustand nicht). Außerhalb einer
        Transition ist ``in_transition`` ``False`` und ``previous == current``
        (opak); während eines Crossfades trägt ``current`` das lerp-Alpha über
        ``previous`` (opak).

        Args:
            now: ``time.monotonic``-Zeitpunkt des Frames.

        Returns:
            Ein :class:`TransitionState` mit alt-/neu-Basis-Plan und Fortschritt.
        """
        current_base = self._base_plan(self._state.emotion)
        if not self.is_in_transition(now):
            # Phase 110: eingeschwungener Zustand. Bei intensity < 1.0 die Emotion
            # als gehaltenen Blend Richtung neutral darstellen (mildere Mimik) –
            # über DENSELBEN Zwei-Plan-Cross-Dissolve wie der Crossfade:
            # previous = neutral (opak), current = Emotion mit alpha = lerp(int.).
            # intensity == 1.0 bleibt opak (byte-identisch zu vor Phase 110).
            intensity = self._state.intensity
            if intensity < 1.0:
                return TransitionState(
                    in_transition=True,
                    progress=intensity,
                    previous=self._base_plan(Emotion.NEUTRAL),
                    current=current_base.with_alpha(lerp_alpha(intensity)),
                    full_blend=True,  # immer Voll-Blend, auch im MOUTH_ONLY-Scope
                )
            return TransitionState(
                in_transition=False,
                progress=1.0,
                previous=current_base,
                current=current_base,
            )
        progress = self._progress(now)
        previous_base = self._base_plan(self._state.previous_emotion)
        return TransitionState(
            in_transition=True,
            progress=progress,
            previous=previous_base,
            current=current_base.with_alpha(lerp_alpha(progress)),
        )

    def current_layers(self, now: float) -> RenderPlan:
        """Einzel-Plan-Sicht des aktuellen Zustands (neue/Ziel-Emotion).

        Liefert den Basis-Plan der aktuellen Emotion. Läuft ein Crossfade,
        spiegelt ``alpha`` den Fortschritt (lerp); außerhalb einer Transition ist
        der Plan opak (``alpha == 255``). Die volle Zwei-Plan-Blend-Info liefert
        :meth:`transition_at`.

        Args:
            now: ``time.monotonic``-Zeitpunkt des Frames.

        Returns:
            Ein :class:`RenderPlan` der aktuellen Emotion (Alpha = Fortschritt).
        """
        current_base = self._base_plan(self._state.emotion)
        if self.is_in_transition(now):
            return current_base.with_alpha(lerp_alpha(self._progress(now)))
        return current_base
