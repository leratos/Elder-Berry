"""Tests: Assistant + RobotClient Integration."""

import json
from unittest.mock import MagicMock

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.core.assistant import Assistant
from elder_berry.llm.base import LLMClient
from elder_berry.robot.client import RobotClient
from elder_berry.robot.protocol import ApiResponse, BatteryStatus
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
def mock_robot():
    robot = MagicMock(spec=RobotClient)
    robot.is_online.return_value = True
    robot.get_battery.return_value = BatteryStatus(
        voltage=7.2,
        percentage=80,
        is_charging=False,
        is_low=False,
    )
    robot.drive.return_value = ApiResponse(success=True, message="Fahre forward")
    robot.stop.return_value = ApiResponse(success=True, message="Gestoppt")
    robot.set_emotion.return_value = ApiResponse(success=True, message="ok")
    robot.set_speaking.return_value = ApiResponse(success=True, message="ok")
    return robot


@pytest.fixture
def character():
    return SaleriaEngine()


@pytest.fixture
def assistant_with_robot(
    mock_llm,
    mock_db,
    mock_controller,
    mock_tts,
    character,
    mock_robot,
):
    """Assistant mit allen Komponenten inkl. RobotClient."""
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
        character=character,
        robot=mock_robot,
    )


@pytest.fixture
def assistant_no_robot(mock_llm, mock_db, mock_controller, mock_tts, character):
    """Assistant ohne RobotClient."""
    return Assistant(
        llm=mock_llm,
        actions_db=mock_db,
        controller=mock_controller,
        tts=mock_tts,
        character=character,
    )


# ---------------------------------------------------------------------------
# Robot-Aktionen: robot_drive
# ---------------------------------------------------------------------------


class TestRobotDrive:
    def test_drive_forward(self, assistant_with_robot, mock_llm, mock_robot):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_drive",
                "params": {"direction": "forward", "speed": 0.8},
                "response": "[motivated] Los geht's!",
            }
        )
        result = assistant_with_robot.process("Fahr vorwärts")
        assert result.action_executed == "robot_drive"
        assert result.action_success is True
        mock_robot.drive.assert_called_once_with("forward", 0.8)

    def test_drive_defaults(self, assistant_with_robot, mock_llm, mock_robot):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_drive",
                "params": {},
                "response": "[neutral] Fahre.",
            }
        )
        assistant_with_robot.process("Fahr")
        mock_robot.drive.assert_called_once_with("forward", 0.5)

    def test_drive_without_robot(self, assistant_no_robot, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_drive",
                "params": {"direction": "left"},
                "response": "[neutral] Kann nicht fahren.",
            }
        )
        result = assistant_no_robot.process("Fahr links")
        assert result.action_executed == "robot_drive"
        assert result.action_success is False

    def test_drive_robot_error(self, assistant_with_robot, mock_llm, mock_robot):
        mock_robot.drive.side_effect = ConnectionError("offline")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_drive",
                "params": {"direction": "forward"},
                "response": "[sad] Verbindung verloren.",
            }
        )
        result = assistant_with_robot.process("Fahr")
        assert result.action_success is False


# ---------------------------------------------------------------------------
# Robot-Aktionen: robot_stop
# ---------------------------------------------------------------------------


class TestRobotStop:
    def test_stop(self, assistant_with_robot, mock_llm, mock_robot):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_stop",
                "params": {"reason": "hindernis"},
                "response": "[neutral] Gestoppt.",
            }
        )
        result = assistant_with_robot.process("Stopp!")
        assert result.action_success is True
        mock_robot.stop.assert_called_once_with("hindernis")

    def test_stop_default_reason(self, assistant_with_robot, mock_llm, mock_robot):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_stop",
                "params": {},
                "response": "[neutral] Halt.",
            }
        )
        assistant_with_robot.process("Halt")
        mock_robot.stop.assert_called_once_with("manual")

    def test_stop_without_robot(self, assistant_no_robot, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_stop",
                "params": {},
                "response": "[neutral] Kein Roboter.",
            }
        )
        result = assistant_no_robot.process("Stopp")
        assert result.action_success is False


# ---------------------------------------------------------------------------
# Emotion-Sync zum RPi5
# ---------------------------------------------------------------------------


class TestEmotionSync:
    def test_emotion_synced_to_robot(self, assistant_with_robot, mock_llm, mock_robot):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[angry] Das nervt!",
            }
        )
        assistant_with_robot.process("Test")
        mock_robot.set_emotion.assert_called_once_with("angry")

    def test_emotion_not_synced_without_robot(self, assistant_no_robot, mock_llm):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[cheerful] Super!",
            }
        )
        # Kein Crash ohne Robot
        result = assistant_no_robot.process("Test")
        assert result.emotion == "cheerful"

    def test_emotion_sync_error_no_crash(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
    ):
        mock_robot.set_emotion.side_effect = ConnectionError("offline")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[sarcastic] Ach wirklich?",
            }
        )
        result = assistant_with_robot.process("Test")
        assert result.emotion == "sarcastic"
        assert result.response == "Ach wirklich?"


