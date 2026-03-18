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
        assert "Elder-Berry Audio" in r.text

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
