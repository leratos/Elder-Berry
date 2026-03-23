"""Tests fuer Drehteller Server-Endpoints mit SimulatedTurntable + TestClient."""
import pytest

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from elder_berry.robot.simulator import (
    SimulatedAvatar,
    SimulatedMotors,
    SimulatedSensors,
    SimulatedTurntable,
)
from elder_berry.robot.server import RobotServer

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


def _create_server(turntable=None):
    return RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        turntable=turntable,
        hostname="test",
    )


class TestSystemUpdateEndpoint:

    def test_update_no_project_root(self):
        server = _create_server()
        client = TestClient(server.app)
        r = client.post("/system/update")
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert "nicht konfiguriert" in r.json()["message"].lower()


class TestTurntableEndpoints:

    def test_status_no_turntable(self):
        server = _create_server(turntable=None)
        client = TestClient(server.app)
        r = client.get("/turntable/status")
        assert r.status_code == 200
        assert r.json()["available"] is False

    def test_status_not_homed(self):
        t = SimulatedTurntable()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.get("/turntable/status")
        data = r.json()
        assert data["available"] is True
        assert data["is_homed"] is False

    def test_home_endpoint(self):
        t = SimulatedTurntable()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.post("/turntable/home")
        assert r.json()["success"] is True
        assert t.is_homed is True

    def test_rotate_absolute(self):
        t = SimulatedTurntable()
        t.home()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.post("/turntable/rotate", json={"target_degrees": 90})
        assert r.json()["success"] is True
        assert t.get_position() == pytest.approx(90.0, abs=0.1)

    def test_rotate_relative(self):
        t = SimulatedTurntable()
        t.home()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.post("/turntable/rotate", json={"relative_degrees": 45})
        assert r.json()["success"] is True
        assert t.get_position() == pytest.approx(45.0, abs=0.1)

    def test_rotate_no_params(self):
        t = SimulatedTurntable()
        t.home()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.post("/turntable/rotate", json={})
        assert r.json()["success"] is False

    def test_rotate_not_homed(self):
        t = SimulatedTurntable()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.post("/turntable/rotate", json={"target_degrees": 90})
        assert r.json()["success"] is False

    def test_stop_endpoint(self):
        t = SimulatedTurntable()
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.post("/turntable/stop")
        assert r.json()["success"] is True

    def test_status_after_rotate(self):
        t = SimulatedTurntable()
        t.home()
        t.rotate_to(60)
        server = _create_server(turntable=t)
        client = TestClient(server.app)
        r = client.get("/turntable/status")
        data = r.json()
        assert data["is_homed"] is True
        assert data["position_degrees"] == pytest.approx(60.0, abs=0.1)
