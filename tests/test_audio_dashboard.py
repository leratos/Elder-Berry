"""Tests für AudioDashboard – FastAPI Web-UI für Audio-Routing."""

import pytest

from elder_berry.core.audio_router import AudioOutputMode, AudioRouter

try:
    from fastapi.testclient import TestClient
    from elder_berry.web.audio_dashboard import AudioDashboard
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


@pytest.fixture
def router_local():
    """AudioRouter mit lokaler Wiedergabe verfügbar."""
    return AudioRouter(local_available=True)


@pytest.fixture
def router_no_local():
    """AudioRouter ohne lokale Wiedergabe."""
    return AudioRouter(local_available=False)


@pytest.fixture
def client_local(router_local):
    """TestClient mit lokaler Wiedergabe."""
    dashboard = AudioDashboard(audio_router=router_local)
    return TestClient(dashboard.app)


@pytest.fixture
def client_no_local(router_no_local):
    """TestClient ohne lokale Wiedergabe."""
    dashboard = AudioDashboard(audio_router=router_no_local)
    return TestClient(dashboard.app)


class TestDashboardHTML:
    """GET / – HTML-Dashboard."""

    def test_returns_html(self, client_local):
        r = client_local.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_contains_title(self, client_local):
        r = client_local.get("/")
        assert "Elder-Berry Settings" in r.text

    def test_contains_toggle_button(self, client_local):
        r = client_local.get("/")
        assert "toggleBtn" in r.text


class TestGetAudioMode:
    """GET /api/audio – aktuellen Modus abfragen."""

    def test_default_matrix_only(self, client_local):
        r = client_local.get("/api/audio")
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "matrix_only"
        assert data["local_available"] is True
        assert data["play_local"] is False

    def test_no_local_available(self, client_no_local):
        r = client_no_local.get("/api/audio")
        data = r.json()
        assert data["local_available"] is False


class TestPostAudioMode:
    """POST /api/audio – Modus setzen/togglen."""

    def test_toggle_to_local(self, client_local):
        r = client_local.post("/api/audio")
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "matrix_and_local"
        assert data["play_local"] is True

    def test_toggle_back(self, client_local):
        client_local.post("/api/audio")
        r = client_local.post("/api/audio")
        data = r.json()
        assert data["mode"] == "matrix_only"

    def test_set_explicit_mode(self, client_local):
        r = client_local.post(
            "/api/audio",
            json={"mode": "matrix_and_local"},
        )
        data = r.json()
        assert data["mode"] == "matrix_and_local"

    def test_set_matrix_only_explicit(self, client_local):
        # Erst auf local setzen
        client_local.post("/api/audio", json={"mode": "matrix_and_local"})
        # Dann zurück
        r = client_local.post("/api/audio", json={"mode": "matrix_only"})
        data = r.json()
        assert data["mode"] == "matrix_only"

    def test_invalid_mode_400(self, client_local):
        r = client_local.post("/api/audio", json={"mode": "invalid"})
        assert r.status_code == 400
        assert "Ungültiger Modus" in r.json()["error"]

    def test_toggle_no_local_stays_matrix(self, client_no_local):
        r = client_no_local.post("/api/audio")
        data = r.json()
        assert data["mode"] == "matrix_only"

    def test_set_local_no_capability_stays(self, client_no_local):
        r = client_no_local.post(
            "/api/audio",
            json={"mode": "matrix_and_local"},
        )
        data = r.json()
        assert data["mode"] == "matrix_only"


# ===========================================================================
# Monitor-Auswahl (Computer Use)
# ===========================================================================

class TestGetMonitors:
    """GET /api/monitors – Monitor-Liste abfragen."""

    def test_no_computer_use(self, client_local):
        r = client_local.get("/api/monitors")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is False
        assert data["monitors"] == []
        assert data["selected"] == 1

    def test_with_computer_use(self, router_local):
        from unittest.mock import MagicMock
        mock_cu = MagicMock()
        mock_cu.get_available_monitors.return_value = [
            {"index": 1, "width": 1920, "height": 1080, "left": 0, "top": 0},
            {"index": 2, "width": 2560, "height": 1440, "left": 1920, "top": 0},
        ]
        mock_cu.monitor_index = 1
        dashboard = AudioDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.get("/api/monitors")
        data = r.json()
        assert data["available"] is True
        assert len(data["monitors"]) == 2
        assert data["selected"] == 1


class TestSetMonitor:
    """POST /api/monitor – Monitor setzen."""

    def test_no_computer_use(self, client_local):
        r = client_local.post("/api/monitor", json={"index": 1})
        assert r.status_code == 400
        assert "nicht verfügbar" in r.json()["error"]

    def test_missing_index(self, router_local):
        from unittest.mock import MagicMock
        mock_cu = MagicMock()
        dashboard = AudioDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.post("/api/monitor", json={})
        assert r.status_code == 400
        assert "fehlt" in r.json()["error"]

    def test_invalid_index(self, router_local):
        from unittest.mock import MagicMock
        mock_cu = MagicMock()
        mock_cu.get_available_monitors.return_value = [
            {"index": 1, "width": 1920, "height": 1080, "left": 0, "top": 0},
        ]
        dashboard = AudioDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.post("/api/monitor", json={"index": 5})
        assert r.status_code == 400
        assert "nicht verfügbar" in r.json()["error"]

    def test_valid_set(self, router_local):
        from unittest.mock import MagicMock
        mock_cu = MagicMock()
        mock_cu.get_available_monitors.return_value = [
            {"index": 1, "width": 1920, "height": 1080, "left": 0, "top": 0},
            {"index": 2, "width": 2560, "height": 1440, "left": 1920, "top": 0},
        ]
        mock_cu.monitor_index = 1
        dashboard = AudioDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.post("/api/monitor", json={"index": 2})
        assert r.status_code == 200
        data = r.json()
        assert data["selected"] == 2
        # Verify setter was called
        assert mock_cu.monitor_index == 2

    def test_html_contains_monitor_section(self, router_local):
        from unittest.mock import MagicMock
        mock_cu = MagicMock()
        dashboard = AudioDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.get("/")
        assert "monitorSelect" in r.text
        assert "Computer Use Monitor" in r.text
