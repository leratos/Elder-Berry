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

Phase 77 Etappe 3: Plugin-Discovery-Sandbox. Standardmaessig sind
``_load_user_directory`` und ``_load_entry_points`` waehrend der
Test-Suite stillgelegt. Sonst wuerden Tests, die ``RemoteCommandHandler``
oder ``load_plugins`` aufrufen, beim Lauf:
1. Tatsaechlich liegende ``~/.elder-berry/plugins/*.py`` einlesen
   (User-Maschine, evtl. fehlerhaft / nicht erwartet im Test).
2. Per ``importlib.metadata.entry_points`` zufaellig pip-installierte
   Pakete der Group ``elder_berry.commands`` laden.
Beides macht die Suite nicht-deterministisch. Tests, die genau diese
Loader pruefen wollen (``test_plugin_user_dir.py``,
``test_plugin_entry_points.py``), markieren sich per
``pytestmark = pytest.mark.real_plugin_loaders``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from elder_berry.comms.commands import registry as plugin_registry
from elder_berry.comms.commands.registry import LoadedPlugin

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
    config.addinivalue_line(
        "markers",
        "real_plugin_loaders: Test will _load_user_directory bzw. "
        "_load_entry_points wirklich laufen lassen (fuer Discovery-"
        "Tests). Standardmaessig sind beide Loader stillgelegt.",
    )


@pytest.fixture(autouse=True)
def _default_origin_for_testclient(request, monkeypatch):
    if request.node.get_closest_marker("no_default_origin") is not None:
        return

    original_request = TestClient.request

    def patched_request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"} and not any(
            k.lower() == "origin" for k in headers
        ):
            headers["origin"] = _DEFAULT_TEST_ORIGIN
        kwargs["headers"] = headers
        return original_request(self, method, url, **kwargs)

    monkeypatch.setattr(TestClient, "request", patched_request)


def _empty_plugin_iter() -> Iterator[LoadedPlugin]:
    return iter(())


@pytest.fixture(autouse=True)
def _disable_external_plugin_loaders(request, monkeypatch):
    """Sandbox: User-Dir- und Entry-Point-Discovery stillgelegt.

    Verhindert, dass Tests waehrend des Laufs lokale User-Plugins oder
    pip-installierte Drittanbieter-Plugins aufnehmen. Der Builtin-Loader
    bleibt unangetastet -- alle 23 Repo-Plugins werden weiter geladen.
    """
    if request.node.get_closest_marker("real_plugin_loaders") is not None:
        return
    monkeypatch.setattr(plugin_registry, "_load_user_directory", _empty_plugin_iter)
    monkeypatch.setattr(plugin_registry, "_load_entry_points", _empty_plugin_iter)
