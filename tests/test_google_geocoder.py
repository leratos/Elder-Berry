"""Tests fuer GoogleGeocoder -- Freitext-Ort -> Koordinaten.

Phase 97 (E0). Alle Tests gegen Mock-httpx-Responses; Live-Calls gegen
die echte Google API macht Lera manuell vor dem PR (Quota-bewusst).

Schwerpunkt der Fehler-Semantik (R2-C3): None NUR bei ZERO_RESULTS;
REQUEST_DENIED / OVER_QUERY_LIMIT / HTTP 403 / 429 -> GeocoderConfigError.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from elder_berry.tools.google_geocoder import (
    GEOCODE_URL,
    GeocoderConfigError,
    GoogleGeocoder,
    LatLng,
)

API_KEY = "test-key"


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


def _ok_response(lat: float = 51.34, lng: float = 12.37) -> dict[str, Any]:
    return {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Leipzig, Deutschland",
                "geometry": {"location": {"lat": lat, "lng": lng}},
            },
        ],
    }


def _make_client(
    *,
    json_body: dict[str, Any] | None = None,
    status_code: int = 200,
) -> MagicMock:
    client = MagicMock(spec=httpx.Client)

    def _get(url: str, params: dict[str, str]) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = json_body or {}
        # HTTP 403/429 werden VOR raise_for_status abgefangen (GeocoderConfigError);
        # andere >=400 sollen ueber raise_for_status fliegen.
        if status_code >= 400 and status_code not in (403, 429):
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "boom",
                request=MagicMock(),
                response=resp,
            )
        else:
            resp.raise_for_status.return_value = None
        return resp

    client.get.side_effect = _get
    return client


# ---------------------------------------------------------------------------
# Konstruktor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            GoogleGeocoder(api_key="")

    def test_close_owned_client_no_error(self) -> None:
        # Eigener (nicht injizierter) Client -> close() schliesst ihn ohne Fehler.
        GoogleGeocoder(api_key=API_KEY).close()

    def test_close_only_closes_owned_client(self) -> None:
        injected = MagicMock(spec=httpx.Client)
        geocoder = GoogleGeocoder(api_key=API_KEY, client=injected)
        geocoder.close()
        injected.close.assert_not_called()


# ---------------------------------------------------------------------------
# Request-Aufbau
# ---------------------------------------------------------------------------


class TestRequest:
    def test_sends_address_key_and_language(self) -> None:
        client = _make_client(json_body=_ok_response())
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)

        geocoder.geocode("Hauptstr. 12, Leipzig")

        client.get.assert_called_once()
        args, kwargs = client.get.call_args
        assert args[0] == GEOCODE_URL
        params = kwargs["params"]
        assert params["address"] == "Hauptstr. 12, Leipzig"
        assert params["key"] == API_KEY
        assert params["language"] == "de"

    def test_empty_location_text_raises(self) -> None:
        client = _make_client(json_body=_ok_response())
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(ValueError, match="location_text"):
            geocoder.geocode("   ")
        client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Erfolg / ZERO_RESULTS
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_ok_returns_first_latlng(self) -> None:
        client = _make_client(json_body=_ok_response(lat=52.5, lng=13.4))
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)

        result = geocoder.geocode("Berlin")

        assert result == LatLng(lat=52.5, lng=13.4)

    def test_zero_results_returns_none(self) -> None:
        client = _make_client(json_body={"status": "ZERO_RESULTS", "results": []})
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)

        assert geocoder.geocode("Nirgendwohausen 999") is None

    def test_ok_without_location_returns_none(self) -> None:
        # OK-Status, aber kaputte/leere results -> None statt Crash.
        client = _make_client(json_body={"status": "OK", "results": []})
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        assert geocoder.geocode("Irgendwo") is None

    def test_ok_result_missing_lat_returns_none(self) -> None:
        body = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lng": 12.0}}}],
        }
        client = _make_client(json_body=body)
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        assert geocoder.geocode("Irgendwo") is None


# ---------------------------------------------------------------------------
# Fehler-Semantik (R2-C3): NICHT als None tarnen
# ---------------------------------------------------------------------------


class TestConfigErrors:
    def test_request_denied_raises_config_error(self) -> None:
        client = _make_client(json_body={"status": "REQUEST_DENIED"})
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(GeocoderConfigError, match="REQUEST_DENIED"):
            geocoder.geocode("Leipzig")

    def test_over_query_limit_raises_config_error(self) -> None:
        client = _make_client(json_body={"status": "OVER_QUERY_LIMIT"})
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(GeocoderConfigError, match="OVER_QUERY_LIMIT"):
            geocoder.geocode("Leipzig")

    def test_unexpected_status_raises_config_error(self) -> None:
        # INVALID_REQUEST u.ae. duerfen NICHT als None ("nicht gefunden")
        # durchgehen.
        client = _make_client(json_body={"status": "INVALID_REQUEST"})
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(GeocoderConfigError, match="INVALID_REQUEST"):
            geocoder.geocode("Leipzig")

    def test_http_403_raises_config_error(self) -> None:
        client = _make_client(json_body={}, status_code=403)
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(GeocoderConfigError, match="403"):
            geocoder.geocode("Leipzig")

    def test_http_429_raises_config_error(self) -> None:
        client = _make_client(json_body={}, status_code=429)
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(GeocoderConfigError, match="429"):
            geocoder.geocode("Leipzig")

    def test_http_500_raises_config_error(self) -> None:
        # Codex PR #302: 500/502/503 als Dienstfehler durchreichen, nicht als
        # roher httpx-Fehler (Handler kennt nur GeocoderConfigError).
        client = _make_client(json_body={}, status_code=500)
        geocoder = GoogleGeocoder(api_key=API_KEY, client=client)
        with pytest.raises(GeocoderConfigError, match="500"):
            geocoder.geocode("Leipzig")
