"""Tests für AvatarController – Legacy- und semantischer Pfad (Phase 83.2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.avatar.attention import NoopAttentionProvider
from elder_berry.avatar.avatar_config_loader import EmotionLayers
from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.controller import AvatarController
from elder_berry.avatar.idle_policy import (
    IdleAction,
    IdleBehaviorPolicy,
    IdleBlinkOverrides,
)
from elder_berry.avatar.state_machine import AvatarStateMachine
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision
from elder_berry.core.audio_analyzer import AmplitudeTrack
from elder_berry.robot.server import AvatarDisplay

# Die fünf Mund-Komponenten der Amplitude-Bucket-Tabelle (§4.2).
_MOUTH_KEYS = frozenset(
    {
        "mouth_neutral_close",
        "mouth_tiny",
        "mouth_halfopen",
        "mouth_open",
        "mouth_wide",
    }
)


def _layers(body: str) -> EmotionLayers:
    return EmotionLayers(
        body=body,
        eye_left="eye_left_open",
        eye_right="eye_right_open",
        mouth="mouth_neutral_close",
        can_blink=True,
    )


def _emotion_map() -> dict[Emotion, EmotionLayers]:
    return {
        Emotion.NEUTRAL: _layers("relaxed"),
        Emotion.CHEERFUL: _layers("welcome"),
        Emotion.ANGRY: _layers("angry"),
    }


@pytest.fixture
def renderer() -> MagicMock:
    return MagicMock(spec=AvatarRenderer)


@pytest.fixture
def state_machine() -> AvatarStateMachine:
    return AvatarStateMachine(emotion_map=_emotion_map())


@pytest.fixture
def controller(renderer, state_machine) -> AvatarController:
    return AvatarController(renderer=renderer, state_machine=state_machine)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class TestControllerInterface:
    def test_is_avatar_display(self, controller):
        assert isinstance(controller, AvatarDisplay)

    def test_get_state_shape(self, controller):
        state = controller.get_state()
        assert state == {
            "emotion": "neutral",
            "speaking": False,
            "speaking_count": 0,
        }


# ---------------------------------------------------------------------------
# Legacy-Pfad: set_emotion
# ---------------------------------------------------------------------------


class TestLegacySetEmotion:
    def test_set_emotion_updates_state_and_renderer(self, controller, renderer):
        controller.set_emotion("cheerful")
        assert controller.get_state()["emotion"] == "cheerful"
        renderer.show_emotion.assert_called_once_with(Emotion.CHEERFUL)

    def test_unknown_emotion_falls_back_to_neutral(self, controller, renderer):
        controller.set_emotion("definitely-not-an-emotion")
        assert controller.get_state()["emotion"] == "neutral"
        renderer.show_emotion.assert_called_once_with(Emotion.NEUTRAL)

    def test_set_emotion_sequence(self, controller, renderer):
        for name, enum in [
            ("angry", Emotion.ANGRY),
            ("cheerful", Emotion.CHEERFUL),
            ("neutral", Emotion.NEUTRAL),
        ]:
            controller.set_emotion(name)
            assert controller.get_state()["emotion"] == name
            renderer.show_emotion.assert_called_with(enum)

    def test_default_confidence_switches(self, controller):
        """Ohne confidence-Argument (Legacy) wird umgeschaltet (Default 1.0)."""
        controller.set_emotion("angry")
        assert controller.get_state()["emotion"] == "angry"

    def test_low_confidence_holds_emotion(self, controller):
        """Phase 108: eine unsichere Emotion (< Gate) hält den Zustand."""
        controller.set_emotion("cheerful", confidence=1.0)  # etabliert
        controller.set_emotion("angry", confidence=0.2)  # unsicher
        assert controller.get_state()["emotion"] == "cheerful"

    def test_high_confidence_switches(self, controller):
        controller.set_emotion("angry", confidence=0.8)
        assert controller.get_state()["emotion"] == "angry"

    def test_rejected_emotion_not_shown_on_renderer(self, controller, renderer):
        """Phase 108: eine gegatete Emotion darf den Renderer nicht umschalten."""
        controller.set_emotion("cheerful", confidence=1.0)  # etabliert + gezeigt
        renderer.show_emotion.reset_mock()
        controller.set_emotion("angry", confidence=0.2)  # gegated
        assert controller.get_state()["emotion"] == "cheerful"  # State gehalten
        renderer.show_emotion.assert_not_called()  # Renderer NICHT umgeschaltet

    def test_accepted_emotion_shown_on_renderer(self, controller, renderer):
        controller.set_emotion("cheerful", confidence=1.0)
        renderer.show_emotion.reset_mock()
        controller.set_emotion("angry", confidence=0.9)  # akzeptiert
        renderer.show_emotion.assert_called_once_with(Emotion.ANGRY)


# ---------------------------------------------------------------------------
# Legacy-Pfad: set_speaking (kantengetriggert)
# ---------------------------------------------------------------------------


class TestLegacySetSpeaking:
    def test_set_speaking_true(self, controller, renderer):
        controller.set_speaking(True)
        assert controller.get_state()["speaking"] is True
        assert controller.get_state()["speaking_count"] == 1
        renderer.show_speaking.assert_called_once_with(True)

    def test_set_speaking_true_is_idempotent(self, controller, renderer):
        """Pro-Frame-Aufruf: nur die erste True-Kante zählt (kein Counter-Drift)."""
        controller.set_speaking(True)
        controller.set_speaking(True)
        controller.set_speaking(True)
        assert controller.get_state()["speaking_count"] == 1
        renderer.show_speaking.assert_called_once_with(True)

    def test_set_speaking_false_initial_is_noop(self, controller, renderer):
        controller.set_speaking(False)  # war nie True → keine Kante
        renderer.show_speaking.assert_not_called()
        assert controller.get_state()["speaking_count"] == 0

    def test_set_speaking_round_trip(self, controller, renderer):
        controller.set_speaking(True)
        controller.set_speaking(False)
        assert controller.get_state()["speaking"] is False
        assert controller.get_state()["speaking_count"] == 0
        assert renderer.show_speaking.call_args_list == [
            ((True,), {}),
            ((False,), {}),
        ]


# ---------------------------------------------------------------------------
# Semantischer Pfad
# ---------------------------------------------------------------------------


class TestSemanticPath:
    def test_on_emotion_decision_forwards(self, controller, renderer):
        decision = EmotionDecision(Emotion.ANGRY, 0.9, "llm_tag", {"llm_tag": 0.7})
        controller.on_emotion_decision(decision)
        assert controller.get_state()["emotion"] == "angry"
        renderer.show_emotion.assert_called_once_with(Emotion.ANGRY)

    def test_overlapping_speech_sessions(self, controller, renderer):
        controller.on_speech_started()
        controller.on_speech_started()
        assert controller.get_state()["speaking_count"] == 2
        assert controller.get_state()["speaking"] is True

        controller.on_speech_ended()
        assert controller.get_state()["speaking_count"] == 1
        assert controller.get_state()["speaking"] is True  # noch eine offen

        controller.on_speech_ended()
        assert controller.get_state()["speaking_count"] == 0
        assert controller.get_state()["speaking"] is False

    def test_on_speech_started_accepts_none_audio_meta(self, controller):
        # Ohne Track: spricht, aber kein Amplitude-Driver (Inline-Random, §4.4).
        controller.on_speech_started(audio_meta=None)
        assert controller.get_state()["speaking"] is True
        assert controller.current_speaking_mouth(now=0.0) is None

    def test_current_layers_reflects_emotion(self, controller):
        controller.on_emotion_decision(EmotionDecision(Emotion.ANGRY, 0.9, "llm_tag", {}))
        plan = controller.current_layers(now=0.0)
        assert plan.body == "angry"


# ---------------------------------------------------------------------------
# current_transition (Phase 83.3, Lock-gewrappte Crossfade-Blend-Info)
# ---------------------------------------------------------------------------


class TestCurrentTransition:
    def test_returns_transition_state(self, controller):
        from elder_berry.avatar.render_plan import TransitionState

        ts = controller.current_transition(now=0.0)
        assert isinstance(ts, TransitionState)
        assert ts.in_transition is False  # frischer Zustand

    def test_reflects_running_crossfade(self, controller, state_machine):
        # NEUTRAL → CHEERFUL ist kein direct_cut-Paar → Crossfade.
        controller.on_emotion_decision(
            EmotionDecision(Emotion.CHEERFUL, 0.9, "llm_tag", {})
        )
        state_machine.state.last_change = 0.0  # deterministische Zeitbasis
        ts = controller.current_transition(now=0.0)
        assert ts.in_transition is True
        assert ts.current.body == "welcome"  # CHEERFUL-Basis
        assert ts.previous.body == "relaxed"  # NEUTRAL-Basis (Fade-Quelle)

    def test_direct_cut_reports_no_transition(self, controller):
        # NEUTRAL → ANGRY IST ein direct_cut-Paar → harter Schnitt.
        controller.on_emotion_decision(
            EmotionDecision(Emotion.ANGRY, 1.0, "llm_tag", {})
        )
        ts = controller.current_transition(now=0.0)
        assert ts.in_transition is False


# ---------------------------------------------------------------------------
# Lip-Sync-Driver-Wahl (Phase 83.4, nur Playback-Modus)
# ---------------------------------------------------------------------------


class TestLipSyncSelection:
    """Der Controller wählt auf der Sprech-Flanke Amplitude vs. kein Driver."""

    def _wide_track(self) -> AmplitudeTrack:
        # Alle Buckets > 0.75 → unabhängig vom Sample-Index immer mouth_wide.
        return AmplitudeTrack(samples=[0.9, 0.9, 0.9], duration_ms=150)

    def test_no_track_means_no_amplitude_driver(self, controller):
        controller.set_speaking(True)  # ohne audio_meta
        assert controller.current_speaking_mouth(now=0.0) is None

    def test_track_activates_amplitude_driver(self, controller, renderer):
        renderer.component_keys = _MOUTH_KEYS
        controller.set_speaking(True, audio_meta=self._wide_track())
        # Amplitude-Driver aktiv → liefert den Bucket-Mund (deterministisch wide).
        assert controller.current_speaking_mouth(now=0.0) == "mouth_wide"

    def test_empty_track_falls_back_to_random(self, controller, renderer):
        renderer.component_keys = _MOUTH_KEYS
        controller.set_speaking(True, audio_meta=AmplitudeTrack(samples=[], duration_ms=0))
        assert controller.current_speaking_mouth(now=0.0) is None

    def test_not_speaking_returns_none(self, controller, renderer):
        renderer.component_keys = _MOUTH_KEYS
        controller.set_speaking(True, audio_meta=self._wide_track())
        controller.set_speaking(False)
        assert controller.current_speaking_mouth(now=0.0) is None

    def test_driver_cleared_after_speech_end(self, controller, renderer):
        renderer.component_keys = _MOUTH_KEYS
        controller.on_speech_started(audio_meta=self._wide_track())
        controller.on_speech_ended()
        # Folge-Sitzung ohne Track → kein gehaltener Amplitude-Driver mehr.
        controller.on_speech_started(audio_meta=None)
        assert controller.current_speaking_mouth(now=0.0) is None

    def test_missing_component_guarded(self, controller, renderer):
        # mouth_wide fehlt → Guard fällt auf mouth_neutral_close (§0.6).
        renderer.component_keys = frozenset({"mouth_neutral_close"})
        controller.set_speaking(True, audio_meta=self._wide_track())
        assert controller.current_speaking_mouth(now=0.0) == "mouth_neutral_close"


# ---------------------------------------------------------------------------
# current_idle_blink (Phase 83.6, Lock-gewrappte Idle/Blink-Overrides)
# ---------------------------------------------------------------------------


def _idle_policy() -> IdleBehaviorPolicy:
    """Deterministische Policy (min == max → kein Flake)."""
    return IdleBehaviorPolicy(
        idle_actions=[
            IdleAction("glance_left", "eye_left_side_open", "eye_right_side_open", None)
        ],
        can_blink={Emotion.NEUTRAL: True},
        attention_provider=NoopAttentionProvider(),
        idle_min=5.0,
        idle_max=5.0,
        idle_duration=2.0,
    )


class TestCurrentIdleBlink:
    def test_empty_without_policy(self, controller):
        """Ohne injizierte Policy → leere Overrides (kein Idle, kein Blink)."""
        assert controller.current_idle_blink(now=0.0) == IdleBlinkOverrides()

    def test_uses_injected_policy(self, renderer, state_machine):
        """Mit Policy liefert current_idle_blink deren frame_overrides."""
        ctrl = AvatarController(
            renderer=renderer, state_machine=state_machine, idle_policy=_idle_policy()
        )
        ctrl.current_idle_blink(now=0.0)  # lazy: plant Idle @5.0 (Mood NEUTRAL)
        ov = ctrl.current_idle_blink(now=5.0)
        assert ov.idle_eyes == ("eye_left_side_open", "eye_right_side_open")

    def test_idle_suppressed_while_speaking(self, renderer, state_machine):
        """Spricht der Avatar, liefert current_idle_blink kein Idle-Override."""
        ctrl = AvatarController(
            renderer=renderer, state_machine=state_machine, idle_policy=_idle_policy()
        )
        ctrl.on_speech_started()  # speaking_count > 0
        ctrl.current_idle_blink(now=0.0)
        ov = ctrl.current_idle_blink(now=5.0)
        assert ov.idle_eyes is None
