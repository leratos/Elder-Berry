"""Tests fuer Harmony-Endpoints in RobotServer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

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
def client_with_harmony(mock_harmony) -> TestClient:
    motors, avatar, sensors = _make_mock_deps()
    server = RobotServer(
        motors=motors, avatar=avatar, sensors=sensors,
        harmony=mock_harmony,
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
