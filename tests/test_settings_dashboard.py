"""Tests für SettingsDashboard – FastAPI Web-UI für Systemeinstellungen."""

import pytest

from elder_berry.core.audio_router import AudioRouter

try:
    from fastapi.testclient import TestClient
    from elder_berry.web.settings_dashboard import SettingsDashboard

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
    dashboard = SettingsDashboard(audio_router=router_local)
    return TestClient(dashboard.app)


@pytest.fixture
def client_no_local(router_no_local):
    """TestClient ohne lokale Wiedergabe."""
    dashboard = SettingsDashboard(audio_router=router_no_local)
    return TestClient(dashboard.app)


class TestDashboardHTML:
    """GET / – HTML-Dashboard."""

    def test_returns_html(self, client_local):
        r = client_local.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_contains_title(self, client_local):
        r = client_local.get("/")
        assert "Elder-Berry Settings" in r.text

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


# ===========================================================================
# Monitor-Auswahl (Computer Use)
# ===========================================================================


class TestGetMonitors:
    """GET /api/monitors – Monitor-Liste abfragen."""

    def test_no_computer_use(self, client_local):
        r = client_local.get("/api/monitors")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is False
        assert data["monitors"] == []
        assert data["selected"] == 1

    def test_with_computer_use(self, router_local):
        from unittest.mock import MagicMock

        mock_cu = MagicMock()
        mock_cu.get_available_monitors.return_value = [
            {"index": 1, "width": 1920, "height": 1080, "left": 0, "top": 0},
            {"index": 2, "width": 2560, "height": 1440, "left": 1920, "top": 0},
        ]
        mock_cu.monitor_index = 1
        dashboard = SettingsDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.get("/api/monitors")
        data = r.json()
        assert data["available"] is True
        assert len(data["monitors"]) == 2
        assert data["selected"] == 1


class TestSetMonitor:
    """POST /api/monitor – Monitor setzen."""

    def test_no_computer_use(self, client_local):
        r = client_local.post("/api/monitor", json={"index": 1})
        assert r.status_code == 400
        assert "nicht verfügbar" in r.json()["error"]

    def test_missing_index(self, router_local):
        from unittest.mock import MagicMock

        mock_cu = MagicMock()
        dashboard = SettingsDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.post("/api/monitor", json={})
        assert r.status_code == 400
        assert "fehlt" in r.json()["error"]

    def test_invalid_index(self, router_local):
        from unittest.mock import MagicMock

        mock_cu = MagicMock()
        mock_cu.get_available_monitors.return_value = [
            {"index": 1, "width": 1920, "height": 1080, "left": 0, "top": 0},
        ]
        dashboard = SettingsDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.post("/api/monitor", json={"index": 5})
        assert r.status_code == 400
        assert "nicht verfügbar" in r.json()["error"]

    def test_valid_set(self, router_local):
        from unittest.mock import MagicMock

        mock_cu = MagicMock()
        mock_cu.get_available_monitors.return_value = [
            {"index": 1, "width": 1920, "height": 1080, "left": 0, "top": 0},
            {"index": 2, "width": 2560, "height": 1440, "left": 1920, "top": 0},
        ]
        mock_cu.monitor_index = 1
        dashboard = SettingsDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.post("/api/monitor", json={"index": 2})
        assert r.status_code == 200
        data = r.json()
        assert data["selected"] == 2
        # Verify setter was called
        assert mock_cu.monitor_index == 2

    def test_html_contains_monitor_section(self, router_local):
        from unittest.mock import MagicMock

        mock_cu = MagicMock()
        dashboard = SettingsDashboard(audio_router=router_local, computer_use=mock_cu)
        client = TestClient(dashboard.app)

        r = client.get("/")
        assert "monitorSelect" in r.text
        assert "Computer Use Monitor" in r.text


# ===========================================================================
# Allowed Senders (Matrix-Sicherheit)
# ===========================================================================


