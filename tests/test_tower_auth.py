"""Tests für Phase 57.3: Tower-Token-Auth (Middleware + TowerAgent).

Prüft, dass der TowerServer Requests ohne gültigen Token ablehnt
und der TowerAgent den Token-Header mitsendet.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tower.tower_server import TowerTokenMiddleware, _load_tower_token

    HAS_TOWER = True
except ImportError:
    HAS_TOWER = False

pytestmark = pytest.mark.skipif(not HAS_TOWER, reason="tower/fastapi nicht verfügbar")


# ---------------------------------------------------------------------------
# TowerTokenMiddleware
# ---------------------------------------------------------------------------


def _make_app(token: str | None = None) -> FastAPI:
    """Erzeugt eine Test-App mit TowerTokenMiddleware."""
    app = FastAPI()
    app.state.tower_token = token
    app.add_middleware(TowerTokenMiddleware)

    @app.get("/status")
    async def status():
        return {"ok": True}

    @app.post("/action")
    async def action():
        return {"ok": True}

    return app


class TestTowerTokenMiddleware:
    """Middleware lehnt Requests ohne/mit falschem Token ab."""

    def test_rejects_missing_header(self):
        client = TestClient(_make_app("secret123"))
        r = client.get("/status")
        assert r.status_code == 401
        assert r.json()["header"] == "X-Saleria-Tower-Token"

    def test_rejects_wrong_token(self):
        client = TestClient(_make_app("secret123"))
        r = client.post(
            "/action",
            json={},
            headers={"X-Saleria-Tower-Token": "wrong"},
        )
        assert r.status_code == 401

    def test_accepts_correct_token(self):
        client = TestClient(_make_app("secret123"))
        r = client.get(
            "/status",
            headers={"X-Saleria-Tower-Token": "secret123"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_500_when_no_token_configured(self):
        client = TestClient(_make_app(None))
        r = client.get("/status")
        assert r.status_code == 500
        assert "nicht konfiguriert" in r.json()["error"]

    def test_constant_time_comparison(self):
        """Token-Vergleich nutzt secrets.compare_digest."""
        import inspect
        from tower.tower_server import TowerTokenMiddleware

        source = inspect.getsource(TowerTokenMiddleware.dispatch)
        assert "compare_digest" in source


# ---------------------------------------------------------------------------
# _load_tower_token
# ---------------------------------------------------------------------------


class TestLoadTowerToken:
    """Token-Lade-Logik: Env → SecretStore → RuntimeError."""

    def test_env_variable_takes_priority(self, monkeypatch):
        monkeypatch.setenv("ELDER_BERRY_TOWER_TOKEN", "from-env")
        assert _load_tower_token() == "from-env"

    def test_secret_store_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ELDER_BERRY_TOWER_TOKEN", raising=False)
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)
        store.set("tower_auth_token", "from-store")
        with patch.dict(os.environ, {}, clear=False):
            with patch("elder_berry.core.secret_store.SecretStore", return_value=store):
                token = _load_tower_token()
        assert token == "from-store"

    def test_raises_when_nothing_configured(self, monkeypatch):
        monkeypatch.delenv("ELDER_BERRY_TOWER_TOKEN", raising=False)
        with patch("elder_berry.core.secret_store.SecretStore") as mock_cls:
            mock_store = MagicMock()
            mock_store.get_or_none.return_value = None
            mock_cls.return_value = mock_store
            with pytest.raises(RuntimeError, match="Kein Tower-Token"):
                _load_tower_token()

    def test_env_beats_store(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ELDER_BERRY_TOWER_TOKEN", "env-wins")
        from elder_berry.core.secret_store import SecretStore

        store = SecretStore(base_dir=tmp_path)
        store.set("tower_auth_token", "store-loses")
        assert _load_tower_token() == "env-wins"


# ---------------------------------------------------------------------------
# TowerAgent auth headers
# ---------------------------------------------------------------------------


class TestTowerAgentAuth:
    """TowerAgent sendet den Token-Header mit."""

    def test_auth_headers_present_when_token_set(self):
        from elder_berry.core.tower_agent import TowerAgent

        agent = TowerAgent(tower_host="127.0.0.1:8090", tower_token="tok123")
        headers = agent._auth_headers()
        assert headers == {"X-Saleria-Tower-Token": "tok123"}

    def test_auth_headers_empty_when_no_token(self):
        from elder_berry.core.tower_agent import TowerAgent

        agent = TowerAgent(tower_host="127.0.0.1:8090")
        headers = agent._auth_headers()
        assert headers == {}

    def test_httpx_client_uses_auth_headers(self):
        """Alle httpx.AsyncClient-Aufrufe haben headers=self._auth_headers()."""
        import inspect
        from elder_berry.core.tower_agent import TowerAgent

        source = inspect.getsource(TowerAgent)
        assert source.count("headers=self._auth_headers()") >= 6


# ---------------------------------------------------------------------------
# Auto-Migration in start_saleria.py
# ---------------------------------------------------------------------------


class TestAutoMigration:
    """Phase 57.3: Token wird beim Agent-Start automatisch generiert."""

    def test_start_saleria_auto_generates_token(self):
        """start_saleria.py Agent-Mode generiert Token wenn keiner existiert."""
        import inspect
        from scripts.start_saleria import run_agent

        source = inspect.getsource(run_agent)
        assert "tower_auth_token" in source
        assert "token_hex" in source

    def test_registry_has_tower_auth_token(self):
        """SECRET_REGISTRY enthält den tower_auth_token-Eintrag."""
        from elder_berry.web.secrets_api import SECRET_REGISTRY

        keys = {e["key"] for e in SECRET_REGISTRY}
        assert "tower_auth_token" in keys

    def test_registry_tower_auth_token_is_sensitive(self):
        from elder_berry.web.secrets_api import SECRET_REGISTRY

        entry = next(e for e in SECRET_REGISTRY if e["key"] == "tower_auth_token")
        assert entry["sensitive"] is True
        assert entry["risk_level"] == "high"
