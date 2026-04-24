"""Tests für Phase 59.1 + 64 H-2: Robot-Token im RPi5-Start-Script.

Phase 59 führte Token-Auth im RobotServer ein. ``start_rpi5.py`` hat den
Parameter aber nie an ``RobotServer`` durchgereicht – die Middleware war
dadurch dauerhaft im Bypass und alle Endpoints (inkl. ``/system/update``,
RCE-fähig) waren im LAN ungeprüft erreichbar. Dieser Test verhindert,
dass diese Regression nochmal passiert.

Phase 64 (H-2) erweitert das um einen Hard-Fail: Wenn kein Token gesetzt
ist und der Host NICHT Loopback ist, soll der Start sofort abbrechen
(statt nur zu warnen -- Warnings wurden im systemd-Log uebersehen).

Der zweite Test (AST-basiert) ist Absicht: ein reiner Unit-Test auf
``_resolve_robot_token`` würde nicht fangen, wenn jemand die Funktion
wieder aus dem ``RobotServer(...)``-Aufruf entfernt. Hardware-Imports
(pygame, lgpio) machen einen echten ``main()``-Aufruf im Test teuer –
AST liest die Datei statisch und ist unabhängig davon.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
START_RPI5 = PROJECT_ROOT / "scripts" / "start_rpi5.py"


def _load_start_rpi5_module():
    """Lädt scripts/start_rpi5.py als Modul (ohne main() auszuführen)."""
    spec = importlib.util.spec_from_file_location("start_rpi5", START_RPI5)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# _resolve_robot_token – Unit-Test
# ---------------------------------------------------------------------------


class TestResolveRobotToken:
    def test_returns_token_from_env(self, monkeypatch):
        monkeypatch.setenv("ELDER_BERRY_ROBOT_TOKEN", "abc123")
        mod = _load_start_rpi5_module()
        assert mod._resolve_robot_token() == "abc123"

    def test_returns_none_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("ELDER_BERRY_ROBOT_TOKEN", raising=False)
        mod = _load_start_rpi5_module()
        assert mod._resolve_robot_token() is None

    def test_returns_none_for_empty_string(self, monkeypatch):
        """Leerer Env-Wert darf keine Auth aktivieren (wäre False Security)."""
        monkeypatch.setenv("ELDER_BERRY_ROBOT_TOKEN", "")
        mod = _load_start_rpi5_module()
        assert mod._resolve_robot_token() is None

    def test_strips_whitespace(self, monkeypatch):
        """Copy-Paste aus systemctl edit kann Whitespace enthalten."""
        monkeypatch.setenv("ELDER_BERRY_ROBOT_TOKEN", "  abc123  ")
        mod = _load_start_rpi5_module()
        assert mod._resolve_robot_token() == "abc123"

    def test_returns_none_for_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("ELDER_BERRY_ROBOT_TOKEN", "   ")
        mod = _load_start_rpi5_module()
        assert mod._resolve_robot_token() is None


# ---------------------------------------------------------------------------
# AST-Regression: RobotServer(...) MUSS robot_token= bekommen
# ---------------------------------------------------------------------------


class TestRobotServerCallUsesToken:
    """Sichert ab, dass der ``RobotServer(...)``-Aufruf in ``main()`` das
    ``robot_token``-kwarg setzt. Genau das war der Phase-59-Regression-Bug:
    Feature galt als ausgeliefert, der Aufruf hatte das Argument aber nie.
    """

    @pytest.fixture
    def start_rpi5_ast(self):
        source = START_RPI5.read_text(encoding="utf-8")
        return ast.parse(source)

    def test_robot_server_called_with_robot_token_kwarg(self, start_rpi5_ast):
        """Im kompletten Script muss ``RobotServer(...)`` mit
        ``robot_token=...`` aufgerufen werden – sonst ist die
        Token-Middleware im Bypass."""
        calls_with_token: list[ast.Call] = []
        all_robot_server_calls: list[ast.Call] = []

        for node in ast.walk(start_rpi5_ast):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if callee_name != "RobotServer":
                continue
            all_robot_server_calls.append(node)
            if any(kw.arg == "robot_token" for kw in node.keywords):
                calls_with_token.append(node)

        assert all_robot_server_calls, (
            "RobotServer(...) wird in scripts/start_rpi5.py gar nicht "
            "aufgerufen – Test-Annahme ungültig."
        )
        assert calls_with_token, (
            "Regression: RobotServer(...) wird in scripts/start_rpi5.py "
            "ohne ``robot_token=``-Argument aufgerufen. Damit bleibt die "
            "Phase-59 Token-Auth im Bypass und alle Endpoints (inkl. "
            "/system/update = RCE) sind im LAN ungeprüft. Nicht "
            "entfernen ohne Sicherheitsimplikation zu verstehen."
        )


# ---------------------------------------------------------------------------
# Phase 64 (H-2): Policy-Enforcement
# ---------------------------------------------------------------------------


class TestIsLoopbackHost:
    """Pruefungen fuer die Loopback-Erkennung."""

    @pytest.fixture
    def module(self):
        return _load_start_rpi5_module()

    def test_localhost_is_loopback(self, module):
        assert module._is_loopback_host("localhost") is True

    def test_localhost_uppercase(self, module):
        assert module._is_loopback_host("LOCALHOST") is True

    def test_127_0_0_1_is_loopback(self, module):
        assert module._is_loopback_host("127.0.0.1") is True

    def test_127_x_x_x_is_loopback(self, module):
        # 127.0.0.0/8 ist komplett Loopback laut RFC 1122.
        assert module._is_loopback_host("127.1.2.3") is True

    def test_ipv6_loopback_is_loopback(self, module):
        assert module._is_loopback_host("::1") is True

    def test_ipv6_loopback_with_brackets(self, module):
        assert module._is_loopback_host("[::1]") is True

    def test_0_0_0_0_not_loopback(self, module):
        # 0.0.0.0 bindet auf ALLE Interfaces -- NICHT Loopback.
        assert module._is_loopback_host("0.0.0.0") is False

    def test_ipv6_any_not_loopback(self, module):
        assert module._is_loopback_host("::") is False

    def test_lan_ip_not_loopback(self, module):
        assert module._is_loopback_host("192.168.1.42") is False

    def test_public_ip_not_loopback(self, module):
        assert module._is_loopback_host("8.8.8.8") is False

    def test_garbage_not_loopback(self, module):
        assert module._is_loopback_host("not-an-ip") is False


class TestEnforceRobotTokenPolicy:
    """Verhalten von _enforce_robot_token_policy."""

    @pytest.fixture
    def module(self):
        return _load_start_rpi5_module()

    def test_token_set_public_host_ok(self, module):
        # Token gesetzt --> egal welches Interface, kein Abbruch.
        module._enforce_robot_token_policy("abc123", "0.0.0.0")

    def test_token_set_loopback_host_ok(self, module):
        module._enforce_robot_token_policy("abc123", "127.0.0.1")

    def test_no_token_loopback_warns_but_passes(self, module, caplog):
        with caplog.at_level(logging.WARNING, logger="elder_berry.rpi5"):
            module._enforce_robot_token_policy(None, "127.0.0.1")
        assert any(
            "NICHT konfiguriert" in r.message for r in caplog.records
        )

    def test_no_token_localhost_passes(self, module):
        module._enforce_robot_token_policy(None, "localhost")

    def test_no_token_public_host_exits(self, module):
        with pytest.raises(SystemExit) as exc:
            module._enforce_robot_token_policy(None, "0.0.0.0")
        assert exc.value.code == 2

    def test_no_token_lan_host_exits(self, module):
        with pytest.raises(SystemExit) as exc:
            module._enforce_robot_token_policy(None, "192.168.1.42")
        assert exc.value.code == 2

    def test_no_token_public_host_logs_fix_hint(self, module, caplog):
        with caplog.at_level(logging.ERROR, logger="elder_berry.rpi5"):
            with pytest.raises(SystemExit):
                module._enforce_robot_token_policy(None, "10.0.0.1")
        error_msgs = " ".join(
            r.message for r in caplog.records if r.levelname == "ERROR"
        )
        assert "ELDER_BERRY_ROBOT_TOKEN" in error_msgs
        assert "127.0.0.1" in error_msgs

    def test_empty_token_treated_as_none(self, module):
        # Leerer Token-String darf nicht als "Token vorhanden" gelten --
        # sonst waere die Policy triviale zu umgehen. Leerer String ist
        # hier falsy, also gleich wie None.
        with pytest.raises(SystemExit):
            module._enforce_robot_token_policy("", "0.0.0.0")
