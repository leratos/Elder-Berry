"""Tests für SettingsTokenManager + SettingsTokenMiddleware (Phase 52.1a)."""

from __future__ import annotations

import os
import stat

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.web.settings_dashboard import SettingsDashboard
    from elder_berry.web.settings_token import (
        SettingsTokenError,
        SettingsTokenManager,
    )
    from elder_berry.web.settings_token_middleware import SettingsTokenMiddleware
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


# ---------------------------------------------------------------------------
# SettingsTokenManager
# ---------------------------------------------------------------------------


class TestSettingsTokenManager:
    """Token-Erzeugung, -Persistenz und -Validierung."""

    def test_generates_new_token_on_first_call(self, tmp_path):
        path = tmp_path / "settings_token"
        manager = SettingsTokenManager(path)
        assert not path.exists()
        token = manager.load_or_create()
        assert path.exists()
        assert token == path.read_text(encoding="utf-8").strip()
        assert len(token) == 64  # 32 Bytes hex

    def test_loads_existing_token(self, tmp_path):
        path = tmp_path / "settings_token"
        path.write_text("abc123def456", encoding="utf-8")
        manager = SettingsTokenManager(path)
        token = manager.load_or_create()
        assert token == "abc123def456"

    def test_regenerates_when_file_empty(self, tmp_path):
        path = tmp_path / "settings_token"
        path.write_text("", encoding="utf-8")
        manager = SettingsTokenManager(path)
        token = manager.load_or_create()
        assert token != ""
        assert len(token) == 64

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "settings_token"
        manager = SettingsTokenManager(path)
        manager.load_or_create()
        assert path.exists()

    @pytest.mark.skipif(os.name != "posix", reason="POSIX-only chmod check")
    def test_token_file_chmod_600_on_posix(self, tmp_path):
        path = tmp_path / "settings_token"
        manager = SettingsTokenManager(path)
        manager.load_or_create()
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_get_before_load_raises(self, tmp_path):
        manager = SettingsTokenManager(tmp_path / "settings_token")
        with pytest.raises(SettingsTokenError):
            manager.get()

    def test_validate_accepts_correct_token(self, tmp_path):
        manager = SettingsTokenManager(tmp_path / "settings_token")
        token = manager.load_or_create()
        assert manager.validate(token) is True

    def test_validate_rejects_wrong_token(self, tmp_path):
        manager = SettingsTokenManager(tmp_path / "settings_token")
        manager.load_or_create()
        assert manager.validate("falsch") is False

    def test_validate_rejects_none_and_empty(self, tmp_path):
        manager = SettingsTokenManager(tmp_path / "settings_token")
        manager.load_or_create()
        assert manager.validate(None) is False
        assert manager.validate("") is False

    def test_load_persists_across_instances(self, tmp_path):
        path = tmp_path / "settings_token"
        first = SettingsTokenManager(path)
        token = first.load_or_create()
        second = SettingsTokenManager(path)
        assert second.load_or_create() == token

    def test_token_length_too_small_raises(self, tmp_path):
        with pytest.raises(SettingsTokenError):
            SettingsTokenManager(tmp_path / "token", token_length=8)


# ---------------------------------------------------------------------------
# SettingsTokenMiddleware
# ---------------------------------------------------------------------------


def _make_app(token_manager: SettingsTokenManager) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SettingsTokenMiddleware, token_manager=token_manager)

    @app.get("/api/secrets/status")
    async def get_status():
        return {"ok": True}

    @app.post("/api/secrets/set")
    async def post_set():
        return {"ok": True}

    @app.post("/api/setup/step/1")
    async def post_setup():
        return {"ok": True}

    @app.post("/api/audio")
    async def post_audio():
        return {"ok": True}

    @app.post("/api/other")
    async def post_other():
        return {"ok": True}

    return app


class TestSettingsTokenMiddleware:
    """Header-Prüfung + Path-/Method-Filter."""

    @pytest.fixture
    def manager(self, tmp_path):
        m = SettingsTokenManager(tmp_path / "settings_token")
        m.load_or_create()
        return m

    @pytest.fixture
    def client(self, manager):
        return TestClient(_make_app(manager))

    def test_get_passes_without_token(self, client):
        r = client.get("/api/secrets/status")
        assert r.status_code == 200

    def test_post_without_token_rejected(self, client):
        r = client.post("/api/secrets/set", json={})
        assert r.status_code == 401
        assert "Settings-Token" in r.json()["error"]
        assert r.json()["header"] == "X-Saleria-Settings-Token"

    def test_post_with_wrong_token_rejected(self, client):
        r = client.post(
            "/api/secrets/set",
            json={},
            headers={"X-Saleria-Settings-Token": "falsch"},
        )
        assert r.status_code == 401

    def test_post_with_correct_token_accepted(self, client, manager):
        r = client.post(
            "/api/secrets/set",
            json={},
            headers={"X-Saleria-Settings-Token": manager.get()},
        )
        assert r.status_code == 200

    def test_setup_endpoint_exempt(self, client):
        r = client.post("/api/setup/step/1", json={})
        assert r.status_code == 200

    def test_audio_endpoint_protected(self, client):
        r = client.post("/api/audio", json={})
        assert r.status_code == 401

    def test_unprotected_path_passes(self, client):
        r = client.post("/api/other", json={})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Integration: SettingsDashboard mit require_settings_token=True
# ---------------------------------------------------------------------------


class TestDashboardWithToken:
    """End-to-End: Dashboard installiert die Middleware korrekt."""

    @pytest.fixture
    def dashboard(self, tmp_path):
        return SettingsDashboard(
            audio_router=AudioRouter(local_available=True),
            require_settings_token=True,
            settings_token_path=tmp_path / "settings_token",
        )

    def test_token_manager_initialized(self, dashboard):
        assert dashboard._token_manager is not None
        assert dashboard._token_manager.get()

    def test_audio_post_without_token_blocked(self, dashboard):
        client = TestClient(dashboard.app)
        r = client.post("/api/audio", json={"mode": "matrix_only"})
        assert r.status_code == 401

    def test_audio_post_with_token_succeeds(self, dashboard):
        client = TestClient(dashboard.app)
        token = dashboard._token_manager.get()
        r = client.post(
            "/api/audio",
            json={"mode": "matrix_only"},
            headers={"X-Saleria-Settings-Token": token},
        )
        assert r.status_code == 200

    def test_get_endpoints_remain_open(self, dashboard):
        client = TestClient(dashboard.app)
        r = client.get("/api/audio")
        assert r.status_code == 200

    def test_default_host_is_loopback(self):
        dashboard = SettingsDashboard(
            audio_router=AudioRouter(local_available=True),
        )
        assert dashboard._host == "127.0.0.1"
