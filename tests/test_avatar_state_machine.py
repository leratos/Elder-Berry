"""Tests für AvatarStateMachine – Emotion, Sprech-Zähler, Layer-Plan (Phase 83.2)."""

from __future__ import annotations

from elder_berry.avatar.avatar_config_loader import EmotionLayers
from elder_berry.avatar.state_machine import (
    DEFAULT_CROSSFADE_FRAMES,
    DEFAULT_DIRECT_CUT_PAIRS,
    AvatarStateMachine,
)
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision


def _layers(body: str) -> EmotionLayers:
    return EmotionLayers(
        body=body,
        eye_left=f"eye_left_{body}",
        eye_right=f"eye_right_{body}",
        mouth=f"mouth_{body}",
        can_blink=True,
    )


def _emotion_map() -> dict[Emotion, EmotionLayers]:
    return {
        Emotion.NEUTRAL: _layers("relaxed"),
        Emotion.ANGRY: _layers("angry"),
        Emotion.CHEERFUL: _layers("welcome"),
        Emotion.SAD: _layers("shy"),
    }


def _decision(emotion: Emotion) -> EmotionDecision:
    return EmotionDecision(emotion, 1.0, "test", {})


def _sm() -> AvatarStateMachine:
    return AvatarStateMachine(emotion_map=_emotion_map())


# ---------------------------------------------------------------------------
# Init / Defaults
# ---------------------------------------------------------------------------


class TestStateMachineInit:
    def test_initial_emotion_neutral(self):
        assert _sm().state.emotion is Emotion.NEUTRAL

    def test_initial_speaking_count_zero(self):
        sm = _sm()
        assert sm.state.speaking_count == 0
        assert sm.is_speaking() is False

    def test_crossfade_frames_default(self):
        assert _sm().crossfade_frames == DEFAULT_CROSSFADE_FRAMES == 8

    def test_crossfade_frames_override(self):
        sm = AvatarStateMachine(emotion_map=_emotion_map(), crossfade_frames=12)
        assert sm.crossfade_frames == 12


# ---------------------------------------------------------------------------
# request_emotion
# ---------------------------------------------------------------------------


class TestRequestEmotion:
    def test_changes_emotion(self):
        sm = _sm()
        sm.request_emotion(_decision(Emotion.ANGRY))
        assert sm.state.emotion is Emotion.ANGRY

    def test_change_updates_last_change(self):
        sm = _sm()
        assert sm.state.last_change == 0.0
        sm.request_emotion(_decision(Emotion.ANGRY))
        assert sm.state.last_change > 0.0

    def test_same_emotion_is_idempotent(self):
        sm = _sm()
        sm.request_emotion(_decision(Emotion.ANGRY))
        stamp = sm.state.last_change
        sm.request_emotion(_decision(Emotion.ANGRY))  # gleiche Emotion
        assert sm.state.last_change == stamp  # kein erneutes Update

    def test_sequence_of_changes(self):
        sm = _sm()
        for emotion in (Emotion.CHEERFUL, Emotion.ANGRY, Emotion.SAD):
            sm.request_emotion(_decision(emotion))
            assert sm.state.emotion is emotion


# ---------------------------------------------------------------------------
# Sprech-Zähler (Counter statt Boolean, Race-Fix §2.3 #9)
# ---------------------------------------------------------------------------


class TestSpeakingCounter:
    def test_increment_sets_speaking(self):
        sm = _sm()
        sm.speech_increment()
        assert sm.state.speaking_count == 1
        assert sm.is_speaking() is True

    def test_single_increment_decrement_round_trip(self):
        sm = _sm()
        sm.speech_increment()
        sm.speech_decrement()
        assert sm.state.speaking_count == 0
        assert sm.is_speaking() is False

    def test_overlapping_increments(self):
        """Zwei Starts → erst nach zwei Enden hört der Avatar auf zu sprechen."""
        sm = _sm()
        sm.speech_increment()
        sm.speech_increment()
        assert sm.state.speaking_count == 2
        assert sm.is_speaking() is True

        sm.speech_decrement()
        assert sm.state.speaking_count == 1
        assert sm.is_speaking() is True  # noch nicht fertig

        sm.speech_decrement()
        assert sm.state.speaking_count == 0
        assert sm.is_speaking() is False

    def test_decrement_clamped_at_zero(self):
        sm = _sm()
        sm.speech_decrement()  # unter 0 nicht möglich
        sm.speech_decrement()
        assert sm.state.speaking_count == 0
        assert sm.is_speaking() is False


