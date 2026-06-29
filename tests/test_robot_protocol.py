"""Tests für Robot-Kommunikation: Protocol, Server, Client, Simulator."""

from dataclasses import asdict

import pytest

from elder_berry.robot.protocol import (
    ApiResponse,
    AvatarCommand,
    BatteryStatus,
    DriveCommand,
    DriveDirection,
    HealthResponse,
    MotorStopCommand,
    RobotStatus,
    SensorReading,
    SensorType,
)

# Server + Simulator brauchen fastapi (optional dependency)
fastapi = pytest.importorskip("fastapi", reason="fastapi nicht installiert")

from elder_berry.robot.simulator import (  # noqa: E402
    SimulatedAvatar,
    SimulatedMotors,
    SimulatedSensors,
    create_simulator,
)


# ---------------------------------------------------------------------------
# Protocol DTOs
# ---------------------------------------------------------------------------


class TestProtocolDTOs:
    def test_drive_direction_values(self):
        assert DriveDirection.FORWARD == "forward"
        assert DriveDirection.STOP == "stop"

    def test_sensor_type_values(self):
        assert SensorType.BATTERY == "battery"
        assert SensorType.CAMERA == "camera"

    def test_avatar_command_defaults(self):
        cmd = AvatarCommand()
        assert cmd.emotion is None
        assert cmd.is_speaking is None

    def test_avatar_command_with_values(self):
        cmd = AvatarCommand(emotion="angry", is_speaking=True)
        assert cmd.emotion == "angry"
        assert cmd.is_speaking is True

    def test_drive_command(self):
        cmd = DriveCommand(direction="forward", speed=0.8)
        assert cmd.direction == "forward"
        assert cmd.speed == 0.8

    def test_drive_command_defaults(self):
        cmd = DriveCommand(direction="left")
        assert cmd.speed == 0.5
        assert cmd.duration is None

    def test_motor_stop_command(self):
        cmd = MotorStopCommand(reason="obstacle")
        assert cmd.reason == "obstacle"

    def test_battery_status_defaults(self):
        bs = BatteryStatus()
        assert bs.voltage == 0.0
        assert bs.percentage == 0
        assert bs.is_charging is False
        assert bs.is_low is False

    def test_battery_status_values(self):
        bs = BatteryStatus(voltage=7.2, percentage=80, is_low=False)
        assert bs.voltage == 7.2

    def test_sensor_reading(self):
        sr = SensorReading(sensor_type="temperature", value=45.0, unit="celsius")
        assert sr.sensor_type == "temperature"
        assert sr.value == 45.0

    def test_robot_status_defaults(self):
        rs = RobotStatus()
        assert rs.online is True
        assert rs.motors_active is False
        assert rs.current_direction == "stop"
        assert rs.avatar_emotion == "neutral"

    def test_health_response(self):
        hr = HealthResponse(status="ok", hostname="test", uptime=42.0)
        assert hr.status == "ok"
        assert hr.uptime == 42.0

    def test_api_response(self):
        ar = ApiResponse(success=True, message="done")
        assert ar.success is True
        assert ar.data is None

    def test_api_response_with_data(self):
        ar = ApiResponse(success=True, data={"key": "value"})
        assert ar.data == {"key": "value"}

    def test_robot_status_serializable(self):
        rs = RobotStatus()
        d = asdict(rs)
        assert isinstance(d, dict)
        assert d["online"] is True


# ---------------------------------------------------------------------------
# Simulator Mock-Klassen
# ---------------------------------------------------------------------------


class TestSimulatedMotors:
    def test_initial_state_stopped(self):
        m = SimulatedMotors()
        state = m.get_state()
        assert state["active"] is False
        assert state["direction"] == "stop"
        assert state["speed"] == 0.0

    def test_drive_sets_state(self):
        m = SimulatedMotors()
        m.drive("forward", 0.7)
        state = m.get_state()
        assert state["active"] is True
        assert state["direction"] == "forward"
        assert state["speed"] == 0.7

    def test_stop_resets_state(self):
        m = SimulatedMotors()
        m.drive("left", 1.0)
        m.stop()
        state = m.get_state()
        assert state["active"] is False
        assert state["direction"] == "stop"

    def test_speed_clamped(self):
        m = SimulatedMotors()
        m.drive("forward", 1.5)
        assert m.get_state()["speed"] == 1.0
        m.drive("forward", -0.5)
        assert m.get_state()["speed"] == 0.0


