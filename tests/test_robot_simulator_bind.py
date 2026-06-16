"""Tests fuer Phase 103 (S1): Robot-Simulator Bind-/Token-Verhalten.

Zwei Luecken aus Befund S1 (carddav... nein: Server-Auth) werden hier
abgesichert:

1. ``create_simulator`` reicht ``robot_token`` jetzt an den ``RobotServer``
   durch (vorher landete die RobotTokenMiddleware dauerhaft im Bypass --
   analog zum Phase-59-Regression-Bug im RPi-Start).
2. Der ``__main__``-Block erzwingt die fail-closed-Bind-Policy
   (AST-Regression, damit der Guard nicht still wegfaellt).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

try:
    from fastapi.testclient import TestClient

    from elder_berry.robot.simulator import create_simulator

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")

SIMULATOR_PY = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "elder_berry"
    / "robot"
    / "simulator.py"
)


class TestCreateSimulatorTokenPassthrough:
    def test_token_is_enforced(self):
        server = create_simulator(robot_token="sim-secret")
        client = TestClient(server.app, raise_server_exceptions=False)
        # Ohne Header blockt die Middleware vor dem Routing.
        assert client.get("/health").status_code == 401
        # Mit korrektem Token kommt der Request durch.
        ok = client.get(
            "/health", headers={"X-Saleria-Robot-Token": "sim-secret"}
        )
        assert ok.status_code == 200

    def test_no_token_is_open(self):
        server = create_simulator()
        client = TestClient(server.app, raise_server_exceptions=False)
        assert client.get("/health").status_code == 200


class TestSimulatorMainEnforcesBindPolicy:
    """AST-Regression: der __main__-Block ruft enforce_token_policy auf."""

    def test_main_calls_enforce_token_policy(self):
        tree = ast.parse(SIMULATOR_PY.read_text(encoding="utf-8"))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        assert "enforce_token_policy" in called, (
            "Regression: simulator.py ruft enforce_token_policy nicht mehr "
            "auf -- der Bind-Guard (S1) ist entfernt. Ohne ihn bindet der "
            "Simulator wieder ohne Auth auf 0.0.0.0."
        )

    def test_create_simulator_call_passes_robot_token(self):
        tree = ast.parse(SIMULATOR_PY.read_text(encoding="utf-8"))
        passes_token = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_simulator"
            and any(kw.arg == "robot_token" for kw in node.keywords)
            for node in ast.walk(tree)
        )
        assert passes_token, (
            "Regression: der create_simulator(...)-Aufruf in __main__ setzt "
            "kein robot_token= -- die Middleware bliebe im Bypass."
        )
