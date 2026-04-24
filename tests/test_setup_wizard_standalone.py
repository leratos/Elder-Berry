"""Tests: Standalone-Setup-Wizard (Phase 63 Regression).

Der Standalone-Wizard wird von ``scripts/start_saleria.py`` bzw.
``scripts/setup_wizard.py`` beim Erst-Setup gestartet. Seit Phase 63
braucht das Template zwingend /static/js/setup_wizard.js und
/static/css/setup_wizard.css -- fehlt der Static-Mount, sind alle
JS-Handler tot und das Setup blockiert.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from elder_berry.web.setup_wizard import build_standalone_wizard_app


class FakeStore:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def has(self, k: str) -> bool: return k in self._d
    def get(self, k: str) -> str: return self._d[k]
    def get_or_none(self, k: str) -> str | None: return self._d.get(k)
    def set(self, k: str, v: str) -> None: self._d[k] = v
    def delete(self, k: str) -> None: del self._d[k]
    def list_keys(self) -> list[str]: return list(self._d.keys())


@pytest.fixture
def client() -> TestClient:
    app = build_standalone_wizard_app(FakeStore())
    return TestClient(app)


class TestStandaloneStaticAssets:
    """Die vom Template referenzierten /static-Assets muessen liefern."""

    def test_setup_wizard_js_available(self, client):
        r = client.get("/static/js/setup_wizard.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]

    def test_setup_wizard_css_available(self, client):
        r = client.get("/static/css/setup_wizard.css")
        assert r.status_code == 200
        assert "text/css" in r.headers["content-type"]

    def test_setup_html_references_static(self, client):
        r = client.get("/setup")
        assert r.status_code == 200
        assert "/static/js/setup_wizard.js" in r.text
        assert "/static/css/setup_wizard.css" in r.text


class TestStandaloneSecurityHeaders:
    """Auch im Erst-Setup (standalone) muss die strikte CSP wirken."""

    def test_csp_has_no_unsafe_inline(self, client):
        r = client.get("/setup")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "'unsafe-inline'" not in csp
        assert "script-src 'self'" in csp
        assert "connect-src 'self'" in csp

    def test_x_frame_options(self, client):
        r = client.get("/setup")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_options(self, client):
        r = client.get("/setup")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"


class TestStandaloneWizardState:
    """App-State-Flags fuer Standalone-Modus bleiben gesetzt."""

    def test_standalone_flag_true(self):
        app = build_standalone_wizard_app(FakeStore())
        assert app.state.standalone is True

    def test_compat_mode_default_false(self):
        app = build_standalone_wizard_app(FakeStore())
        assert app.state.compat_mode is False

    def test_compat_mode_opt_in(self):
        app = build_standalone_wizard_app(FakeStore(), compat_mode=True)
        assert app.state.compat_mode is True