class TestSimulatedAvatar:
    def test_initial_state_neutral(self):
        a = SimulatedAvatar()
        state = a.get_state()
        assert state["emotion"] == "neutral"
        assert state["speaking"] is False

    def test_set_emotion(self):
        a = SimulatedAvatar()
        a.set_emotion("angry")
        assert a.get_state()["emotion"] == "angry"

    def test_set_speaking(self):
        a = SimulatedAvatar()
        a.set_speaking(True)
        assert a.get_state()["speaking"] is True

    def test_set_speaking_ignores_audio_meta(self):
        # 83.4: Simulator hat keinen Lip-Sync → audio_meta wird ignoriert.
        from elder_berry.core.audio_analyzer import AmplitudeTrack

        a = SimulatedAvatar()
        a.set_speaking(True, audio_meta=AmplitudeTrack(samples=[0.5], duration_ms=50))
        assert a.get_state()["speaking"] is True


class TestSimulatedSensors:
    def test_battery_initial_values(self):
        s = SimulatedSensors()
        b = s.get_battery()
        assert b.percentage == 85
        assert b.voltage > 7.0
        assert b.is_low is False

    def test_battery_voltage_range(self):
        s = SimulatedSensors()
        b = s.get_battery()
        assert 6.0 <= b.voltage <= 7.4

    def test_get_all_has_expected_keys(self):
        s = SimulatedSensors()
        data = s.get_all()
        assert "battery" in data
        assert "temperature" in data
        assert "ir" in data

    def test_temperature_values_realistic(self):
        s = SimulatedSensors()
        data = s.get_all()
        cpu = data["temperature"]["cpu"]
        assert 40.0 <= cpu <= 55.0


# ---------------------------------------------------------------------------
# Server + Client Integration (FastAPI TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    """Erstellt einen RobotServer mit simulierter Hardware."""
    return create_simulator()


@pytest.fixture
def client(server):
    """FastAPI TestClient für den RobotServer."""
    from fastapi.testclient import TestClient

    return TestClient(server.app)


class TestServerHealth:
    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["hostname"] == "elder-berry-simulator"
        assert data["uptime"] >= 0

    def test_status_endpoint(self, client):
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["online"] is True
        assert data["avatar_emotion"] == "neutral"
        assert data["motors_active"] is False


