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
        assert any("robot_token" in m.lower() or "elder_berry_robot_token" in m.lower()
                   for m in messages), (
            f"Erwartetes Token-Warning nicht gefunden. Logs: {messages}"
        )

    def test_warning_logged_when_empty_string(self, caplog):
        with caplog.at_level(logging.WARNING, logger="elder_berry.robot.server"):
            _create_server(robot_token="")
        messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("robot_token" in m.lower() or "elder_berry_robot_token" in m.lower()
                   for m in messages), (
            f"Erwartetes Token-Warning für leeren String nicht gefunden. Logs: {messages}"
        )

    def test_no_warning_when_token_set(self, caplog):
        with caplog.at_level(logging.WARNING, logger="elder_berry.robot.server"):
            _create_server(robot_token="supersecrettoken123")
        warning_messages = [
            r.message for r in caplog.records
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
