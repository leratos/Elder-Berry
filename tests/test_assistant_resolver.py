"""Tests: Assistant ⇄ EmotionResolver-Anbindung (Phase 83.5).

Deckt den opt-in-Pfad ab: bei gesetztem ``emotion_resolver`` leitet
``process()`` die Emotion über ``resolve_from_llm`` ab (statt
``extract_emotion``), reicht die ``EmotionDecision`` additiv an den Robot
weiter und aktualisiert den Avatar. Ohne Resolver bleibt der heutige
``extract_emotion``-Pfad (1-armiger ``set_emotion``) unverändert – die
bestehenden Assistant-/Robot-Tests bleiben damit grün.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.character.base import Emotion
from elder_berry.character.emotion_resolver import EmotionDecision, EmotionResolver
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.core.assistant import Assistant
from elder_berry.llm.base import LLMClient
from elder_berry.robot.client import RobotClient
from elder_berry.robot.protocol import ApiResponse
from elder_berry.tts.base import TTSEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def mock_db(tmp_path):
    return ActionsDB(db_path=tmp_path / "test.db")


@pytest.fixture
def mock_controller():
    return MagicMock(spec=ActionController)


@pytest.fixture
def mock_tts():
    return MagicMock(spec=TTSEngine)


@pytest.fixture
def mock_avatar():
    return MagicMock()


@pytest.fixture
def mock_robot():
    robot = MagicMock(spec=RobotClient)
    robot.set_emotion.return_value = ApiResponse(success=True, message="ok")
    robot.set_speaking.return_value = ApiResponse(success=True, message="ok")
    return robot


@pytest.fixture
def character():
    return SaleriaEngine()


@pytest.fixture
def resolver(character):
    return EmotionResolver(
        character=character,
        emotion_tracker=character.emotion_tracker,
    )


def _make_assistant(
    *, llm, db, controller, tts, character, robot=None, avatar=None, resolver=None
):
    return Assistant(
        llm=llm,
        actions_db=db,
        controller=controller,
        tts=tts,
        character=character,
        avatar=avatar,
        robot=robot,
        emotion_resolver=resolver,
    )


def _llm_returns(mock_llm, response: str) -> None:
    mock_llm.generate.return_value = json.dumps(
        {"action": None, "params": {}, "response": response}
    )


# ---------------------------------------------------------------------------
# Resolver-Pfad (opt-in)
# ---------------------------------------------------------------------------


class TestResolverPath:
    def test_decision_forwarded_to_robot(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, mock_robot, resolver
    ):
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            robot=mock_robot,
            resolver=resolver,
        )
        _llm_returns(mock_llm, "[cheerful] Hi")
        result = assistant.process("Hallo")

        assert result.emotion == "cheerful"
        # set_emotion bekommt die Emotion als String PLUS die Decision (additiv).
        call = mock_robot.set_emotion.call_args
        assert call.args == ("cheerful",)
        decision = call.kwargs["decision"]
        assert isinstance(decision, EmotionDecision)
        assert decision.emotion is Emotion.CHEERFUL
        assert decision.confidence == pytest.approx(0.7)
        assert decision.source == "llm_tag"

    def test_avatar_shows_resolved_emotion(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, mock_avatar, resolver
    ):
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            avatar=mock_avatar,
            resolver=resolver,
        )
        _llm_returns(mock_llm, "[angry] Grr")
        assistant.process("Test")
        mock_avatar.show_emotion.assert_called_once_with(Emotion.ANGRY)

    def test_resolver_used_not_extract_emotion(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, resolver
    ):
        # extract_emotion darf im Resolver-Pfad NICHT aufgerufen werden.
        character.extract_emotion = MagicMock(  # type: ignore[method-assign]
            wraps=character.extract_emotion
        )
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            resolver=resolver,
        )
        _llm_returns(mock_llm, "[cheerful] Hi")
        assistant.process("Hallo")
        character.extract_emotion.assert_not_called()

    def test_b4_recorded_series_identical_for_tagged_turn(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, resolver
    ):
        # Bei vorhandenem Tag: set_mood + tracker.record wie heute (B4).
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            resolver=resolver,
        )
        _llm_returns(mock_llm, "[cheerful] Hi")
        assistant.process("Hallo")

        assert character.get_mood().current_emotion is Emotion.CHEERFUL
        assert character.emotion_tracker.entry_count == 1
        dom, _ = character.emotion_tracker.dominant_with_confidence()
        assert dom is Emotion.CHEERFUL

    def test_no_tag_empty_tracker_is_neutral(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, resolver
    ):
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            resolver=resolver,
        )
        _llm_returns(mock_llm, "Einfach nur Text ohne Tag.")
        result = assistant.process("Hallo")

        assert result.emotion == "neutral"
        # Kein Tag → kein record/set_mood.
        assert character.emotion_tracker.entry_count == 0

    def test_no_tag_with_trend_surfaces_trend_emotion(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, resolver
    ):
        # Bewusste Verhaltensänderung (§0.3, mit Lera bestätigt): ohne Tag, aber
        # mit gefülltem Tracker liefert der Resolver die Trend-Emotion (statt
        # heute NEUTRAL) bei niedriger Confidence – ohne neuen record (kein Tag).
        character.emotion_tracker.record(Emotion.CHEERFUL)
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            resolver=resolver,
        )
        _llm_returns(mock_llm, "Text ohne Tag.")
        result = assistant.process("Hallo")

        assert result.emotion == "cheerful"
        # Kein zusätzlicher record (Tag fehlt) – Tracker bleibt bei 1 Eintrag.
        assert character.emotion_tracker.entry_count == 1


# ---------------------------------------------------------------------------
# Legacy-Pfad (kein Resolver) – Rückwärtskompatibilität
# ---------------------------------------------------------------------------


class TestLegacyPathUnchanged:
    def test_set_emotion_called_one_arg_without_resolver(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, mock_robot
    ):
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            robot=mock_robot,
            resolver=None,
        )
        _llm_returns(mock_llm, "[angry] Das nervt!")
        result = assistant.process("Test")

        assert result.emotion == "angry"
        # Ohne Resolver bleibt der Aufruf 1-armig (keine decision-kwargs).
        mock_robot.set_emotion.assert_called_once_with("angry")

    def test_extract_emotion_records_without_resolver(
        self, mock_llm, mock_db, mock_controller, mock_tts, character
    ):
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            resolver=None,
        )
        _llm_returns(mock_llm, "[cheerful] Hi")
        assistant.process("Hallo")
        # extract_emotion zeichnet wie bisher auf.
        assert character.get_mood().current_emotion is Emotion.CHEERFUL
        assert character.emotion_tracker.entry_count == 1

    def test_weak_intensity_synthesizes_decision_without_resolver(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, mock_robot
    ):
        # Phase 109: ohne Resolver bekommt der Roboter bei schwacher Intensität
        # trotzdem die (gleich skalierte) Confidence -> Gate hält die Emotion.
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            robot=mock_robot,
            resolver=None,
        )
        _llm_returns(mock_llm, "[angry:0.4] etwas genervt")
        assistant.process("Test")

        call = mock_robot.set_emotion.call_args
        assert call.args == ("angry",)
        decision = call.kwargs["decision"]
        assert isinstance(decision, EmotionDecision)
        # Modell B: getaggt → volle Confidence (schaltet), Intensität = Tiefe.
        assert decision.confidence == pytest.approx(1.0)
        assert decision.intensity == pytest.approx(0.4)
        assert decision.source == "legacy_intensity"

    def test_full_intensity_stays_one_arg_without_resolver(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, mock_robot
    ):
        # Bare Tag (volle Intensität) bleibt 1-armig -- byte-identisch zu früher.
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            robot=mock_robot,
            resolver=None,
        )
        _llm_returns(mock_llm, "[cheerful] Hi")
        assistant.process("Hallo")
        mock_robot.set_emotion.assert_called_once_with("cheerful")

    def test_zero_intensity_not_synthesized_without_resolver(
        self, mock_llm, mock_db, mock_controller, mock_tts, character, mock_robot
    ):
        # [angry:0.0] = kein Signal → keine synthetisierte (confident) Decision,
        # sonst angry-State bei alpha-0-/Neutral-Render. 1-armig (decision=None).
        assistant = _make_assistant(
            llm=mock_llm,
            db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            robot=mock_robot,
            resolver=None,
        )
        _llm_returns(mock_llm, "[angry:0.0] egal")
        assistant.process("Test")
        mock_robot.set_emotion.assert_called_once_with("angry")
