"""Tests fuer RobotServer Token-Authentifizierung und Startup-Verhalten."""

import logging

import pytest

try:
    from fastapi.testclient import TestClient
    from elder_berry.robot.simulator import (
        SimulatedAvatar,
        SimulatedMotors,
        SimulatedSensors,
    )
    from elder_berry.robot.server import RobotServer

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


def _create_server(**kwargs):
    return RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        hostname="test",
        **kwargs,
    )


class TestRobotTokenWarning:
    """RobotServer loggt beim Start ein WARNING wenn kein Token gesetzt ist."""

    def test_warning_logged_when_no_token(self, caplog):
        with caplog.at_level(logging.WARNING, logger="elder_berry.robot.server"):
            _create_server(robot_token=None)
        messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "robot_token" in m.lower() or "elder_berry_robot_token" in m.lower()
            for m in messages
        ), f"Erwartetes Token-Warning nicht gefunden. Logs: {messages}"

    def test_warning_logged_when_empty_string(self, caplog):
        with caplog.at_level(logging.WARNING, logger="elder_berry.robot.server"):
            _create_server(robot_token="")
        messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "robot_token" in m.lower() or "elder_berry_robot_token" in m.lower()
            for m in messages
        ), (
            f"Erwartetes Token-Warning für leeren String nicht gefunden. Logs: {messages}"
        )

    def test_no_warning_when_token_set(self, caplog):
        with caplog.at_level(logging.WARNING, logger="elder_berry.robot.server"):
            _create_server(robot_token="supersecrettoken123")
        warning_messages = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and "robot_token" in r.message.lower()
        ]
        assert warning_messages == [], (
            f"Unerwartetes Token-Warning obwohl Token gesetzt: {warning_messages}"
        )


class TestRobotTokenAuth:
    """Endpoints werden bei gesetztem Token korrekt geschuetzt."""

    def test_health_without_token_rejected(self):
        server = _create_server(robot_token="geheimestoken")
        client = TestClient(server.app, raise_server_exceptions=False)
        r = client.get("/health")
        assert r.status_code == 401

    def test_health_with_correct_token_allowed(self):
        server = _create_server(robot_token="geheimestoken")
        client = TestClient(server.app, raise_server_exceptions=False)
        r = client.get("/health", headers={"X-Saleria-Robot-Token": "geheimestoken"})
        assert r.status_code == 200

    def test_health_with_wrong_token_rejected(self):
        server = _create_server(robot_token="geheimestoken")
        client = TestClient(server.app, raise_server_exceptions=False)
        r = client.get("/health", headers={"X-Saleria-Robot-Token": "falschestoken"})
        assert r.status_code == 401

    def test_no_token_configured_allows_all(self):
        """Backwards-Compat: ohne Token-Konfiguration kein Auth-Check."""
        server = _create_server(robot_token=None)
        client = TestClient(server.app, raise_server_exceptions=False)
        r = client.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Kamera: Quality-Bounds + Leer-JPEG + Exception ohne Info-Leak
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402


class TestCameraCaptureSecurity:
    """Sicherheitstests fuer den /camera/capture Endpoint."""

    def _create_server_with_camera(self, camera_mock):
        return RobotServer(
            motors=SimulatedMotors(),
            avatar=SimulatedAvatar(),
            sensors=SimulatedSensors(),
            camera=camera_mock,
            hostname="test",
        )

    def test_quality_out_of_range_clamped(self):
        """Qualitätswerte außerhalb [1,100] werden still abgeschnitten."""
        camera = MagicMock()
        camera.is_available.return_value = True
        camera.capture_jpeg.return_value = b"\xff\xd8\xff" + b"\x00" * 100
        camera.get_resolution.return_value = (640, 480)

        server = self._create_server_with_camera(camera)
        client = TestClient(server.app, raise_server_exceptions=False)

        r = client.get("/camera/capture?quality=999")
        assert r.status_code == 200
        assert r.json()["success"] is True
        # capture_jpeg wurde mit quality=100 (geclampter Wert) aufgerufen
        called_quality = camera.capture_jpeg.call_args[1]["quality"]
        assert 1 <= called_quality <= 100

    def test_quality_negative_clamped(self):
        camera = MagicMock()
        camera.is_available.return_value = True
        camera.capture_jpeg.return_value = b"\xff\xd8\xff" + b"\x00" * 100
        camera.get_resolution.return_value = (640, 480)

        server = self._create_server_with_camera(camera)
        client = TestClient(server.app, raise_server_exceptions=False)

        r = client.get("/camera/capture?quality=-10")
        assert r.status_code == 200
        called_quality = camera.capture_jpeg.call_args[1]["quality"]
        assert called_quality == 1

    def test_empty_jpeg_returns_error(self):
        """Leere JPEG-Bytes führen zu success=False ohne Exception."""
        camera = MagicMock()
        camera.is_available.return_value = True
        camera.capture_jpeg.return_value = b""  # leeres Ergebnis
        camera.get_resolution.return_value = (640, 480)

        server = self._create_server_with_camera(camera)
        client = TestClient(server.app, raise_server_exceptions=False)

        r = client.get("/camera/capture")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False

    def test_exception_does_not_leak_details(self):
        """Exceptions im Kamera-Code dürfen nicht im Response-Text stehen."""
        camera = MagicMock()
        camera.is_available.return_value = True
        camera.capture_jpeg.side_effect = RuntimeError(
            "INTERNAL_SECRET_PATH:/dev/video0"
        )

        server = self._create_server_with_camera(camera)
        client = TestClient(server.app, raise_server_exceptions=False)

        r = client.get("/camera/capture")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "INTERNAL_SECRET_PATH" not in data.get("message", "")
