"""Tests: Setup-Wizard API – FastAPI-Endpoints."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.setup_wizard import (
    SETUP_COMPLETE_KEY,
    register_setup_wizard_routes,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeSecretStore:
    """In-Memory SecretStore für Tests."""

    def __init__(self, initial: dict[str, str] | None = None):
        self._data: dict[str, str] = dict(initial or {})

    def has(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> str:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        del self._data[key]

    def list_keys(self) -> list[str]:
        return list(self._data.keys())


@pytest.fixture
def fresh_store():
    """Leerer SecretStore – frische Installation."""
    return FakeSecretStore()


@pytest.fixture
def partial_store():
    """SecretStore mit Anthropic-Key gesetzt."""
    return FakeSecretStore({"anthropic_api_key": "sk-test-key"})


@pytest.fixture
def complete_store():
    """SecretStore mit allen Pflicht-Keys."""
    return FakeSecretStore({
        "anthropic_api_key": "sk-test",
        "matrix_homeserver": "https://matrix.example.com",
        "matrix_user_id": "@bot:example.com",
        "matrix_access_token": "syt_valid",
        "matrix_room_id": "!room:example.com",
        "matrix_allowed_senders": "@user:example.com",
        SETUP_COMPLETE_KEY: "true",
    })


def _make_client(store: FakeSecretStore) -> TestClient:
    app = FastAPI()
    register_setup_wizard_routes(app, store)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Status-Endpoint
# ---------------------------------------------------------------------------

class TestSetupStatus:
    def test_fresh_install(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.get("/api/setup/status")
        data = r.json()
        assert data["completed"] is False
        assert data["current_step"] == 2  # Step 1 hat keine required_keys
        assert "anthropic" in data["missing"]

    def test_partial_config(self, partial_store):
        client = _make_client(partial_store)
        r = client.get("/api/setup/status")
        data = r.json()
        assert data["completed"] is False
        assert "anthropic" in data["configured"]
        assert "matrix" in data["missing"]

    def test_complete_config(self, complete_store):
        client = _make_client(complete_store)
        r = client.get("/api/setup/status")
        data = r.json()
        assert data["completed"] is True
        assert "anthropic" in data["configured"]
        assert "matrix" in data["configured"]


# ---------------------------------------------------------------------------
# Step GET
# ---------------------------------------------------------------------------

class TestStepGet:
    def test_load_step_values(self, partial_store):
        client = _make_client(partial_store)
        r = client.get("/api/setup/step/2")
        data = r.json()
        assert data["step"] == 2
        assert data["name"] == "LLM-Backend"
        # API-Key ist sensitiv → nur is_set zurückgeben
        assert data["values"]["anthropic_api_key"]["is_set"] is True

    def test_password_not_in_get(self, complete_store):
        """GET gibt keine Passwort-Werte zurück."""
        client = _make_client(complete_store)
        r = client.get("/api/setup/step/3")
        data = r.json()
        # matrix_access_token ist sensitiv
        assert "value" not in data["values"]["matrix_access_token"]
        assert data["values"]["matrix_access_token"]["is_set"] is True
        # matrix_homeserver ist nicht sensitiv → Wert zurückgeben
        assert data["values"]["matrix_homeserver"]["value"] == "https://matrix.example.com"

    def test_invalid_step(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.get("/api/setup/step/99")
        assert r.status_code == 400

    def test_empty_step(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.get("/api/setup/step/4")
        data = r.json()
        # Nextcloud noch nicht konfiguriert
        assert data["values"]["nextcloud_url"]["is_set"] is False


# ---------------------------------------------------------------------------
# Step POST (Save)
# ---------------------------------------------------------------------------

class TestStepSave:
    def test_save_required_keys(self, fresh_store):
        """Pflicht-Keys werden gespeichert."""
        client = _make_client(fresh_store)
        with patch(
            "elder_berry.web.setup_wizard._run_llm_tests",
            return_value={"anthropic": {"success": True, "model": "claude-sonnet-4-6"}},
        ):
            r = client.post("/api/setup/step/2", json={
                "anthropic_api_key": "sk-new-key",
            })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "anthropic_api_key" in data["saved_keys"]
        assert fresh_store.get("anthropic_api_key") == "sk-new-key"

    def test_save_missing_required(self, fresh_store):
        """Fehlende Pflicht-Keys → 400."""
        client = _make_client(fresh_store)
        r = client.post("/api/setup/step/2", json={})
        assert r.status_code == 400
        data = r.json()
        assert "fehlt" in data["error"].lower() or "Pflichtfeld" in data["error"]

    def test_save_optional_step(self, fresh_store):
        """Optionale Schritte akzeptieren leere Bodies."""
        client = _make_client(fresh_store)
        # Nextcloud ist optional – keine required_keys
        r = client.post("/api/setup/step/4", json={
            "nextcloud_url": "https://cloud.example.com",
            "nextcloud_user": "admin",
        })
        assert r.status_code == 200
        assert fresh_store.get("nextcloud_url") == "https://cloud.example.com"

    def test_ignores_unknown_keys(self, fresh_store):
        """Unbekannte Keys werden ignoriert."""
        client = _make_client(fresh_store)
        r = client.post("/api/setup/step/6", json={
            "weather_city": "Berlin",
            "unknown_key": "should_be_ignored",
        })
        assert r.status_code == 200
        assert fresh_store.has("weather_city")
        assert not fresh_store.has("unknown_key")

    def test_preserves_existing_keys(self, partial_store):
        """Bestehende Keys werden nicht gelöscht."""
        client = _make_client(partial_store)
        # Matrix-Verbindungstest mocken (kein echter Server)
        with patch(
            "elder_berry.web.setup_wizard._run_matrix_tests",
            return_value={"matrix": {"success": True}},
        ):
            r = client.post("/api/setup/step/3", json={
                "matrix_homeserver": "https://matrix.example.com",
                "matrix_user_id": "@bot:example.com",
                "matrix_access_token": "syt_token",
                "matrix_room_id": "!room:example.com",
                "matrix_allowed_senders": "@user:example.com",
            })
        assert r.status_code == 200
        assert partial_store.get("anthropic_api_key") == "sk-test-key"

    def test_invalid_step_number(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.post("/api/setup/step/0", json={})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Test-Endpoint
# ---------------------------------------------------------------------------

class TestServiceTest:
    def test_ollama_test(self, fresh_store):
        client = _make_client(fresh_store)
        with patch(
            "elder_berry.web.setup_wizard.SetupTests.test_ollama",
            return_value={"success": True, "models": ["phi4:14b"]},
        ):
            r = client.post("/api/setup/test/ollama", json={})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_unknown_service(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.post("/api/setup/test/unknown_service", json={})
        assert r.status_code == 400

    def test_missing_params(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.post("/api/setup/test/anthropic", json={})
        assert r.status_code == 400
        assert "fehlt" in r.json()["error"]


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------

class TestSetupComplete:
    def test_marks_done(self, fresh_store):
        # Phase 58: PW muss vorher gesetzt sein
        client = _make_client(fresh_store)
        r0 = client.post(
            "/api/setup/dashboard-password",
            json={"password": "supersecret123"},
        )
        assert r0.status_code == 200
        r = client.post("/api/setup/complete")
        data = r.json()
        assert data["success"] is True
        assert data["redirect"] == "/"
        assert fresh_store.get(SETUP_COMPLETE_KEY) == "true"

    def test_complete_requires_dashboard_password(self, fresh_store):
        """Phase 58: Ohne Dashboard-Passwort schlägt complete fehl."""
        client = _make_client(fresh_store)
        r = client.post("/api/setup/complete")
        assert r.status_code == 409
        assert r.json()["code"] == "dashboard_password_required"
        assert fresh_store.get_or_none(SETUP_COMPLETE_KEY) is None

    def test_dashboard_password_endpoint_validates(self, fresh_store):
        """Phase 58: Endpoint prüft Mindestlänge."""
        client = _make_client(fresh_store)
        r1 = client.post(
            "/api/setup/dashboard-password", json={"password": "short"},
        )
        assert r1.status_code == 400
        assert r1.json()["code"] == "weak_password"

        r2 = client.post("/api/setup/dashboard-password", json={})
        assert r2.status_code == 400
        assert r2.json()["code"] == "missing_password"

    def test_dashboard_password_endpoint_stores_hash(self, fresh_store):
        """Phase 58: Hash wird im SecretStore unter dem richtigen Key abgelegt."""
        from elder_berry.web.dashboard_auth import PASSWORD_HASH_KEY
        client = _make_client(fresh_store)
        r = client.post(
            "/api/setup/dashboard-password",
            json={"password": "supersecret123"},
        )
        assert r.status_code == 200
        stored = fresh_store.get_or_none(PASSWORD_HASH_KEY)
        assert stored is not None
        assert stored.startswith("$2b$")

    def test_re_setup_redirects_to_settings(self, complete_store):
        """Phase 52.3: Nach Abschluss redirected /setup → /settings."""
        client = _make_client(complete_store)
        r = client.get("/setup", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/settings"

    def test_re_setup_force_opens_wizard(self, complete_store):
        """Mit ?force=1 öffnet der Wizard auch nach Abschluss."""
        client = _make_client(complete_store)
        r = client.get("/setup?force=1", follow_redirects=False)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_first_run_serves_wizard(self, fresh_store):
        """First Run (kein Marker): /setup liefert direkt das HTML."""
        client = _make_client(fresh_store)
        r = client.get("/setup", follow_redirects=False)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class TestProviders:
    def test_provider_list(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.get("/api/setup/providers")
        data = r.json()
        assert "strato" in data
        assert data["strato"]["imap_host"] == "imap.strato.de"
        assert data["strato"]["imap_port"] == 993

    def test_all_providers_have_fields(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.get("/api/setup/providers")
        data = r.json()
        for name, info in data.items():
            assert "imap_host" in info, f"{name} fehlt imap_host"
            assert "smtp_host" in info, f"{name} fehlt smtp_host"
            assert "imap_port" in info, f"{name} fehlt imap_port"
            assert "smtp_port" in info, f"{name} fehlt smtp_port"


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

class TestPrerequisites:
    def test_returns_python_version(self, fresh_store):
        client = _make_client(fresh_store)
        r = client.get("/api/setup/prerequisites")
        data = r.json()
        assert "python" in data
        assert "." in data["python"]
