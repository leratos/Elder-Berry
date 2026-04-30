"""Tests für Phase 57.1: Loopback-Default + Grace-Period.

Prüft, dass Setup-Wizard und TowerAgent per Default auf 127.0.0.1 binden,
die Env-Variablen greifen und die Grace-Period-Logik beim Upgrade korrekt
ist (Marker-Datei, compat_mode-Flag, Banner im UI).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from elder_berry.web.setup_wizard import (
        run_setup_wizard,
        register_setup_wizard_routes,
    )

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


# ---------------------------------------------------------------------------
# run_setup_wizard – bind-Parameter
# ---------------------------------------------------------------------------


class TestSetupWizardBind:
    """Phase 57.1: run_setup_wizard Default-Bind + Env-Override."""

    def test_default_bind_is_loopback(self):
        """Default-Parameterwert muss 127.0.0.1 sein."""
        import inspect

        sig = inspect.signature(run_setup_wizard)
        assert sig.parameters["bind"].default == "127.0.0.1"

    @patch("uvicorn.run")
    def test_bind_parameter_forwarded_to_uvicorn(self, mock_run, tmp_path):
        """Der bind-Wert wird an uvicorn.run(host=...) durchgereicht."""
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)

        run_setup_wizard(store, port=9999, bind="192.168.1.50")

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["host"] == "192.168.1.50"
        assert kwargs["port"] == 9999

    @patch("uvicorn.run")
    def test_compat_mode_sets_app_state(self, mock_run, tmp_path):
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)

        run_setup_wizard(store, compat_mode=True)

        # FastAPI-App wird als erstes positionales Arg an uvicorn.run übergeben
        app = mock_run.call_args[0][0]
        assert getattr(app.state, "compat_mode", False) is True

    @patch("uvicorn.run")
    def test_migration_marker_sets_app_state(self, mock_run, tmp_path):
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)
        marker = tmp_path / ".phase57_migration_done"

        run_setup_wizard(store, migration_marker=marker)

        app = mock_run.call_args[0][0]
        assert getattr(app.state, "migration_marker", None) == marker


# ---------------------------------------------------------------------------
# Grace-Period: Compat-Banner im Wizard-UI
# ---------------------------------------------------------------------------


class TestCompatBanner:
    """Phase 57.1a: Gelbes Banner wird injiziert wenn compat_mode aktiv."""

    def _make_wizard_app(self, secret_store, compat_mode: bool = False):
        app = FastAPI()
        app.state.compat_mode = compat_mode
        app.state.migration_marker = None
        register_setup_wizard_routes(app, secret_store)
        return app

    def test_banner_present_in_compat_mode(self, tmp_path):
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)

        app = self._make_wizard_app(store, compat_mode=True)
        client = TestClient(app)
        r = client.get("/setup")
        assert r.status_code == 200
        assert "LAN-Kompatibilit" in r.text
        assert "ELDER_BERRY_SETUP_BIND" in r.text

    def test_banner_absent_in_normal_mode(self, tmp_path):
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)

        app = self._make_wizard_app(store, compat_mode=False)
        client = TestClient(app)
        r = client.get("/setup")
        assert r.status_code == 200
        assert "LAN-Kompatibilit" not in r.text


# ---------------------------------------------------------------------------
# Grace-Period: Marker-Datei beim Complete
# ---------------------------------------------------------------------------


class TestMigrationMarker:
    """Phase 57.1a: /api/setup/complete schreibt die Marker-Datei."""

    def test_marker_written_on_complete(self, tmp_path):
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)
        marker = tmp_path / ".phase57_migration_done"

        app = FastAPI()
        app.state.standalone = False
        app.state.compat_mode = False
        app.state.migration_marker = marker
        register_setup_wizard_routes(app, store)

        client = TestClient(app)
        # Phase 58: complete verlangt vorher gesetztes Dashboard-PW
        r0 = client.post(
            "/api/setup/dashboard-password",
            json={"password": "supersecret123"},
        )
        assert r0.status_code == 200
        r = client.post("/api/setup/complete")
        assert r.status_code == 200
        assert marker.exists()
        assert marker.read_text(encoding="utf-8") == "done"

    def test_no_marker_written_when_path_none(self, tmp_path):
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)

        app = FastAPI()
        app.state.standalone = False
        app.state.compat_mode = False
        app.state.migration_marker = None
        register_setup_wizard_routes(app, store)

        client = TestClient(app)
        # Phase 58: complete verlangt vorher gesetztes Dashboard-PW
        r0 = client.post(
            "/api/setup/dashboard-password",
            json={"password": "supersecret123"},
        )
        assert r0.status_code == 200
        r = client.post("/api/setup/complete")
        assert r.status_code == 200
        # Kein Marker-Pfad → kein Crash, kein Marker
        assert not (tmp_path / ".phase57_migration_done").exists()


# ---------------------------------------------------------------------------
# Tower-Agent Bind (start_saleria.py)
# ---------------------------------------------------------------------------


class TestTowerAgentBind:
    """Phase 57.1: TowerServer Default-Bind aus Start-Skript."""

    def test_start_saleria_has_tower_bind_env_reference(self):
        """start_saleria.py muss ELDER_BERRY_TOWER_BIND referenzieren."""
        source = Path(__file__).parent.parent / "scripts" / "start_saleria.py"
        content = source.read_text(encoding="utf-8")
        assert "ELDER_BERRY_TOWER_BIND" in content

    def test_start_saleria_tower_bind_default_loopback(self):
        """Default in der os.environ.get-Zeile muss 127.0.0.1 sein."""
        source = Path(__file__).parent.parent / "scripts" / "start_saleria.py"
        content = source.read_text(encoding="utf-8")
        assert 'os.environ.get("ELDER_BERRY_TOWER_BIND", "127.0.0.1")' in content

    def test_start_saleria_has_setup_bind_env_reference(self):
        """start_saleria.py muss ELDER_BERRY_SETUP_BIND referenzieren."""
        source = Path(__file__).parent.parent / "scripts" / "start_saleria.py"
        content = source.read_text(encoding="utf-8")
        assert "ELDER_BERRY_SETUP_BIND" in content

    def test_start_saleria_setup_bind_default_loopback(self):
        """Default in der os.environ.get-Zeile muss 127.0.0.1 sein."""
        source = Path(__file__).parent.parent / "scripts" / "start_saleria.py"
        content = source.read_text(encoding="utf-8")
        assert 'os.environ.get("ELDER_BERRY_SETUP_BIND", "127.0.0.1")' in content
