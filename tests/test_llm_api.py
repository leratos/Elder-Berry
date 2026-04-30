"""Tests für LLM-Router-Erweiterung (mode) und LLM-API-Endpoints."""

import pytest

try:
    from fastapi.testclient import TestClient
    from elder_berry.web.settings_dashboard import SettingsDashboard
    from elder_berry.llm.router import LLMRouter
    from elder_berry.llm.base import LLMClient
    from elder_berry.core.audio_router import AudioRouter

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

pytestmark = pytest.mark.skipif(not HAS_DEPS, reason="Dependencies nicht installiert")


# ------------------------------------------------------------------
# Fake LLM-Clients
# ------------------------------------------------------------------


class FakeLLMClient(LLMClient):
    """Konfigurierbarer Fake-Client für Tests."""

    def __init__(self, name: str, model: str, available: bool = True) -> None:
        self.name = name
        self.model = model
        self._available = available
        self._last_prompt: str | None = None

    def is_available(self) -> bool:
        return self._available

    def generate(self, prompt: str, system: str = "") -> str:
        if not self._available:
            raise RuntimeError(f"{self.name} nicht verfügbar")
        self._last_prompt = prompt
        return f"[{self.name}] Antwort"


class FakeSecretStore:
    """Minimaler In-Memory SecretStore."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(data) if data else {}

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def get(self, key: str) -> str:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        del self._data[key]


# ------------------------------------------------------------------
# LLMRouter unit tests (mode-Erweiterung)
# ------------------------------------------------------------------


class TestLLMRouterMode:
    """Tests für die mode-Erweiterung des LLMRouter."""

    def _make_router(
        self,
        primary_available: bool = True,
        fallback_available: bool = True,
        mode: str = "api_preferred",
    ) -> LLMRouter:
        primary = FakeLLMClient("anthropic", "claude-sonnet-4-6", primary_available)
        fallback = FakeLLMClient("ollama", "phi4:14b", fallback_available)
        return LLMRouter(primary=primary, fallback=fallback, mode=mode)

    def test_mode_default(self):
        router = self._make_router()
        assert router.mode == "api_preferred"

    def test_mode_setter(self):
        router = self._make_router()
        router.mode = "local_only"
        assert router.mode == "local_only"

    def test_mode_invalid_constructor(self):
        with pytest.raises(ValueError, match="Ungültiger LLM-Modus"):
            self._make_router(mode="turbo")

    def test_mode_invalid_setter(self):
        router = self._make_router()
        with pytest.raises(ValueError, match="Ungültiger LLM-Modus"):
            router.mode = "invalid"

    def test_select_client_api_preferred_both(self):
        router = self._make_router(primary_available=True, fallback_available=True)
        assert router.active_backend == "anthropic"

    def test_select_client_api_preferred_no_primary(self):
        router = self._make_router(primary_available=False, fallback_available=True)
        assert router.active_backend == "ollama"

    def test_select_client_api_preferred_none(self):
        router = self._make_router(primary_available=False, fallback_available=False)
        assert router.active_backend == "none"

    def test_select_client_local_only(self):
        router = self._make_router(
            primary_available=True,
            fallback_available=True,
            mode="local_only",
        )
        assert router.active_backend == "ollama"

    def test_select_client_local_only_no_fallback(self):
        router = self._make_router(
            primary_available=True,
            fallback_available=False,
            mode="local_only",
        )
        with pytest.raises(RuntimeError, match="local_only"):
            router.generate("test")

    def test_generate_uses_correct_backend(self):
        primary = FakeLLMClient("anthropic", "claude-sonnet-4-6", True)
        fallback = FakeLLMClient("ollama", "phi4:14b", True)
        router = LLMRouter(primary=primary, fallback=fallback, mode="local_only")
        result = router.generate("Hallo")
        assert "[ollama]" in result
        assert fallback._last_prompt == "Hallo"
        assert primary._last_prompt is None

    def test_active_backend_reflects_mode(self):
        router = self._make_router(primary_available=True, fallback_available=True)
        assert router.active_backend == "anthropic"
        router.mode = "local_only"
        assert router.active_backend == "ollama"

    def test_primary_fallback_properties(self):
        router = self._make_router()
        assert router.primary_name == "claude-sonnet-4-6"
        assert router.fallback_name == "phi4:14b"
        assert router.primary_available is True
        assert router.fallback_available is True


# ------------------------------------------------------------------
# LLM-API-Endpoint-Tests
# ------------------------------------------------------------------


def _make_client(
    primary_available: bool = True,
    fallback_available: bool = True,
    mode: str = "api_preferred",
    with_store: bool = True,
) -> tuple[TestClient, LLMRouter, FakeSecretStore | None]:
    primary = FakeLLMClient("anthropic", "claude-sonnet-4-6", primary_available)
    fallback = FakeLLMClient("ollama", "phi4:14b", fallback_available)
    router = LLMRouter(primary=primary, fallback=fallback, mode=mode)
    store = FakeSecretStore() if with_store else None
    audio = AudioRouter(local_available=False)
    dashboard = SettingsDashboard(
        audio_router=audio,
        secret_store=store,
        llm_router=router,
    )
    return TestClient(dashboard.app), router, store


class TestLLMStatusEndpoint:
    """GET /api/llm/status"""

    def test_status_api_preferred(self):
        client, _, _ = _make_client()
        r = client.get("/api/llm/status")
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert data["mode"] == "api_preferred"
        assert data["active_backend"] == "anthropic"

    def test_status_both_available(self):
        client, _, _ = _make_client()
        data = client.get("/api/llm/status").json()
        assert data["primary"]["available"] is True
        assert data["fallback"]["available"] is True
        assert data["primary"]["name"] == "claude-sonnet-4-6"
        assert data["fallback"]["name"] == "phi4:14b"

    def test_status_ollama_only(self):
        client, _, _ = _make_client(primary_available=False)
        data = client.get("/api/llm/status").json()
        assert data["active_backend"] == "ollama"
        assert data["primary"]["available"] is False
        assert data["fallback"]["available"] is True

    def test_status_no_router(self):
        audio = AudioRouter(local_available=False)
        dashboard = SettingsDashboard(audio_router=audio, llm_router=None)
        client = TestClient(dashboard.app)
        data = client.get("/api/llm/status").json()
        assert data["available"] is False
        assert data["active_backend"] == "none"


class TestLLMModeEndpoint:
    """POST /api/llm/mode"""

    def test_switch_to_local(self):
        client, router, store = _make_client()
        r = client.post("/api/llm/mode", json={"mode": "local_only"})
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "local_only"
        assert data["active_backend"] == "ollama"
        assert router.mode == "local_only"

    def test_switch_to_api(self):
        client, router, _ = _make_client(mode="local_only")
        r = client.post("/api/llm/mode", json={"mode": "api_preferred"})
        assert r.status_code == 200
        assert r.json()["mode"] == "api_preferred"
        assert router.mode == "api_preferred"

    def test_invalid_mode(self):
        client, _, _ = _make_client()
        r = client.post("/api/llm/mode", json={"mode": "turbo"})
        assert r.status_code == 400
        assert "Ungültiger" in r.json()["error"]

    def test_no_router(self):
        audio = AudioRouter(local_available=False)
        dashboard = SettingsDashboard(audio_router=audio, llm_router=None)
        client = TestClient(dashboard.app)
        r = client.post("/api/llm/mode", json={"mode": "local_only"})
        assert r.status_code == 503

    def test_mode_persisted_in_secret_store(self):
        client, _, store = _make_client()
        client.post("/api/llm/mode", json={"mode": "local_only"})
        assert store.get("llm_mode") == "local_only"

    def test_mode_persisted_switch_back(self):
        client, _, store = _make_client(mode="local_only")
        client.post("/api/llm/mode", json={"mode": "api_preferred"})
        assert store.get("llm_mode") == "api_preferred"
