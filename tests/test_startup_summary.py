"""Tests: Phase 52.2 – Startup-Summary in scripts/start_saleria.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# scripts/ ist kein Python-Package – via spec aus Datei laden
_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "start_saleria.py"


@pytest.fixture(scope="module")
def start_saleria():
    spec = importlib.util.spec_from_file_location("start_saleria_mod", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["start_saleria_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_store(values: dict[str, str | None]):
    """Mock-SecretStore mit get_or_none()."""
    store = MagicMock()
    store.get_or_none.side_effect = lambda k: values.get(k)
    return store


# ---------------------------------------------------------------------------
# _summary_check_secrets
# ---------------------------------------------------------------------------

class TestSummaryCheckSecrets:
    def test_all_set_returns_true(self, start_saleria):
        store = _make_store({"a": "x", "b": "y"})
        assert start_saleria._summary_check_secrets(store, ["a", "b"]) is True

    def test_one_missing_returns_false(self, start_saleria):
        store = _make_store({"a": "x", "b": None})
        assert start_saleria._summary_check_secrets(store, ["a", "b"]) is False

    def test_empty_string_counts_as_missing(self, start_saleria):
        store = _make_store({"a": ""})
        assert start_saleria._summary_check_secrets(store, ["a"]) is False

    def test_no_store_returns_false(self, start_saleria):
        assert start_saleria._summary_check_secrets(None, ["a"]) is False

    def test_exception_returns_false(self, start_saleria):
        store = MagicMock()
        store.get_or_none.side_effect = RuntimeError("db down")
        assert start_saleria._summary_check_secrets(store, ["a"]) is False


# ---------------------------------------------------------------------------
# _summary_llm_label
# ---------------------------------------------------------------------------

class TestSummaryLlmLabel:
    def test_none(self, start_saleria):
        assert start_saleria._summary_llm_label(None) == "kein Backend"

    def test_backend_only(self, start_saleria):
        llm = MagicMock(spec=["active_backend"])
        llm.active_backend = "anthropic"
        assert start_saleria._summary_llm_label(llm) == "anthropic"

    def test_backend_and_model(self, start_saleria):
        llm = MagicMock(spec=["active_backend", "active_model"])
        llm.active_backend = "anthropic"
        llm.active_model = "claude-sonnet-4-6"
        result = start_saleria._summary_llm_label(llm)
        assert "anthropic" in result and "claude-sonnet-4-6" in result


# ---------------------------------------------------------------------------
# _summary_tower_label
# ---------------------------------------------------------------------------

class TestSummaryTowerLabel:
    def test_no_host_warn(self, start_saleria):
        store = _make_store({})
        sym, label = start_saleria._summary_tower_label(store, None)
        assert sym == "⚠"
        assert "nicht konfiguriert" in label

    def test_agent_online(self, start_saleria):
        store = _make_store({"tower_host": "127.0.0.1:12769"})
        agent = MagicMock()
        agent.heartbeat = AsyncMock(return_value=True)
        sym, label = start_saleria._summary_tower_label(store, agent)
        assert sym == "✓"
        assert "127.0.0.1:12769" in label

    def test_agent_offline(self, start_saleria):
        store = _make_store({"tower_host": "127.0.0.1:12769"})
        agent = MagicMock()
        agent.heartbeat = AsyncMock(return_value=False)
        sym, label = start_saleria._summary_tower_label(store, agent)
        assert sym == "✗"
        assert "nicht erreichbar" in label

    def test_agent_raises(self, start_saleria):
        store = _make_store({"tower_host": "127.0.0.1:12769"})
        agent = MagicMock()
        agent.heartbeat = AsyncMock(side_effect=RuntimeError("boom"))
        sym, _ = start_saleria._summary_tower_label(store, agent)
        assert sym == "✗"


# ---------------------------------------------------------------------------
# _summary_robot_label
# ---------------------------------------------------------------------------

class TestSummaryRobotLabel:
    def test_no_host_warn(self, start_saleria):
        sym, label = start_saleria._summary_robot_label(_make_store({}), None)
        assert sym == "⚠"
        assert "nicht konfiguriert" in label

    def test_no_robot_offline(self, start_saleria):
        store = _make_store({"robot_host": "http://pi:8000"})
        sym, label = start_saleria._summary_robot_label(store, None)
        assert sym == "✗"

    def test_robot_online(self, start_saleria):
        store = _make_store({"robot_host": "http://pi:8000"})
        robot = MagicMock()
        robot.is_online.return_value = True
        sym, label = start_saleria._summary_robot_label(store, robot)
        assert sym == "✓"
        assert "http://pi:8000" in label

    def test_robot_raises(self, start_saleria):
        store = _make_store({"robot_host": "http://pi:8000"})
        robot = MagicMock()
        robot.is_online.side_effect = RuntimeError("dead")
        sym, _ = start_saleria._summary_robot_label(store, robot)
        assert sym == "✗"


# ---------------------------------------------------------------------------
# _print_startup_summary
# ---------------------------------------------------------------------------

class TestPrintStartupSummary:
    def _row(self, rows, name):
        for sym, n, label in rows:
            if n == name:
                return sym, label
        raise AssertionError(f"Row '{name}' nicht gefunden in {rows}")

    def test_all_unconfigured(self, start_saleria, capsys):
        rows = start_saleria._print_startup_summary(secret_store=_make_store({}))
        out = capsys.readouterr().out
        assert "Saleria – Startup Summary" in out
        # Alle Services außer Tower (kein host → ⚠)
        for name in ("LLM", "Matrix", "Kalender", "Wetter", "E-Mail",
                     "Nextcloud", "Tower", "RPi5"):
            sym, _ = self._row(rows, name)
            assert sym == "⚠", f"{name} sollte ⚠ sein"

    def test_llm_active_backend(self, start_saleria, capsys):
        llm = MagicMock(spec=["active_backend", "active_model"])
        llm.active_backend = "anthropic"
        llm.active_model = "claude-sonnet-4-6"
        rows = start_saleria._print_startup_summary(
            secret_store=_make_store({}), llm=llm,
        )
        sym, label = self._row(rows, "LLM")
        assert sym == "✓"
        assert "anthropic" in label

    def test_matrix_with_password(self, start_saleria, capsys):
        store = _make_store({
            "matrix_homeserver": "https://matrix.example.com",
            "matrix_user_id": "@bot:matrix.example.com",
            "matrix_password": "secret",
        })
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, label = self._row(rows, "Matrix")
        assert sym == "✓"
        assert "@bot:matrix.example.com" in label

    def test_matrix_with_token(self, start_saleria):
        store = _make_store({
            "matrix_homeserver": "https://matrix.example.com",
            "matrix_user_id": "@bot:matrix.example.com",
            "matrix_access_token": "abc",
        })
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, _ = self._row(rows, "Matrix")
        assert sym == "✓"

    def test_calendar_nextcloud(self, start_saleria):
        store = _make_store({
            "nextcloud_url": "https://cloud.example.com",
            "nextcloud_user": "user",
        })
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, label = self._row(rows, "Kalender")
        assert sym == "✓"
        assert "Nextcloud" in label

    def test_weather_city(self, start_saleria):
        store = _make_store({"weather_city": "Berlin"})
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, label = self._row(rows, "Wetter")
        assert sym == "✓"
        assert "Berlin" in label

    def test_weather_coords_only(self, start_saleria):
        store = _make_store({
            "weather_latitude": "52.52",
            "weather_longitude": "13.41",
        })
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, label = self._row(rows, "Wetter")
        assert sym == "✓"
        assert "Koordinaten" in label

    def test_email_complete(self, start_saleria):
        store = _make_store({
            "email_imap_host": "imap.strato.de",
            "email_user": "me@example.com",
            "email_password": "secret",
        })
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, label = self._row(rows, "E-Mail")
        assert sym == "✓"
        assert "me@example.com" in label

    def test_nextcloud_complete(self, start_saleria):
        store = _make_store({
            "nextcloud_url": "https://cloud.example.com",
            "nextcloud_user": "u",
            "nextcloud_app_password": "p",
        })
        rows = start_saleria._print_startup_summary(secret_store=store)
        sym, _ = self._row(rows, "Nextcloud")
        assert sym == "✓"

    def test_tower_uses_provided_agent(self, start_saleria):
        store = _make_store({"tower_host": "127.0.0.1:12769"})
        agent = MagicMock()
        agent.heartbeat = AsyncMock(return_value=True)
        rows = start_saleria._print_startup_summary(
            secret_store=store, tower_agent=agent,
        )
        sym, _ = self._row(rows, "Tower")
        assert sym == "✓"

    def test_robot_provided(self, start_saleria):
        store = _make_store({"robot_host": "http://pi:8000"})
        robot = MagicMock()
        robot.is_online.return_value = True
        rows = start_saleria._print_startup_summary(
            secret_store=store, robot=robot,
        )
        sym, _ = self._row(rows, "RPi5")
        assert sym == "✓"

    def test_box_drawing_present(self, start_saleria, capsys):
        start_saleria._print_startup_summary(secret_store=_make_store({}))
        out = capsys.readouterr().out
        assert "╔" in out and "╗" in out
        assert "╠" in out and "╣" in out
        assert "╚" in out and "╝" in out
