"""Tests für /settings Unified Panel-Route (Phase 52.1b)."""

from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient

    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.web.settings_dashboard import SettingsDashboard
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


@pytest.fixture
def client():
    dashboard = SettingsDashboard(audio_router=AudioRouter(local_available=True))
    return TestClient(dashboard.app)


def _panel_bundle(client) -> str:
    """HTML + ausgelagerte JS-Datei als kombinierter String.

    Phase 63: Das Unified Panel-Template referenziert jetzt
    /static/js/settings_panel.js. Die folgenden Assertions pruefen
    unabhaengig davon, in welcher Datei die Zeichenfolge steht.
    """
    html = client.get("/settings").text
    js = client.get("/static/js/settings_panel.js").text
    return html + "\n" + js


class TestSettingsPanelRoute:
    """GET /settings rendert das Unified Settings-Panel."""

    def test_returns_html(self, client):
        r = client.get("/settings")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_contains_layout_skeleton(self, client):
        r = client.get("/settings")
        assert 'id="tabList"' in r.text
        assert 'id="fieldContainer"' in r.text
        assert 'id="tokenModal"' in r.text

    def test_has_token_header_constant(self, client):
        assert "X-Saleria-Settings-Token" in _panel_bundle(client)

    def test_calls_secrets_status_and_settings_schema(self, client):
        body = _panel_bundle(client)
        assert "/api/secrets/status" in body
        assert "/api/settings/schema" in body
        assert "/api/settings/values" in body

    def test_calls_setup_test_endpoint(self, client):
        assert "/api/setup/test/" in _panel_bundle(client)

    def test_high_risk_confirm_present(self, client):
        assert "kritisch" in _panel_bundle(client)


class TestSettingsPanelData:
    """Stellt sicher, dass die vom Panel benötigten Endpoints vorhanden sind."""

    def test_secrets_status_endpoint_exists(self, client):
        r = client.get("/api/secrets/status")
        assert r.status_code == 200
        assert "categories" in r.json()

    def test_settings_schema_endpoint_exists(self, client):
        r = client.get("/api/settings/schema")
        assert r.status_code == 200
        assert "settings" in r.json()

    def test_settings_values_endpoint_exists(self, client):
        r = client.get("/api/settings/values")
        assert r.status_code == 200
        assert "values" in r.json()
