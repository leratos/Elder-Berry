"""Tests für Agent-Kommunikation: Protocol, Server, Client."""
import io
import struct
import wave
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.agent.protocol import (
    ActionRequest,
    ActionResult,
    AgentStatus,
    ApiResponse,
    HealthResponse,
)

# Server braucht fastapi (optional dependency)
fastapi = pytest.importorskip("fastapi", reason="fastapi nicht installiert")

from elder_berry.actions.base import ActionController, WindowInfo  # noqa: E402
from elder_berry.agent.server import AgentServer, SUPPORTED_ACTIONS  # noqa: E402


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def make_wav_bytes(duration: float = 0.1, sample_rate: int = 22050) -> bytes:
    """Erzeugt gültige WAV-Bytes (Stille) für Tests."""
    n_frames = int(sample_rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Mock ActionController
# ---------------------------------------------------------------------------

class MockActionController(ActionController):
    """Test-Double für ActionController."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, method: str, *args, **kwargs):
        self.calls.append((method, args, kwargs))

    def press_key(self, key: str) -> None:
        self._record("press_key", key)

    def type_text(self, text: str, interval: float = 0.02) -> None:
        self._record("type_text", text, interval=interval)

    def hotkey(self, *keys: str) -> None:
        self._record("hotkey", *keys)

    def move_mouse(self, x: int, y: int, duration: float = 0.25) -> None:
        self._record("move_mouse", x, y, duration=duration)

    def click(self, x: int | None = None, y: int | None = None,
              button: str = "left") -> None:
        self._record("click", x=x, y=y, button=button)

    def list_windows(self) -> list[WindowInfo]:
        self._record("list_windows")
        return [WindowInfo(title="Test Window", handle=12345)]

    def focus_window(self, title: str) -> bool:
        self._record("focus_window", title)
        return True

    def minimize_window(self, title: str) -> bool:
        self._record("minimize_window", title)
        return True

    def maximize_window(self, title: str) -> bool:
        self._record("maximize_window", title)
        return True

    def get_volume(self) -> float:
        self._record("get_volume")
        return 0.75

    def set_volume(self, level: float) -> None:
        self._record("set_volume", level)

    def mute(self, state: bool = True) -> None:
        self._record("mute", state)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_controller():
    return MockActionController()


@pytest.fixture
def agent_server(mock_controller):
    return AgentServer(controller=mock_controller, hostname="test-laptop")


@pytest.fixture
def client(agent_server):
    from fastapi.testclient import TestClient
    return TestClient(agent_server.app)


# ---------------------------------------------------------------------------
# Protocol DTOs
# ---------------------------------------------------------------------------

class TestProtocolDTOs:
    def test_action_request_defaults(self):
        req = ActionRequest(action_type="press_key")
        assert req.action_type == "press_key"
        assert req.params == {}

    def test_action_request_with_params(self):
        req = ActionRequest(action_type="type_text", params={"text": "hello"})
        assert req.params == {"text": "hello"}

    def test_action_request_frozen(self):
        req = ActionRequest(action_type="press_key")
        with pytest.raises(AttributeError):
            req.action_type = "other"

    def test_agent_status_defaults(self):
        status = AgentStatus()
        assert status.online is True
        assert status.hostname == ""
        assert status.available_actions == []

    def test_agent_status_with_actions(self):
        status = AgentStatus(available_actions=["press_key", "mute"])
        assert len(status.available_actions) == 2

    def test_health_response_defaults(self):
        hr = HealthResponse()
        assert hr.status == "ok"
        assert hr.version == "0.1.0"

    def test_health_response_with_values(self):
        hr = HealthResponse(status="ok", hostname="laptop", uptime=42.0)
        assert hr.hostname == "laptop"
        assert hr.uptime == 42.0

    def test_api_response(self):
        ar = ApiResponse(success=True, message="done")
        assert ar.success is True
        assert ar.data is None

    def test_api_response_with_data(self):
        ar = ApiResponse(success=True, data={"key": "val"})
        assert ar.data == {"key": "val"}

    def test_action_result_success(self):
        result = ActionResult(success=True, action_type="press_key", message="OK")
        assert result.success is True
        assert result.return_value is None

    def test_action_result_with_return_value(self):
        result = ActionResult(
            success=True, action_type="get_volume",
            return_value=0.75,
        )
        assert result.return_value == 0.75

    def test_action_result_failure(self):
        result = ActionResult(
            success=False, action_type="unknown",
            message="Unbekannte Aktion: unknown",
        )
        assert result.success is False

    def test_agent_status_serializable(self):
        status = AgentStatus(hostname="test", available_actions=["press_key"])
        d = asdict(status)
        assert isinstance(d, dict)
        assert d["hostname"] == "test"

    def test_health_response_frozen(self):
        hr = HealthResponse()
        with pytest.raises(AttributeError):
            hr.status = "error"


# ---------------------------------------------------------------------------
# Server: Health + Status
# ---------------------------------------------------------------------------

class TestAgentServerHealth:
    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["hostname"] == "test-laptop"
        assert data["uptime"] >= 0

    def test_status_endpoint(self, client):
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["online"] is True
        assert data["hostname"] == "test-laptop"
        assert isinstance(data["available_actions"], list)
        assert "press_key" in data["available_actions"]


# ---------------------------------------------------------------------------
# Server: Action Execution
# ---------------------------------------------------------------------------

class TestAgentServerActions:
    def test_press_key(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "press_key", "params": {"key": "enter"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["action_type"] == "press_key"
        assert mock_controller.calls[-1][0] == "press_key"

    def test_type_text(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "type_text", "params": {"text": "hello"},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert mock_controller.calls[-1][0] == "type_text"

    def test_hotkey(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "hotkey", "params": {"keys": ["ctrl", "c"]},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert mock_controller.calls[-1][0] == "hotkey"

    def test_move_mouse(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "move_mouse", "params": {"x": 100, "y": 200},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_click(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "click", "params": {"x": 50, "y": 50, "button": "right"},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_list_windows(self, client):
        r = client.post("/action/execute", json={
            "action_type": "list_windows", "params": {},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["return_value"], list)
        assert data["return_value"][0]["title"] == "Test Window"

    def test_focus_window(self, client):
        r = client.post("/action/execute", json={
            "action_type": "focus_window", "params": {"title": "Test"},
        })
        assert r.status_code == 200
        assert r.json()["return_value"] is True

    def test_minimize_window(self, client):
        r = client.post("/action/execute", json={
            "action_type": "minimize_window", "params": {"title": "Test"},
        })
        assert r.status_code == 200
        assert r.json()["return_value"] is True

    def test_maximize_window(self, client):
        r = client.post("/action/execute", json={
            "action_type": "maximize_window", "params": {"title": "Test"},
        })
        assert r.status_code == 200
        assert r.json()["return_value"] is True

    def test_get_volume(self, client):
        r = client.post("/action/execute", json={
            "action_type": "get_volume", "params": {},
        })
        assert r.status_code == 200
        assert r.json()["return_value"] == 0.75

    def test_set_volume(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "set_volume", "params": {"level": 0.5},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_mute(self, client, mock_controller):
        r = client.post("/action/execute", json={
            "action_type": "mute", "params": {"state": True},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_unknown_action_fails(self, client):
        r = client.post("/action/execute", json={
            "action_type": "self_destruct", "params": {},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "Unbekannte Aktion" in data["message"]

    def test_missing_params_fails(self, client):
        r = client.post("/action/execute", json={
            "action_type": "press_key", "params": {},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "Parameter" in data["message"] or "key" in data["message"].lower()


# ---------------------------------------------------------------------------
# Server: Audio Playback
# ---------------------------------------------------------------------------

class TestAgentServerAudio:
    @patch.object(AgentServer, "_play_wav")
    def test_play_audio_success(self, mock_play, client):
        wav_data = make_wav_bytes()
        r = client.post(
            "/audio/play",
            files={"file": ("test.wav", wav_data, "audio/wav")},
            data={"emotion": "cheerful"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "cheerful" in data["message"]
        mock_play.assert_called_once()

    @patch.object(AgentServer, "_play_wav")
    def test_play_audio_default_emotion(self, mock_play, client):
        wav_data = make_wav_bytes()
        r = client.post(
            "/audio/play",
            files={"file": ("test.wav", wav_data, "audio/wav")},
        )
        assert r.status_code == 200
        assert "neutral" in r.json()["message"]

    @patch.object(AgentServer, "_play_wav", side_effect=Exception("Bad WAV"))
    def test_play_audio_invalid_wav(self, mock_play, client):
        r = client.post(
            "/audio/play",
            files={"file": ("bad.wav", b"not-a-wav", "audio/wav")},
            data={"emotion": "neutral"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# Server: SUPPORTED_ACTIONS Liste
# ---------------------------------------------------------------------------

class TestSupportedActions:
    def test_all_action_types_covered(self):
        expected = {
            "press_key", "type_text", "hotkey",
            "move_mouse", "click",
            "list_windows", "focus_window", "minimize_window", "maximize_window",
            "get_volume", "set_volume", "mute",
        }
        assert set(SUPPORTED_ACTIONS) == expected

    def test_status_lists_all_actions(self, client):
        r = client.get("/status")
        actions = r.json()["available_actions"]
        assert len(actions) == len(SUPPORTED_ACTIONS)
