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
import time
from typing import Any

from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.idle_policy import IdleBehaviorPolicy, IdleBlinkOverrides
from elder_berry.avatar.lip_sync import AmplitudeLipSyncDriver, LipSyncDriver
from elder_berry.avatar.render_plan import RenderPlan, TransitionState
from elder_berry.avatar.state_machine import AvatarStateMachine
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision
from elder_berry.core.audio_analyzer import AmplitudeTrack
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
        idle_policy: IdleBehaviorPolicy | None = None,
    ) -> None:
        """
        Args:
            renderer: Aktiver Avatar-Renderer (treibt in 83.2 weiterhin das
                Frame über ``show_emotion``/``show_speaking``/``update``).
            state_machine: Semantischer Zustand (Emotion + Sprech-Zähler).
            idle_policy: Idle-/Blink-Logik (83.6). ``None`` → der Controller
                liefert leere Idle/Blink-Overrides (Standalone/Tests; kein Idle,
                kein Blink). Das Produktions-Wiring (``RPi5AvatarDisplay``) baut
                die Policy aus der geladenen Avatar-Config + ``NoopAttentionProvider``
                und injiziert sie, sodass sich am Verhalten nichts ändert.
        """
        self._renderer = renderer
        self._state_machine = state_machine
        self._idle_policy = idle_policy
        self._lock = threading.Lock()
        # Letzter über den Legacy-Pfad gesetzter Sprech-Zustand (Edge-Detection).
        self._legacy_speaking = False
        # Aktiver Lip-Sync-Driver (83.4, nur Playback-Modus). Gesetzt auf der
        # steigenden Sprech-Flanke, wenn ein nutzbarer AmplitudeTrack vorliegt;
        # sonst ``None`` → der Renderer behält seinen Inline-Random (§4.4).
        self._lip_sync: LipSyncDriver | None = None

    # -- AvatarDisplay-Interface (REST-kompatibel) ----------------------------

    def set_emotion(self, emotion: str, confidence: float = 1.0) -> None:
        """REST-Pfad: Emotion als String setzen (unbekannt → NEUTRAL).

        Phase 108: ``confidence`` (vom Bot-seitigen ``EmotionResolver``, über die
        REST-Grenze durchgereicht) entscheidet im :class:`AvatarStateMachine`-
        Confidence-Gate, ob die Emotion überhaupt umgeschaltet wird. Ohne
        expliziten Wert (Legacy-/extract_emotion-Pfad) bleibt es bei ``1.0`` →
        das Gate passiert immer, Verhalten unverändert.
        """
        try:
            parsed = Emotion(emotion)
        except ValueError:
            logger.warning("Unbekannte Emotion '%s' → NEUTRAL", safe_log(emotion))
            parsed = Emotion.NEUTRAL
        self.on_emotion_decision(
            EmotionDecision(parsed, confidence, _LEGACY_SOURCE, {})
        )

    def set_speaking(
        self, is_speaking: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        """Legacy-Pfad: Sprech-Zustand setzen (kantengetriggert).

        Pro Frame aufrufbar; nur ein echter Wechsel löst einen
        Sprech-Zähler-Übergang aus. Edge-Detection und Zähler-Mutation laufen
        atomar unter einem Lock (kein Race bei konkurrierenden Aufrufern).

        ``audio_meta`` (83.4) ist nur auf der **steigenden** Flanke relevant:
        liegt ein nutzbarer AmplitudeTrack vor, wird der
        :class:`AmplitudeLipSyncDriver` aktiviert; sonst bleibt es beim
        Renderer-Inline-Random (§4.4).
        """
        with self._lock:
            if is_speaking == self._legacy_speaking:
                return
            self._legacy_speaking = is_speaking
            self._apply_speech_delta_locked(is_speaking, audio_meta)

    def get_state(self) -> dict[str, Any]:
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

        Phase 108: ``show_emotion`` wird nur aufgerufen, wenn die StateMachine die
        Decision **übernommen** hat (oder die Emotion bereits aktiv war). Eine vom
        Confidence-Gate verworfene Emotion darf den Renderer nicht umschalten,
        sonst zeigte das Display die abgelehnte Emotion, während ``get_state`` die
        gehaltene meldet.
        """
        with self._lock:
            if self._state_machine.request_emotion(decision):
                self._renderer.show_emotion(decision.emotion)

    def on_speech_started(self, audio_meta: AmplitudeTrack | None = None) -> None:
        """Beginn einer Sprech-Sitzung (semantischer Pfad).

        ``audio_meta`` (83.4): liegt ein nutzbarer AmplitudeTrack vor, wird der
        :class:`AmplitudeLipSyncDriver` aktiviert (nur Playback-Modus).
        """
        with self._lock:
            self._apply_speech_delta_locked(started=True, audio_meta=audio_meta)

    def on_speech_ended(self) -> None:
        """Ende einer Sprech-Sitzung (Zähler -1, ab 0 endet das Sprechen)."""
        with self._lock:
            self._apply_speech_delta_locked(started=False)

    def _apply_speech_delta_locked(
        self, started: bool, audio_meta: AmplitudeTrack | None = None
    ) -> None:
        """Mutiert den Sprech-Zähler und leitet den Zustand an den Renderer.

        Caller **muss** ``self._lock`` halten – so bleiben Zähler-Übergang,
        Lip-Sync-Driver-Wahl und Renderer-Forwarding atomar und geordnet.
        """
        if started:
            self._state_machine.speech_increment()
            self._select_lip_sync_driver_locked(audio_meta)
        else:
            self._state_machine.speech_decrement()
            if not self._state_machine.is_speaking():
                self._lip_sync = None
        self._renderer.show_speaking(self._state_machine.is_speaking())

    def _select_lip_sync_driver_locked(
        self, audio_meta: AmplitudeTrack | None
    ) -> None:
        """Wählt den Lip-Sync-Driver für die beginnende Sprech-Sitzung (83.4).

        AmplitudeTrack vorhanden und nicht leer → :class:`AmplitudeLipSyncDriver`
        (mit Komponenten-Existenz-Guard aus ``renderer.component_keys``, §0.6);
        sonst ``None`` → der Renderer behält seinen Inline-Random (§4.4). Caller
        **muss** ``self._lock`` halten.
        """
        if audio_meta is None or audio_meta.is_empty():
            self._lip_sync = None
            return
        driver = AmplitudeLipSyncDriver(
            audio_meta,
            available_components=self._renderer.component_keys,
        )
        driver.start(time.monotonic())
        self._lip_sync = driver

    def current_speaking_mouth(self, now: float) -> str | None:
        """Liefert den Mund-Key des aktiven Lip-Sync-Drivers (oder ``None``).

        Der Render-Loop liest hiermit **pro Frame** den Amplitude-Mund und reicht
        ihn an ``renderer.update(speaking_mouth=...)``. ``None``, solange kein
        Driver aktiv ist oder nicht gesprochen wird → der Renderer rendert
        byte-identisch (Inline-Random / kein Lip-Sync). Lock-gewrappt, derselbe
        Vertrag wie :meth:`current_transition`.
        """
        with self._lock:
            if self._lip_sync is None or not self._state_machine.is_speaking():
                return None
            return self._lip_sync.mouth_at(now)

    def current_idle_blink(self, now: float) -> IdleBlinkOverrides:
        """Liefert die pro Frame aufgelösten Idle-/Blink-Overrides (unter Lock).

        Der Render-Loop liest hiermit **pro Frame** Idle + Blink und reicht sie an
        ``renderer.update(idle_blink=...)``. Die Policy bekommt die aktuelle
        (Ziel-)Emotion und den Sprech-Zustand aus der StateMachine; ihre
        Timer-Mutation läuft unter demselben Lock wie die übrigen ``current_*``-
        Reads und die StateMachine-Mutationen (§0.6/§6.5). Ohne injizierte Policy
        (``None``) sind die Overrides leer (kein Idle, kein Blink).
        """
        with self._lock:
            if self._idle_policy is None:
                return IdleBlinkOverrides()
            mood = self._state_machine.state.emotion
            is_speaking = self._state_machine.is_speaking()
            return self._idle_policy.frame_overrides(now, mood, is_speaking)

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
