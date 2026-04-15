"""Tests: Phase 52.1a – /api/settings/test/{service} + /api/settings/security."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.settings_test_api import (
    SERVICE_TESTS,
    _allowed_senders_count,
    _compute_cors_origins,
    _MissingSecret,
    _require,
    register_settings_test_routes,
)


def _make_store(values: dict[str, str | None]):
    store = MagicMock()
    store.get_or_none.side_effect = lambda k: values.get(k)
    return store


def _make_app(store, port=8090):
    app = FastAPI()
    register_settings_test_routes(app, store, port)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper-Funktionen
# ---------------------------------------------------------------------------

class TestRequireHelper:
    def test_present(self):
        store = _make_store({"a": "x"})
        assert _require(store, "a") == "x"

    def test_missing_raises(self):
        store = _make_store({})
        with pytest.raises(_MissingSecret, match="fehlt"):
            _require(store, "a")

    def test_empty_raises(self):
        store = _make_store({"a": ""})
        with pytest.raises(_MissingSecret):
            _require(store, "a")


class TestComputeCorsOrigins:
    def test_default_localhost(self):
        origins = _compute_cors_origins(_make_store({}), 8090)
        assert "http://localhost:8090" in origins
        assert "http://127.0.0.1:8090" in origins
        assert len(origins) == 2

    def test_with_dashboard_origin(self):
        store = _make_store({"dashboard_origin": "https://saleria.example.com"})
        origins = _compute_cors_origins(store, 8090)
        assert "https://saleria.example.com" in origins
        assert len(origins) == 3

    def test_no_store(self):
        origins = _compute_cors_origins(None, 9999)
        assert origins == ["http://localhost:9999", "http://127.0.0.1:9999"]


class TestAllowedSendersCount:
    def test_no_store(self):
        assert _allowed_senders_count(None) == 0

    def test_empty(self):
        assert _allowed_senders_count(_make_store({})) == 0

    def test_three_senders(self):
        store = _make_store({
            "matrix_allowed_senders": "@a:x.com,@b:x.com,@c:x.com",
        })
        assert _allowed_senders_count(store) == 3

    def test_skips_blanks(self):
        store = _make_store({"matrix_allowed_senders": "@a:x.com,,  ,@b:x.com"})
        assert _allowed_senders_count(store) == 2


# ---------------------------------------------------------------------------
# /api/settings/test/{service}
# ---------------------------------------------------------------------------

class TestServiceEndpointBasics:
    def test_unknown_service_404(self):
        client = _make_app(_make_store({}))
        r = client.post("/api/settings/test/unknown_thing")
        assert r.status_code == 404
        body = r.json()
        assert "available" in body
        assert "anthropic" in body["available"]

    def test_no_secret_store_503(self):
        client = _make_app(None)
        r = client.post("/api/settings/test/anthropic")
        assert r.status_code == 503

    def test_missing_credentials_400(self):
        client = _make_app(_make_store({}))
        r = client.post("/api/settings/test/anthropic")
        assert r.status_code == 400
        body = r.json()
        assert body["missing_config"] is True
        assert "anthropic_api_key" in body["error"]

    def test_service_appended_to_response(self):
        store = _make_store({"anthropic_api_key": "sk-test"})
        with patch(
            "elder_berry.web.setup_tests.SetupTests.test_anthropic",
            new=AsyncMock(return_value={"success": True, "model": "claude"}),
        ):
            client = _make_app(store)
            r = client.post("/api/settings/test/anthropic")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["service"] == "anthropic"
        assert body["model"] == "claude"


class TestServiceRunners:
    """Smoke-Tests pro Service – mocken die jeweilige SetupTests-Methode."""

    def _patch_and_call(self, method_name, service, store, expected_args=None):
        path = f"elder_berry.web.setup_tests.SetupTests.{method_name}"
        mocked = AsyncMock(return_value={"success": True})
        with patch(path, new=mocked):
            client = _make_app(store)
            r = client.post(f"/api/settings/test/{service}")
        return r, mocked

    def test_anthropic(self):
        store = _make_store({"anthropic_api_key": "sk-1"})
        r, mock = self._patch_and_call("test_anthropic", "anthropic", store)
        assert r.status_code == 200
        mock.assert_awaited_once_with("sk-1")

    def test_groq(self):
        store = _make_store({"groq_api_key": "gsk-1"})
        r, mock = self._patch_and_call("test_groq", "groq", store)
        assert r.status_code == 200
        mock.assert_awaited_once_with("gsk-1")

    def test_brave(self):
        store = _make_store({"brave_api_key": "BSA1"})
        r, mock = self._patch_and_call("test_brave", "brave", store)
        assert r.status_code == 200

    def test_google_maps(self):
        store = _make_store({"google_maps_api_key": "G1"})
        r, mock = self._patch_and_call("test_google_maps", "google_maps", store)
        assert r.status_code == 200

    def test_matrix_with_token(self):
        store = _make_store({
            "matrix_homeserver": "https://m.example.com",
            "matrix_user_id": "@bot:m.example.com",
            "matrix_access_token": "tok",
            "matrix_room_id": "!room:m.example.com",
        })
        r, mock = self._patch_and_call("test_matrix", "matrix", store)
        assert r.status_code == 200
        mock.assert_awaited_once_with(
            "https://m.example.com",
            "@bot:m.example.com",
            "tok",
            "!room:m.example.com",
        )

    def test_matrix_missing_token(self):
        store = _make_store({
            "matrix_homeserver": "https://m.example.com",
            "matrix_user_id": "@bot:m.example.com",
        })
        client = _make_app(store)
        r = client.post("/api/settings/test/matrix")
        assert r.status_code == 400
        assert "matrix_access_token" in r.json()["error"]

    def test_nextcloud(self):
        store = _make_store({
            "nextcloud_url": "https://cloud.example.com",
            "nextcloud_user": "u",
            "nextcloud_app_password": "p",
        })
        r, mock = self._patch_and_call("test_nextcloud", "nextcloud", store)
        assert r.status_code == 200
        mock.assert_awaited_once_with("https://cloud.example.com", "u", "p")

    def test_email_default_ports(self):
        store = _make_store({
            "email_imap_host": "imap.strato.de",
            "smtp_host": "smtp.strato.de",
            "email_user": "me@example.com",
            "email_password": "pw",
        })
        r, mock = self._patch_and_call("test_email", "email", store)
        assert r.status_code == 200
        # Default-Ports
        mock.assert_awaited_once_with(
            "imap.strato.de", 993, "smtp.strato.de", 465,
            "me@example.com", "pw",
        )

    def test_email_custom_ports(self):
        store = _make_store({
            "email_imap_host": "imap.example.com",
            "email_imap_port": "143",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "email_user": "u",
            "email_password": "p",
        })
        r, mock = self._patch_and_call("test_email", "email", store)
        assert r.status_code == 200
        mock.assert_awaited_once_with(
            "imap.example.com", 143, "smtp.example.com", 587, "u", "p",
        )

    def test_ollama_sync_test(self):
        store = _make_store({})
        with patch(
            "elder_berry.web.setup_tests.SetupTests.test_ollama",
            return_value={"success": True, "models": ["llama3"]},
        ):
            client = _make_app(store)
            r = client.post("/api/settings/test/ollama")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_tower_online(self):
        store = _make_store({"tower_host": "127.0.0.1:12769"})
        with patch("elder_berry.core.tower_agent.TowerAgent") as mock_cls:
            instance = MagicMock()
            instance.heartbeat = AsyncMock(return_value=True)
            mock_cls.return_value = instance
            client = _make_app(store)
            r = client.post("/api/settings/test/tower")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_tower_offline(self):
        store = _make_store({"tower_host": "127.0.0.1:12769"})
        with patch("elder_berry.core.tower_agent.TowerAgent") as mock_cls:
            instance = MagicMock()
            instance.heartbeat = AsyncMock(return_value=False)
            mock_cls.return_value = instance
            client = _make_app(store)
            r = client.post("/api/settings/test/tower")
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_rpi5_online(self):
        store = _make_store({"robot_host": "http://pi:8000"})
        with patch("elder_berry.robot.client.RobotClient") as mock_cls:
            instance = MagicMock()
            instance.is_online.return_value = True
            mock_cls.return_value = instance
            client = _make_app(store)
            r = client.post("/api/settings/test/rpi5")
        assert r.status_code == 200
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# /api/settings/security
# ---------------------------------------------------------------------------

class TestSecurityEndpoint:
    def test_default(self):
        client = _make_app(_make_store({}))
        r = client.get("/api/settings/security")
        assert r.status_code == 200
        body = r.json()
        assert "cors" in body
        assert "allowed_senders" in body
        assert body["cors"]["editable"] is False
        assert "http://localhost:8090" in body["cors"]["origins"]
        assert body["allowed_senders"]["count"] == 0
        assert body["allowed_senders"]["configured"] is False

    def test_with_dashboard_origin_and_senders(self):
        store = _make_store({
            "dashboard_origin": "https://app.example.com",
            "matrix_allowed_senders": "@a:x.com,@b:x.com",
        })
        client = _make_app(store)
        body = client.get("/api/settings/security").json()
        assert "https://app.example.com" in body["cors"]["origins"]
        assert body["allowed_senders"]["count"] == 2
        assert body["allowed_senders"]["configured"] is True

    def test_no_store(self):
        client = _make_app(None)
        body = client.get("/api/settings/security").json()
        assert body["allowed_senders"]["count"] == 0


# ---------------------------------------------------------------------------
# Service-Registry-Konsistenz
# ---------------------------------------------------------------------------

class TestServiceRegistry:
    def test_all_runners_async(self):
        """Alle Einträge in SERVICE_TESTS müssen async sein."""
        import inspect
        for name, runner in SERVICE_TESTS.items():
            assert inspect.iscoroutinefunction(runner), \
                f"{name}: runner ist nicht async"

    def test_expected_services(self):
        expected = {
            "anthropic", "groq", "brave", "google_maps",
            "matrix", "nextcloud", "email", "ollama",
            "tower", "rpi5",
        }
        assert expected.issubset(set(SERVICE_TESTS.keys()))
