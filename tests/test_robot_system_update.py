"""Phase 104 (Q2): Fehler-/Leak-Pfade des robot /system/update-Endpoints.

Deckt die except-Zweige ab (subprocess wirft) und sichert insbesondere, dass
die rohe Exception NICHT in die HTTP-Antwort geschrieben wird (Leak-Fix).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from fastapi.testclient import TestClient

    from elder_berry.robot.server import RobotServer
    from elder_berry.robot.simulator import (
        SimulatedAvatar,
        SimulatedMotors,
        SimulatedSensors,
    )

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


def _server(tmp_path):
    return RobotServer(
        motors=SimulatedMotors(),
        avatar=SimulatedAvatar(),
        sensors=SimulatedSensors(),
        hostname="test",
        project_root=tmp_path,
    )


def _run_ok(out: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = out
    m.stderr = ""
    return m


_SECRET = "SECRET-/root/.netrc"


class TestSystemUpdateErrorPaths:
    def test_rev_list_failure_defaults_to_up_to_date(self, tmp_path):
        server = _server(tmp_path)
        client = TestClient(server.app, raise_server_exceptions=False)
        # fetch ok, rev-list wirft -> behind=0 -> "Alles aktuell"
        seq = [_run_ok(), OSError("boom")]
        with patch("elder_berry.robot.server.subprocess.run", side_effect=seq):
            r = client.post("/system/update")
        assert r.status_code == 200
        assert "aktuell" in r.json()["message"].lower()

    def test_pip_failure_does_not_leak(self, tmp_path):
        server = _server(tmp_path)
        client = TestClient(server.app, raise_server_exceptions=False)
        # fetch ok, rev-list "2", pull ok, pip wirft
        seq = [_run_ok(), _run_ok("2\n"), _run_ok(), RuntimeError(_SECRET)]
        with patch("elder_berry.robot.server.subprocess.run", side_effect=seq):
            r = client.post("/system/update")
        msg = r.json()["message"]
        assert "Details im Log" in msg
        assert _SECRET not in msg

    def test_systemctl_failure_does_not_leak(self, tmp_path):
        server = _server(tmp_path)
        client = TestClient(server.app, raise_server_exceptions=False)
        # fetch/rev-list/pull/pip ok (4x run), dann Popen (systemctl) wirft
        seq = [_run_ok(), _run_ok("2\n"), _run_ok(), _run_ok()]
        with (
            patch("elder_berry.robot.server.subprocess.run", side_effect=seq),
            patch(
                "elder_berry.robot.server.subprocess.Popen",
                side_effect=RuntimeError(_SECRET),
            ),
        ):
            r = client.post("/system/update")
        msg = r.json()["message"]
        assert "Details im Log" in msg
        assert _SECRET not in msg