# ---------------------------------------------------------------------------
# direct_cut_pairs (in 83.2 reiner Datensatz)
# ---------------------------------------------------------------------------


class TestDirectCutPairs:
    def test_default_pairs_present(self):
        sm = _sm()
        assert sm.direct_cut_pairs is DEFAULT_DIRECT_CUT_PAIRS
        assert (Emotion.NEUTRAL, Emotion.ANGRY) in sm.direct_cut_pairs
        assert (Emotion.CHEERFUL, Emotion.ANGRY) in sm.direct_cut_pairs
        assert (Emotion.MOTIVATED, Emotion.ANGRY) in sm.direct_cut_pairs
        assert (Emotion.NEUTRAL, Emotion.SAD) in sm.direct_cut_pairs
        assert (Emotion.SHY, Emotion.ANGRY) in sm.direct_cut_pairs

    def test_default_pairs_count(self):
        assert len(DEFAULT_DIRECT_CUT_PAIRS) == 5

    def test_custom_pairs_accepted(self):
        custom = frozenset({(Emotion.SAD, Emotion.CHEERFUL)})
        sm = AvatarStateMachine(emotion_map=_emotion_map(), direct_cut_pairs=custom)
        assert sm.direct_cut_pairs == custom

    def test_default_pairs_not_mutated_between_instances(self):
        # Default ist ein geteiltes frozenset → unveränderlich, keine Cross-Talk.
        sm_a = _sm()
        sm_b = _sm()
        assert sm_a.direct_cut_pairs is sm_b.direct_cut_pairs


# ---------------------------------------------------------------------------
# current_layers → RenderPlan
# ---------------------------------------------------------------------------


class TestCurrentLayers:
    def test_returns_base_layers_for_current_emotion(self):
        sm = _sm()
        sm.request_emotion(_decision(Emotion.ANGRY))
        plan = sm.current_layers(now=0.0)
        assert plan.body == "angry"
        assert plan.eye_left == "eye_left_angry"
        assert plan.eye_right == "eye_right_angry"
        assert plan.mouth == "mouth_angry"

    def test_default_plan_is_opaque_no_offset(self):
        plan = _sm().current_layers(now=1.5)
        assert plan.alpha == 255
        assert plan.y_offset == 0

    def test_unmapped_emotion_falls_back_to_neutral(self):
        # Map ohne MOTIVATED; current_layers darf nicht crashen.
        sm = AvatarStateMachine(emotion_map={Emotion.NEUTRAL: _layers("relaxed")})
        sm.request_emotion(_decision(Emotion.MOTIVATED))
        plan = sm.current_layers(now=0.0)
        assert plan.body == "relaxed"  # NEUTRAL-Fallback


# ---------------------------------------------------------------------------
# Crossfade-Transition (Phase 83.3)
# ---------------------------------------------------------------------------


def _sm_fast() -> AvatarStateMachine:
    """SM mit duration = 10/10 = 1.0 s → exakte, float-stabile Progress-Punkte."""
    return AvatarStateMachine(emotion_map=_emotion_map(), crossfade_frames=10, fps=10)


def _start_transition(sm: AvatarStateMachine, emotion: Emotion) -> None:
    """Startet einen Crossfade und pinnt die Zeitbasis deterministisch auf 0.0."""
    sm.request_emotion(_decision(emotion))
    sm.state.last_change = 0.0  # now == Fortschritt in Sekunden == Progress


