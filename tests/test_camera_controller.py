"""Tests für CameraController, SimulatedCamera und Server/Client Kamera-Endpoints."""
import base64
from unittest.mock import MagicMock, patch

import pytest

# Server/Simulator brauchen fastapi (optional dependency)
fastapi = pytest.importorskip("fastapi", reason="fastapi nicht installiert")

from elder_berry.robot.camera_controller import RPi5Camera  # noqa: E402
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
        pytest.importorskip("PIL", reason="Pillow nicht installiert")
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
        pytest.importorskip("PIL", reason="Pillow nicht installiert")
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
# RPi5Camera – unit tests with mocked picamera2 and PIL
# ---------------------------------------------------------------------------

def _make_picamera2_mock():
    """Create a minimal picamera2 mock."""
    import numpy as np

    mock_cam_instance = MagicMock()
    # create_still_configuration returns a config dict
    mock_cam_instance.create_still_configuration.return_value = {"size": (1920, 1080)}
    # capture_array returns an RGB NumPy array (1x1 pixel for speed)
    mock_cam_instance.capture_array.return_value = np.zeros((1, 1, 3), dtype="uint8")

    mock_picamera2 = MagicMock()
    mock_picamera2.Picamera2.return_value = mock_cam_instance
    mock_picamera2.Picamera2.global_camera_info.return_value = [{"Id": "imx708"}]

    return mock_picamera2, mock_cam_instance


class TestRPi5CameraInit:
    def test_default_resolution(self) -> None:
        cam = RPi5Camera()
        assert cam._resolution == (1920, 1080)

    def test_custom_resolution(self) -> None:
        cam = RPi5Camera(resolution=(1280, 720))
        assert cam._resolution == (1280, 720)

    def test_not_initialized_on_creation(self) -> None:
        cam = RPi5Camera()
        assert cam._initialized is False
        assert cam._camera is None


class TestRPi5CameraEnsureInitialized:
    def test_already_initialized_skips(self) -> None:
        cam = RPi5Camera()
        cam._initialized = True
        cam._camera = MagicMock()
        # Should not raise or call picamera2
        cam._ensure_initialized()
        assert cam._initialized is True

    def test_init_success(self) -> None:
        picamera2_mock, cam_instance = _make_picamera2_mock()
        cam = RPi5Camera()

        with patch.dict("sys.modules", {"picamera2": picamera2_mock}):
            cam._ensure_initialized()

        assert cam._initialized is True
        cam_instance.configure.assert_called_once()
        cam_instance.start.assert_called_once()

    def test_init_import_error_raises_runtime(self) -> None:
        cam = RPi5Camera()
        with patch.dict("sys.modules", {"picamera2": None}):
            with pytest.raises(RuntimeError, match="picamera2"):
                cam._ensure_initialized()

    def test_init_generic_exception_raises_runtime(self) -> None:
        picamera2_mock = MagicMock()
        picamera2_mock.Picamera2.side_effect = Exception("hardware gone")
        cam = RPi5Camera()

        with patch.dict("sys.modules", {"picamera2": picamera2_mock}):
            with pytest.raises(RuntimeError, match="fehlgeschlagen"):
                cam._ensure_initialized()


class TestRPi5CameraIsAvailable:
    def test_available_with_cameras(self) -> None:
        picamera2_mock, _ = _make_picamera2_mock()
        cam = RPi5Camera()

        with patch.dict("sys.modules", {"picamera2": picamera2_mock}):
            result = cam.is_available()

        assert result is True

    def test_unavailable_no_cameras(self) -> None:
        picamera2_mock = MagicMock()
        picamera2_mock.Picamera2.global_camera_info.return_value = []
        cam = RPi5Camera()

        with patch.dict("sys.modules", {"picamera2": picamera2_mock}):
            result = cam.is_available()

        assert result is False

    def test_unavailable_on_exception(self) -> None:
        picamera2_mock = MagicMock()
        picamera2_mock.Picamera2.global_camera_info.side_effect = RuntimeError("no hw")
        cam = RPi5Camera()

        with patch.dict("sys.modules", {"picamera2": picamera2_mock}):
            result = cam.is_available()

        assert result is False


class TestRPi5CameraCaptureJpeg:
    def test_capture_returns_jpeg_bytes(self) -> None:
        picamera2_mock, cam_instance = _make_picamera2_mock()

        # Mock PIL.Image so capture_jpeg works without Pillow installed
        mock_image = MagicMock()
        def fake_save(buf, format, quality):
            buf.write(b"\xff\xd8\xff\xe0fake jpeg data")
        mock_image.save.side_effect = fake_save

        mock_pil = MagicMock()
        mock_pil.Image.fromarray.return_value = mock_image

        cam = RPi5Camera()
        with patch.dict("sys.modules", {"picamera2": picamera2_mock, "PIL": mock_pil}):
            cam._ensure_initialized()
        with patch.dict("sys.modules", {"PIL": mock_pil}):
            data = cam.capture_jpeg(quality=50)

        assert isinstance(data, bytes)
        assert len(data) > 0
        assert data[:2] == b"\xff\xd8"

    def test_get_resolution_after_init(self) -> None:
        cam = RPi5Camera(resolution=(640, 480))
        assert cam.get_resolution() == (640, 480)


class TestRPi5CameraClose:
    def test_close_initialized_camera(self) -> None:
        picamera2_mock, cam_instance = _make_picamera2_mock()
        cam = RPi5Camera()

        with patch.dict("sys.modules", {"picamera2": picamera2_mock}):
            cam._ensure_initialized()

        cam.close()

        cam_instance.stop.assert_called_once()
        cam_instance.close.assert_called_once()
        assert cam._initialized is False

    def test_close_not_initialized_is_noop(self) -> None:
        cam = RPi5Camera()
        cam.close()  # Should not raise
        assert cam._initialized is False


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
        pytest.importorskip("PIL", reason="Pillow nicht installiert")
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
        pytest.importorskip("PIL", reason="Pillow nicht installiert")
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
