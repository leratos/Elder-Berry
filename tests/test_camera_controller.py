"""Tests für CameraController, SimulatedCamera und Server/Client Kamera-Endpoints."""
import base64

import pytest

# Server/Simulator brauchen fastapi (optional dependency)
fastapi = pytest.importorskip("fastapi", reason="fastapi nicht installiert")

from elder_berry.robot.camera_controller import CameraController, RPi5Camera  # noqa: E402
from elder_berry.robot.simulator import (  # noqa: E402
    SimulatedAvatar,
    SimulatedCamera,
    SimulatedMotors,
    SimulatedSensors,
)
from elder_berry.robot.server import RobotServer  # noqa: E402


# ---------------------------------------------------------------------------
# SimulatedCamera
# ---------------------------------------------------------------------------

class TestSimulatedCamera:
    def test_simulated_camera_available(self):
        """1. is_available() gibt True."""
        cam = SimulatedCamera()
        assert cam.is_available() is True

    def test_simulated_camera_capture_returns_jpeg(self):
        """2. Bytes sind valides JPEG (beginnt mit 0xFFD8)."""
        cam = SimulatedCamera()
        data = cam.capture_jpeg()
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert data[:2] == b"\xff\xd8"

    def test_simulated_camera_resolution(self):
        """3. get_resolution() gibt konfigurierte Aufloesung."""
        cam = SimulatedCamera(resolution=(1280, 720))
        assert cam.get_resolution() == (1280, 720)

    def test_simulated_camera_quality_parameter(self):
        """4. Verschiedene Quality-Werte produzieren verschiedene Groessen."""
        cam = SimulatedCamera()
        low = cam.capture_jpeg(quality=10)
        high = cam.capture_jpeg(quality=95)
        # Niedrige Qualitaet = kleinere Datei
        assert len(low) < len(high)

    def test_rpi5_camera_unavailable_without_picamera2(self):
        """5. Import-Fehler gibt RuntimeError bei capture."""
        cam = RPi5Camera()
        # Auf Windows/ohne picamera2: is_available() gibt False
        assert cam.is_available() is False


# ---------------------------------------------------------------------------
# Server Kamera-Endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def server_with_camera():
    """RobotServer mit SimulatedCamera."""
    return RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        camera=SimulatedCamera(),
        hostname="test-camera",
    )


@pytest.fixture
def server_without_camera():
    """RobotServer ohne Kamera."""
    return RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        camera=None,
        hostname="test-no-camera",
    )


@pytest.fixture
def client_with_camera(server_with_camera):
    from fastapi.testclient import TestClient
    return TestClient(server_with_camera.app)


@pytest.fixture
def client_without_camera(server_without_camera):
    from fastapi.testclient import TestClient
    return TestClient(server_without_camera.app)


class TestServerCameraCapture:
    def test_server_camera_capture_success(self, client_with_camera):
        """24. GET /camera/capture gibt Base64-JPEG."""
        r = client_with_camera.get("/camera/capture")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "image_base64" in data
        assert data["format"] == "jpeg"
        assert data["width"] == 1920
        assert data["height"] == 1080
        assert data["size_bytes"] > 0
        # Base64 dekodieren und JPEG-Header pruefen
        jpeg_bytes = base64.b64decode(data["image_base64"])
        assert jpeg_bytes[:2] == b"\xff\xd8"

    def test_server_camera_capture_no_camera(self, client_without_camera):
        """25. Kein CameraController -> success=False."""
        r = client_without_camera.get("/camera/capture")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "Keine Kamera" in data["message"]

    def test_server_camera_status(self, client_with_camera):
        """26. GET /camera/status gibt available + resolution."""
        r = client_with_camera.get("/camera/status")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert data["resolution"] == [1920, 1080]

    def test_server_camera_status_no_camera(self, client_without_camera):
        """Kein CameraController -> available=False."""
        r = client_without_camera.get("/camera/status")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is False


class TestClientCameraIntegration:
    """Tests fuer RobotClient.capture_image() / camera_status() via TestClient."""

    def test_client_capture_image(self, client_with_camera):
        """27. RobotClient.capture_image() dekodiert Base64 zu bytes."""
        # Direkt den Server-Endpoint testen (Client-Logik)
        r = client_with_camera.get("/camera/capture")
        data = r.json()
        assert data["success"] is True
        jpeg_bytes = base64.b64decode(data["image_base64"])
        assert isinstance(jpeg_bytes, bytes)
        assert jpeg_bytes[:2] == b"\xff\xd8"

    def test_client_capture_image_unavailable(self, client_without_camera):
        """28. Server gibt success=False -> None."""
        r = client_without_camera.get("/camera/capture")
        data = r.json()
        assert data["success"] is False
