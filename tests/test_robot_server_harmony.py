"""Tests fuer Harmony-Endpoints in RobotServer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from elder_berry.robot.harmony_layout_manager import HarmonyLayoutManager
from elder_berry.robot.harmony_scene_manager import HarmonySceneManager
from elder_berry.robot.server import RobotServer


# -- Fixtures -------------------------------------------------------------- #

def _make_mock_deps():
    """Erzeugt minimale Mock-Dependencies fuer RobotServer."""
    motors = MagicMock()
    motors.get_state.return_value = {"active": False, "direction": "stop", "speed": 0.0}
    avatar = MagicMock()
    avatar.get_state.return_value = {"emotion": "neutral", "speaking": False}
    sensors = MagicMock()
    sensors.get_battery.return_value = MagicMock(
        percentage=100, voltage=5.0, charging=False,
    )
    sensors.get_all.return_value = {}
    return motors, avatar, sensors


@pytest.fixture
def mock_harmony():
    h = AsyncMock()
    h.is_connected = True
    h.get_current_activity = AsyncMock(return_value="Fernsehen")
    h.list_activities = AsyncMock(return_value=["Fernsehen", "Musik"])
    h.list_devices = AsyncMock(return_value=["Denon AVR-X3500H", "Samsung TV"])
    h.start_activity = AsyncMock(return_value=True)
    h.send_command = AsyncMock(return_value=True)
    h.power_off = AsyncMock(return_value=True)
    return h


@pytest.fixture
def mock_layout_manager(tmp_path):
    return HarmonyLayoutManager(layouts_path=tmp_path / "layouts.json")


@pytest.fixture
def mock_scene_manager(tmp_path, mock_harmony):
    return HarmonySceneManager(
        adapter=mock_harmony,
        scenes_path=tmp_path / "scenes.json",
    )


@pytest.fixture
def client_with_harmony(
    mock_harmony, mock_layout_manager, mock_scene_manager,
) -> TestClient:
    motors, avatar, sensors = _make_mock_deps()
    server = RobotServer(
        motors=motors, avatar=avatar, sensors=sensors,
        harmony=mock_harmony,
        harmony_layouts=mock_layout_manager,
        harmony_scenes=mock_scene_manager,
    )
    return TestClient(server.app)


@pytest.fixture
def client_without_harmony() -> TestClient:
    motors, avatar, sensors = _make_mock_deps()
    server = RobotServer(motors=motors, avatar=avatar, sensors=sensors)
    return TestClient(server.app)


# -- Tests ----------------------------------------------------------------- #

class TestHarmonyStatus:
    def test_get_status_connected(self, client_with_harmony, mock_harmony):
        r = client_with_harmony.get("/harmony/status")
        assert r.status_code == 200
        data = r.json()
        assert data["connected"] is True
        assert data["current_activity"] == "Fernsehen"

    def test_get_status_disconnected(self, client_with_harmony, mock_harmony):
        mock_harmony.is_connected = False
        mock_harmony.get_current_activity = AsyncMock(return_value=None)
        r = client_with_harmony.get("/harmony/status")
        assert r.status_code == 200
        data = r.json()
        assert data["connected"] is False
        assert data["current_activity"] is None


class TestHarmonyConfig:
    def test_get_config_returns_activities_and_devices(
        self, client_with_harmony,
    ):
        r = client_with_harmony.get("/harmony/config")
        assert r.status_code == 200
        data = r.json()
        assert "Fernsehen" in data["activities"]
        assert "Denon AVR-X3500H" in data["devices"]


class TestHarmonyActivity:
    def test_post_activity_success(self, client_with_harmony, mock_harmony):
        r = client_with_harmony.post(
            "/harmony/activity", json={"activity": "Fernsehen"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["activity"] == "Fernsehen"
        mock_harmony.start_activity.assert_awaited_once_with("Fernsehen")

    def test_post_activity_not_found(self, client_with_harmony, mock_harmony):
        mock_harmony.start_activity = AsyncMock(return_value=False)
        r = client_with_harmony.post(
            "/harmony/activity", json={"activity": "Gaming"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is False


class TestHarmonyCommand:
    def test_post_command_success(self, client_with_harmony, mock_harmony):
        r = client_with_harmony.post(
            "/harmony/command",
            json={"device": "Denon AVR-X3500H", "command": "VolumeUp"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_post_command_device_not_found(
        self, client_with_harmony, mock_harmony,
    ):
        mock_harmony.send_command = AsyncMock(return_value=False)
        r = client_with_harmony.post(
            "/harmony/command",
            json={"device": "Xbox", "command": "PowerOn"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_post_command_with_repeat(self, client_with_harmony, mock_harmony):
        r = client_with_harmony.post(
            "/harmony/command",
            json={
                "device": "Denon AVR-X3500H",
                "command": "VolumeUp",
                "repeat": 3,
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        mock_harmony.send_command.assert_awaited_once_with(
            device="Denon AVR-X3500H", command="VolumeUp", repeat=3,
        )


class TestHarmonyOff:
    def test_post_power_off(self, client_with_harmony, mock_harmony):
        r = client_with_harmony.post("/harmony/off")
        assert r.status_code == 200
        assert r.json()["success"] is True
        mock_harmony.power_off.assert_awaited_once()


DETAILED_CONFIG = {
    "activities": [
        {"id": "38979034", "label": "Fernsehen",
         "volume_device": "Denon AVR-X3500H",
         "channel_device": "Samsung TV"},
    ],
    "devices": [
        {"id": "74828509", "label": "Denon AVR-X3500H",
         "control_groups": [
             {"name": "Volume", "commands": ["VolumeUp", "VolumeDown", "Mute"]},
         ]},
    ],
}


class TestHarmonyConfigDetailed:
    def test_get_config_detailed(self, client_with_harmony, mock_harmony):
        mock_harmony.get_detailed_config = MagicMock(return_value=DETAILED_CONFIG)
        r = client_with_harmony.get("/harmony/config/detailed")
        assert r.status_code == 200
        data = r.json()
        assert len(data["activities"]) == 1
        assert data["activities"][0]["volume_device"] == "Denon AVR-X3500H"
        assert len(data["devices"]) == 1
        assert data["devices"][0]["control_groups"][0]["name"] == "Volume"

    def test_config_detailed_503_without_harmony(self, client_without_harmony):
        r = client_without_harmony.get("/harmony/config/detailed")
        assert r.status_code == 503


class TestHarmonyLayouts:
    def test_get_layouts_empty(self, client_with_harmony, mock_harmony):
        r = client_with_harmony.get("/harmony/layouts")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_post_then_get_layouts(self, client_with_harmony, mock_harmony):
        payload = {
            "activities": {"Test": {"sections": []}},
            "devices": {},
        }
        r = client_with_harmony.post("/harmony/layouts", json=payload)
        assert r.status_code == 200
        assert r.json()["success"] is True

        r2 = client_with_harmony.get("/harmony/layouts")
        assert r2.json()["activities"]["Test"] == {"sections": []}

    def test_layouts_503_without_harmony(self, client_without_harmony):
        r = client_without_harmony.get("/harmony/layouts")
        assert r.status_code == 503

    def test_save_layouts_503_without_harmony(self, client_without_harmony):
        r = client_without_harmony.post("/harmony/layouts", json={})
        assert r.status_code == 503


class TestHarmonyScenes:
    def test_get_scenes_empty(self, client_with_harmony):
        r = client_with_harmony.get("/harmony/scenes")
        assert r.status_code == 200
        assert r.json()["scenes"] == []

    def test_save_and_get_scene(self, client_with_harmony):
        scene = {
            "name": "Gaming",
            "steps": [{"device": "TV", "cmd": "PowerOn"}],
        }
        r = client_with_harmony.post("/harmony/scenes", json=scene)
        assert r.status_code == 200
        assert r.json()["success"] is True

        r2 = client_with_harmony.get("/harmony/scenes")
        assert len(r2.json()["scenes"]) == 1
        assert r2.json()["scenes"][0]["name"] == "Gaming"

    def test_save_scene_invalid(self, client_with_harmony):
        r = client_with_harmony.post(
            "/harmony/scenes", json={"name": ""},
        )
        assert r.status_code == 400

    def test_start_scene(self, client_with_harmony, mock_harmony):
        scene = {
            "name": "Gaming",
            "steps": [{"device": "TV", "cmd": "PowerOn"}],
        }
        client_with_harmony.post("/harmony/scenes", json=scene)
        r = client_with_harmony.post(
            "/harmony/scene/start", json={"name": "Gaming"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["steps_ok"] == 1

    def test_start_scene_not_found(self, client_with_harmony):
        r = client_with_harmony.post(
            "/harmony/scene/start", json={"name": "Nope"},
        )
        assert r.status_code == 404

    def test_delete_scene(self, client_with_harmony):
        scene = {
            "name": "Gaming",
            "steps": [{"device": "TV", "cmd": "PowerOn"}],
        }
        client_with_harmony.post("/harmony/scenes", json=scene)
        r = client_with_harmony.delete("/harmony/scene/Gaming")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_delete_scene_not_found(self, client_with_harmony):
        r = client_with_harmony.delete("/harmony/scene/Nope")
        assert r.status_code == 404

    def test_scenes_503_without_config(self, client_without_harmony):
        r = client_without_harmony.get("/harmony/scenes")
        assert r.status_code == 503

    def test_start_scene_503_without_config(self, client_without_harmony):
        r = client_without_harmony.post(
            "/harmony/scene/start", json={"name": "Gaming"},
        )
        assert r.status_code == 503

    def test_delete_scene_503_without_config(self, client_without_harmony):
        r = client_without_harmony.delete("/harmony/scene/Gaming")
        assert r.status_code == 503


class TestHarmony503:
    def test_status_503_when_not_configured(self, client_without_harmony):
        r = client_without_harmony.get("/harmony/status")
        assert r.status_code == 503

    def test_config_503_when_not_configured(self, client_without_harmony):
        r = client_without_harmony.get("/harmony/config")
        assert r.status_code == 503

    def test_activity_503_when_not_configured(self, client_without_harmony):
        r = client_without_harmony.post(
            "/harmony/activity", json={"activity": "Fernsehen"},
        )
        assert r.status_code == 503

    def test_command_503_when_not_configured(self, client_without_harmony):
        r = client_without_harmony.post(
            "/harmony/command",
            json={"device": "Receiver", "command": "VolumeUp"},
        )
        assert r.status_code == 503

    def test_off_503_when_not_configured(self, client_without_harmony):
        r = client_without_harmony.post("/harmony/off")
        assert r.status_code == 503
