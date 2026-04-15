"""Tests: Phase 52.1b – Settings-Panel-Frontend (Smoke-Tests).

Vanilla-JS-UIs lassen sich ohne Browser nur eingeschränkt prüfen.
Diese Tests verifizieren, dass:
- die /settings-Route das Template ausliefert
- das Template alle 3 Tabs, alle erwarteten Hooks und alle benötigten
  API-Endpunkt-URLs enthält
- die Backend-Endpunkte, die das Frontend aufruft, alle existieren
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from elder_berry.core.audio_router import AudioRouter
from elder_berry.web.settings_dashboard import SettingsDashboard


_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src" / "elder_berry" / "web" / "templates" / "settings_panel.html"
)


@pytest.fixture
def dashboard():
    secret_store = MagicMock()
    secret_store.get_or_none.return_value = None
    secret_store.has.return_value = True  # Setup gilt als abgeschlossen
    dash = SettingsDashboard(
        audio_router=AudioRouter(),
        secret_store=secret_store,
    )
    return dash


@pytest.fixture
def client(dashboard):
    return TestClient(dashboard.app)


# ---------------------------------------------------------------------------
# Template-Datei
# ---------------------------------------------------------------------------

class TestTemplateFile:
    def test_exists(self):
        assert _TEMPLATE.exists(), f"Template fehlt: {_TEMPLATE}"

    def test_is_html(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text
        assert "</html>" in text

    def test_has_three_tabs(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        for tab in ("dienste", "verhalten", "sicherheit"):
            assert f'data-tab="{tab}"' in text
            assert f'id="tab-{tab}"' in text

    def test_calls_secrets_status(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/secrets/status" in text

    def test_calls_settings_schema_and_values(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/settings/schema" in text
        assert "/api/settings/values" in text

    def test_calls_settings_update(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/settings/update" in text

    def test_calls_security_endpoint(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/settings/security" in text

    def test_calls_test_endpoint(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/settings/test/" in text

    def test_calls_secrets_set(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "/api/secrets/set" in text

    def test_has_deep_link_handling(self):
        text = _TEMPLATE.read_text(encoding="utf-8")
        assert "location.hash" in text

    def test_no_external_scripts(self):
        """Settings-Panel darf keine externen CDN-Skripte laden."""
        text = _TEMPLATE.read_text(encoding="utf-8").lower()
        assert "<script src=" not in text  # nur inline-Script erlaubt


# ---------------------------------------------------------------------------
# /settings-Route
# ---------------------------------------------------------------------------

class TestSettingsRoute:
    def test_route_returns_template(self, client):
        r = client.get("/settings")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert "Elder-Berry – Einstellungen" in body
        assert 'data-tab="dienste"' in body

    def test_route_does_not_redirect_to_setup(self, client):
        """Im Gegensatz zu / leitet /settings nicht zum Setup-Wizard um."""
        r = client.get("/settings", follow_redirects=False)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Backend-Endpunkte, die das Frontend aufruft, müssen existieren
# ---------------------------------------------------------------------------

class TestBackendContractsExist:
    def test_secrets_status(self, client):
        r = client.get("/api/secrets/status")
        assert r.status_code == 200

    def test_settings_schema(self, client):
        r = client.get("/api/settings/schema")
        assert r.status_code == 200
        body = r.json()
        assert "settings" in body

    def test_settings_values(self, client):
        r = client.get("/api/settings/values")
        assert r.status_code == 200

    def test_security_endpoint(self, client):
        r = client.get("/api/settings/security")
        assert r.status_code == 200
        body = r.json()
        assert "cors" in body and "allowed_senders" in body

    def test_test_endpoint_known_service(self, client):
        # Ohne Credentials → 400 missing_config (= Endpoint existiert)
        r = client.post("/api/settings/test/anthropic")
        assert r.status_code in (400, 503)

    def test_test_endpoint_unknown_service(self, client):
        r = client.post("/api/settings/test/foo_bar_unknown")
        assert r.status_code == 404