class TestGetAllowedSenders:
    """GET /api/allowed-senders – Status abfragen."""

    def test_no_secret_store(self, client_local):
        """Ohne SecretStore: available=False."""
        r = client_local.get("/api/allowed-senders")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is False
        assert data["configured"] is False
        assert data["count"] == 0

    def test_not_configured(self, router_local):
        """SecretStore vorhanden, aber kein Key gesetzt."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.get_or_none.return_value = None
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.get("/api/allowed-senders")
        data = r.json()
        assert data["available"] is True
        assert data["configured"] is False
        assert data["count"] == 0

    def test_configured_single(self, router_local):
        """Ein Sender konfiguriert."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.get_or_none.return_value = "@user:matrix.example.com"
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.get("/api/allowed-senders")
        data = r.json()
        assert data["available"] is True
        assert data["configured"] is True
        assert data["count"] == 1

    def test_configured_multiple(self, router_local):
        """Mehrere Sender konfiguriert."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.get_or_none.return_value = (
            "@user1:matrix.example.com, @user2:matrix.example.com"
        )
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.get("/api/allowed-senders")
        data = r.json()
        assert data["count"] == 2


class TestPostAllowedSenders:
    """POST /api/allowed-senders – Sender setzen/entfernen."""

    def test_no_secret_store(self, client_local):
        """Ohne SecretStore: 400."""
        r = client_local.post(
            "/api/allowed-senders",
            json={"senders": "@user:test.com"},
        )
        assert r.status_code == 400
        assert "SecretStore" in r.json()["error"]

    def test_empty_body(self, router_local):
        """Leerer Body: 400."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post("/api/allowed-senders")
        assert r.status_code == 400

    def test_set_valid_sender(self, router_local):
        """Gültigen Sender setzen."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"senders": "@user:matrix.example.com"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["configured"] is True
        assert data["count"] == 1
        mock_store.set.assert_called_once_with(
            "matrix_allowed_senders",
            "@user:matrix.example.com",
        )

    def test_set_multiple_senders(self, router_local):
        """Mehrere gültige Sender setzen."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"senders": "@a:test.com, @b:test.com"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2

    def test_invalid_sender_format(self, router_local):
        """Ungültiges Format: kein @ oder kein : → 400."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"senders": "ungueltig"},
        )
        assert r.status_code == 400
        assert "Ungültige Matrix-ID" in r.json()["error"]
        mock_store.set.assert_not_called()

    def test_mixed_valid_invalid(self, router_local):
        """Mix aus gültig und ungültig: 400, nichts wird gespeichert."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"senders": "@valid:test.com, invalid"},
        )
        assert r.status_code == 400
        mock_store.set.assert_not_called()

    def test_remove_senders(self, router_local):
        """Sender entfernen."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"action": "remove"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["configured"] is False
        assert data["count"] == 0
        mock_store.delete.assert_called_once_with("matrix_allowed_senders")

    def test_remove_nonexistent_ok(self, router_local):
        """Entfernen wenn nicht vorhanden: kein Fehler."""
        from unittest.mock import MagicMock

        class SecretNotFoundError(Exception):
            pass

        mock_store = MagicMock()
        mock_store.delete.side_effect = SecretNotFoundError("nicht da")
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"action": "remove"},
        )
        assert r.status_code == 200

    def test_empty_senders_string(self, router_local):
        """Leerer senders-String: 400."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.post(
            "/api/allowed-senders",
            json={"senders": "   "},
        )
        assert r.status_code == 400

    def test_html_contains_senders_section(self, router_local):
        """HTML enthält Sicherheits-Sektion."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        dashboard = SettingsDashboard(
            audio_router=router_local,
            secret_store=mock_store,
        )
        client = TestClient(dashboard.app)

        r = client.get("/")
        assert "senderInput" in r.text
        assert "Sicherheit" in r.text
        assert "Erlaubte Matrix-Absender" in r.text


def test_settings_schema_contains_phase45_registry(router_local):
    from unittest.mock import MagicMock

    mock_store = MagicMock()
    mock_store.get_or_none.return_value = None
    dashboard = SettingsDashboard(audio_router=router_local, secret_store=mock_store)
    client = TestClient(dashboard.app)

    r = client.get("/api/settings/schema")
    assert r.status_code == 200
    data = r.json()
    keys = {item["key"] for item in data["settings"]}
    assert {
        "matrix_allowed_senders",
        "user_timezone",
        "stt_timeout",
        "llm_mode",
    }.issubset(keys)


def test_settings_values_returns_defaults(router_local):
    from unittest.mock import MagicMock

    mock_store = MagicMock()
    mock_store.get_or_none.return_value = None
    dashboard = SettingsDashboard(audio_router=router_local, secret_store=mock_store)
    client = TestClient(dashboard.app)

    r = client.get("/api/settings/values")
    assert r.status_code == 200
    data = r.json()["values"]
    assert data["matrix_allowed_senders"] == ""
    assert data["user_timezone"] == "Europe/Berlin"
    assert data["stt_timeout"] == 120.0
    assert data["llm_mode"] == "api_preferred"


def test_settings_update_validates_timezone(router_local):
    from unittest.mock import MagicMock

    mock_store = MagicMock()
    mock_store.get_or_none.return_value = None
    dashboard = SettingsDashboard(audio_router=router_local, secret_store=mock_store)
    client = TestClient(dashboard.app)

    r = client.post(
        "/api/settings/update", json={"key": "user_timezone", "value": "Mars/Olympus"}
    )
    assert r.status_code == 400
    assert "Ungültige Zeitzone" in r.json()["error"]


def test_settings_update_persists_llm_mode(router_local):
    from unittest.mock import MagicMock

    mock_store = MagicMock()
    mock_store.get_or_none.side_effect = (
        lambda key: None if key != "llm_mode" else "local_preferred"
    )
    dashboard = SettingsDashboard(audio_router=router_local, secret_store=mock_store)
    client = TestClient(dashboard.app)

    r = client.post(
        "/api/settings/update", json={"key": "llm_mode", "value": "local_preferred"}
    )
    assert r.status_code == 200
    assert r.json()["value"] == "local_preferred"
    mock_store.set.assert_called_with("llm_mode", "local_preferred")
