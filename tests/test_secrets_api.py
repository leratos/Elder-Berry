"""Tests für die Secrets-API (/api/secrets/*) im SettingsDashboard."""

import pytest

from elder_berry.core.audio_router import AudioRouter

try:
    from fastapi.testclient import TestClient
    from elder_berry.web.settings_dashboard import SettingsDashboard
    from elder_berry.web.secrets_api import SECRET_REGISTRY

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


class FakeSecretStore:
    """Minimaler In-Memory SecretStore für Tests."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(data) if data else {}

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def get(self, key: str) -> str:
        val = self._data.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        if key not in self._data:
            raise KeyError(key)
        del self._data[key]


@pytest.fixture
def fake_store():
    """Leerer FakeSecretStore."""
    return FakeSecretStore()


@pytest.fixture
def fake_store_with_data():
    """FakeSecretStore mit ein paar vorhandenen Keys."""
    return FakeSecretStore({
        "anthropic_api_key": "sk-ant-test123",
        "weather_city": "Berlin",
        "email_imap_port": "993",
    })


@pytest.fixture
def client(fake_store):
    """TestClient mit leerem SecretStore."""
    router = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(audio_router=router, secret_store=fake_store)
    return TestClient(dashboard.app)


@pytest.fixture
def client_with_data(fake_store_with_data):
    """TestClient mit vorhandenen Secrets."""
    router = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(audio_router=router, secret_store=fake_store_with_data)
    return TestClient(dashboard.app)


@pytest.fixture
def client_no_store():
    """TestClient ohne SecretStore."""
    router = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(audio_router=router, secret_store=None)
    return TestClient(dashboard.app)


# ------------------------------------------------------------------
# GET /api/secrets/status
# ------------------------------------------------------------------

class TestSecretsStatus:
    """GET /api/secrets/status – Registry-basierter Status."""

    def test_all_registry_keys_present(self, client):
        r = client.get("/api/secrets/status")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        # Alle Keys aus der Registry müssen vorkommen
        all_keys = set()
        for cat in data["categories"]:
            for entry in cat["keys"]:
                all_keys.add(entry["key"])
        registry_keys = {e["key"] for e in SECRET_REGISTRY}
        assert all_keys == registry_keys

    def test_is_set_correct(self, client_with_data):
        r = client_with_data.get("/api/secrets/status")
        data = r.json()
        key_status = {}
        for cat in data["categories"]:
            for entry in cat["keys"]:
                key_status[entry["key"]] = entry["is_set"]
        assert key_status["anthropic_api_key"] is True
        assert key_status["weather_city"] is True
        assert key_status["brave_api_key"] is False

    def test_categories_grouped(self, client):
        r = client.get("/api/secrets/status")
        data = r.json()
        cat_names = [c["name"] for c in data["categories"]]
        assert "KI & Sprache" in cat_names
        assert "Matrix" in cat_names
        assert "E-Mail" in cat_names

    def test_no_secret_store(self, client_no_store):
        r = client_no_store.get("/api/secrets/status")
        data = r.json()
        assert data["available"] is False
        assert data["categories"] == []

    def test_entry_has_metadata(self, client):
        """Einträge enthalten sensitive + requires_restart Flags."""
        r = client.get("/api/secrets/status")
        data = r.json()
        # Finde anthropic_api_key
        for cat in data["categories"]:
            for entry in cat["keys"]:
                if entry["key"] == "anthropic_api_key":
                    assert entry["sensitive"] is True
                    assert entry["requires_restart"] is True
                    assert "link" in entry
                    return
        pytest.fail("anthropic_api_key nicht gefunden")


# ------------------------------------------------------------------
# POST /api/secrets/set
# ------------------------------------------------------------------

class TestSecretsSet:
    """POST /api/secrets/set – Key setzen."""

    def test_set_new_key(self, client, fake_store):
        r = client.post("/api/secrets/set", json={"key": "brave_api_key", "value": "BSA-test"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["key"] == "brave_api_key"
        assert fake_store.get_or_none("brave_api_key") == "BSA-test"

    def test_set_update_existing(self, client_with_data, fake_store_with_data):
        r = client_with_data.post(
            "/api/secrets/set",
            json={"key": "weather_city", "value": "München"},
        )
        assert r.status_code == 200
        assert fake_store_with_data.get("weather_city") == "München"

    def test_set_empty_value_rejected(self, client):
        r = client.post("/api/secrets/set", json={"key": "brave_api_key", "value": ""})
        assert r.status_code == 400
        assert "leer" in r.json()["error"].lower()

    def test_set_whitespace_only_rejected(self, client):
        r = client.post("/api/secrets/set", json={"key": "brave_api_key", "value": "   "})
        assert r.status_code == 400

    def test_set_no_body(self, client):
        r = client.post("/api/secrets/set", json={})
        assert r.status_code == 400

    def test_set_value_too_long(self, client):
        long_value = "x" * 4097
        r = client.post("/api/secrets/set", json={"key": "brave_api_key", "value": long_value})
        assert r.status_code == 400
        assert "lang" in r.json()["error"].lower()

    def test_set_invalid_key_chars(self, client):
        r = client.post("/api/secrets/set", json={"key": "My-Key!", "value": "test"})
        assert r.status_code == 400
        assert "Kleinbuchstaben" in r.json()["error"]

    def test_set_returns_restart_flag(self, client):
        r = client.post(
            "/api/secrets/set",
            json={"key": "matrix_access_token", "value": "syt_test"},
        )
        assert r.status_code == 200
        assert r.json()["requires_restart"] is True

    def test_set_no_secret_store(self, client_no_store):
        r = client_no_store.post(
            "/api/secrets/set",
            json={"key": "brave_api_key", "value": "test"},
        )
        assert r.status_code == 503

    def test_set_unknown_key_accepted(self, client, fake_store):
        """Unbekannte Keys (nicht in Registry) werden akzeptiert."""
        r = client.post(
            "/api/secrets/set",
            json={"key": "custom_key_xyz", "value": "hello"},
        )
        assert r.status_code == 200
        assert fake_store.get("custom_key_xyz") == "hello"


# ------------------------------------------------------------------
# Typ-Validierung
# ------------------------------------------------------------------

class TestSecretsTypeValidation:
    """Typ-spezifische Validierung anhand der Registry."""

    def test_int_valid(self, client, fake_store):
        r = client.post(
            "/api/secrets/set",
            json={"key": "email_imap_port", "value": "993"},
        )
        assert r.status_code == 200
        assert fake_store.get("email_imap_port") == "993"

    def test_int_invalid(self, client):
        r = client.post(
            "/api/secrets/set",
            json={"key": "email_imap_port", "value": "abc"},
        )
        assert r.status_code == 400
        assert "Ganzzahl" in r.json()["error"]

    def test_int_out_of_range(self, client):
        r = client.post(
            "/api/secrets/set",
            json={"key": "smtp_port", "value": "99999"},
        )
        assert r.status_code == 400

    def test_float_valid(self, client, fake_store):
        r = client.post(
            "/api/secrets/set",
            json={"key": "weather_latitude", "value": "52.52"},
        )
        assert r.status_code == 200

    def test_float_out_of_range(self, client):
        r = client.post(
            "/api/secrets/set",
            json={"key": "weather_latitude", "value": "999"},
        )
        assert r.status_code == 400

    def test_url_valid(self, client, fake_store):
        r = client.post(
            "/api/secrets/set",
            json={"key": "matrix_homeserver", "value": "https://matrix.example.com"},
        )
        assert r.status_code == 200

    def test_url_invalid(self, client):
        r = client.post(
            "/api/secrets/set",
            json={"key": "matrix_homeserver", "value": "matrix.example.com"},
        )
        assert r.status_code == 400
        assert "http" in r.json()["error"].lower()


# ------------------------------------------------------------------
# POST /api/secrets/delete
# ------------------------------------------------------------------

class TestSecretsDelete:
    """POST /api/secrets/delete – Key löschen."""

    def test_delete_existing(self, client_with_data, fake_store_with_data):
        r = client_with_data.post(
            "/api/secrets/delete",
            json={"key": "weather_city"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert fake_store_with_data.get_or_none("weather_city") is None

    def test_delete_nonexistent(self, client):
        r = client.post("/api/secrets/delete", json={"key": "nonexistent_key"})
        assert r.status_code == 404

    def test_delete_no_key(self, client):
        r = client.post("/api/secrets/delete", json={})
        assert r.status_code == 400

    def test_delete_no_secret_store(self, client_no_store):
        r = client_no_store.post(
            "/api/secrets/delete",
            json={"key": "weather_city"},
        )
        assert r.status_code == 503