class TestTransitionStart:
    def test_non_direct_cut_starts_transition(self):
        sm = _sm_fast()
        # NEUTRAL → CHEERFUL ist KEIN direct_cut-Paar.
        _start_transition(sm, Emotion.CHEERFUL)
        assert sm.is_in_transition(now=0.0) is True
        assert sm.state.emotion is Emotion.CHEERFUL  # Ziel sofort gesetzt
        assert sm.state.previous_emotion is Emotion.NEUTRAL  # Fade-Quelle

    def test_transition_at_carries_both_bases(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        ts = sm.transition_at(now=0.5)
        assert ts.in_transition is True
        assert ts.previous.body == "relaxed"  # NEUTRAL-Basis (opak)
        assert ts.previous.alpha == 255
        assert ts.current.body == "welcome"  # CHEERFUL-Basis (gefadet)


class TestDirectCutActive:
    def test_direct_cut_pair_is_hard(self):
        sm = _sm_fast()
        # NEUTRAL → ANGRY IST ein direct_cut-Paar → harter Schnitt.
        sm.request_emotion(_decision(Emotion.ANGRY))
        assert sm.is_in_transition(now=sm.state.last_change) is False
        assert sm.state.emotion is Emotion.ANGRY
        assert sm.state.previous_emotion is Emotion.ANGRY  # previous == emotion
        ts = sm.transition_at(now=sm.state.last_change)
        assert ts.in_transition is False
        assert ts.current.body == "angry"
        assert ts.previous.body == "angry"

    def test_reverse_of_pair_crossfades(self):
        sm = _sm_fast()
        sm.request_emotion(_decision(Emotion.ANGRY))  # harter Schnitt nach ANGRY
        # ANGRY → NEUTRAL ist NICHT als Paar gelistet → Crossfade.
        sm.request_emotion(_decision(Emotion.NEUTRAL))
        sm.state.last_change = 0.0
        assert sm.is_in_transition(now=0.0) is True
        assert sm.state.previous_emotion is Emotion.ANGRY


class TestTransitionProgress:
    def test_alpha_zero_at_start(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        assert sm.transition_at(now=0.0).current.alpha == 0

    def test_alpha_quarter(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        assert sm.transition_at(now=0.25).current.alpha == 64  # round(255*0.25)

    def test_alpha_half(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        assert sm.transition_at(now=0.5).current.alpha == 128  # round(255*0.5)

    def test_alpha_monotonic_non_decreasing(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        alphas = [sm.transition_at(now=t / 10).current.alpha for t in range(11)]
        assert alphas == sorted(alphas)
        assert alphas[0] == 0

    def test_transition_ends_at_full_progress(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        ts = sm.transition_at(now=1.0)  # progress == 1.0
        assert ts.in_transition is False
        assert ts.current.alpha == 255  # opak, Transition vorbei
        assert ts.current.body == "welcome"

    def test_transition_clamped_after_end(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        assert sm.is_in_transition(now=5.0) is False  # weit nach Ende

    def test_zero_fps_disables_crossfade(self):
        # fps <= 0 -> _progress liefert sofort 1.0 -> keine Transition (Guard).
        sm = AvatarStateMachine(emotion_map=_emotion_map(), fps=0)
        sm.request_emotion(_decision(Emotion.CHEERFUL))  # kein direct_cut-Paar
        sm.state.last_change = 0.0
        assert sm.is_in_transition(now=0.0) is False
        assert sm.transition_at(now=0.0).in_transition is False

    def test_zero_crossfade_frames_disables_crossfade(self):
        sm = AvatarStateMachine(emotion_map=_emotion_map(), crossfade_frames=0)
        sm.request_emotion(_decision(Emotion.CHEERFUL))
        sm.state.last_change = 0.0
        assert sm.is_in_transition(now=0.0) is False


class TestSameEmotionNoTransition:
    def test_same_emotion_no_transition(self):
        sm = _sm_fast()
        sm.request_emotion(_decision(Emotion.NEUTRAL))  # == aktuelle Emotion
        assert sm.is_in_transition(now=0.0) is False

    def test_same_emotion_keeps_previous_equal(self):
        sm = _sm_fast()
        sm.request_emotion(_decision(Emotion.NEUTRAL))
        assert sm.state.previous_emotion is sm.state.emotion


class TestCurrentLayersAlpha:
    def test_alpha_reflects_progress_during_transition(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)
        plan = sm.current_layers(now=0.5)
        assert plan.body == "welcome"  # Ziel-Emotion
        assert plan.alpha == 128

    def test_opaque_outside_transition(self):
        sm = _sm_fast()
        sm.request_emotion(_decision(Emotion.ANGRY))  # harter Schnitt
        plan = sm.current_layers(now=sm.state.last_change)
        assert plan.alpha == 255


class TestMidTransitionRequest:
    def test_new_request_restarts_from_target(self):
        sm = _sm_fast()
        _start_transition(sm, Emotion.CHEERFUL)  # NEUTRAL → CHEERFUL
        # Mitten im Fade (Progress 0.5) eine neue Decision: CHEERFUL → SAD
        # (kein direct_cut-Paar) → frische Transition von CHEERFUL aus.
        sm.request_emotion(_decision(Emotion.SAD))
        assert sm.state.emotion is Emotion.SAD
        assert sm.state.previous_emotion is Emotion.CHEERFUL
