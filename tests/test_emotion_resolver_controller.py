"""E2E-Akzeptanz Phase 83.5: EmotionResolver → AvatarController → StateMachine.

Bildet den logischen Datenfluss aus §7-83.5 ab: eine getaggte LLM-Antwort wird
vom Resolver zu einer ``EmotionDecision`` (Confidence ≥ 0.7) aggregiert; diese
Decision an den ``AvatarController`` gereicht triggert in der StateMachine den
Übergang von NEUTRAL. Der REST-Transport (Bot → RPi5) ist additiv und trägt die
Decision nur fürs Logging (§6.3); hier wird daher der Controller direkt
bedient – so wie alle Avatar-Integrationstests dieser Phase.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.avatar.avatar_config_loader import EmotionLayers
from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.controller import AvatarController
from elder_berry.avatar.state_machine import AvatarStateMachine
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionResolver
from elder_berry.character.saleria import SaleriaEngine


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
def resolver() -> EmotionResolver:
    engine = SaleriaEngine()
    return EmotionResolver(character=engine, emotion_tracker=engine.emotion_tracker)


@pytest.fixture
def renderer() -> MagicMock:
    return MagicMock(spec=AvatarRenderer)


@pytest.fixture
def state_machine() -> AvatarStateMachine:
    return AvatarStateMachine(emotion_map=_emotion_map())


@pytest.fixture
def controller(renderer, state_machine) -> AvatarController:
    return AvatarController(renderer=renderer, state_machine=state_machine)


class TestResolverToController:
    def test_cheerful_tag_yields_confidence_0_7(self, resolver):
        decision = resolver.resolve_from_llm("[cheerful] Hi")
        assert decision.emotion is Emotion.CHEERFUL
        # Tag + leerer Tracker = exakt 0.7 (§0.7).
        assert decision.confidence == pytest.approx(0.7)
        assert decision.confidence >= 0.7
        assert decision.source == "llm_tag"

    def test_decision_triggers_transition_from_neutral(
        self, resolver, controller, state_machine, renderer
    ):
        # Ausgangslage: NEUTRAL, keine Transition.
        assert state_machine.state.emotion is Emotion.NEUTRAL
        assert not state_machine.is_in_transition(state_machine.state.last_change)

        decision = resolver.resolve_from_llm("[cheerful] Hi")
        controller.on_emotion_decision(decision)

        # Übergang von NEUTRAL → CHEERFUL ist angestoßen.
        assert state_machine.state.emotion is Emotion.CHEERFUL
        assert state_machine.state.previous_emotion is Emotion.NEUTRAL
        # NEUTRAL→CHEERFUL ist kein direct_cut_pair → Crossfade läuft.
        assert state_machine.is_in_transition(state_machine.state.last_change)
        renderer.show_emotion.assert_called_once_with(Emotion.CHEERFUL)
