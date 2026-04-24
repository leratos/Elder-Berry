"""Projekt-weites pytest-Setup.

Phase 64 (H-1): Patcht den Starlette-TestClient so, dass alle
state-changing Requests automatisch einen Default-``Origin``-Header
bekommen. Die neue OriginCheckMiddleware rejected POST/PUT/DELETE/PATCH
ohne passenden Origin -- ohne diesen Patch wuerden ~100 bestehende
Tests mit 403 kippen, obwohl die Produktion fuer Browser-Aufrufe
korrekt funktioniert.

Tests, die explizit das Fehlen oder ein fremdes Origin pruefen wollen
(z.B. ``tests/test_origin_check_middleware.py``), markieren sich per
``pytestmark = pytest.mark.no_default_origin`` -- dann greift der
Patch nicht.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

# Der Default-Port des SettingsDashboard ist 8090; setup_security setzt
# allowed_origins=["http://localhost:8090", "http://127.0.0.1:8090"].
_DEFAULT_TEST_ORIGIN = "http://localhost:8090"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "no_default_origin: Test erwartet, dass der TestClient ohne "
        "automatisch gesetzten Origin-Header arbeitet (fuer CSRF-"
        "Middleware-Tests).",
    )


@pytest.fixture(autouse=True)
def _default_origin_for_testclient(request, monkeypatch):
    if request.node.get_closest_marker("no_default_origin") is not None:
        return

    original_request = TestClient.request

    def patched_request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if (
            str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"}
            and not any(k.lower() == "origin" for k in headers)
        ):
            headers["origin"] = _DEFAULT_TEST_ORIGIN
        kwargs["headers"] = headers
        return original_request(self, method, url, **kwargs)

    monkeypatch.setattr(TestClient, "request", patched_request)
