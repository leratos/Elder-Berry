"""Tests: Phase 63 -- /api/setup/geocode Proxy-Endpoint fuer Nominatim.

Der Wizard ruft Nominatim nicht mehr direkt aus dem Browser auf. Der
Server-seitige Proxy umgeht die strikte CSP (connect-src 'self') und
liefert ein schlankes Format zurueck.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elder_berry.web.setup_wizard import register_setup_wizard_routes


class FakeSecretStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def has(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str) -> str:
        return self._data[key]

    def get_or_none(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        del self._data[key]

    def list_keys(self) -> list[str]:
        return list(self._data.keys())


@pytest.fixture
def client():
    app = FastAPI()
    register_setup_wizard_routes(app, FakeSecretStore())
    return TestClient(app)


def _mock_response(status: int, json_data):
    """Erzeugt ein Mock-httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    if isinstance(json_data, Exception):
        resp.json.side_effect = json_data
    else:
        resp.json.return_value = json_data
    return resp


def _patch_httpx(resp=None, side_effect=None):
    """Patch httpx.AsyncClient.get im setup_wizard-Modul.

    Liefert einen AsyncMock zurueck, der entweder ``resp`` zurueckgibt
    oder ``side_effect`` wirft.
    """
    mock_get = AsyncMock()
    if side_effect is not None:
        mock_get.side_effect = side_effect
    else:
        mock_get.return_value = resp
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = mock_get
    return patch(
        "elder_berry.web.setup_wizard.httpx.AsyncClient",
        return_value=mock_client,
    ), mock_get


class TestGeocodeSuccess:
    def test_found_city_returns_lat_lon(self, client):
        patcher, _ = _patch_httpx(resp=_mock_response(
            200,
            [{"lat": "52.5200", "lon": "13.4050", "display_name": "Berlin, DE"}],
        ))
        with patcher:
            r = client.get("/api/setup/geocode?q=Berlin")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["lat"] == pytest.approx(52.52, abs=1e-4)
        assert data["lon"] == pytest.approx(13.405, abs=1e-4)
        assert "Berlin" in data["display_name"]

    def test_user_agent_and_accept_language_sent(self, client):
        patcher, mock_get = _patch_httpx(resp=_mock_response(
            200, [{"lat": "0", "lon": "0", "display_name": "X"}],
        ))
        with patcher:
            client.get("/api/setup/geocode?q=Paris")
        headers = mock_get.call_args.kwargs["headers"]
        assert "Elder-Berry" in headers["User-Agent"]
        assert headers["Accept-Language"] == "de"

    def test_query_forwarded_to_nominatim(self, client):
        patcher, mock_get = _patch_httpx(resp=_mock_response(
            200, [{"lat": "0", "lon": "0", "display_name": "X"}],
        ))
        with patcher:
            client.get("/api/setup/geocode?q=  Hamburg  ")
        params = mock_get.call_args.kwargs["params"]
        assert params["q"] == "Hamburg"  # stripped
        assert params["format"] == "json"
        assert params["limit"] == 1


class TestGeocodeClientErrors:
    def test_empty_query_returns_400(self, client):
        r = client.get("/api/setup/geocode?q=")
        assert r.status_code == 400
        assert r.json()["success"] is False

    def test_missing_query_returns_400(self, client):
        r = client.get("/api/setup/geocode")
        assert r.status_code == 400

    def test_whitespace_only_query_returns_400(self, client):
        r = client.get("/api/setup/geocode?q=   ")
        assert r.status_code == 400

    def test_very_long_query_returns_400(self, client):
        r = client.get("/api/setup/geocode?q=" + "A" * 300)
        assert r.status_code == 400


class TestGeocodeUpstreamFailures:
    def test_nominatim_500_returns_502(self, client):
        patcher, _ = _patch_httpx(resp=_mock_response(500, []))
        with patcher:
            r = client.get("/api/setup/geocode?q=Berlin")
        assert r.status_code == 502
        assert r.json()["success"] is False

    def test_network_error_returns_502(self, client):
        patcher, _ = _patch_httpx(
            side_effect=httpx.ConnectError("connection refused"),
        )
        with patcher:
            r = client.get("/api/setup/geocode?q=Berlin")
        assert r.status_code == 502
        assert "Netzwerkfehler" in r.json()["error"]

    def test_non_json_response_returns_502(self, client):
        patcher, _ = _patch_httpx(resp=_mock_response(
            200, ValueError("not json"),
        ))
        with patcher:
            r = client.get("/api/setup/geocode?q=Berlin")
        assert r.status_code == 502

    def test_empty_result_returns_not_found(self, client):
        patcher, _ = _patch_httpx(resp=_mock_response(200, []))
        with patcher:
            r = client.get("/api/setup/geocode?q=XXXUNKNOWN")
        # 200 mit success=false -- kein Upstream-Fehler, nur kein Treffer
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert "nicht gefunden" in body["error"].lower()

    def test_malformed_result_returns_502(self, client):
        """Nominatim liefert Dict statt List -- Format unerwartet."""
        patcher, _ = _patch_httpx(resp=_mock_response(
            200, [{"lat": "not-a-number", "lon": "0"}],
        ))
        with patcher:
            r = client.get("/api/setup/geocode?q=Berlin")
        assert r.status_code == 502
