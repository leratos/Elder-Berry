"""Tests fuer GoogleMapsRoutePlanner -- Multi-Stop Directions + POI.

Phase 92 (E1). Alle Tests gegen Mock-httpx-Responses. Live-Calls
gegen die echte Google API macht Lera manuell vor dem PR (Quota-
bewusst).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from elder_berry.tools.google_maps_route_planner import (
    DIRECTIONS_URL,
    GoogleMapsRoutePlanner,
    MultiStopRouteResult,
    POICandidate,
    POIRequest,
    PlannedRoute,
    RouteError,
    Stop,
)


API_KEY = "test-key"


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


def _directions_response(
    *,
    status: str = "OK",
    waypoint_order: list[int] | None = None,
    legs: list[dict[str, Any]] | None = None,
    polyline: str = "abc_polyline",
) -> dict[str, Any]:
    if legs is None:
        legs = [
            {"distance": {"value": 1000}, "duration": {"value": 60}},
            {"distance": {"value": 2000}, "duration": {"value": 120}},
        ]
    routes: list[dict[str, Any]] = []
    if status == "OK":
        routes = [
            {
                "legs": legs,
                "waypoint_order": waypoint_order or [],
                "overview_polyline": {"points": polyline},
            },
        ]
    return {"status": status, "routes": routes}


def _places_response(*places_with_detour: tuple[str, int]) -> dict[str, Any]:
    """Baut places + parallele routingSummaries.

    Args:
        places_with_detour: Tuples (name, detour_seconds).
    """
    places = []
    summaries = []
    for idx, (name, detour) in enumerate(places_with_detour):
        places.append(
            {
                "id": f"place_{idx}",
                "displayName": {"text": name},
                "formattedAddress": f"{name}-Adr",
                "rating": 4.0 + idx * 0.1,
            },
        )
        summaries.append(
            {"legs": [{"duration": f"{detour}s"}]},
        )
    return {"places": places, "routingSummaries": summaries}


def _make_client(
    *,
    get_response: dict[str, Any] | None = None,
    post_response: dict[str, Any] | None = None,
    get_status: int = 200,
    post_status: int = 200,
) -> MagicMock:
    client = MagicMock(spec=httpx.Client)

    def _get(url: str, params: dict[str, str]) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = get_status
        resp.json.return_value = get_response or {}
        if get_status >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "boom",
                request=MagicMock(),
                response=resp,
            )
        else:
            resp.raise_for_status.return_value = None
        return resp

    def _post(url: str, json: dict[str, Any], headers: dict[str, str]) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = post_status
        resp.json.return_value = post_response or {}
        if post_status >= 400 and post_status not in (401, 403, 429):
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "boom",
                request=MagicMock(),
                response=resp,
            )
        else:
            resp.raise_for_status.return_value = None
        return resp

    client.get.side_effect = _get
    client.post.side_effect = _post
    return client


@pytest.fixture
def stops() -> dict[str, Stop]:
    return {
        "origin": Stop("Musterstr. 5, Berlin", "Home"),
        "lisa": Stop("Hauptstr. 12, Leipzig", "Lisa"),
        "andrea": Stop("Mozartweg 4, Markranstaedt", "Andrea"),
        "destination": Stop("Hauptbahnhof Leipzig", "Hbf"),
    }


# ---------------------------------------------------------------------------
# Konstruktor / Close
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_api_key_missing_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            GoogleMapsRoutePlanner("")

    def test_close_releases_owned_client(self) -> None:
        planner = GoogleMapsRoutePlanner(API_KEY)
        planner._client = MagicMock(spec=httpx.Client)
        planner.close()
        planner._client.close.assert_called_once()

    def test_close_does_not_release_injected_client(self) -> None:
        client = MagicMock(spec=httpx.Client)
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.close()
        client.close.assert_not_called()


# ---------------------------------------------------------------------------
# Directions-API
# ---------------------------------------------------------------------------


class TestPlanDirections:
    def test_plan_optimize_true_default(
        self,
        stops: dict[str, Stop],
    ) -> None:
        client = _make_client(get_response=_directions_response())
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.plan(
            origin=stops["origin"],
            people_stops=[stops["lisa"], stops["andrea"]],
            destination=stops["destination"],
        )
        # waypoints-Param muss optimize:true tragen
        _, kwargs = client.get.call_args
        params = kwargs.get("params", {})
        assert params["waypoints"].startswith("optimize:true|")

    def test_plan_url_is_directions_endpoint(
        self,
        stops: dict[str, Stop],
    ) -> None:
        client = _make_client(get_response=_directions_response())
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
        )
        args, _ = client.get.call_args
        assert args[0] == DIRECTIONS_URL

    def test_plan_waypoint_order_applied(
        self,
        stops: dict[str, Stop],
    ) -> None:
        """waypoint_order=[1,0] -> Andrea vor Lisa in ordered_stops."""
        client = _make_client(
            get_response=_directions_response(waypoint_order=[1, 0]),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[stops["lisa"], stops["andrea"]],
            destination=stops["destination"],
        ).route
        names = [s.label for s in result.ordered_stops]
        assert names == ["Home", "Andrea", "Lisa", "Hbf"]

    def test_plan_origin_destination_not_in_waypoint_order(
        self,
        stops: dict[str, Stop],
    ) -> None:
        """Origin/Destination bleiben Anfang/Ende, egal was die API sagt."""
        client = _make_client(
            get_response=_directions_response(waypoint_order=[2, 0, 1]),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[stops["lisa"], stops["andrea"], Stop("Kaufland")],
            destination=stops["destination"],
        ).route
        assert result.ordered_stops[0].label == "Home"
        assert result.ordered_stops[-1].label == "Hbf"

    def test_plan_zero_results(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(status="ZERO_RESULTS"),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        with pytest.raises(RouteError, match="ZERO_RESULTS"):
            planner.plan(
                origin=stops["origin"],
                people_stops=[],
                destination=stops["destination"],
            )

    def test_plan_over_query_limit(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(status="OVER_QUERY_LIMIT"),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        with pytest.raises(RouteError, match="OVER_QUERY_LIMIT"):
            planner.plan(
                origin=stops["origin"],
                people_stops=[],
                destination=stops["destination"],
            )

    def test_plan_request_denied(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(status="REQUEST_DENIED"),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        with pytest.raises(RouteError, match="REQUEST_DENIED"):
            planner.plan(
                origin=stops["origin"],
                people_stops=[],
                destination=stops["destination"],
            )

    def test_plan_empty_routes_array(self, stops: dict[str, Stop]) -> None:
        client = _make_client(get_response={"status": "OK", "routes": []})
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        with pytest.raises(RouteError, match="Keine Route"):
            planner.plan(
                origin=stops["origin"],
                people_stops=[],
                destination=stops["destination"],
            )

    def test_plan_no_waypoints_no_optimize(self, stops: dict[str, Stop]) -> None:
        """Ohne Waypoints darf der waypoints-Param nicht gesetzt sein."""
        client = _make_client(
            get_response=_directions_response(
                legs=[{"distance": {"value": 1000}, "duration": {"value": 60}}],
            ),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
        )
        _, kwargs = client.get.call_args
        assert "waypoints" not in kwargs["params"]

    def test_plan_total_duration_aggregated(
        self,
        stops: dict[str, Stop],
    ) -> None:
        client = _make_client(
            get_response=_directions_response(
                legs=[
                    {"distance": {"value": 5000}, "duration": {"value": 600}},
                    {"distance": {"value": 10000}, "duration": {"value": 1200}},
                ],
            ),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[stops["lisa"]],
            destination=stops["destination"],
        ).route
        assert result.total_duration_seconds == 1800
        assert result.leg_durations_seconds == (600, 1200)
        assert "30 Minuten" in result.total_duration_text
        assert "15,0 km" in result.total_distance_text

    def test_plan_url_encoding_umlauts(
        self,
        stops: dict[str, Stop],
    ) -> None:
        """Umlaute im Stop-Address werden von httpx via params= encoded."""
        client = _make_client(get_response=_directions_response())
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.plan(
            origin=Stop("Mühlenstraße 4"),
            people_stops=[],
            destination=Stop("Görlitzer Park"),
        )
        # httpx wuerde das Encoding selbst machen; wir pruefen nur, dass
        # die Roh-Strings als params durchgereicht werden -- httpx codiert
        # sie beim echten Aufruf URL-safe.
        _, kwargs = client.get.call_args
        assert kwargs["params"]["origin"] == "Mühlenstraße 4"

    def test_plan_polyline_in_result(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(polyline="MY_POLYLINE"),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[stops["lisa"]],
            destination=stops["destination"],
        ).route
        assert result.encoded_polyline == "MY_POLYLINE"


# ---------------------------------------------------------------------------
# Places-API
# ---------------------------------------------------------------------------


class TestPlanWithPOI:
    def test_post_body_contains_polyline(
        self,
        stops: dict[str, Stop],
    ) -> None:
        client = _make_client(
            get_response=_directions_response(polyline="ROUTE_PL"),
            post_response=_places_response(),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Kaufland"),
        )
        _, kwargs = client.post.call_args
        body = kwargs["json"]
        assert (
            body["searchAlongRouteParameters"]["polyline"]["encodedPolyline"]
            == "ROUTE_PL"
        )
        assert body["textQuery"] == "Kaufland"

    def test_post_field_mask_header_set(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response=_places_response(),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Kaufland"),
        )
        _, kwargs = client.post.call_args
        assert "X-Goog-FieldMask" in kwargs["headers"]
        assert "routingSummaries" in kwargs["headers"]["X-Goog-FieldMask"]

    def test_poi_detour_mapping(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response=_places_response(
                ("Kaufland A", 120),
                ("Kaufland B", 600),
            ),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Kaufland"),
        )
        assert len(result.poi_candidates) == 2
        # Aufsteigend sortiert nach Detour
        assert result.poi_candidates[0].detour_seconds == 120
        assert result.poi_candidates[1].detour_seconds == 600

    def test_poi_empty_results_no_error(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response={"places": []},
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Kaufland"),
        )
        assert result.poi_candidates == ()

    def test_poi_filters_by_max_detour(
        self,
        stops: dict[str, Stop],
    ) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response=_places_response(
                ("Nah", 200),
                ("Mittel", 500),
                ("Zu Weit", 900),
            ),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(
                category="Kaufland",
                max_detour_seconds=600,
            ),
        )
        names = [p.name for p in result.poi_candidates]
        assert names == ["Nah", "Mittel"]

    def test_poi_caps_to_5(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response=_places_response(
                *[(f"K{i}", 100 + i * 10) for i in range(8)],
            ),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Kaufland"),
        )
        assert len(result.poi_candidates) == 5

    def test_poi_name_hint_filters(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response=_places_response(
                ("Lidl Berlin", 100),
                ("Rewe Berlin", 200),
                ("Lidl Leipzig", 300),
            ),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Supermarkt", name_hint="Lidl"),
        )
        names = [p.name for p in result.poi_candidates]
        assert names == ["Lidl Berlin", "Lidl Leipzig"]

    def test_poi_skips_when_polyline_empty(
        self,
        stops: dict[str, Stop],
    ) -> None:
        client = _make_client(
            get_response=_directions_response(polyline=""),
            post_response=_places_response(("K", 100)),
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        result = planner.plan(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            poi_request=POIRequest(category="Kaufland"),
        )
        # Polyline leer -> Places-Call wird gar nicht abgesetzt
        client.post.assert_not_called()
        assert result.poi_candidates == ()

    def test_poi_rate_limit_raises(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response={},
            post_status=429,
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        with pytest.raises(RouteError, match="Rate-Limit"):
            planner.plan(
                origin=stops["origin"],
                people_stops=[],
                destination=stops["destination"],
                poi_request=POIRequest(category="Kaufland"),
            )

    def test_poi_api_key_blocked_raises(self, stops: dict[str, Stop]) -> None:
        client = _make_client(
            get_response=_directions_response(),
            post_response={},
            post_status=403,
        )
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        with pytest.raises(RouteError, match="API-Key"):
            planner.plan(
                origin=stops["origin"],
                people_stops=[],
                destination=stops["destination"],
                poi_request=POIRequest(category="Kaufland"),
            )


# ---------------------------------------------------------------------------
# finalize_with_poi
# ---------------------------------------------------------------------------


class TestFinalizeWithPOI:
    def test_appends_poi_as_waypoint(self, stops: dict[str, Stop]) -> None:
        client = _make_client(get_response=_directions_response())
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        chosen = POICandidate(
            name="Kaufland Gruenau",
            address="Lidicestr. 1, Leipzig",
            place_id="ChIJ1234",
            detour_seconds=300,
            rating=4.2,
        )
        planner.finalize_with_poi(
            origin=stops["origin"],
            people_stops=[stops["lisa"]],
            destination=stops["destination"],
            chosen_poi=chosen,
        )
        _, kwargs = client.get.call_args
        # Der POI-Adresse muss im waypoints-Param stehen
        assert "Lidicestr. 1, Leipzig" in kwargs["params"]["waypoints"]

    def test_falls_back_to_place_id(self, stops: dict[str, Stop]) -> None:
        """POI ohne Adresse -> place_id:<id> wird benutzt."""
        client = _make_client(get_response=_directions_response())
        planner = GoogleMapsRoutePlanner(API_KEY, client=client)
        chosen = POICandidate(
            name="Kaufland",
            address="",
            place_id="ChIJ5678",
            detour_seconds=100,
            rating=None,
        )
        planner.finalize_with_poi(
            origin=stops["origin"],
            people_stops=[],
            destination=stops["destination"],
            chosen_poi=chosen,
        )
        _, kwargs = client.get.call_args
        assert "place_id:ChIJ5678" in kwargs["params"]["waypoints"]


# ---------------------------------------------------------------------------
# Format-Helfer
# ---------------------------------------------------------------------------


class TestFormatHelpers:
    @pytest.mark.parametrize(
        "secs,expected",
        [
            (30, "30 Sekunden"),
            (60, "1 Minuten"),
            (120, "2 Minuten"),
            (3600, "1 Stunde"),
            (3660, "1 Stunde 1 Minuten"),
            (7200, "2 Stunden"),
            (7320, "2 Stunden 2 Minuten"),
        ],
    )
    def test_format_duration(self, secs: int, expected: str) -> None:
        assert GoogleMapsRoutePlanner._format_duration(secs) == expected

    @pytest.mark.parametrize(
        "m,expected",
        [
            (500, "500 m"),
            (1000, "1,0 km"),
            (15300, "15,3 km"),
            (48200, "48,2 km"),
        ],
    )
    def test_format_distance(self, m: int, expected: str) -> None:
        assert GoogleMapsRoutePlanner._format_distance(m) == expected


# ---------------------------------------------------------------------------
# Dataclasses (smoke)
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_stop_frozen(self) -> None:
        s = Stop("X")
        with pytest.raises(AttributeError):
            s.address = "Y"  # type: ignore[misc]

    def test_planned_route_default_poi_empty(self) -> None:
        route = MultiStopRouteResult(
            ordered_stops=(Stop("A"), Stop("B")),
            total_duration_seconds=60,
            total_duration_text="1 Minuten",
            total_distance_text="1,0 km",
            leg_durations_seconds=(60,),
            encoded_polyline="x",
        )
        planned = PlannedRoute(route=route)
        assert planned.poi_candidates == ()
