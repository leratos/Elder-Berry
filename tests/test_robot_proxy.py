"""Tests fuer src/elder_berry/web/robot_proxy.py (Phase 66).

Validiert:
- Reverse-Proxy reicht GET/POST/DELETE/PUT/PATCH durch
- Robot-Token aus dem SecretStore wird automatisch hinzugefuegt
- Cookie + Host-Header werden NICHT durchgereicht
- Fehlende ``robot_host`` -> 503
- Connection-Error -> 502, Timeout -> 504
- Query-Strings werden weitergeleitet
- Body wird transparent durchgereicht
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.robot_proxy import (
    ROBOT_AUTH_TOKEN_KEY,
    ROBOT_HOST_KEY,
    ROBOT_TOKEN_HEADER,
    register_robot_proxy_routes,
)


class _FakeStore:
    """In-Memory-SecretStore fuer Tests."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data = data or {}

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


def _make_app(store: _FakeStore) -> FastAPI:
    app = FastAPI()
    register_robot_proxy_routes(app, store)
    return app


def _mock_upstream(
    status_code: int = 200,
    content: bytes = b'{"ok": true}',
    headers: dict[str, str] | None = None,
):
    """Erstellt einen Mock-AsyncClient, der eine konkrete httpx.Response liefert."""
    response = httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers or {"content-type": "application/json"},
    )
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# Konfigurations-Edge-Cases
# ---------------------------------------------------------------------------


class TestRobotHostMissing:
    def test_no_host_returns_503(self):
        app = _make_app(_FakeStore())  # leerer Store
        client = TestClient(app)
        r = client.get("/api/robot/harmony/status")
        assert r.status_code == 503
        assert r.json()["code"] == "no_robot_host"

    def test_empty_host_returns_503(self):
        app = _make_app(_FakeStore({ROBOT_HOST_KEY: "   "}))
        client = TestClient(app)
        r = client.get("/api/robot/anything")
        assert r.status_code == 503

    def test_host_without_scheme_gets_http_prefix(self):
        store = _FakeStore({ROBOT_HOST_KEY: "127.0.0.1:12800"})
        app = _make_app(store)
        client = TestClient(app)
        with patch("httpx.AsyncClient", return_value=_mock_upstream()) as mock:
            client.get("/api/robot/health")
        called_url = mock.return_value.request.call_args[0][1]
        assert called_url.startswith("http://127.0.0.1:12800/")

    def test_host_with_https_scheme_kept(self):
        store = _FakeStore({ROBOT_HOST_KEY: "https://robot.example.com"})
        app = _make_app(store)
        client = TestClient(app)
        with patch("httpx.AsyncClient", return_value=_mock_upstream()) as mock:
            client.get("/api/robot/health")
        called_url = mock.return_value.request.call_args[0][1]
        assert called_url.startswith("https://robot.example.com/")


# ---------------------------------------------------------------------------
# Method-Pass-Through + Body
# ---------------------------------------------------------------------------


class TestProxyMethods:
    @pytest.fixture
    def store(self) -> _FakeStore:
        return _FakeStore(
            {
                ROBOT_HOST_KEY: "127.0.0.1:12800",
                ROBOT_AUTH_TOKEN_KEY: "tok-abc-123",
            }
        )

    @pytest.fixture
    def client(self, store):
        app = _make_app(store)
        return TestClient(app)

    def test_get_proxied(self, client):
        upstream = _mock_upstream(content=b'{"connected": true}')
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/harmony/status")
        assert r.status_code == 200
        assert r.json() == {"connected": True}
        assert upstream.request.call_args[0][0] == "GET"
        assert (
            upstream.request.call_args[0][1] == "http://127.0.0.1:12800/harmony/status"
        )

    def test_post_with_body(self, client):
        upstream = _mock_upstream(content=b'{"ok": true}')
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.post(
                "/api/robot/harmony/activity",
                json={"activity": "Fernsehen"},
            )
        assert r.status_code == 200
        # Body wurde durchgereicht
        body_bytes = upstream.request.call_args.kwargs["content"]
        assert b"Fernsehen" in body_bytes

    def test_delete_proxied(self, client):
        upstream = _mock_upstream(status_code=204, content=b"")
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.delete("/api/robot/harmony/scene/Gaming")
        assert r.status_code == 204
        assert upstream.request.call_args[0][0] == "DELETE"
        assert "/harmony/scene/Gaming" in upstream.request.call_args[0][1]

    def test_put_proxied(self, client):
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.put("/api/robot/harmony/layouts", json={"x": 1})
        assert r.status_code == 200
        assert upstream.request.call_args[0][0] == "PUT"

    def test_patch_proxied(self, client):
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.patch("/api/robot/x", json={"y": 2})
        assert r.status_code == 200
        assert upstream.request.call_args[0][0] == "PATCH"

    def test_query_string_forwarded(self, client):
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            client.get("/api/robot/sensors?detail=full&count=10")
        called_url = upstream.request.call_args[0][1]
        assert "detail=full" in called_url
        assert "count=10" in called_url


# ---------------------------------------------------------------------------
# Header-Filterung
# ---------------------------------------------------------------------------