class TestServerAvatar:
    def test_set_emotion(self, client):
        r = client.post("/avatar/emotion", json={"emotion": "angry"})
        assert r.status_code == 200
        assert r.json()["success"] is True

        # Status prüfen
        status = client.get("/status").json()
        assert status["avatar_emotion"] == "angry"

    def test_set_speaking(self, client):
        r = client.post("/avatar/emotion", json={"is_speaking": True})
        assert r.status_code == 200

        status = client.get("/status").json()
        assert status["avatar_speaking"] is True

    def test_set_both(self, client):
        r = client.post(
            "/avatar/emotion",
            json={"emotion": "cheerful", "is_speaking": True},
        )
        assert r.status_code == 200

        status = client.get("/status").json()
        assert status["avatar_emotion"] == "cheerful"
        assert status["avatar_speaking"] is True

    def test_set_emotion_with_decision_logs_and_sets(self, client):
        # Phase 83.5: additives decision-Feld – die Emotion wird normal gesetzt,
        # die Decision dient nur dem Server-Logging (kein Verhaltenswechsel).
        r = client.post(
            "/avatar/emotion",
            json={
                "emotion": "cheerful",
                "decision": {
                    "emotion": "cheerful",
                    "confidence": 0.7,
                    "source": "llm_tag",
                },
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        status = client.get("/status").json()
        assert status["avatar_emotion"] == "cheerful"

    def test_decision_without_emotion_is_ignored(self, client):
        # Ohne emotion bleibt der Emotion-Block (inkl. decision-Logging) inaktiv.
        r = client.post(
            "/avatar/emotion",
            json={
                "is_speaking": True,
                "decision": {
                    "emotion": "angry",
                    "confidence": 0.9,
                    "source": "llm_tag",
                },
            },
        )
        assert r.status_code == 200
        status = client.get("/status").json()
        assert status["avatar_emotion"] == "neutral"


class TestServerAvatarAmplitude:
    """Phase 83.4: additive amplitude-Felder werden zum AmplitudeTrack geroutet."""

    def _server_with_capturing_avatar(self):
        from elder_berry.robot.server import AvatarDisplay, RobotServer
        from elder_berry.robot.simulator import SimulatedMotors, SimulatedSensors

        captured: dict = {}

        class CapturingAvatar(AvatarDisplay):
            def set_emotion(self, emotion: str, confidence: float = 1.0) -> None:
                captured["emotion"] = emotion
                captured["confidence"] = confidence

            def set_speaking(self, is_speaking, audio_meta=None) -> None:
                captured["is_speaking"] = is_speaking
                captured["audio_meta"] = audio_meta

            def get_state(self) -> dict:
                return {"emotion": "neutral", "speaking": False}

        server = RobotServer(
            motors=SimulatedMotors(),
            avatar=CapturingAvatar(),
            sensors=SimulatedSensors(),
        )
        return server, captured

    def _client(self, server):
        from fastapi.testclient import TestClient

        return TestClient(server.app)

    def test_amplitude_routed_as_track(self):
        server, captured = self._server_with_capturing_avatar()
        r = self._client(server).post(
            "/avatar/emotion",
            json={
                "is_speaking": True,
                "amplitude": [0.1, 0.9],
                "amplitude_duration_ms": 100,
            },
        )
        assert r.status_code == 200
        track = captured["audio_meta"]
        assert track is not None
        assert track.samples == [0.1, 0.9]
        assert track.duration_ms == 100

    def test_no_amplitude_means_no_track(self):
        server, captured = self._server_with_capturing_avatar()
        self._client(server).post("/avatar/emotion", json={"is_speaking": True})
        assert captured["is_speaking"] is True
        assert captured["audio_meta"] is None

    def test_duration_derived_when_missing(self):
        server, captured = self._server_with_capturing_avatar()
        self._client(server).post(
            "/avatar/emotion",
            json={"is_speaking": True, "amplitude": [0.2, 0.3, 0.4]},
        )
        # 3 Buckets × 50ms = 150ms abgeleitet.
        assert captured["audio_meta"].duration_ms == 150

    def test_backward_compatible_without_amplitude_fields(self):
        # Alt-Client ohne amplitude-Felder bleibt gültig (rückwärtskompatibel).
        server, _ = self._server_with_capturing_avatar()
        r = self._client(server).post(
            "/avatar/emotion", json={"emotion": "angry", "is_speaking": False}
        )
        assert r.status_code == 200

    def test_amplitude_over_cap_rejected(self):
        # Übergroße amplitude-Liste → 422 (Memory-DoS-Schutz, Codex P2).
        from elder_berry.robot.server import MAX_AMPLITUDE_SAMPLES

        server, captured = self._server_with_capturing_avatar()
        huge = [0.1] * (MAX_AMPLITUDE_SAMPLES + 1)
        r = self._client(server).post(
            "/avatar/emotion", json={"is_speaking": True, "amplitude": huge}
        )
        assert r.status_code == 422
        assert "is_speaking" not in captured  # Avatar nie erreicht


class TestServerMotors:
    def test_drive_forward(self, client):
        r = client.post(
            "/motor/drive",
            json={"direction": "forward", "speed": 0.8},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

        status = client.get("/status").json()
        assert status["motors_active"] is True
        assert status["current_direction"] == "forward"

    def test_stop(self, client):
        client.post("/motor/drive", json={"direction": "forward"})
        r = client.post("/motor/stop", json={"reason": "test"})
        assert r.status_code == 200

        status = client.get("/status").json()
        assert status["motors_active"] is False
        assert status["current_direction"] == "stop"


class TestServerSensors:
    def test_battery_endpoint(self, client):
        r = client.get("/sensor/battery")
        assert r.status_code == 200
        data = r.json()
        assert "voltage" in data
        assert "percentage" in data
        assert data["percentage"] == 85

    def test_all_sensors_endpoint(self, client):
        r = client.get("/sensor/all")
        assert r.status_code == 200
        data = r.json()
        assert "battery" in data
        assert "temperature" in data
        assert "ir" in data
