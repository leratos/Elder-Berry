"""AvatarController – semantische Empfangsstelle für Avatar-Inputs (Phase 83.2).

Der Controller implementiert das ``AvatarDisplay``-ABC (aus ``robot/server.py``)
und ersetzt im Render-Loop die heutige Direkt-Verdrahtung
``RPi5AvatarDisplay → LayeredSpriteRenderer.show_emotion/show_speaking``. Er hält
eine :class:`AvatarStateMachine` (semantischer Zustand) und leitet parallel an
den Renderer weiter, damit das sichtbare Verhalten in 83.2 **identisch** bleibt.

Zwei Eingangs-APIs:

- **Legacy / REST** (``AvatarDisplay``): ``set_emotion(str)`` / ``set_speaking(
  bool)`` / ``get_state()`` – rückwärtskompatibel zum bestehenden
  ``/avatar/emotion``-Pfad.
- **Semantisch** (intern, später eigene REST-Routen): ``on_emotion_decision`` /
  ``on_speech_started`` / ``on_speech_ended``.

``set_speaking(bool)`` ist **kantengetriggert**: Der Render-Loop ruft es pro
Frame mit dem aktuellen Snapshot; nur echte Wechsel lösen den
Sprech-Zähler-Übergang aus (identisch zu ``on_speech_started/-ended``, ohne
``audio_meta``). So bleibt der Sprech-Zähler korrekt, obwohl er pro Frame
angestoßen wird. Der reine Zähler-Pfad (überlappende ``on_speech_started``,
83.5) ist für den semantischen Eingang reserviert; beide Eingänge gleichzeitig
zu mischen ist nicht vorgesehen.

Thread-Modell: Ein einziger ``threading.Lock`` deckt **atomar** die
Edge-Detection, die StateMachine-Mutation, das Renderer-Forwarding **und**
``current_layers``-Read (§0.6 / §6.5). Dadurch bleiben Zustand
(``get_state``) und gerendertes Bild auch bei konkurrierenden REST-/semantischen
Aufrufern konsistent und in Reihenfolge. In 83.2 wird der Controller nur vom
Render-Loop-Thread bedient; die Serialisierung ist bereits der Vertrag für 83.5,
wenn der REST-Thread direkt ``on_emotion_decision``/``set_speaking`` aufruft.
"""

from __future__ import annotations

import logging
import threading

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.render_plan import RenderPlan, TransitionState
from elder_berry.avatar.state_machine import AvatarStateMachine
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision
from elder_berry.core.log_sanitize import safe_log
from elder_berry.robot.server import AvatarDisplay

logger = logging.getLogger(__name__)

# Quelle für Decisions, die der Legacy-Pfad synthetisiert (kein Resolver-Score).
_LEGACY_SOURCE = "legacy_rest"


class AvatarController(AvatarDisplay):
    """Vermittelt zwischen semantischen Inputs, StateMachine und Renderer."""

    def __init__(
        self,
        renderer: AvatarRenderer,
        state_machine: AvatarStateMachine,
    ) -> None:
        """
        Args:
            renderer: Aktiver Avatar-Renderer (treibt in 83.2 weiterhin das
                Frame über ``show_emotion``/``show_speaking``/``update``).
            state_machine: Semantischer Zustand (Emotion + Sprech-Zähler).
        """
        self._renderer = renderer
        self._state_machine = state_machine
        self._lock = threading.Lock()
        # Letzter über den Legacy-Pfad gesetzter Sprech-Zustand (Edge-Detection).
        self._legacy_speaking = False

    # -- AvatarDisplay-Interface (REST-kompatibel) ----------------------------

    def set_emotion(self, emotion: str) -> None:
        """Legacy-Pfad: Emotion als String setzen (unbekannt → NEUTRAL)."""
        try:
            parsed = Emotion(emotion)
        except ValueError:
            logger.warning("Unbekannte Emotion '%s' → NEUTRAL", safe_log(emotion))
            parsed = Emotion.NEUTRAL
        self.on_emotion_decision(
            EmotionDecision(parsed, 1.0, _LEGACY_SOURCE, {})
        )

    def set_speaking(self, is_speaking: bool) -> None:
        """Legacy-Pfad: Sprech-Zustand setzen (kantengetriggert).

        Pro Frame aufrufbar; nur ein echter Wechsel löst einen
        Sprech-Zähler-Übergang aus. Edge-Detection und Zähler-Mutation laufen
        atomar unter einem Lock (kein Race bei konkurrierenden Aufrufern).
        """
        with self._lock:
            if is_speaking == self._legacy_speaking:
                return
            self._legacy_speaking = is_speaking
            self._apply_speech_delta_locked(is_speaking)

    def get_state(self) -> dict:
        """Liefert den semantischen Zustand (Emotion, Speaking, Zähler)."""
        with self._lock:
            state = self._state_machine.state
            return {
                "emotion": state.emotion.value,
                "speaking": self._state_machine.is_speaking(),
                "speaking_count": state.speaking_count,
            }

    # -- Erweiterte semantische API (intern) ----------------------------------

    def on_emotion_decision(self, decision: EmotionDecision) -> None:
        """Übernimmt eine aggregierte Emotion in StateMachine + Renderer.

        State-Mutation und Renderer-Forwarding laufen unter demselben Lock,
        damit ``get_state`` und das gerenderte Bild bei konkurrierenden Aufrufern
        nicht auseinanderlaufen.
        """
        with self._lock:
            self._state_machine.request_emotion(decision)
            self._renderer.show_emotion(decision.emotion)

    def on_speech_started(self, audio_meta: object | None = None) -> None:
        """Beginn einer Sprech-Sitzung (``audio_meta`` ist 83.4-Stub)."""
        del audio_meta  # Amplitude-Spur erst 83.4 (nur Playback-Modus).
        with self._lock:
            self._apply_speech_delta_locked(started=True)

    def on_speech_ended(self) -> None:
        """Ende einer Sprech-Sitzung (Zähler -1, ab 0 endet das Sprechen)."""
        with self._lock:
            self._apply_speech_delta_locked(started=False)

    def _apply_speech_delta_locked(self, started: bool) -> None:
        """Mutiert den Sprech-Zähler und leitet den Zustand an den Renderer.

        Caller **muss** ``self._lock`` halten – so bleiben Zähler-Übergang und
        Renderer-Forwarding atomar und geordnet.
        """
        if started:
            self._state_machine.speech_increment()
        else:
            self._state_machine.speech_decrement()
        self._renderer.show_speaking(self._state_machine.is_speaking())

    def current_layers(self, now: float) -> RenderPlan:
        """Liefert den Einzel-Plan des aktuellen Zustands (unter Lock).

        Einzel-Plan-Sicht (neue/Ziel-Emotion, Alpha spiegelt den Crossfade-
        Fortschritt). Die volle Zwei-Plan-Blend-Info liefert
        :meth:`current_transition`.
        """
        with self._lock:
            return self._state_machine.current_layers(now)

    def current_transition(self, now: float) -> TransitionState:
        """Liefert die Crossfade-Blend-Info des aktuellen Zustands (unter Lock).

        Der Render-Loop liest hiermit **pro Frame** die Transition und reicht sie
        an ``renderer.update(transition=...)``. Lock-gewrappt, damit der Read mit
        den StateMachine-Mutationen (``on_emotion_decision``/``set_emotion``)
        geordnet bleibt – derselbe Vertrag wie der übrige Controller (§0.6/§6.5),
        forward-looking für 83.5 (REST-Thread mutiert parallel).
        """
        with self._lock:
            return self._state_machine.transition_at(now)
