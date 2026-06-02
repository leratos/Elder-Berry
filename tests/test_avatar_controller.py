"""Tests für AvatarController – Legacy- und semantischer Pfad (Phase 83.2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.avatar.avatar_config_loader import EmotionLayers
from elder_berry.avatar.base import AvatarRenderer
from elder_berry.avatar.controller import AvatarController
from elder_berry.avatar.state_machine import AvatarStateMachine
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision
from elder_berry.robot.server import AvatarDisplay


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

    def test_on_speech_started_accepts_audio_meta_stub(self, controller):
        # 83.4-Stub: audio_meta wird in 83.2 ignoriert, darf aber übergeben werden.
        controller.on_speech_started(audio_meta={"amplitude": [0.1, 0.2]})
        assert controller.get_state()["speaking"] is True

    def test_current_layers_reflects_emotion(self, controller):
        controller.on_emotion_decision(EmotionDecision(Emotion.ANGRY, 0.9, "llm_tag", {}))
        plan = controller.current_layers(now=0.0)
        assert plan.body == "angry"
