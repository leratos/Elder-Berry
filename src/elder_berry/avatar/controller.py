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
Frame mit dem aktuellen Snapshot; nur echte Wechsel lösen
``on_speech_started/-ended`` aus. So bleibt der Sprech-Zähler korrekt, obwohl er
pro Frame angestoßen wird. Der reine Zähler-Pfad (überlappende
``on_speech_started``, 83.5) ist für den semantischen Eingang reserviert; beide
Eingänge gleichzeitig zu mischen ist nicht vorgesehen.

Thread-Modell: Ein einziger ``threading.Lock`` deckt StateMachine-Mutation
**und** ``current_layers``-Read (§0.6 / §6.5). In 83.2 wird der Controller nur
vom Render-Loop-Thread bedient; der Lock implementiert bereits den Vertrag für
83.5, wenn der REST-Thread direkt ``on_emotion_decision`` aufruft.
"""

from __future__ import annotations

import logging
import threading

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.render_plan import RenderPlan
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

        Pro Frame aufrufbar; nur ein echter Wechsel löst
        ``on_speech_started``/``on_speech_ended`` aus.
        """
        with self._lock:
            if is_speaking == self._legacy_speaking:
                return
            self._legacy_speaking = is_speaking
        if is_speaking:
            self.on_speech_started()
        else:
            self.on_speech_ended()

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
        """Übernimmt eine aggregierte Emotion in StateMachine + Renderer."""
        with self._lock:
            self._state_machine.request_emotion(decision)
        # Renderer-Weiterleitung außerhalb des SM-Locks: Der Renderer wird in
        # 83.2 ausschließlich vom Render-Loop-Thread berührt.
        self._renderer.show_emotion(decision.emotion)

    def on_speech_started(self, audio_meta: object | None = None) -> None:
        """Beginn einer Sprech-Sitzung (``audio_meta`` ist 83.4-Stub)."""
        del audio_meta  # Amplitude-Spur erst 83.4 (nur Playback-Modus).
        with self._lock:
            self._state_machine.speech_increment()
            speaking = self._state_machine.is_speaking()
        self._renderer.show_speaking(speaking)

    def on_speech_ended(self) -> None:
        """Ende einer Sprech-Sitzung (Zähler -1, ab 0 endet das Sprechen)."""
        with self._lock:
            self._state_machine.speech_decrement()
            speaking = self._state_machine.is_speaking()
        self._renderer.show_speaking(speaking)

    def current_layers(self, now: float) -> RenderPlan:
        """Liefert den Layer-Plan des aktuellen Zustands (unter Lock).

        In 83.2 noch nicht die autoritative Frame-Quelle (der Renderer baut sein
        Frame in ``update()`` selbst); eingeführt für 83.3 (Crossfade).
        """
        with self._lock:
            return self._state_machine.current_layers(now)
