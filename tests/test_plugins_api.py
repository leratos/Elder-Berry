"""Tests fuer Plugin-Inspector-API (Phase 77.5).

Prueft:
- ``GET /api/plugins`` liefert die geladenen Plugins.
- Body-Format: ``plugins[].{name,priority,category,source,...}`` plus
  ``summary.total`` und ``summary.by_source``.
- Source-Aggregation in der Test-Sandbox: nur ``builtin`` mit korrektem
  Count, ``user_dir`` und ``entry_point`` jeweils 0 (conftest stubbed
  diese Loader).
- Auth: ohne Login -> 401, mit gueltigem Cookie -> 200 (R5 im Konzept).
- Sort nach priority.

Test ist NICHT strict-mypy-geprueft (analog test_plugin_registry.py).
"""

from __future__ import annotations

import pytest

from elder_berry.core.audio_router import AudioRouter

try:
    from fastapi.testclient import TestClient

    from elder_berry.web.dashboard_auth import COOKIE_NAME
    from elder_berry.web.settings_dashboard import SettingsDashboard

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


class _FakeStore:
    """Minimal-In-Memory-SecretStore + has() fuer Setup-Wizard-Bypass."""

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

    def has(self, key: str) -> bool:
        return key in self._data

    @property
    def secrets_path(self):  # type: ignore[no-untyped-def]
        # SettingsDashboard nutzt secret_store.secrets_path.parent fuer
        # die SessionRevocationList -- darf nicht None sein.
        from pathlib import Path

        return Path(__file__).parent / "_unused"


@pytest.fixture
def open_client() -> TestClient:
    """Dashboard ohne Login (Standard-Test-Setup, analog test_secrets_api)."""
    router = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(audio_router=router, secret_store=_FakeStore())
    return TestClient(dashboard.app)


@pytest.fixture
def authed_client_pair(tmp_path):  # type: ignore[no-untyped-def]
    """Dashboard mit aktiver Auth + (TestClient ohne Cookie, mit Cookie).

    Setzt setup_wizard_completed=true, damit der Setup-Wizard-Bypass
    nicht greift -- sonst wuerde /api/plugins ohne Login durchgehen.
    """
    store = _FakeStore({"setup_wizard_completed": "true"})
    router = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(
        audio_router=router,
        secret_store=store,
        require_dashboard_login=True,
    )
    client_anon = TestClient(dashboard.app)
    # Login-Passwort setzen + Cookie holen
    auth = dashboard._auth_manager
    assert auth is not None
    auth.set_password("test-password")
    cookie, _exp = auth.issue_session()
    client_authed = TestClient(dashboard.app, cookies={COOKIE_NAME: cookie})
    return client_anon, client_authed


# --- Body-Format -----------------------------------------------------


class TestPluginsApiBody:
    def test_returns_200(self, open_client):
        r = open_client.get("/api/plugins")
        assert r.status_code == 200

    def test_body_has_plugins_and_summary(self, open_client):
        r = open_client.get("/api/plugins")
        data = r.json()
        assert "plugins" in data
        assert "summary" in data
        assert isinstance(data["plugins"], list)
        assert data["plugins"], "Plugin-Liste war leer"

    def test_plugin_entry_has_required_fields(self, open_client):
        r = open_client.get("/api/plugins")
        plugins = r.json()["plugins"]
        first = plugins[0]
        for field in (
            "name",
            "priority",
            "category",
            "version",
            "source",
            "source_path",
            "conflicts",
            "requires",
            "active",
            "help_section_excerpt",
        ):
            assert field in first, f"Feld '{field}' fehlt: {first}"

    def test_plugins_sorted_by_priority(self, open_client):
        r = open_client.get("/api/plugins")
        plugins = r.json()["plugins"]
        priorities = [p["priority"] for p in plugins]
        assert priorities == sorted(priorities)


# --- Source-Aggregation ---------------------------------------------


class TestPluginsApiSummary:
    def test_summary_total_matches_plugin_count(self, open_client):
        r = open_client.get("/api/plugins")
        data = r.json()
        assert data["summary"]["total"] == len(data["plugins"])

    def test_summary_by_source_has_all_keys(self, open_client):
        r = open_client.get("/api/plugins")
        by_source = r.json()["summary"]["by_source"]
        assert set(by_source.keys()) == {"builtin", "user_dir", "entry_point"}

    def test_in_test_sandbox_only_builtin(self, open_client):
        """Conftest stubbed user_dir + entry_points -> nur Builtin."""
        r = open_client.get("/api/plugins")
        data = r.json()
        by_source = data["summary"]["by_source"]
        assert by_source["user_dir"] == 0
        assert by_source["entry_point"] == 0
        assert by_source["builtin"] == data["summary"]["total"]
        assert by_source["builtin"] > 0

    def test_all_plugins_have_builtin_source_in_sandbox(self, open_client):
        r = open_client.get("/api/plugins")
        sources = {p["source"] for p in r.json()["plugins"]}
        assert sources == {"builtin"}


# --- Auth (R5) ------------------------------------------------------


class TestPluginsApiAuth:
    def test_anon_request_returns_401(self, authed_client_pair):
        client_anon, _ = authed_client_pair
        r = client_anon.get("/api/plugins")
        assert r.status_code == 401

    def test_authed_request_returns_200(self, authed_client_pair):
        _, client_authed = authed_client_pair
        r = client_authed.get("/api/plugins")
        assert r.status_code == 200
        assert "plugins" in r.json()