# ---------------------------------------------------------------------------
# Speaking-Sync zum RPi5
# ---------------------------------------------------------------------------


class TestSpeakingSync:
    def test_speaking_synced_to_robot(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
        mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] Hallo",
            }
        )
        assistant_with_robot.process("Hi")
        calls = mock_robot.set_speaking.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] is True
        assert calls[1].args[0] is False

    def test_speaking_false_on_tts_error(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
        mock_tts,
    ):
        mock_tts.speak.side_effect = RuntimeError("TTS kaputt")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] Test",
            }
        )
        assistant_with_robot.process("Test")
        last_call = mock_robot.set_speaking.call_args_list[-1]
        assert last_call.args[0] is False

    def test_speaking_sync_error_no_crash(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
        mock_tts,
    ):
        mock_robot.set_speaking.side_effect = ConnectionError("offline")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] Hallo",
            }
        )
        # Kein Crash trotz Robot-Fehler
        result = assistant_with_robot.process("Hi")
        assert result.response == "Hallo"


# ---------------------------------------------------------------------------
# System-Prompt: Robot-Status
# ---------------------------------------------------------------------------


class TestRobotStatusInPrompt:
    def test_prompt_contains_battery_status(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] ok",
            }
        )
        assistant_with_robot.process("Status?")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system",
            mock_llm.generate.call_args[1].get("system", ""),
        )
        assert "ONLINE" in system_prompt
        assert "80%" in system_prompt
        assert "7.2V" in system_prompt

    def test_prompt_battery_low_warning(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
    ):
        mock_robot.get_battery.return_value = BatteryStatus(
            voltage=6.2,
            percentage=15,
            is_low=True,
        )
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] ok",
            }
        )
        assistant_with_robot.process("Status?")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system",
            mock_llm.generate.call_args[1].get("system", ""),
        )
        assert "WARNUNG" in system_prompt
        assert "Ladestation" in system_prompt

    def test_prompt_robot_offline(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
    ):
        mock_robot.is_online.return_value = False
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] ok",
            }
        )
        assistant_with_robot.process("Status?")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system",
            mock_llm.generate.call_args[1].get("system", ""),
        )
        assert "OFFLINE" in system_prompt

    def test_prompt_no_robot_no_status(
        self,
        assistant_no_robot,
        mock_llm,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] ok",
            }
        )
        assistant_no_robot.process("Test")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system",
            mock_llm.generate.call_args[1].get("system", ""),
        )
        assert "Roboter-Status" not in system_prompt

    def test_prompt_robot_connection_error(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
    ):
        mock_robot.is_online.side_effect = ConnectionError("timeout")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] ok",
            }
        )
        assistant_with_robot.process("Test")
        system_prompt = mock_llm.generate.call_args.kwargs.get(
            "system",
            mock_llm.generate.call_args[1].get("system", ""),
        )
        assert "OFFLINE" in system_prompt
        assert "fehlgeschlagen" in system_prompt


# ---------------------------------------------------------------------------
# Voller Flow: Robot + Emotion + TTS
# ---------------------------------------------------------------------------


class TestFullRobotFlow:
    def test_drive_with_emotion_and_tts(
        self,
        assistant_with_robot,
        mock_llm,
        mock_robot,
        mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_drive",
                "params": {"direction": "forward", "speed": 0.6},
                "response": "[motivated] Auf geht's, vorwärts!",
            }
        )
        result = assistant_with_robot.process("Fahr los")
        assert result.action_executed == "robot_drive"
        assert result.action_success is True
        assert result.emotion == "motivated"
        assert result.response == "Auf geht's, vorwärts!"
        mock_robot.drive.assert_called_once_with("forward", 0.6)
        mock_robot.set_emotion.assert_called_once_with("motivated")
        mock_tts.speak.assert_called_once_with(
            "Auf geht's, vorwärts!",
            emotion="motivated",
        )

    def test_existing_actions_still_work(
        self,
        assistant_with_robot,
        mock_llm,
        mock_controller,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "press_key",
                "params": {"key": "enter"},
                "response": "[neutral] Enter gedrückt.",
            }
        )
        result = assistant_with_robot.process("Drücke Enter")
        assert result.action_success is True
        mock_controller.press_key.assert_called_once_with("enter")
