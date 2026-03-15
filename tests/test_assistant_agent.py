"""Tests: Assistant + AgentClient Integration."""
import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.agent.client import AgentClient
from elder_berry.agent.protocol import ActionResult, ApiResponse
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.core.assistant import Assistant, AssistantResult
from elder_berry.llm.base import LLMClient
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
    tts = MagicMock(spec=TTSEngine)
    tts.generate_audio.return_value = Path("/tmp/test.wav")
    return tts


@pytest.fixture
def character():
    return SaleriaEngine()


@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=AgentClient)
    agent.is_online.return_value = True
    agent.execute_action.return_value = ActionResult(
        success=True, action_type="press_key", message="OK",
    )
    agent.play_audio.return_value = ApiResponse(success=True, message="Audio abgespielt")
    agent.play_audio_file.return_value = ApiResponse(success=True, message="Audio abgespielt")
    return agent


@pytest.fixture
def assistant_with_agent(
    mock_llm, mock_db, mock_controller, mock_tts, character, mock_agent,
):
    """Assistant mit AgentClient (Laptop verbunden)."""
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
        character=character,
        agent=mock_agent,
    )


@pytest.fixture
def assistant_no_agent(mock_llm, mock_db, mock_controller, mock_tts, character):
    """Assistant ohne AgentClient."""
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
        character=character,
    )


# ---------------------------------------------------------------------------
# Agent-Routing: PC-Aktionen
# ---------------------------------------------------------------------------

class TestAgentActionRouting:
    def test_action_routed_to_agent(
        self, assistant_with_agent, mock_llm, mock_agent, mock_controller,
    ):
        mock_llm.generate.return_value = json.dumps({
            "action": "press_key",
            "params": {"key": "enter"},
            "response": "[neutral] Enter gedrückt.",
        })
        result = assistant_with_agent.process("Drücke Enter")
        assert result.action_success is True
        mock_agent.execute_action.assert_called_once_with("press_key", {"key": "enter"})
        mock_controller.press_key.assert_not_called()

    def test_action_local_without_agent(
        self, assistant_no_agent, mock_llm, mock_controller,
    ):
        mock_llm.generate.return_value = json.dumps({
            "action": "press_key",
            "params": {"key": "space"},
            "response": "[neutral] Space gedrückt.",
        })
        result = assistant_no_agent.process("Drücke Space")
        assert result.action_success is True
        mock_controller.press_key.assert_called_once_with("space")

    def test_agent_offline_falls_back_to_local(
        self, assistant_with_agent, mock_llm, mock_agent, mock_controller,
    ):
        mock_agent.is_online.return_value = False
        mock_llm.generate.return_value = json.dumps({
            "action": "set_volume",
            "params": {"level": 0.5},
            "response": "[neutral] Lautstärke auf 50%.",
        })
        result = assistant_with_agent.process("Lautstärke runter")
        assert result.action_success is True
        mock_agent.execute_action.assert_not_called()
        mock_controller.set_volume.assert_called_once_with(0.5)

    def test_agent_error_falls_back_to_local(
        self, assistant_with_agent, mock_llm, mock_agent, mock_controller,
    ):
        mock_agent.execute_action.side_effect = ConnectionError("timeout")
        mock_llm.generate.return_value = json.dumps({
            "action": "mute",
            "params": {"state": True},
            "response": "[neutral] Stummgeschaltet.",
        })
        result = assistant_with_agent.process("Stummschalten")
        assert result.action_success is True
        mock_controller.mute.assert_called_once_with(True)

    def test_agent_action_failure_reported(
        self, assistant_with_agent, mock_llm, mock_agent,
    ):
        mock_agent.execute_action.return_value = ActionResult(
            success=False, action_type="focus_window",
            message="Fenster nicht gefunden",
        )
        mock_llm.generate.return_value = json.dumps({
            "action": "focus_window",
            "params": {"title": "Notepad"},
            "response": "[neutral] Fokussiere Notepad.",
        })
        result = assistant_with_agent.process("Öffne Notepad")
        assert result.action_success is False

    def test_hotkey_routed_to_agent(
        self, assistant_with_agent, mock_llm, mock_agent,
    ):
        mock_llm.generate.return_value = json.dumps({
            "action": "hotkey",
            "params": {"keys": ["ctrl", "c"]},
            "response": "[neutral] Kopiert.",
        })
        result = assistant_with_agent.process("Kopiere")
        assert result.action_success is True
        mock_agent.execute_action.assert_called_once_with(
            "hotkey", {"keys": ["ctrl", "c"]},
        )


# ---------------------------------------------------------------------------
# Robot-Aktionen gehen NICHT über Agent
# ---------------------------------------------------------------------------

