"""Tests fuer RobotClient.probe() + is_online()-Delegation (Phase 96-A).

probe() klassifiziert die Erreichbarkeit (ok/auth/rate_limited/unreachable)
und haertet gegen non-200/non-JSON-Antworten. Der Kern-Akzeptanztest unten
beweist die Recovery OHNE Bot-Neustart: derselbe Client erholt sich pro Call,
sobald der RPi wieder antwortet (Regressionsschutz gegen Incident #708).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from elder_berry.robot.client import RobotClient

_Handler = Callable[[httpx.Request], httpx.Response]


def _client_with_handler(handler: _Handler) -> RobotClient:
    """RobotClient ueber httpx.MockTransport, ohne __init__/Netz/Logging."""
    client = RobotClient.__new__(RobotClient)
    client._base_url = "http://rpi"
    client._timeout = 5.0
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://rpi",
    )
    return client


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "ok"})


class TestProbeClassification:
    def test_ok(self):
        assert _client_with_handler(_ok_handler).probe() == "ok"

    def test_status_not_ok_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "degraded"})

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_401_is_auth(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "token"})

        assert _client_with_handler(handler).probe() == "auth"

    def test_403_is_auth(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        assert _client_with_handler(handler).probe() == "auth"

    def test_429_is_rate_limited(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate"})

        assert _client_with_handler(handler).probe() == "rate_limited"

    def test_500_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_502_html_body_is_unreachable(self):
        # nginx/Tunnel-502 mit HTML-Body: JSONDecodeError darf nicht leaken.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="<html>Bad Gateway</html>")

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_200_non_json_body_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>nope</html>")

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_200_empty_body_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"")

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_200_json_list_body_is_unreachable(self):
        # 200 + gueltiges aber Nicht-Objekt-JSON ([]): data.get darf nicht
        # mit AttributeError durchschlagen.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_200_json_null_body_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=None)

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_connect_error_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        assert _client_with_handler(handler).probe() == "unreachable"

    def test_timeout_is_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("slow")

        assert _client_with_handler(handler).probe() == "unreachable"


class TestIsOnlineDelegation:
    def test_is_online_true_only_on_ok(self):
        assert _client_with_handler(_ok_handler).is_online() is True

    def test_is_online_false_on_auth(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={})

        assert _client_with_handler(handler).is_online() is False

    def test_is_online_false_on_unreachable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("x")

        assert _client_with_handler(handler).is_online() is False


class TestBootRecoveryWithoutRestart:
    """Kern-Akzeptanztest (§Tests im Konzept): Fehler beim 'Boot', danach
    erreichbar -> derselbe Client liefert ohne Neustart wieder 'ok'."""

    def test_recovers_after_transient_auth_failure(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(401, json={"error": "token"})
            return httpx.Response(200, json={"status": "ok"})

        client = _client_with_handler(handler)
        # "Boot"-Probe scheitert mit Auth (kein robot=None-Latch noetig) ...
        assert client.probe() == "auth"
        assert client.is_online() is False
        # ... danach erreichbar -> Recovery OHNE neuen Client / Neustart.
        assert client.probe() == "ok"
        assert client.is_online() is True

    def test_recovers_after_transient_network_failure(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("rpi still booting")
            return httpx.Response(200, json={"status": "ok"})

        client = _client_with_handler(handler)
        assert client.is_online() is False  # 1. Call: ConnectError
        assert client.is_online() is True  # 2. Call: erreichbar, kein Neustart
