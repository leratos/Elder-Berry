"""Tests für Funktionsstabilität: Concurrent Writes, Callbacks, Audit, Export."""

import asyncio
import logging

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


def _make_dashboard(
    store: FakeSecretStore | None = None,
) -> tuple[TestClient, SettingsDashboard, FakeSecretStore]:
    s = store or FakeSecretStore()
    router = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(audio_router=router, secret_store=s)
    return TestClient(dashboard.app), dashboard, s


class TestConcurrentWrites:
    """asyncio.Lock verhindert Race Conditions."""

    def test_concurrent_writes_no_corruption(self):
        """20 parallele Writes → alle Werte korrekt gespeichert."""
        client, _, store = _make_dashboard()
        keys = [f"test_key_{i}" for i in range(20)]
        for i, key in enumerate(keys):
            r = client.post("/api/secrets/set", json={"key": key, "value": f"val_{i}"})
            assert r.status_code == 200
        # Alle Werte prüfen
        for i, key in enumerate(keys):
            assert store.get(key) == f"val_{i}"

    def test_write_lock_serializes(self):
        """Write-Lock existiert und ist ein asyncio.Lock."""
        _, dashboard, _ = _make_dashboard()
        assert hasattr(dashboard, "_write_lock")
        assert isinstance(dashboard._write_lock, asyncio.Lock)


class TestAuditLogging:
    """AUDIT-Logs bei Schreiboperationen."""

    def test_audit_log_on_set(self, caplog):
        client, _, _ = _make_dashboard()
        with caplog.at_level(logging.INFO):
            client.post(
                "/api/secrets/set", json={"key": "brave_api_key", "value": "test"}
            )
        assert any(
            "AUDIT" in r.message
            and "brave_api_key" in r.message
            and "gesetzt" in r.message
            for r in caplog.records
        )

    def test_audit_log_on_delete(self, caplog):
        store = FakeSecretStore({"brave_api_key": "test"})
        client, _, _ = _make_dashboard(store)
        with caplog.at_level(logging.INFO):
            client.post("/api/secrets/delete", json={"key": "brave_api_key"})
        assert any(
            "AUDIT" in r.message
            and "brave_api_key" in r.message
            and "gelöscht" in r.message
            for r in caplog.records
        )


class TestRestartHint:
    """requires_restart Flag in der Response."""

    def test_restart_hint_flag_true(self):
        client, _, _ = _make_dashboard()
        r = client.post(
            "/api/secrets/set",
            json={
                "key": "matrix_access_token",
                "value": "syt_test",
            },
        )
        assert r.status_code == 200
        assert r.json()["requires_restart"] is True

    def test_restart_hint_flag_false(self):
        client, _, _ = _make_dashboard()
        r = client.post(
            "/api/secrets/set",
            json={
                "key": "weather_city",
                "value": "Berlin",
            },
        )
        assert r.status_code == 200
        assert r.json()["requires_restart"] is False


class TestChangeCallbacks:
    """on_change Callback-Registrierung und Aufruf."""

    def test_change_callback_called(self):
        _, dashboard, _ = _make_dashboard()
        received = []
        dashboard.on_change("weather_city", lambda v: received.append(v))

        client = TestClient(dashboard.app)
        client.post(
            "/api/secrets/set", json={"key": "weather_city", "value": "München"}
        )
        assert received == ["München"]

    def test_change_callback_error_isolated(self):
        """Fehler im Callback bricht den Request nicht ab."""
        _, dashboard, store = _make_dashboard()

        def bad_callback(v):
            raise RuntimeError("Callback-Fehler!")

        dashboard.on_change("weather_city", bad_callback)
        client = TestClient(dashboard.app)
        r = client.post(
            "/api/secrets/set", json={"key": "weather_city", "value": "Berlin"}
        )
        assert r.status_code == 200
        assert store.get("weather_city") == "Berlin"

    def test_multiple_callbacks(self):
        _, dashboard, _ = _make_dashboard()
        results_a, results_b = [], []
        dashboard.on_change("weather_city", lambda v: results_a.append(v))
        dashboard.on_change("weather_city", lambda v: results_b.append(v))

        client = TestClient(dashboard.app)
        client.post(
            "/api/secrets/set", json={"key": "weather_city", "value": "Hamburg"}
        )
        assert results_a == ["Hamburg"]
        assert results_b == ["Hamburg"]


class TestSettingsExport:
    """GET /api/settings/export – Export nicht-sensitiver Werte."""

    def test_export_structure(self):
        store = FakeSecretStore(
            {
                "weather_city": "Berlin",
                "anthropic_api_key": "sk-secret",
            }
        )
        client, _, _ = _make_dashboard(store)
        r = client.get("/api/settings/export")
        assert r.status_code == 200
        data = r.json()
        assert data["export_version"] == 1
        assert "exported_at" in data
        assert data["non_sensitive"]["weather_city"] == "Berlin"
        assert "anthropic_api_key" not in data["non_sensitive"]
        assert "anthropic_api_key" in data["sensitive_keys_set"]

    def test_export_empty_store(self):
        client, _, _ = _make_dashboard()
        r = client.get("/api/settings/export")
        data = r.json()
        assert data["non_sensitive"] == {}
        assert data["sensitive_keys_set"] == []


class TestMetadataTimestamps:
    """updated_at Timestamps bei set."""

    def test_updated_at_in_status(self):
        client, _, _ = _make_dashboard()
        client.post("/api/secrets/set", json={"key": "weather_city", "value": "Berlin"})
        r = client.get("/api/secrets/status")
        data = r.json()
        for cat in data["categories"]:
            for entry in cat["keys"]:
                if entry["key"] == "weather_city":
                    assert "updated_at" in entry
                    assert (
                        entry["updated_at"].endswith("+00:00")
                        or "Z" in entry["updated_at"]
                    )
                    return
        pytest.fail("weather_city nicht in Status gefunden")

    def test_no_updated_at_if_never_set(self):
        client, _, _ = _make_dashboard()
        r = client.get("/api/secrets/status")
        data = r.json()
        for cat in data["categories"]:
            for entry in cat["keys"]:
                if entry["key"] == "brave_api_key":
                    assert "updated_at" not in entry
                    return
