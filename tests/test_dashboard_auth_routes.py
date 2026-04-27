"""Tests für Dashboard-Auth-Endpoints (Phase 58)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.dashboard_auth import (
    COOKIE_NAME,
    DashboardAuthManager,
)
from elder_berry.web.dashboard_auth_routes import (
    register_dashboard_auth_routes,
)


class _FakeStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get_or_none(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value

    def has(self, key):
        return key in self._data


@pytest.fixture
def auth() -> DashboardAuthManager:
    return DashboardAuthManager(_FakeStore())


@pytest.fixture
def client(auth: DashboardAuthManager) -> TestClient:
    app = FastAPI()
    register_dashboard_auth_routes(app, auth)
    return TestClient(app)


# -- /api/dashboard/auth/status -------------------------------------- #

class TestAuthStatus:
    def test_initial_state_no_password(
        self, client: TestClient
    ) -> None:
        r = client.get("/api/dashboard/auth/status")
        assert r.status_code == 200
        data = r.json()
        assert data["authenticated"] is False
        assert data["password_set"] is False
        assert data["expires_at"] is None

    def test_password_set_unauthenticated(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        r = client.get("/api/dashboard/auth/status")
        data = r.json()
        assert data["password_set"] is True
        assert data["authenticated"] is False

    def test_authenticated_with_valid_cookie(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        cookie, exp = auth.issue_session()
        client.cookies.set(COOKIE_NAME, cookie)
        r = client.get("/api/dashboard/auth/status")
        data = r.json()
        assert data["authenticated"] is True
        assert data["expires_at"] == exp


# -- /api/dashboard/login -------------------------------------------- #

class TestLogin:
    def test_login_no_password_set(
        self, client: TestClient
    ) -> None:
        r = client.post(
            "/api/dashboard/login",
            json={"password": "anything"},
        )
        assert r.status_code == 409
        assert r.json()["code"] == "password_not_set"

    def test_login_correct_password(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        r = client.post(
            "/api/dashboard/login",
            json={"password": "supersecret123"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "expires_at" in r.json()
        # Cookie wurde gesetzt
        assert COOKIE_NAME in r.cookies

    def test_login_wrong_password(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        r = client.post(
            "/api/dashboard/login",
            json={"password": "wrong"},
        )
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_password"

    def test_login_missing_password(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        r = client.post("/api/dashboard/login", json={})
        assert r.status_code == 400
        assert r.json()["code"] == "missing_password"

    def test_login_empty_body(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        r = client.post("/api/dashboard/login")
        assert r.status_code == 400


# -- /api/dashboard/logout ------------------------------------------- #

class TestLogout:
    def test_logout_clears_cookie(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        cookie, _ = auth.issue_session()
        client.cookies.set(COOKIE_NAME, cookie)
        r = client.post("/api/dashboard/logout")
        assert r.status_code == 200
        # Set-Cookie löscht durch leeren Wert / Max-Age=0
        sc = r.headers.get("set-cookie", "")
        assert COOKIE_NAME in sc

    def test_logout_works_without_cookie(
        self, client: TestClient
    ) -> None:
        r = client.post("/api/dashboard/logout")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Phase 70 (H-1): Server-side Revocation auf Logout
# ---------------------------------------------------------------------------


class TestLogoutServerSideRevocation:
    """Logout darf den HMAC-Token nicht nur browser-seitig entwerten."""

    def _build(self):
        from elder_berry.web.session_revocation_list import (
            SessionRevocationList,
        )

        store = _FakeStore()
        rl = SessionRevocationList()
        auth = DashboardAuthManager(store, revocation_list=rl)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        register_dashboard_auth_routes(app, auth)
        return TestClient(app), auth, rl

    def test_logout_marks_cookie_revoked(self) -> None:
        client, auth, rl = self._build()
        auth.set_password("supersecret123")
        cookie, _ = auth.issue_session()
        client.cookies.set(COOKIE_NAME, cookie)

        r = client.post("/api/dashboard/logout")
        assert r.status_code == 200
        assert r.json()["revoked"] is True
        # verify_session muss diesen Cookie nun ablehnen
        from elder_berry.web.dashboard_auth import InvalidSessionError
        with pytest.raises(InvalidSessionError):
            auth.verify_session(cookie)

    def test_stolen_cookie_after_logout_is_dead(self) -> None:
        """Szenario: Angreifer hat den Cookie kopiert. Nutzer logged sich
        aus. Angreifer-Replay muss scheitern."""
        client, auth, rl = self._build()
        auth.set_password("supersecret123")
        cookie, _ = auth.issue_session()
        client.cookies.set(COOKIE_NAME, cookie)

        # Logout
        client.post("/api/dashboard/logout")

        # auth/status mit altem Cookie -> nicht mehr authenticated
        # (wir setzen den Cookie manuell, weil delete_cookie() ihn aus
        # dem Test-Client entfernt hat)
        client.cookies.set(COOKIE_NAME, cookie)
        r = client.get("/api/dashboard/auth/status")
        data = r.json()
        assert data["authenticated"] is False

    def test_logout_without_cookie_does_not_crash(self) -> None:
        client, _, _ = self._build()
        r = client.post("/api/dashboard/logout")
        assert r.status_code == 200
        assert r.json()["revoked"] is False

    def test_logout_with_invalid_cookie_does_not_revoke(self) -> None:
        client, _, rl = self._build()
        client.cookies.set(COOKIE_NAME, "definitely-not.a-valid-cookie")
        r = client.post("/api/dashboard/logout")
        assert r.status_code == 200
        assert r.json()["revoked"] is False
        assert len(rl) == 0


# -- /api/dashboard/password ----------------------------------------- #

class TestChangePassword:
    def test_set_initial_password(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        # Noch kein PW gesetzt → kein current_password nötig
        r = client.post(
            "/api/dashboard/password",
            json={"new_password": "newsecret123"},
        )
        assert r.status_code == 200
        assert auth.is_password_set()
        assert auth.verify_password("newsecret123")

    def test_change_with_correct_current(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("oldsecret123")
        r = client.post(
            "/api/dashboard/password",
            json={
                "current_password": "oldsecret123",
                "new_password": "newsecret123",
            },
        )
        assert r.status_code == 200
        assert auth.verify_password("newsecret123")

    def test_change_with_wrong_current(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("oldsecret123")
        r = client.post(
            "/api/dashboard/password",
            json={
                "current_password": "wrong",
                "new_password": "newsecret123",
            },
        )
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_current_password"
        # Altes PW bleibt aktiv
        assert auth.verify_password("oldsecret123")

    def test_change_with_weak_new_password(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("oldsecret123")
        r = client.post(
            "/api/dashboard/password",
            json={
                "current_password": "oldsecret123",
                "new_password": "short",
            },
        )
        assert r.status_code == 400
        assert r.json()["code"] == "weak_password"

    def test_change_returns_fresh_cookie(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("oldsecret123")
        r = client.post(
            "/api/dashboard/password",
            json={
                "current_password": "oldsecret123",
                "new_password": "newsecret123",
            },
        )
        assert COOKIE_NAME in r.cookies

    def test_change_missing_new_password(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("oldsecret123")
        r = client.post(
            "/api/dashboard/password",
            json={"current_password": "oldsecret123"},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Phase 65 (M-4): /api/dashboard/logout-all
# ---------------------------------------------------------------------------


class TestLogoutAll:
    """Globales Logout -- rotiert das Session-Secret."""

    def test_requires_login_cookie(
        self, client: TestClient
    ) -> None:
        r = client.post("/api/dashboard/logout-all")
        assert r.status_code == 401
        assert r.json()["code"] == "auth_required"

    def test_rejects_invalid_cookie(
        self, client: TestClient
    ) -> None:
        client.cookies.set(COOKIE_NAME, "not.a.valid.cookie")
        r = client.post("/api/dashboard/logout-all")
        assert r.status_code == 401

    def test_rotates_secret(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        old_cookie, _ = auth.issue_session()
        client.cookies.set(COOKIE_NAME, old_cookie)

        # Vor Rotation: altes Cookie ist gueltig
        auth.verify_session(old_cookie)

        r = client.post("/api/dashboard/logout-all")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Nach Rotation: altes Cookie wird mit InvalidSessionError abgelehnt
        from elder_berry.web.dashboard_auth import InvalidSessionError
        with pytest.raises(InvalidSessionError):
            auth.verify_session(old_cookie)

    def test_returns_fresh_cookie_for_caller(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        old_cookie, _ = auth.issue_session()
        client.cookies.set(COOKIE_NAME, old_cookie)

        r = client.post("/api/dashboard/logout-all")
        assert r.status_code == 200
        assert COOKIE_NAME in r.cookies

        new_cookie = r.cookies[COOKIE_NAME]
        assert new_cookie != old_cookie
        # Neues Cookie muss mit rotiertem Secret verifizierbar sein
        auth.verify_session(new_cookie)

    def test_other_sessions_become_invalid(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        """Szenario: zwei Geraete mit je eigenem Cookie. Device A
        triggert logout-all. Device B's Cookie ist danach ungueltig."""
        auth.set_password("supersecret123")
        cookie_a, _ = auth.issue_session()
        cookie_b, _ = auth.issue_session()

        # Verify beide gueltig initial
        auth.verify_session(cookie_a)
        auth.verify_session(cookie_b)

        # Device A ruft logout-all
        client.cookies.set(COOKIE_NAME, cookie_a)
        r = client.post("/api/dashboard/logout-all")
        assert r.status_code == 200

        # Device B's Cookie ist jetzt tot
        from elder_berry.web.dashboard_auth import InvalidSessionError
        with pytest.raises(InvalidSessionError):
            auth.verify_session(cookie_b)

    def test_returns_new_expiry(
        self, client: TestClient, auth: DashboardAuthManager
    ) -> None:
        auth.set_password("supersecret123")
        cookie, _ = auth.issue_session()
        client.cookies.set(COOKIE_NAME, cookie)

        r = client.post("/api/dashboard/logout-all")
        assert "expires_at" in r.json()
        assert isinstance(r.json()["expires_at"], int)
