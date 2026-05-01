"""Tests für DashboardAuthMiddleware (Phase 58)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.dashboard_auth import (
    COOKIE_NAME,
    DashboardAuthManager,
)
from elder_berry.web.dashboard_auth_middleware import (
    DashboardAuthMiddleware,
)


class _FakeStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def has(self, key: str) -> bool:
        return key in self._data


def _build_app(
    store: _FakeStore | None = None,
    with_secret_store: bool = True,
) -> tuple[FastAPI, DashboardAuthManager, _FakeStore]:
    if store is None:
        store = _FakeStore()
    auth = DashboardAuthManager(store)
    app = FastAPI()

    # Test-Endpoints für alle Pfad-Kategorien
    @app.get("/")
    async def root():
        return {"ok": True}

    @app.get("/api/secrets/status")
    async def secrets_status():
        return {"ok": True}

    @app.post("/api/settings/values")
    async def settings_set():
        return {"ok": True}

    @app.get("/api/system/health")
    async def system_health():
        return {"ok": True}

    @app.get("/api/avatar/assets")
    async def avatar_assets():
        return {"ok": True}

    @app.get("/avatar/editor")
    async def avatar_editor():
        return {"ok": True}

    @app.get("/api/dashboard/auth/status")
    async def auth_status():
        return {"authenticated": False}

    @app.post("/api/dashboard/login")
    async def login():
        return {"ok": True}

    @app.get("/api/setup/probe")
    async def setup_probe():
        return {"ok": True}

    @app.post("/api/setup/save")
    async def setup_save():
        return {"ok": True}

    @app.post("/harmony/command")
    async def harmony_command():
        return {"ok": True}

    # Phase 66: Robot-Proxy unter /api/robot/*
    @app.get("/api/robot/harmony/status")
    async def robot_proxy_status():
        return {"ok": True}

    @app.post("/api/robot/harmony/command")
    async def robot_proxy_command():
        return {"ok": True}

    @app.get("/static/style.css")
    async def static_css():
        return {"ok": True}

    app.add_middleware(
        DashboardAuthMiddleware,
        auth_manager=auth,
        secret_store=store if with_secret_store else None,
    )
    return app, auth, store


# -- Geschützte Pfade ohne Cookie -> 401 ----------------------------- #


class TestProtectedWithoutCookie:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/secrets/status"),
            ("post", "/api/settings/values"),
            ("get", "/api/system/health"),
            ("get", "/api/avatar/assets"),
            ("get", "/avatar/editor"),
            # Phase 66: Robot-Proxy darf nur eingeloggt erreicht werden,
            # sonst koennte ein nicht-authentifizierter Browser den RPi5
            # ueber die Saleria-Bruecke steuern.
            ("get", "/api/robot/harmony/status"),
            ("post", "/api/robot/harmony/command"),
        ],
    )
    def test_blocks_without_cookie(self, method: str, path: str) -> None:
        app, _, _ = _build_app()
        client = TestClient(app)
        response = getattr(client, method)(path)
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"


# -- Offene Pfade ohne Cookie -> 200 --------------------------------- #


class TestUnprotected:
    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/static/style.css",
            "/api/dashboard/auth/status",
            "/api/dashboard/login",
        ],
    )
    def test_open_endpoints_pass(self, path: str) -> None:
        app, _, _ = _build_app()
        client = TestClient(app)
        response = (
            client.get(path) if path != "/api/dashboard/login" else client.post(path)
        )
        assert response.status_code == 200

    def test_harmony_open(self) -> None:
        app, _, _ = _build_app()
        client = TestClient(app)
        response = client.post("/harmony/command")
        assert response.status_code == 200


# -- Wizard-Exemption ------------------------------------------------ #


class TestWizardExemption:
    def test_wizard_open_before_first_run(self) -> None:
        app, _, _ = _build_app()
        client = TestClient(app)
        assert client.get("/api/setup/probe").status_code == 200
        assert client.post("/api/setup/save").status_code == 200

    def test_wizard_protected_after_first_run(self) -> None:
        store = _FakeStore()
        store.set("setup_wizard_completed", "true")
        app, _, _ = _build_app(store=store)
        client = TestClient(app)
        assert client.get("/api/setup/probe").status_code == 401
        assert client.post("/api/setup/save").status_code == 401

    def test_wizard_open_when_no_secret_store(self) -> None:
        app, _, _ = _build_app(with_secret_store=False)
        client = TestClient(app)
        # Ohne SecretStore: First-Run gilt als nicht abgeschlossen
        assert client.get("/api/setup/probe").status_code == 200


# -- Mit gültigem Cookie -> 200 ------------------------------------- #


class TestWithValidCookie:
    def test_valid_cookie_passes(self) -> None:
        app, auth, _ = _build_app()
        cookie, _ = auth.issue_session()
        client = TestClient(app, cookies={COOKIE_NAME: cookie})
        response = client.get("/api/secrets/status")
        assert response.status_code == 200

    def test_invalid_cookie_blocked(self) -> None:
        app, _, _ = _build_app()
        client = TestClient(app, cookies={COOKIE_NAME: "garbage"})
        response = client.get("/api/secrets/status")
        assert response.status_code == 401

    def test_post_with_cookie_passes(self) -> None:
        app, auth, _ = _build_app()
        cookie, _ = auth.issue_session()
        client = TestClient(app, cookies={COOKIE_NAME: cookie})
        response = client.post("/api/settings/values")
        assert response.status_code == 200


# -- Sliding Renewal ------------------------------------------------- #


class TestSlidingRenewal:
    def test_old_cookie_gets_refreshed(self, monkeypatch) -> None:
        import time as time_module

        store = _FakeStore()
        auth = DashboardAuthManager(store, ttl_hours=1)
        # Cookie mit iat=1000, exp=1000+3600
        cookie, exp = auth.issue_session(now=1000)

        app = FastAPI()

        @app.get("/api/secrets/status")
        async def s():
            return {"ok": True}

        app.add_middleware(
            DashboardAuthMiddleware,
            auth_manager=auth,
            secret_store=store,
        )
        # Aktuelle Zeit so setzen, dass Restlaufzeit < ttl/2 ist:
        # ttl_seconds=3600, also wenn < 1800 Sekunden Rest.
        # exp=4600, jetzt=4000 → Rest 600 < 1800
        monkeypatch.setattr(time_module, "time", lambda: 4000)

        client = TestClient(app, cookies={COOKIE_NAME: cookie})
        response = client.get("/api/secrets/status")
        assert response.status_code == 200
        # Set-Cookie-Header muss neuen Cookie liefern
        assert COOKIE_NAME in response.headers.get("set-cookie", "")

    def test_fresh_cookie_not_refreshed(self) -> None:
        app, auth, _ = _build_app()
        cookie, _ = auth.issue_session()
        client = TestClient(app, cookies={COOKIE_NAME: cookie})
        response = client.get("/api/secrets/status")
        assert response.status_code == 200
        # Cookie ist frisch → kein Refresh erwartet
        assert COOKIE_NAME not in response.headers.get("set-cookie", "")


# -- Cache-Invalidation --------------------------------------------- #


class TestCacheInvalidation:
    def test_invalidate_after_setup_complete(self) -> None:
        store = _FakeStore()
        app, _, _ = _build_app(store=store)
        client = TestClient(app)

        # Vorher: Wizard offen
        assert client.get("/api/setup/probe").status_code == 200

        # First-Run-Marker setzen + invalidieren
        store.set("setup_wizard_completed", "true")
        from elder_berry.web.dashboard_auth_middleware import (
            invalidate_setup_completion_cache,
        )

        invalidate_setup_completion_cache()

        # Nachher: Wizard verlangt Login
        assert client.get("/api/setup/probe").status_code == 401
