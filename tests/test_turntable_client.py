"""Tests fuer RobotClient Drehteller-Methoden mit MockTransport."""
import json

import httpx
import pytest

from elder_berry.robot.client import RobotClient
from elder_berry.robot.protocol import ApiResponse


def _mock_transport(responses: dict):
    """Erstellt einen MockTransport der auf URL-Pfade reagiert."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        key = f"{method} {path}"
        if key in responses:
            return httpx.Response(200, json=responses[key])
        return httpx.Response(404, json={"error": "not found"})
    return httpx.MockTransport(handler)


class TestTurntableClient:

    def test_rotate_turntable_absolute(self):
        transport = _mock_transport({
            "POST /turntable/rotate": {"success": True, "message": "Rotation zu 90 Grad gestartet"},
        })
        client = RobotClient.__new__(RobotClient)
        client._client = httpx.Client(transport=transport, base_url="http://test")
        resp = client.rotate_turntable(target_degrees=90)
        assert resp.success is True

    def test_rotate_turntable_relative(self):
        transport = _mock_transport({
            "POST /turntable/rotate": {"success": True, "message": "Rotation um 45 Grad gestartet"},
        })
        client = RobotClient.__new__(RobotClient)
        client._client = httpx.Client(transport=transport, base_url="http://test")
        resp = client.rotate_turntable(relative_degrees=45)
        assert resp.success is True

    def test_home_turntable(self):
        transport = _mock_transport({
            "POST /turntable/home": {"success": True, "message": "Homing gestartet"},
        })
        client = RobotClient.__new__(RobotClient)
        client._client = httpx.Client(transport=transport, base_url="http://test")
        resp = client.home_turntable()
        assert resp.success is True

    def test_stop_turntable(self):
        transport = _mock_transport({
            "POST /turntable/stop": {"success": True, "message": "Rotation gestoppt"},
        })
        client = RobotClient.__new__(RobotClient)
        client._client = httpx.Client(transport=transport, base_url="http://test")
        resp = client.stop_turntable()
        assert resp.success is True

    def test_turntable_status(self):
        transport = _mock_transport({
            "GET /turntable/status": {
                "available": True,
                "is_homed": True,
                "is_moving": False,
                "position_degrees": 45.0,
            },
        })
        client = RobotClient.__new__(RobotClient)
        client._client = httpx.Client(transport=transport, base_url="http://test")
        status = client.turntable_status()
        assert status["available"] is True
        assert status["position_degrees"] == 45.0
