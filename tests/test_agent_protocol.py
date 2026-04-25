"""Tests für Agent-Kommunikation: Protocol, Server, Client."""
import io
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
        data = r.json()
        assert data["success"] is False
        # Exception-Details dürfen NICHT in der Response auftauchen
        assert "Bad WAV" not in data.get("message", "")


# ---------------------------------------------------------------------------
# Server: Token-Auth (Security-Fix)
# ---------------------------------------------------------------------------

class TestAgentServerTokenAuth:
    """AgentServer schützt Endpoints mit Token-Auth wenn agent_token gesetzt."""

    def _make_server_with_token(self, token: str | None):
        return AgentServer(
            controller=MockActionController(),
            hostname="test-laptop",
            agent_token=token,
        )

    def test_no_token_configured_allows_all(self):
        """Backwards-Compat: ohne Token-Konfiguration kein Auth-Check."""
        server = self._make_server_with_token(None)
        from fastapi.testclient import TestClient
        c = TestClient(server.app, raise_server_exceptions=False)
        r = c.get("/health")
        assert r.status_code == 200

    def test_token_required_when_configured(self):
        """Mit konfiguriertem Token wird jeder Request ohne Token abgelehnt."""
        server = self._make_server_with_token("geheimtoken123")
        from fastapi.testclient import TestClient
        c = TestClient(server.app, raise_server_exceptions=False)
        r = c.get("/health")
        assert r.status_code == 401

    def test_correct_token_grants_access(self):
        server = self._make_server_with_token("geheimtoken123")
        from fastapi.testclient import TestClient
        c = TestClient(server.app, raise_server_exceptions=False)
        r = c.get("/health", headers={"X-Saleria-Agent-Token": "geheimtoken123"})
        assert r.status_code == 200

    def test_wrong_token_rejected(self):
        server = self._make_server_with_token("geheimtoken123")
        from fastapi.testclient import TestClient
        c = TestClient(server.app, raise_server_exceptions=False)
        r = c.get("/health", headers={"X-Saleria-Agent-Token": "falsch"})
        assert r.status_code == 401

    def test_post_action_protected_with_token(self):
        server = self._make_server_with_token("tok")
        from fastapi.testclient import TestClient
        c = TestClient(server.app, raise_server_exceptions=False)
        r = c.post(
            "/action/execute",
            json={"action_type": "press_key", "params": {"key": "enter"}},
        )
        assert r.status_code == 401

    def test_warning_logged_when_no_token(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="elder_berry.agent.server"):
            self._make_server_with_token(None)
        messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("agent_token" in m.lower() or "elder_berry_agent_token" in m.lower()
                   for m in messages), f"Token-Warning erwartet. Logs: {messages}"

    def test_no_warning_when_token_set(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="elder_berry.agent.server"):
            self._make_server_with_token("supersecret")
        warning_messages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING and "agent_token" in r.message.lower()
        ]
        assert warning_messages == []


class TestAgentClientToken:
    """AgentClient sendet Token-Header wenn agent_token gesetzt."""

    def test_token_sent_in_header(self):
        from elder_berry.agent.client import AgentClient
        from elder_berry.agent.server import AGENT_TOKEN_HEADER
        with patch("elder_berry.agent.client.httpx.Client") as mock_cls:
            AgentClient(base_url="http://localhost:8001", agent_token="mytoken")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["headers"][AGENT_TOKEN_HEADER] == "mytoken"

    def test_no_header_when_no_token(self):
        from elder_berry.agent.client import AgentClient
        from elder_berry.agent.server import AGENT_TOKEN_HEADER
        with patch("elder_berry.agent.client.httpx.Client") as mock_cls:
            AgentClient(base_url="http://localhost:8001", agent_token=None)
        call_kwargs = mock_cls.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert AGENT_TOKEN_HEADER not in headers


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


# ---------------------------------------------------------------------------
# AgentClient – Tests mit gemocktem httpx
# ---------------------------------------------------------------------------