class TestRobotActionsNotRouted:
    def test_robot_drive_not_via_agent(
        self, mock_llm, mock_db, mock_controller, mock_tts, character,
        mock_agent,
    ):
        from elder_berry.robot.client import RobotClient
        from elder_berry.robot.protocol import ApiResponse as RobotApiResponse

        mock_robot = MagicMock(spec=RobotClient)
        mock_robot.is_online.return_value = True
        mock_robot.get_battery.return_value = MagicMock(
            percentage=80, voltage=7.2, is_low=False, is_charging=False,
        )
        mock_robot.drive.return_value = RobotApiResponse(
            success=True, message="Fahre",
        )
        mock_robot.set_emotion.return_value = RobotApiResponse(
            success=True, message="ok",
        )
        mock_robot.set_speaking.return_value = RobotApiResponse(
            success=True, message="ok",
        )

        assistant = Assistant(
            llm=mock_llm, actions_db=mock_db, controller=mock_controller,
            tts=mock_tts, character=character,
            robot=mock_robot, agent=mock_agent,
        )

        mock_llm.generate.return_value = json.dumps({
            "action": "robot_drive",
            "params": {"direction": "forward", "speed": 0.7},
            "response": "[motivated] Los!",
        })
        result = assistant.process("Fahr")
        assert result.action_success is True
        mock_robot.drive.assert_called_once_with("forward", 0.7)
        mock_agent.execute_action.assert_not_called()


# ---------------------------------------------------------------------------
# TTS via Agent
# ---------------------------------------------------------------------------

class TestTTSViaAgent:
    def test_audio_sent_to_agent(
        self, assistant_with_agent, mock_llm, mock_agent, mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {},
            "response": "[cheerful] Hallo!",
        })
        # generate_audio schreibt eine Datei → wir simulieren das
        mock_tts.generate_audio.return_value = Path("/tmp/test.wav")

        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant_with_agent.process("Hi")

        mock_tts.generate_audio.assert_called_once()
        mock_agent.play_audio_file.assert_called_once()
        # Lokales speak darf NICHT aufgerufen werden
        mock_tts.speak.assert_not_called()

    def test_audio_local_without_agent(
        self, assistant_no_agent, mock_llm, mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {},
            "response": "[neutral] Hallo!",
        })
        assistant_no_agent.process("Hi")
        mock_tts.speak.assert_called_once_with("Hallo!", emotion="neutral")
        mock_tts.generate_audio.assert_not_called()

    def test_audio_fallback_when_generate_not_supported(
        self, assistant_with_agent, mock_llm, mock_agent, mock_tts,
    ):
        mock_tts.generate_audio.side_effect = NotImplementedError("nicht verfügbar")
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {},
            "response": "[sarcastic] Na toll.",
        })
        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant_with_agent.process("Test")
        mock_tts.speak.assert_called_once_with("Na toll.", emotion="sarcastic")
        mock_agent.play_audio_file.assert_not_called()

    def test_audio_agent_offline_plays_locally(
        self, assistant_with_agent, mock_llm, mock_agent, mock_tts,
    ):
        mock_agent.is_online.return_value = False
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {},
            "response": "[neutral] Hallo.",
        })
        assistant_with_agent.process("Hi")
        mock_tts.speak.assert_called_once_with("Hallo.", emotion="neutral")
        mock_tts.generate_audio.assert_not_called()

    def test_emotion_passed_to_agent_audio(
        self, assistant_with_agent, mock_llm, mock_agent, mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps({
            "action": None, "params": {},
            "response": "[angry] Nerv mich nicht!",
        })
        mock_tts.generate_audio.return_value = Path("/tmp/angry.wav")

        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant_with_agent.process("Test")

        # Prüfe dass emotion an play_audio_file übergeben wird
        play_call = mock_agent.play_audio_file.call_args
        assert play_call.kwargs.get("emotion") == "angry" or \
               (len(play_call.args) > 1 and play_call.args[1] == "angry")


# ---------------------------------------------------------------------------
# Rückwärtskompatibilität
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    def test_assistant_works_without_agent_param(
        self, mock_llm, mock_db, mock_controller,
    ):
        """Assistant funktioniert wie bisher wenn kein agent übergeben wird."""
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
        )
        mock_llm.generate.return_value = json.dumps({
            "action": "press_key",
            "params": {"key": "enter"},
            "response": "Enter gedrückt.",
        })
        result = assistant.process("Enter")
        assert result.action_success is True
        mock_controller.press_key.assert_called_once_with("enter")

    def test_unknown_action_still_fails(
        self, assistant_with_agent, mock_llm, mock_agent,
    ):
        mock_agent.execute_action.return_value = ActionResult(
            success=False, action_type="unknown",
            message="Unbekannte Aktion",
        )
        mock_llm.generate.return_value = json.dumps({
            "action": "fly_to_moon",
            "params": {},
            "response": "[neutral] Das geht nicht.",
        })
        result = assistant_with_agent.process("Flieg zum Mond")
        # Agent gibt False zurück → Ergebnis ist False
        assert result.action_success is False
