"""Tests: Assistant + AgentClient Integration."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.actions.base import ActionController
from elder_berry.actions.db import ActionsDB
from elder_berry.agent.client import AgentClient
from elder_berry.agent.protocol import ActionResult, ApiResponse
from elder_berry.character.saleria import SaleriaEngine
from elder_berry.core.assistant import Assistant
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
        success=True,
        action_type="press_key",
        message="OK",
    )
    agent.play_audio.return_value = ApiResponse(
        success=True, message="Audio abgespielt"
    )
    agent.play_audio_file.return_value = ApiResponse(
        success=True, message="Audio abgespielt"
    )
    return agent


@pytest.fixture
def assistant_with_agent(
    mock_llm,
    mock_db,
    mock_controller,
    mock_tts,
    character,
    mock_agent,
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
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_controller,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "press_key",
                "params": {"key": "enter"},
                "response": "[neutral] Enter gedrückt.",
            }
        )
        result = assistant_with_agent.process("Drücke Enter")
        assert result.action_success is True
        mock_agent.execute_action.assert_called_once_with("press_key", {"key": "enter"})
        mock_controller.press_key.assert_not_called()

    def test_action_local_without_agent(
        self,
        assistant_no_agent,
        mock_llm,
        mock_controller,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "press_key",
                "params": {"key": "space"},
                "response": "[neutral] Space gedrückt.",
            }
        )
        result = assistant_no_agent.process("Drücke Space")
        assert result.action_success is True
        mock_controller.press_key.assert_called_once_with("space")

    def test_agent_offline_falls_back_to_local(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_controller,
    ):
        mock_agent.is_online.return_value = False
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "set_volume",
                "params": {"level": 0.5},
                "response": "[neutral] Lautstärke auf 50%.",
            }
        )
        result = assistant_with_agent.process("Lautstärke runter")
        assert result.action_success is True
        mock_agent.execute_action.assert_not_called()
        mock_controller.set_volume.assert_called_once_with(0.5)

    def test_agent_error_falls_back_to_local(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_controller,
    ):
        mock_agent.execute_action.side_effect = ConnectionError("timeout")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "mute",
                "params": {"state": True},
                "response": "[neutral] Stummgeschaltet.",
            }
        )
        result = assistant_with_agent.process("Stummschalten")
        assert result.action_success is True
        mock_controller.mute.assert_called_once_with(True)

    def test_agent_action_failure_reported(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
    ):
        mock_agent.execute_action.return_value = ActionResult(
            success=False,
            action_type="focus_window",
            message="Fenster nicht gefunden",
        )
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "focus_window",
                "params": {"title": "Notepad"},
                "response": "[neutral] Fokussiere Notepad.",
            }
        )
        result = assistant_with_agent.process("Öffne Notepad")
        assert result.action_success is False

    def test_hotkey_routed_to_agent(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "hotkey",
                "params": {"keys": ["ctrl", "c"]},
                "response": "[neutral] Kopiert.",
            }
        )
        result = assistant_with_agent.process("Kopiere")
        assert result.action_success is True
        mock_agent.execute_action.assert_called_once_with(
            "hotkey",
            {"keys": ["ctrl", "c"]},
        )


# ---------------------------------------------------------------------------
# Robot-Aktionen gehen NICHT über Agent
# ---------------------------------------------------------------------------


class TestRobotActionsNotRouted:
    def test_robot_drive_not_via_agent(
        self,
        mock_llm,
        mock_db,
        mock_controller,
        mock_tts,
        character,
        mock_agent,
    ):
        from elder_berry.robot.client import RobotClient
        from elder_berry.robot.protocol import ApiResponse as RobotApiResponse

        mock_robot = MagicMock(spec=RobotClient)
        mock_robot.is_online.return_value = True
        mock_robot.get_battery.return_value = MagicMock(
            percentage=80,
            voltage=7.2,
            is_low=False,
            is_charging=False,
        )
        mock_robot.drive.return_value = RobotApiResponse(
            success=True,
            message="Fahre",
        )
        mock_robot.set_emotion.return_value = RobotApiResponse(
            success=True,
            message="ok",
        )
        mock_robot.set_speaking.return_value = RobotApiResponse(
            success=True,
            message="ok",
        )

        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            robot=mock_robot,
            agent=mock_agent,
        )

        mock_llm.generate.return_value = json.dumps(
            {
                "action": "robot_drive",
                "params": {"direction": "forward", "speed": 0.7},
                "response": "[motivated] Los!",
            }
        )
        result = assistant.process("Fahr")
        assert result.action_success is True
        mock_robot.drive.assert_called_once_with("forward", 0.7)
        mock_agent.execute_action.assert_not_called()


# ---------------------------------------------------------------------------
# TTS via Agent
# ---------------------------------------------------------------------------


class TestTTSViaAgent:
    def test_audio_sent_to_agent(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[cheerful] Hallo!",
            }
        )
        # generate_audio schreibt eine Datei → wir simulieren das
        mock_tts.generate_audio.return_value = Path("/tmp/test.wav")

        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant_with_agent.process("Hi")

        mock_tts.generate_audio.assert_called_once()
        mock_agent.play_audio_file.assert_called_once()
        # Lokales speak darf NICHT aufgerufen werden
        mock_tts.speak.assert_not_called()

    def test_audio_local_without_agent(
        self,
        assistant_no_agent,
        mock_llm,
        mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] Hallo!",
            }
        )
        assistant_no_agent.process("Hi")
        mock_tts.speak.assert_called_once_with("Hallo!", emotion="neutral")
        mock_tts.generate_audio.assert_not_called()

    def test_audio_fallback_when_generate_not_supported(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_tts,
    ):
        mock_tts.generate_audio.side_effect = NotImplementedError("nicht verfügbar")
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[sarcastic] Na toll.",
            }
        )
        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant_with_agent.process("Test")
        mock_tts.speak.assert_called_once_with("Na toll.", emotion="sarcastic")
        mock_agent.play_audio_file.assert_not_called()

    def test_audio_agent_offline_plays_locally(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_tts,
    ):
        mock_agent.is_online.return_value = False
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[neutral] Hallo.",
            }
        )
        assistant_with_agent.process("Hi")
        mock_tts.speak.assert_called_once_with("Hallo.", emotion="neutral")
        mock_tts.generate_audio.assert_not_called()

    def test_emotion_passed_to_agent_audio(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
        mock_tts,
    ):
        mock_llm.generate.return_value = json.dumps(
            {
                "action": None,
                "params": {},
                "response": "[angry] Nerv mich nicht!",
            }
        )
        mock_tts.generate_audio.return_value = Path("/tmp/angry.wav")

        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant_with_agent.process("Test")

        # Prüfe dass emotion an play_audio_file übergeben wird
        play_call = mock_agent.play_audio_file.call_args
        assert play_call.kwargs.get("emotion") == "angry" or (
            len(play_call.args) > 1 and play_call.args[1] == "angry"
        )


# ---------------------------------------------------------------------------
# Rückwärtskompatibilität
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_assistant_works_without_agent_param(
        self,
        mock_llm,
        mock_db,
        mock_controller,
    ):
        """Assistant funktioniert wie bisher wenn kein agent übergeben wird."""
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
        )
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "press_key",
                "params": {"key": "enter"},
                "response": "Enter gedrückt.",
            }
        )
        result = assistant.process("Enter")
        assert result.action_success is True
        mock_controller.press_key.assert_called_once_with("enter")

    def test_unknown_action_still_fails(
        self,
        assistant_with_agent,
        mock_llm,
        mock_agent,
    ):
        mock_agent.execute_action.return_value = ActionResult(
            success=False,
            action_type="unknown",
            message="Unbekannte Aktion",
        )
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "fly_to_moon",
                "params": {},
                "response": "[neutral] Das geht nicht.",
            }
        )
        result = assistant_with_agent.process("Flieg zum Mond")
        # Agent gibt False zurück → Ergebnis ist False
        assert result.action_success is False


# ---------------------------------------------------------------------------
# Amplitude-Lip-Sync im Playback-Modus (Phase 83.4)
# ---------------------------------------------------------------------------


class TestAmplitudeLipSync:
    """Im Agent-Playback baut der Bot aus dem TTS-WAV den AmplitudeTrack und
    sendet ihn additiv an den RPi5 (§4.2/§7-83.4). Nur Playback-Modus (B1).
    """

    def _wav_bytes(self) -> bytes:
        import array
        import io
        import math
        import wave

        rate = 16000
        n = int(rate * 0.3)
        pcm = array.array(
            "h",
            (int(0.8 * math.sin(2 * math.pi * 220 * i / rate) * 32767) for i in range(n)),
        )
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    def test_amplitude_track_sent_to_robot(
        self, mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
    ):
        from elder_berry.core.audio_analyzer import AmplitudeTrack
        from elder_berry.robot.client import RobotClient

        wav = self._wav_bytes()

        def gen(text, out, emotion=None):
            Path(out).write_bytes(wav)
            return out

        mock_tts.generate_audio.side_effect = gen
        mock_robot = MagicMock(spec=RobotClient)
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            agent=mock_agent,
            robot=mock_robot,
        )
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Hallo"}
        )
        assistant.process("Hi")

        start_calls = [
            c
            for c in mock_robot.set_speaking.call_args_list
            if c.args and c.args[0] is True
        ]
        assert start_calls, "robot.set_speaking(True, ...) muss laufen"
        track = start_calls[0].kwargs.get("audio_meta")
        assert isinstance(track, AmplitudeTrack)
        assert not track.is_empty()
        # Audio wurde via Agent abgespielt (Datei-Pfad).
        mock_agent.play_audio_file.assert_called_once()

    def test_no_track_when_analyzer_unavailable(
        self, mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
    ):
        from elder_berry.robot.client import RobotClient

        # Analyzer liefert kein Profil (z.B. numpy fehlt / MP3) → kein Track.
        analyzer = MagicMock()
        analyzer.profile.return_value = None
        mock_robot = MagicMock(spec=RobotClient)
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            agent=mock_agent,
            robot=mock_robot,
            audio_analyzer=analyzer,
        )
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Hallo"}
        )
        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant.process("Hi")

        start_calls = [
            c
            for c in mock_robot.set_speaking.call_args_list
            if c.args and c.args[0] is True
        ]
        assert start_calls
        assert start_calls[0].kwargs.get("audio_meta") is None

    def _robot_assistant(self, mock_llm, mock_db, mock_controller, character,
                         mock_agent, mock_tts, **kw):
        from elder_berry.robot.client import RobotClient

        mock_robot = MagicMock(spec=RobotClient)
        assistant = Assistant(
            llm=mock_llm,
            actions_db=mock_db,
            controller=mock_controller,
            tts=mock_tts,
            character=character,
            agent=mock_agent,
            robot=mock_robot,
            **kw,
        )
        mock_llm.generate.return_value = json.dumps(
            {"action": None, "params": {}, "response": "[neutral] Hallo"}
        )
        return assistant, mock_robot

    def test_mp3_output_not_sent_to_wav_only_agent(
        self, mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
    ):
        # TTSRouter/ElevenLabs gibt eine .mp3 zurück → NICHT an den WAV-Agent;
        # stattdessen lokal via speak(), kein Amplitude-Track (Codex P2).
        mock_tts.generate_audio.return_value = Path("/tmp/voice.mp3")
        assistant, mock_robot = self._robot_assistant(
            mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
        )
        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant.process("Hi")
        mock_agent.play_audio_file.assert_not_called()
        mock_tts.speak.assert_called_once_with("Hallo", emotion="neutral")
        start = [
            c for c in mock_robot.set_speaking.call_args_list
            if c.args and c.args[0] is True
        ]
        assert start and start[0].kwargs.get("audio_meta") is None

    def test_generate_audio_error_falls_back_to_speak(
        self, mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
    ):
        mock_tts.generate_audio.side_effect = RuntimeError("GPU OOM")
        assistant, _ = self._robot_assistant(
            mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
        )
        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant.process("Hi")
        mock_agent.play_audio_file.assert_not_called()
        mock_tts.speak.assert_called_once_with("Hallo", emotion="neutral")

    def test_amplitude_analysis_error_yields_no_track(
        self, mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts
    ):
        # WAV vorhanden, aber Analyse wirft → kein Track, Agent spielt trotzdem.
        analyzer = MagicMock()
        analyzer.profile.side_effect = ValueError("boom")
        mock_tts.generate_audio.return_value = Path("/tmp/clip.wav")
        assistant, mock_robot = self._robot_assistant(
            mock_llm, mock_db, mock_controller, character, mock_agent, mock_tts,
            audio_analyzer=analyzer,
        )
        with patch("elder_berry.core.assistant.Path.unlink"):
            assistant.process("Hi")
        mock_agent.play_audio_file.assert_called_once()
        start = [
            c for c in mock_robot.set_speaking.call_args_list
            if c.args and c.args[0] is True
        ]
        assert start and start[0].kwargs.get("audio_meta") is None
