"""Tests fuer Harmony-Methoden in RobotClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from elder_berry.robot.client import RobotClient


# -- Fixtures -------------------------------------------------------------- #


@pytest.fixture
def mock_transport():
    """Mock-Transport der vordefinierte Responses liefert."""
    return {}


def _make_client(responses: dict[str, httpx.Response]) -> RobotClient:
    """Erzeugt RobotClient mit gemocktem httpx.Client."""
    client = RobotClient.__new__(RobotClient)
    client._base_url = "http://localhost:8000"
    client._timeout = 5.0

    mock_httpx = MagicMock(spec=httpx.Client)

    def mock_get(url, **kwargs):
        resp = responses.get(("GET", url))
        if resp is None:
            raise httpx.ConnectError("Mock: no response")
        return resp

    def mock_post(url, **kwargs):
        resp = responses.get(("POST", url))
        if resp is None:
            raise httpx.ConnectError("Mock: no response")
        return resp

    def mock_delete(url, **kwargs):
        resp = responses.get(("DELETE", url))
        if resp is None:
            raise httpx.ConnectError("Mock: no response")
        return resp

    mock_httpx.get = mock_get
    mock_httpx.post = mock_post
    mock_httpx.delete = mock_delete
    client._client = mock_httpx
    return client


def _json_response(data: dict, status_code: int = 200) -> httpx.Response:
    """Erzeugt eine httpx.Response mit JSON-Body."""
    r = httpx.Response(
        status_code=status_code,
        json=data,
        request=httpx.Request("GET", "http://test"),
    )
    return r


# -- Tests ----------------------------------------------------------------- #


class TestHarmonyStatus:
    def test_harmony_status_connected(self):
        client = _make_client(
            {
                ("GET", "/harmony/status"): _json_response(
                    {
                        "connected": True,
                        "current_activity": "Fernsehen",
                    }
                ),
            }
        )
        result = client.harmony_status()
        assert result["connected"] is True
        assert result["current_activity"] == "Fernsehen"

    def test_harmony_status_disconnected(self):
        client = _make_client(
            {
                ("GET", "/harmony/status"): _json_response(
                    {
                        "connected": False,
                        "current_activity": None,
                    }
                ),
            }
        )
        result = client.harmony_status()
        assert result["connected"] is False

    def test_harmony_status_connection_error(self):
        client = _make_client({})  # Kein Response = ConnectError
        result = client.harmony_status()
        assert result["connected"] is False
        assert result["current_activity"] is None


class TestHarmonyConfig:
    def test_harmony_config_returns_dict(self):
        client = _make_client(
            {
                ("GET", "/harmony/config"): _json_response(
                    {
                        "activities": ["Fernsehen", "Musik"],
                        "devices": ["Denon AVR-X3500H"],
                    }
                ),
            }
        )
        result = client.harmony_config()
        assert "Fernsehen" in result["activities"]
        assert "Denon AVR-X3500H" in result["devices"]

    def test_harmony_config_connection_error(self):
        client = _make_client({})
        result = client.harmony_config()
        assert result == {"activities": [], "devices": []}


class TestHarmonyConfigDetailed:
    def test_harmony_config_detailed_returns_dict(self):
        client = _make_client(
            {
                ("GET", "/harmony/config/detailed"): _json_response(
                    {
                        "activities": [
                            {
                                "id": "38979034",
                                "label": "Fernsehen",
                                "volume_device": "Denon AVR-X3500H",
                            },
                        ],
                        "devices": [
                            {
                                "id": "74828509",
                                "label": "Denon AVR-X3500H",
                                "control_groups": [
                                    {
                                        "name": "Volume",
                                        "commands": ["VolumeUp", "VolumeDown"],
                                    },
                                ],
                            },
                        ],
                    }
                ),
            }
        )
        result = client.harmony_config_detailed()
        assert len(result["activities"]) == 1
        assert result["activities"][0]["volume_device"] == "Denon AVR-X3500H"
        assert len(result["devices"]) == 1

    def test_harmony_config_detailed_connection_error(self):
        client = _make_client({})
        result = client.harmony_config_detailed()
        assert result == {"activities": [], "devices": []}


class TestHarmonyLayouts:
    def test_harmony_layouts_returns_dict(self):
        client = _make_client(
            {
                ("GET", "/harmony/layouts"): _json_response(
                    {
                        "activities": {"Fernsehen": {"sections": []}},
                        "devices": {},
                    }
                ),
            }
        )
        result = client.harmony_layouts()
        assert "Fernsehen" in result["activities"]

    def test_harmony_layouts_connection_error(self):
        client = _make_client({})
        result = client.harmony_layouts()
        assert result == {"activities": {}, "devices": {}}

    def test_harmony_save_layouts_success(self):
        client = _make_client(
            {
                ("POST", "/harmony/layouts"): _json_response({"success": True}),
            }
        )
        assert client.harmony_save_layouts({"test": True}) is True

    def test_harmony_save_layouts_connection_error(self):
        client = _make_client({})
        assert client.harmony_save_layouts({}) is False


class TestHarmonyScenes:
    def test_harmony_scenes_returns_list(self):
        client = _make_client(
            {
                ("GET", "/harmony/scenes"): _json_response(
                    {
                        "scenes": [{"name": "Gaming", "steps": []}],
                    }
                ),
            }
        )
        result = client.harmony_scenes()
        assert len(result) == 1
        assert result[0]["name"] == "Gaming"

    def test_harmony_scenes_connection_error(self):
        client = _make_client({})
        assert client.harmony_scenes() == []

    def test_harmony_save_scene_success(self):
        client = _make_client(
            {
                ("POST", "/harmony/scenes"): _json_response({"success": True}),
            }
        )
        assert client.harmony_save_scene({"name": "Test", "steps": []}) is True

    def test_harmony_save_scene_connection_error(self):
        client = _make_client({})
        assert client.harmony_save_scene({}) is False

    def test_harmony_start_scene_success(self):
        client = _make_client(
            {
                ("POST", "/harmony/scene/start"): _json_response(
                    {
                        "success": True,
                        "steps_ok": 2,
                        "steps_total": 2,
                    }
                ),
            }
        )
        result = client.harmony_start_scene("Gaming")
        assert result["success"] is True
        assert result["steps_ok"] == 2

    def test_harmony_start_scene_connection_error(self):
        client = _make_client({})
        result = client.harmony_start_scene("Gaming")
        assert result["success"] is False

    def test_harmony_delete_scene_success(self):
        client = _make_client(
            {
                ("DELETE", "/harmony/scene/Gaming"): _json_response(
                    {"success": True},
                ),
            }
        )
        assert client.harmony_delete_scene("Gaming") is True

    def test_harmony_delete_scene_connection_error(self):
        client = _make_client({})
        assert client.harmony_delete_scene("Gaming") is False


class TestHarmonyStartActivity:
    def test_harmony_start_activity_success(self):
        client = _make_client(
            {
                ("POST", "/harmony/activity"): _json_response(
                    {
                        "success": True,
                        "activity": "Fernsehen",
                    }
                ),
            }
        )
        assert client.harmony_start_activity("Fernsehen") is True

    def test_harmony_start_activity_failure(self):
        client = _make_client(
            {
                ("POST", "/harmony/activity"): _json_response(
                    {
                        "success": False,
                        "activity": "Gaming",
                    }
                ),
            }
        )
        assert client.harmony_start_activity("Gaming") is False

    def test_harmony_start_activity_connection_error(self):
        client = _make_client({})
        assert client.harmony_start_activity("Fernsehen") is False


class TestHarmonySendCommand:
    def test_harmony_send_command_success(self):
        client = _make_client(
            {
                ("POST", "/harmony/command"): _json_response({"success": True}),
            }
        )
        assert client.harmony_send_command("Receiver", "VolumeUp") is True

    def test_harmony_send_command_failure(self):
        client = _make_client(
            {
                ("POST", "/harmony/command"): _json_response({"success": False}),
            }
        )
        assert client.harmony_send_command("Receiver", "VolumeUp") is False

    def test_harmony_send_command_connection_error(self):
        client = _make_client({})
        assert client.harmony_send_command("Receiver", "VolumeUp") is False


class TestHarmonyPowerOff:
    def test_harmony_power_off_success(self):
        client = _make_client(
            {
                ("POST", "/harmony/off"): _json_response({"success": True}),
            }
        )
        assert client.harmony_power_off() is True

    def test_harmony_power_off_failure(self):
        client = _make_client(
            {
                ("POST", "/harmony/off"): _json_response({"success": False}),
            }
        )
        assert client.harmony_power_off() is False

    def test_harmony_power_off_connection_error(self):
        client = _make_client({})
        assert client.harmony_power_off() is False
