"""Tests für RoutePlanner – Google Maps Directions API."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.tools.route_planner import (
    RouteError,
    RoutePlanner,
    RouteResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def planner() -> RoutePlanner:
    return RoutePlanner(api_key="TEST_KEY")


@pytest.fixture
def planner_custom_buffer() -> RoutePlanner:
    return RoutePlanner(api_key="TEST_KEY", default_buffer_minutes=30)


def _directions_response(
    *,
    status: str = "OK",
    duration_value: int = 4800,
    duration_text: str = "1 Stunde 20 Minuten",
    distance_text: str = "85,3 km",
    summary: str = "A10",
    start_address: str = "Musterstr. 5, 12345 Berlin",
    end_address: str = "Hauptstr. 12, 10115 Berlin",
    traffic_duration: dict | None = None,
    routes: list | None = None,
) -> dict:
    """Erstellt eine Mock-Directions-API-Response."""
    if routes is not None:
        return {"status": status, "routes": routes}
    leg: dict = {
        "duration": {"value": duration_value, "text": duration_text},
        "distance": {"text": distance_text},
        "start_address": start_address,
        "end_address": end_address,
    }
    if traffic_duration:
        leg["duration_in_traffic"] = traffic_duration
    return {
        "status": status,
        "routes": [{"legs": [leg], "summary": summary}],
    }


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_buffer(self, planner: RoutePlanner) -> None:
        assert planner.buffer_minutes == 15

    def test_custom_buffer(self, planner_custom_buffer: RoutePlanner) -> None:
        assert planner_custom_buffer.buffer_minutes == 30


# ---------------------------------------------------------------------------
# get_route
# ---------------------------------------------------------------------------


class TestGetRoute:
    def test_success(self, planner: RoutePlanner) -> None:
        resp = _directions_response()
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        with patch.object(planner._client, "get", return_value=mock_resp):
            result = planner.get_route("Berlin", "Hamburg")

        assert isinstance(result, RouteResult)
        assert result.duration_seconds == 4800
        assert result.duration_text == "1 Stunde 20 Minuten"
        assert result.distance_text == "85,3 km"
        assert result.summary == "A10"
        assert result.start_address == "Musterstr. 5, 12345 Berlin"
        assert result.end_address == "Hauptstr. 12, 10115 Berlin"

    def test_with_departure_time_future(self, planner: RoutePlanner) -> None:
        """departure_time in Zukunft → wird als Param mitgesendet."""
        resp = _directions_response()
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        future = datetime.now() + timedelta(hours=2)
        with patch.object(planner._client, "get", return_value=mock_resp) as mock_get:
            planner.get_route("Berlin", "Hamburg", departure_time=future)

        params = mock_get.call_args[1]["params"]
        assert "departure_time" in params
        assert params["traffic_model"] == "best_guess"

    def test_departure_time_in_past_ignored(self, planner: RoutePlanner) -> None:
        """Vergangene departure_time → ohne Traffic-Params."""
        resp = _directions_response()
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        past = datetime.now() - timedelta(hours=2)
        with patch.object(planner._client, "get", return_value=mock_resp) as mock_get:
            planner.get_route("Berlin", "Hamburg", departure_time=past)

        params = mock_get.call_args[1]["params"]
        assert "departure_time" not in params
        assert "traffic_model" not in params

    def test_with_traffic_duration(self, planner: RoutePlanner) -> None:
        """duration_in_traffic wird bevorzugt über duration."""
        resp = _directions_response(
            traffic_duration={"value": 5400, "text": "1 Stunde 30 Minuten"},
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        with patch.object(planner._client, "get", return_value=mock_resp):
            result = planner.get_route("Berlin", "Hamburg")

        assert result.duration_seconds == 5400
        assert result.duration_text == "1 Stunde 30 Minuten"

    def test_api_error_status(self, planner: RoutePlanner) -> None:
        """Status != OK → RouteError."""
        resp = _directions_response(status="ZERO_RESULTS")
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        with patch.object(planner._client, "get", return_value=mock_resp):
            with pytest.raises(RouteError, match="ZERO_RESULTS"):
                planner.get_route("nirgendwo", "nirgendwohin")

    def test_no_routes(self, planner: RoutePlanner) -> None:
        """Leere routes-Liste → RouteError."""
        resp = _directions_response(routes=[])
        resp["status"] = "OK"
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        with patch.object(planner._client, "get", return_value=mock_resp):
            with pytest.raises(RouteError, match="Keine Route"):
                planner.get_route("A", "B")

    def test_network_error(self, planner: RoutePlanner) -> None:
        """Netzwerkfehler → httpx.RequestError durchgereicht."""
        with patch.object(
            planner._client,
            "get",
            side_effect=httpx.ConnectError("timeout"),
        ):
            with pytest.raises(httpx.ConnectError):
                planner.get_route("A", "B")

    def test_params_contain_language_and_units(
        self,
        planner: RoutePlanner,
    ) -> None:
        resp = _directions_response()
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp
        mock_resp.raise_for_status = MagicMock()

        with patch.object(planner._client, "get", return_value=mock_resp) as mock_get:
            planner.get_route("Berlin", "Hamburg")

        params = mock_get.call_args[1]["params"]
        assert params["language"] == "de"
        assert params["units"] == "metric"
        assert params["key"] == "TEST_KEY"


# ---------------------------------------------------------------------------
# calculate_departure
# ---------------------------------------------------------------------------


class TestCalculateDeparture:
    def test_simple(self, planner: RoutePlanner) -> None:
        """16:00 Ankunft, 60min Dauer, 15min Puffer → 14:45."""
        arrival = datetime(2026, 4, 5, 16, 0)
        dep = planner.calculate_departure(arrival, 3600)
        assert dep == datetime(2026, 4, 5, 14, 45)

    def test_custom_buffer(self, planner_custom_buffer: RoutePlanner) -> None:
        """30min Puffer statt 15min."""
        arrival = datetime(2026, 4, 5, 16, 0)
        dep = planner_custom_buffer.calculate_departure(arrival, 3600)
        assert dep == datetime(2026, 4, 5, 14, 30)

    def test_midnight_wrap(self, planner: RoutePlanner) -> None:
        """Fahrt über Mitternacht: 01:00 Ankunft, 3h Dauer → Vortag 21:45."""
        arrival = datetime(2026, 4, 5, 1, 0)
        dep = planner.calculate_departure(arrival, 10800)  # 3h
        assert dep == datetime(2026, 4, 4, 21, 45)


# ---------------------------------------------------------------------------
# generate_maps_link
# ---------------------------------------------------------------------------


class TestGenerateMapsLink:
    def test_basic_link(self, planner: RoutePlanner) -> None:
        link = planner.generate_maps_link("Berlin", "Hamburg")
        assert "origin=Berlin" in link
        assert "destination=Hamburg" in link
        assert "travelmode=driving" in link
        assert link.startswith("https://www.google.com/maps/dir/")

    def test_umlauts_encoded(self, planner: RoutePlanner) -> None:
        """Straßennamen mit Umlauten werden URL-encoded."""
        link = planner.generate_maps_link(
            "Königstraße 5, München",
            "Löwenstraße 10, Nürnberg",
        )
        # Umlaute sollten encoded sein (ö → %C3%B6 etc.)
        assert "K%C3%B6nig" in link or "Königstraße" not in link


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_minimal(self, planner: RoutePlanner) -> None:
        """Nur Pflichtfelder."""
        data = {
            "status": "OK",
            "routes": [
                {
                    "legs": [
                        {
                            "duration": {"value": 600, "text": "10 Min."},
                            "distance": {"text": "5 km"},
                            "start_address": "A",
                            "end_address": "B",
                        }
                    ],
                }
            ],
        }
        result = planner._parse_response(data)
        assert result.duration_seconds == 600
        assert result.summary == ""

    def test_full(self, planner: RoutePlanner) -> None:
        data = _directions_response()
        result = planner._parse_response(data)
        assert result.duration_seconds == 4800
        assert result.summary == "A10"
        assert result.distance_text == "85,3 km"

    def test_traffic_preferred(self, planner: RoutePlanner) -> None:
        """duration_in_traffic wird über duration bevorzugt."""
        data = _directions_response(
            traffic_duration={"value": 6000, "text": "1h 40min"},
        )
        result = planner._parse_response(data)
        assert result.duration_seconds == 6000
        assert result.duration_text == "1h 40min"


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close(self, planner: RoutePlanner) -> None:
        with patch.object(planner._client, "close") as mock_close:
            planner.close()
        mock_close.assert_called_once()