class TestAgentClient:
    """Tests fuer AgentClient mit gemocktem httpx.Client."""

    def _make_client(self, mock_http):
        from elder_berry.agent.client import AgentClient
        with patch("elder_berry.agent.client.httpx.Client", return_value=mock_http):
            return AgentClient(base_url="http://localhost:8001", timeout=5.0)

    def test_init_sets_base_url(self):
        mock_http = MagicMock()
        from elder_berry.agent.client import AgentClient
        with patch("elder_berry.agent.client.httpx.Client", return_value=mock_http) as mock_cls:
            c = AgentClient(base_url="http://test:9000", timeout=3.0)
        mock_cls.assert_called_once()
        assert c._base_url == "http://test:9000"

    def test_init_strips_trailing_slash(self):
        from elder_berry.agent.client import AgentClient
        with patch("elder_berry.agent.client.httpx.Client"):
            c = AgentClient(base_url="http://test:9000/")
        assert c._base_url == "http://test:9000"

    def test_close_calls_http_close(self):
        mock_http = MagicMock()
        c = self._make_client(mock_http)
        c.close()
        mock_http.close.assert_called_once()

    def test_health_success(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok", "hostname": "laptop", "uptime": 42.0, "version": "0.1.0"
        }
        mock_http.get.return_value = mock_resp

        c = self._make_client(mock_http)
        result = c.health()

        assert result.status == "ok"
        assert result.hostname == "laptop"
        mock_http.get.assert_called_once_with("/health")

    def test_is_online_true(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok", "hostname": "", "uptime": 0.0, "version": "0.1.0"
        }
        mock_http.get.return_value = mock_resp

        c = self._make_client(mock_http)
        assert c.is_online() is True

    def test_is_online_false_on_http_error(self):
        import httpx
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("unreachable")

        c = self._make_client(mock_http)
        assert c.is_online() is False

    def test_is_online_false_on_generic_exception(self):
        mock_http = MagicMock()
        mock_http.get.side_effect = RuntimeError("unexpected")

        c = self._make_client(mock_http)
        assert c.is_online() is False

    def test_get_status(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "online": True, "hostname": "laptop",
            "uptime": 5.0, "available_actions": ["press_key"]
        }
        mock_http.get.return_value = mock_resp

        c = self._make_client(mock_http)
        result = c.get_status()

        assert result.online is True
        assert result.hostname == "laptop"
        assert "press_key" in result.available_actions

    def test_execute_action(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "success": True, "action_type": "press_key", "message": "ok"
        }
        mock_http.post.return_value = mock_resp

        c = self._make_client(mock_http)
        result = c.execute_action("press_key", {"key": "F5"})

        assert result.success is True
        assert result.action_type == "press_key"
        mock_http.post.assert_called_once_with(
            "/action/execute",
            json={"action_type": "press_key", "params": {"key": "F5"}},
        )

    def test_execute_action_no_params(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "success": True, "action_type": "mute", "message": "ok"
        }
        mock_http.post.return_value = mock_resp

        c = self._make_client(mock_http)
        result = c.execute_action("mute")

        call_args = mock_http.post.call_args
        assert call_args[1]["json"]["params"] == {}

    def test_play_audio(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "message": "played"}
        mock_http.post.return_value = mock_resp

        c = self._make_client(mock_http)
        result = c.play_audio(b"RIFF...", emotion="happy")

        assert result.success is True
        call_args = mock_http.post.call_args
        assert call_args[0][0] == "/audio/play"
        assert call_args[1]["data"]["emotion"] == "happy"

    def test_play_audio_file(self, tmp_path):
        wav_file = tmp_path / "speech.wav"
        wav_file.write_bytes(b"RIFF audio data")

        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"success": True, "message": "played"}
        mock_http.post.return_value = mock_resp

        c = self._make_client(mock_http)
        result = c.play_audio_file(wav_file, emotion="neutral")

        assert result.success is True
        call_args = mock_http.post.call_args
        assert call_args[1]["data"]["emotion"] == "neutral"
        # filename should be the file name
        files_arg = call_args[1]["files"]
        assert files_arg["file"][0] == "speech.wav"
