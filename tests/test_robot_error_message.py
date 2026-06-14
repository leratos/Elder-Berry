"""Tests fuer robot_error_message + ROBOT_NOT_CONFIGURED_TEXT (Phase 96-C).

Lockt den Nachrichten-Kontrakt: Auth (401/403) und Rate-Limit (429) muessen
klar von Netz-/Timeout-Fehlern getrennt sein, damit ein fehlender/ungueltiger
Robot-Token nicht mehr als "nicht erreichbar" fehlinterpretiert wird
(Incident 2026-06-03, #708).
"""

from __future__ import annotations

import httpx

from elder_berry.comms.commands.base import (
    ROBOT_NOT_CONFIGURED_TEXT,
    robot_error_message,
)


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://rpi/health")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"HTTP {code}", request=req, response=resp)


class TestRobotErrorMessage:
    def test_401_is_token_hint(self):
        msg = robot_error_message(_status_error(401))
        assert "Token" in msg
        assert "nicht erreichbar" not in msg

    def test_403_is_token_hint(self):
        assert "Token" in robot_error_message(_status_error(403))

    def test_429_is_rate_limit(self):
        msg = robot_error_message(_status_error(429))
        assert "Rate-Limit" in msg or "überlastet" in msg

    def test_500_is_unreachable(self):
        assert "nicht erreichbar" in robot_error_message(_status_error(500))

    def test_502_is_unreachable(self):
        assert "nicht erreichbar" in robot_error_message(_status_error(502))

    def test_connect_error_is_unreachable(self):
        msg = robot_error_message(httpx.ConnectError("boom"))
        assert "nicht erreichbar" in msg
        assert "Token" not in msg

    def test_timeout_is_unreachable(self):
        msg = robot_error_message(httpx.ReadTimeout("slow"))
        assert "nicht erreichbar" in msg

    def test_non_http_error_falls_back(self):
        # Programmierfehler werden NICHT als "nicht erreichbar" maskiert.
        msg = robot_error_message(ValueError("kaputt"))
        assert "nicht erreichbar" not in msg
        assert "❌" in msg

    def test_404_uses_generic_fallback(self):
        # 4xx ausser 401/403/429 -> generische user_friendly_error-Meldung.
        msg = robot_error_message(_status_error(404))
        assert "nicht erreichbar" not in msg
        assert "Token" not in msg


class TestRobotNotConfiguredText:
    def test_mentions_not_configured(self):
        assert "nicht konfiguriert" in ROBOT_NOT_CONFIGURED_TEXT
        # Das alte irrefuehrende "nicht verbunden" darf nicht mehr auftauchen.
        assert "nicht verbunden" not in ROBOT_NOT_CONFIGURED_TEXT