class TestHeaderHandling:
    def test_token_added_when_configured(self):
        store = _FakeStore(
            {
                ROBOT_HOST_KEY: "127.0.0.1:12800",
                ROBOT_AUTH_TOKEN_KEY: "secret-token-xyz",
            }
        )
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            client.get("/api/robot/health")
        sent_headers = upstream.request.call_args.kwargs["headers"]
        assert sent_headers.get(ROBOT_TOKEN_HEADER) == "secret-token-xyz"

    def test_no_token_no_header(self):
        store = _FakeStore({ROBOT_HOST_KEY: "127.0.0.1:12800"})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            client.get("/api/robot/health")
        sent_headers = upstream.request.call_args.kwargs["headers"]
        assert ROBOT_TOKEN_HEADER not in sent_headers
        assert ROBOT_TOKEN_HEADER.lower() not in {k.lower() for k in sent_headers}

    def test_client_supplied_token_is_overwritten(self):
        """Defensiv: Client darf nicht eigenen Robot-Token einschmuggeln."""
        store = _FakeStore(
            {
                ROBOT_HOST_KEY: "127.0.0.1:12800",
                ROBOT_AUTH_TOKEN_KEY: "server-side-token",
            }
        )
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            client.get(
                "/api/robot/health",
                headers={ROBOT_TOKEN_HEADER: "EVIL-CLIENT-TOKEN"},
            )
        sent = upstream.request.call_args.kwargs["headers"]
        assert sent.get(ROBOT_TOKEN_HEADER) == "server-side-token"

    def test_cookie_header_stripped(self):
        store = _FakeStore({ROBOT_HOST_KEY: "127.0.0.1:12800"})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            client.get(
                "/api/robot/health",
                cookies={"eb_dashboard_session": "abc"},
            )
        sent = upstream.request.call_args.kwargs["headers"]
        # Kein Cookie-Header an den RPi5 weitergeben
        assert "cookie" not in {k.lower() for k in sent}

    def test_host_header_stripped(self):
        store = _FakeStore({ROBOT_HOST_KEY: "127.0.0.1:12800"})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            client.get("/api/robot/health")
        sent = upstream.request.call_args.kwargs["headers"]
        # Host-Header wuerde sonst fern.example.com ausweisen.
        assert "host" not in {k.lower() for k in sent}

    def test_response_cors_headers_stripped(self):
        """Antwort-CORS-Header vom RobotServer NICHT durchreichen --
        sonst gibts doppelte Header in der Browser-Antwort und CORS
        bricht."""
        store = _FakeStore({ROBOT_HOST_KEY: "127.0.0.1:12800"})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream(
            headers={
                "content-type": "application/json",
                "access-control-allow-origin": "*",
                "access-control-allow-methods": "GET",
            },
        )
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/health")
        # Kein CORS-Header in der Browser-Antwort
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ---------------------------------------------------------------------------
# Fehler-Pfade
# ---------------------------------------------------------------------------


class TestErrorPaths:
    @pytest.fixture
    def client(self):
        store = _FakeStore(
            {
                ROBOT_HOST_KEY: "127.0.0.1:12800",
                ROBOT_AUTH_TOKEN_KEY: "tok",
            }
        )
        return TestClient(_make_app(store))

    def test_connection_error_returns_502(self, client):
        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            r = client.get("/api/robot/health")
        assert r.status_code == 502
        assert r.json()["code"] == "rpi5_unreachable"

    def test_timeout_returns_504(self, client):
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=httpx.ReadTimeout("slow"),
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            r = client.get("/api/robot/health")
        assert r.status_code == 504
        assert r.json()["code"] == "rpi5_timeout"

    def test_generic_request_error_returns_502(self, client):
        mock_client = MagicMock()
        mock_client.request = AsyncMock(
            side_effect=httpx.RequestError("malformed"),
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            r = client.get("/api/robot/health")
        assert r.status_code == 502
        assert r.json()["code"] == "proxy_error"

    def test_upstream_4xx_passed_through(self, client):
        """RobotServer 401 (kein/falscher Token) muss als 401 ankommen."""
        upstream = _mock_upstream(
            status_code=401,
            content=b'{"error": "Robot-Token erforderlich oder ungueltig."}',
        )
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/health")
        assert r.status_code == 401
        assert "Robot-Token" in r.json()["error"]

    def test_upstream_5xx_passed_through(self, client):
        upstream = _mock_upstream(
            status_code=500,
            content=b'{"error": "internal"}',
        )
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/health")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# SSRF Defense-in-Depth (CodeQL py/partial-ssrf)
# ---------------------------------------------------------------------------


class TestSSRFDefenseInDepth:
    """robot_host und upstream_path werden Format-validiert bevor httpx.request."""

    @pytest.mark.parametrize(
        "bad_host",
        [
            "file:///etc/passwd",
            "gopher://internal:70/",
            "ftp://example.com",
            "javascript:alert(1)",
            "http://",
            "https://",
            "http://bad_host.example.com",  # underscore
        ],
    )
    def test_invalid_host_returns_503_without_request(self, bad_host):
        store = _FakeStore({ROBOT_HOST_KEY: bad_host})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/health")
        assert r.status_code == 503
        assert r.json()["code"] == "invalid_robot_host"
        # KEIN HTTP-Request darf abgesetzt worden sein
        upstream.request.assert_not_called()

    @pytest.mark.parametrize(
        "good_host",
        [
            "192.168.1.10:8001",
            "rpi5.local:8001",
            "http://192.168.1.10:8001",
            "https://rpi5.example.com",
        ],
    )
    def test_valid_host_passes_validation(self, good_host):
        store = _FakeStore({ROBOT_HOST_KEY: good_host})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/health")
        assert r.status_code == 200
        upstream.request.assert_called_once()

    def test_path_with_scheme_injection_blocked(self):
        store = _FakeStore({ROBOT_HOST_KEY: "192.168.1.10:8001"})
        app = _make_app(store)
        client = TestClient(app)
        upstream = _mock_upstream()
        # Pfad enthaelt ``://`` -> Scheme-Injection-Versuch
        with patch("httpx.AsyncClient", return_value=upstream):
            r = client.get("/api/robot/foo/http://attacker.com/bar")
        assert r.status_code == 400
        assert r.json()["code"] == "invalid_path"
        upstream.request.assert_not_called()
