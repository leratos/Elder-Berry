"""Tests: Phase 52.3 – /setup blockt mit Bestätigungs-Dialog nach Setup-Completion."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.setup_wizard import (
    SETUP_COMPLETE_KEY,
    _RECONFIRM_PAGE,
    register_setup_wizard_routes,
)


def _app(secret_store):
    app = FastAPI()
    register_setup_wizard_routes(app, secret_store)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Reconfirm-Page-HTML
# ---------------------------------------------------------------------------

class TestReconfirmPage:
    def test_contains_links(self):
        assert "/settings#dienste" in _RECONFIRM_PAGE
        assert 'href="/setup?confirm=1"' in _RECONFIRM_PAGE
        assert 'href="/"' in _RECONFIRM_PAGE

    def test_contains_warning(self):
        assert "Setup ist bereits abgeschlossen" in _RECONFIRM_PAGE
        assert "Schritt" in _RECONFIRM_PAGE


# ---------------------------------------------------------------------------
# /setup Route-Verhalten
# ---------------------------------------------------------------------------

class TestSetupRouteBlocking:
    def test_first_run_serves_wizard(self, tmp_path, monkeypatch):
        """Wenn Setup nicht abgeschlossen ist, liefert /setup den Wizard."""
        store = MagicMock()
        store.has.side_effect = lambda k: False  # nichts gesetzt
        client = _app(store)

        r = client.get("/setup")
        assert r.status_code == 200
        # Entweder der Wizard oder das Template-fehlt-Fallback,
        # aber NIEMALS die Reconfirm-Seite
        assert "Setup ist bereits abgeschlossen" not in r.text

    def test_completed_blocks_with_confirm_page(self):
        """Wenn setup_wizard_completed gesetzt ist, kommt die Reconfirm-Seite."""
        store = MagicMock()
        store.has.side_effect = lambda k: k == SETUP_COMPLETE_KEY
        client = _app(store)

        r = client.get("/setup")
        assert r.status_code == 200
        assert "Setup ist bereits abgeschlossen" in r.text
        assert "/settings#dienste" in r.text
        assert "/setup?confirm=1" in r.text

    def test_completed_with_confirm_serves_wizard(self):
        """Mit ?confirm=1 wird der Wizard auch nach Completion ausgeliefert."""
        store = MagicMock()
        store.has.side_effect = lambda k: k == SETUP_COMPLETE_KEY
        client = _app(store)

        r = client.get("/setup?confirm=1")
        assert r.status_code == 200
        # Kein Reconfirm-Inhalt
        assert "Setup ist bereits abgeschlossen" not in r.text

    def test_confirm_zero_explicitly_blocks(self):
        """confirm=0 verhält sich wie ohne Parameter."""
        store = MagicMock()
        store.has.side_effect = lambda k: k == SETUP_COMPLETE_KEY
        client = _app(store)

        r = client.get("/setup?confirm=0")
        assert "Setup ist bereits abgeschlossen" in r.text

    def test_confirm_other_value_blocks(self):
        """Beliebige Werte ungleich 1 blocken weiterhin."""
        store = MagicMock()
        store.has.side_effect = lambda k: k == SETUP_COMPLETE_KEY
        client = _app(store)

        r = client.get("/setup?confirm=2")
        assert "Setup ist bereits abgeschlossen" in r.text
