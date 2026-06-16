"""Tests fuer Phase 103 (S1): AgentServer Konstruktor-Bind-Guard.

Defense-in-Depth: Ein AgentServer ohne agent_token darf nicht fuer einen
Nicht-Loopback-Bind konstruiert werden (sonst ist die AgentTokenMiddleware im
Bypass und die PC-Aktions-Endpoints waeren im LAN ungeprueft).
``bind_host`` ist optional (Default None) -- bestehende tokenlose
Konstruktionen und der Loopback-Betrieb bleiben unveraendert.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

try:
    from elder_berry.agent.server import AgentServer

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi nicht installiert")


def _build(**kwargs):
    return AgentServer(controller=MagicMock(), hostname="test-laptop", **kwargs)


class TestAgentServerBindGuard:
    def test_no_token_non_loopback_raises(self):
        with pytest.raises(ValueError, match="nicht-Loopback"):
            _build(agent_token=None, bind_host="0.0.0.0")

    def test_no_token_lan_ip_raises(self):
        with pytest.raises(ValueError):
            _build(agent_token=None, bind_host="192.168.1.51")

    def test_no_token_no_bind_host_raises(self):
        # fail-closed: ohne Token MUSS bind_host explizit (Loopback) gesetzt
        # sein -- sonst koennte ein ad-hoc-Wrapper eine ungeschuetzte App bauen.
        with pytest.raises(ValueError, match="bind_host explizit"):
            _build(agent_token=None)

    def test_no_token_loopback_ok(self):
        # Loopback ohne Token ist erlaubt (nur Warnung im Konstruktor).
        _build(agent_token=None, bind_host="127.0.0.1")

    def test_token_set_non_loopback_ok(self):
        # Mit Token darf der Server auch fuer 0.0.0.0 konstruiert werden.
        _build(agent_token="agent-secret", bind_host="0.0.0.0")

    def test_token_set_no_bind_host_ok(self):
        # Mit Token ist bind_host frei (auch None) -- das Token schuetzt.
        _build(agent_token="agent-secret")
