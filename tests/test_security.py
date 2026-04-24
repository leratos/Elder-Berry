"""Tests für Sicherheits-Features: Security Headers, CORS, Exception-Handler."""

import pytest

from elder_berry.core.audio_router import AudioRouter

try:
    from fastapi.testclient import TestClient
    from elder_berry.web.settings_dashboard import SettingsDashboard

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


class FakeSecretStore:
    """Minimaler In-Memory SecretStore."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(data) if data else {}

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def get(self, key: str) -> str:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        del self._data[key]


@pytest.fixture
def client():
    """TestClient ohne dashboard_origin (nur localhost)."""
    router = AudioRouter(local_available=False)
    store = FakeSecretStore()
    dashboard = SettingsDashboard(audio_router=router, secret_store=store)
    return TestClient(dashboard.app)


@pytest.fixture
def client_with_origin():
    """TestClient mit dashboard_origin gesetzt."""
    router = AudioRouter(local_available=False)
    store = FakeSecretStore({"dashboard_origin": "https://fern.last-strawberry.com"})
    dashboard = SettingsDashboard(audio_router=router, secret_store=store)
    return TestClient(dashboard.app)


# ------------------------------------------------------------------
# Security Headers
# ------------------------------------------------------------------

class TestSecurityHeaders:
    """Alle Responses müssen Security-Header enthalten."""

    def test_x_content_type_options(self, client):
        r = client.get("/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        r = client.get("/health")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client):
        r = client.get("/health")
        assert r.headers.get("Referrer-Policy") == "no-referrer"

    def test_csp_present(self, client):
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy")
        assert csp is not None
        assert "default-src 'self'" in csp

    def test_csp_no_unsafe_inline(self, client):
        """Phase 63: 'unsafe-inline' darf nicht mehr im CSP auftauchen."""
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "'unsafe-inline'" not in csp, (
            f"CSP enthaelt noch 'unsafe-inline' (XSS-Schutz neutralisiert): {csp}"
        )

    def test_csp_no_unsafe_eval(self, client):
        """'unsafe-eval' darf ebenfalls nicht gesetzt sein."""
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "'unsafe-eval'" not in csp

    def test_csp_connect_src_self(self, client):
        """connect-src muss auf 'self' beschraenkt sein (kein externer fetch)."""
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "connect-src 'self'" in csp

    def test_permissions_policy_present(self, client):
        """Permissions-Policy-Header deaktiviert ungenutzte APIs."""
        r = client.get("/health")
        pp = r.headers.get("Permissions-Policy")
        assert pp is not None
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp

    def test_permissions_policy_on_api_endpoint(self, client):
        """Permissions-Policy auch auf API-Endpoints."""
        r = client.get("/api/audio")
        pp = r.headers.get("Permissions-Policy")
        assert pp is not None

    def test_headers_on_api_endpoint(self, client):
        """Security-Header auch auf API-Endpoints."""
        r = client.get("/api/audio")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_headers_on_post(self, client):
        """Security-Header auch bei POST-Responses."""
        r = client.post("/api/audio", json={"mode": "matrix_only"})
        assert r.headers.get("X-Content-Type-Options") == "nosniff"


# ------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------

class TestCORS:
    """CORS-Konfiguration Tests."""

    def test_cors_localhost_allowed(self, client):
        """Localhost-Origin wird akzeptiert."""
        r = client.options(
            "/api/audio",
            headers={
                "Origin": "http://localhost:8090",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") == "http://localhost:8090"

    def test_cors_127_allowed(self, client):
        """127.0.0.1 Origin wird akzeptiert."""
        r = client.options(
            "/api/audio",
            headers={
                "Origin": "http://127.0.0.1:8090",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:8090"

    def test_cors_random_origin_blocked(self, client):
        """Unbekannte Origins werden nicht gespiegelt."""
        r = client.options(
            "/api/audio",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        allow_origin = r.headers.get("access-control-allow-origin")
        assert allow_origin != "https://evil.example.com"

    def test_cors_dashboard_origin_allowed(self, client_with_origin):
        """Konfigurierte dashboard_origin wird akzeptiert."""
        r = client_with_origin.options(
            "/api/audio",
            headers={
                "Origin": "https://fern.last-strawberry.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            r.headers.get("access-control-allow-origin")
            == "https://fern.last-strawberry.com"
        )

    def test_cors_methods_restricted(self, client):
        """Nur GET, POST, DELETE erlaubt."""
        r = client.options(
            "/api/audio",
            headers={
                "Origin": "http://localhost:8090",
                "Access-Control-Request-Method": "GET",
            },
        )
        allowed = r.headers.get("access-control-allow-methods", "")
        # PUT sollte nicht erlaubt sein
        assert "PUT" not in allowed


# ------------------------------------------------------------------
# Exception-Handler
# ------------------------------------------------------------------

class TestExceptionHandler:
    """Globaler Exception-Handler fängt unbehandelte Fehler."""

    def test_health_returns_ok(self, client):
        """Normaler Endpoint funktioniert weiterhin."""
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_404_still_works(self, client):
        """Unbekannte Pfade ergeben 404 (nicht 500)."""
        r = client.get("/api/nonexistent")
        assert r.status_code in (404, 405)
