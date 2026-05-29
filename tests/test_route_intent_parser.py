"""Tests fuer RouteIntentParser -- Pattern-Vorfilter + Sonnet-Tool-Call.

Phase 92 (E2). Sonnet-Calls werden gemockt (AnthropicClient.tool_call);
keine echten API-Roundtrips.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from elder_berry.tools.route_intent_parser import (
    ROUTE_EXTRACT_TOOL,
    IntentStop,
    RouteIntent,
    RouteIntentExtractionError,
    RouteIntentParser,
    is_multi_stop_candidate,
)


# ---------------------------------------------------------------------------
# Pattern-Vorfilter
# ---------------------------------------------------------------------------


class TestIsMultiStopCandidate:
    @pytest.mark.parametrize(
        "text",
        [
            "Ich muss nach Leipzig, vorher noch Lisa abholen",
            "Ich muss von zuhause zu Nadine und dann zu Lisa, unterwegs zu Hornbach",
            "Ich muss von zuhause zu Nadine und dann zu Lisa",
            "Fahrt zu Andrea, auf dem weg kaufe ich ein",
            "Plane meine route nach Berlin, unterwegs tanken",
            "Fahre nach Markranstaedt, vorher Lisa und Andrea abholen",
            "Navigation nach Leipzig, ueber Markranstaedt",
            "Fahr nach Leipzig via Halle",
            "Route nach Berlin, danach Lisa abholen",
        ],
    )
    def test_true_for_multi_stop(self, text: str) -> None:
        assert is_multi_stop_candidate(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Plane meine fahrt zu Lisa",
            "Wie komme ich zu Andrea",
            "Navigation zu Lisa",
            "Fahrt von Mama zu Lisa, morgen 16 uhr",
            "Fahr mich nach Leipzig",
        ],
    )
    def test_false_for_single_stop(self, text: str) -> None:
        assert is_multi_stop_candidate(text) is False

    def test_false_for_non_route(self) -> None:
        # Keine Route-Intro -> egal wie viele Stop-Hints
        assert is_multi_stop_candidate("Vorher noch einkaufen") is False

    def test_false_for_empty(self) -> None:
        assert is_multi_stop_candidate("") is False


# ---------------------------------------------------------------------------
# Tool-Schema
# ---------------------------------------------------------------------------


class TestToolSchema:
    def test_tool_name(self) -> None:
        assert ROUTE_EXTRACT_TOOL["name"] == "extract_multi_stop_route"

    def test_destination_required(self) -> None:
        schema = ROUTE_EXTRACT_TOOL["input_schema"]
        assert "destination" in schema["required"]
        assert "waypoints" in schema["required"]

    def test_waypoint_type_enum(self) -> None:
        wp_schema = ROUTE_EXTRACT_TOOL["input_schema"]["properties"]["waypoints"][
            "items"
        ]
        type_enum = wp_schema["properties"]["type"]["enum"]
        assert set(type_enum) == {"contact", "address", "poi"}


# ---------------------------------------------------------------------------
# Parse mit Sonnet-Mock
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_client() -> MagicMock:
    client = MagicMock()
    return client


@pytest.fixture
def parser(anthropic_client: MagicMock) -> RouteIntentParser:
    return RouteIntentParser(anthropic_client)


def _sonnet_response(
    *,
    origin: dict[str, Any] | None = None,
    destination: dict[str, Any] | None = None,
    waypoints: list[dict[str, Any]] | None = None,
    arrival_time_text: str = "",
) -> dict[str, Any]:
    return {
        "origin": origin if origin is not None else {"type": "home", "value": ""},
        "destination": destination
        if destination is not None
        else {"type": "contact", "value": "Lisa"},
        "waypoints": waypoints or [],
        "arrival_time_text": arrival_time_text,
    }


class TestParse:
    def test_basic_two_contact_waypoints(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Leipzig Hbf"},
            waypoints=[
                {
                    "type": "contact",
                    "value": "Lisa",
                    "constraint": "before_destination",
                },
                {
                    "type": "contact",
                    "value": "Andrea",
                    "constraint": "before_destination",
                },
            ],
        )
        intent = parser.parse(
            "Ich muss nach Leipzig Hbf, vorher Lisa und Andrea abholen",
        )
        assert intent.origin.type == "home"
        assert intent.destination.value == "Leipzig Hbf"
        assert [w.value for w in intent.waypoints] == ["Lisa", "Andrea"]

    def test_with_poi_along_route(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Leipzig Hbf"},
            waypoints=[
                {
                    "type": "poi",
                    "value": "Kaufland",
                    "poi_category": "supermarket",
                    "constraint": "along_route",
                },
            ],
        )
        intent = parser.parse(
            "Fahr nach Leipzig Hbf, unterwegs bei Kaufland einkaufen",
        )
        poi = intent.waypoints[0]
        assert poi.type == "poi"
        assert poi.poi_category == "supermarket"
        assert poi.constraint == "along_route"

    def test_with_arrival_time(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Lisa"},
            waypoints=[],
            arrival_time_text="morgen um 16 uhr",
        )
        intent = parser.parse("Ich muss morgen um 16 uhr bei Lisa sein")
        assert intent.arrival_time_text == "morgen um 16 uhr"

    def test_origin_default_home(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Lisa"},
        )
        intent = parser.parse("Fahrt zu Lisa")
        assert intent.origin.type == "home"

    def test_origin_explicit_contact(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            origin={"type": "contact", "value": "Mama"},
            destination={"type": "contact", "value": "Lisa"},
        )
        intent = parser.parse("Fahr von Mama zu Lisa")
        assert intent.origin.type == "contact"
        assert intent.origin.value == "Mama"

    def test_origin_explicit_address(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            origin={"type": "address", "value": "Musterstr. 5, Berlin"},
            destination={"type": "address", "value": "Hauptstr. 12, Leipzig"},
        )
        intent = parser.parse(
            "Fahrt von Musterstr. 5, Berlin nach Hauptstr. 12, Leipzig",
        )
        assert intent.origin.type == "address"
        assert intent.destination.type == "address"

    def test_poi_default_along_route(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        """POI ohne explicit constraint -> along_route Default."""
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Andrea"},
            waypoints=[{"type": "poi", "value": "Tankstelle"}],
        )
        intent = parser.parse("Fahr zu Andrea, unterwegs tanken")
        assert intent.waypoints[0].constraint == "along_route"

    def test_contact_default_before_destination(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        """Contact ohne explicit constraint -> before_destination Default."""
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Andrea"},
            waypoints=[{"type": "contact", "value": "Lisa"}],
        )
        intent = parser.parse("Fahr zu Andrea, vorher Lisa abholen")
        assert intent.waypoints[0].constraint == "before_destination"

    def test_repairs_chained_destination_phrase_from_live_case(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={
                "type": "contact",
                "value": "Nadine und dann zu Lisa. Unterwegs moechte ich noch zu Hornbach",
            },
            waypoints=[],
        )
        intent = parser.parse(
            "Ich muss von zuhause zu Nadine und dann zu Lisa. "
            "Unterwegs moechte ich noch zu Hornbach.",
        )
        assert intent.destination.value == "Lisa"
        assert [waypoint.value for waypoint in intent.waypoints] == [
            "Nadine",
            "Hornbach",
        ]
        assert intent.waypoints[0].type == "contact"
        assert intent.waypoints[1].type == "poi"
        assert intent.waypoints[1].constraint == "along_route"

    def test_heuristic_parse_without_anthropic_for_live_case(self) -> None:
        parser = RouteIntentParser(None)
        intent = parser.parse(
            "Ich muss von zuhause zu Nadine und dann zu Lisa. "
            "Unterwegs moechte ich noch zu Hornbach.",
        )
        assert intent.origin.type == "home"
        assert intent.destination.value == "Lisa"
        assert [waypoint.value for waypoint in intent.waypoints] == [
            "Nadine",
            "Hornbach",
        ]
        assert intent.waypoints[0].type == "contact"
        assert intent.waypoints[1].type == "poi"

    def test_heuristic_parse_without_anthropic_for_chained_nach(self) -> None:
        parser = RouteIntentParser(None)
        intent = parser.parse("Ich muss von zuhause zu Nadine und dann nach Lisa")
        assert intent.origin.type == "home"
        assert intent.destination.value == "Lisa"
        assert [waypoint.value for waypoint in intent.waypoints] == ["Nadine"]

    def test_heuristic_parse_without_anthropic_for_chained_richtung(self) -> None:
        parser = RouteIntentParser(None)
        intent = parser.parse("Ich muss von zuhause zu Nadine und dann richtung Lisa")
        assert intent.origin.type == "home"
        assert intent.destination.value == "Lisa"
        assert [waypoint.value for waypoint in intent.waypoints] == ["Nadine"]

    def test_heuristic_parse_with_vorher_and_poi(self) -> None:
        parser = RouteIntentParser(None)
        intent = parser.parse(
            "Ich muss nach Leipzig Hbf, vorher Lisa und Andrea abholen, "
            "unterwegs bei Hornbach einkaufen",
        )
        assert intent.destination.value == "Leipzig Hbf"
        assert [waypoint.value for waypoint in intent.waypoints] == [
            "Lisa",
            "Andrea",
            "Hornbach einkaufen",
        ]
        assert intent.waypoints[2].type == "poi"
        assert intent.arrival_time_text == ""

    def test_heuristic_parse_preserves_arrival_time_text(self) -> None:
        parser = RouteIntentParser(None)
        intent = parser.parse(
            "Fahrt morgen um 16 uhr nach Leipzig Hbf, vorher Andrea abholen",
        )
        assert intent.destination.value == "Leipzig Hbf"
        assert intent.arrival_time_text == "morgen um 16 uhr"

    # ------------------------------------------------------------------
    # Fehlerfaelle
    # ------------------------------------------------------------------

    def test_destination_missing_raises(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = {
            "origin": {"type": "home"},
            "waypoints": [],
        }
        with pytest.raises(RouteIntentExtractionError, match="destination"):
            parser.parse("Mache irgendwas")

    def test_destination_empty_value_raises(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": ""},
        )
        with pytest.raises(RouteIntentExtractionError, match="leeren value"):
            parser.parse("Fahrt zu jemand")

    def test_destination_invalid_type_raises(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "ufo", "value": "X"},
        )
        with pytest.raises(RouteIntentExtractionError, match="stop type"):
            parser.parse("X")

    def test_destination_home_type_not_allowed(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        """Destination darf nicht 'home' sein (waere semantisch sinnlos)."""
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "home", "value": ""},
        )
        with pytest.raises(RouteIntentExtractionError, match="stop type"):
            parser.parse("Fahr nach Hause")

    def test_waypoints_not_a_list_raises(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = {
            "destination": {"type": "contact", "value": "Lisa"},
            "waypoints": "lisa, andrea",
        }
        with pytest.raises(RouteIntentExtractionError, match="waypoints"):
            parser.parse("...")

    def test_waypoint_item_not_dict_raises(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = _sonnet_response(
            destination={"type": "contact", "value": "Andrea"},
            waypoints=["Lisa"],  # type: ignore[list-item]
        )
        with pytest.raises(RouteIntentExtractionError, match="kein Dict"):
            parser.parse("...")

    def test_origin_invalid_falls_back_to_home(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        """Origin = None oder ungueltiges Dict -> Default home.

        Bewusst tolerant: der User wollte sicher ein Routing-Ergebnis,
        ein fehlendes origin ist kein Grund zum Crash.
        """
        anthropic_client.tool_call.return_value = {
            "destination": {"type": "contact", "value": "Lisa"},
            "waypoints": [],
            # origin fehlt komplett
        }
        intent = parser.parse("Fahrt zu Lisa")
        assert intent.origin.type == "home"

    def test_origin_non_dict_falls_back_to_home(
        self,
        parser: RouteIntentParser,
        anthropic_client: MagicMock,
    ) -> None:
        anthropic_client.tool_call.return_value = {
            "origin": "home",
            "destination": {"type": "contact", "value": "Lisa"},
            "waypoints": [],
        }
        intent = parser.parse("Fahrt zu Lisa")
        assert intent.origin.type == "home"


# ---------------------------------------------------------------------------
# DTOs (smoke)
# ---------------------------------------------------------------------------


class TestDTOs:
    def test_intent_stop_frozen(self) -> None:
        s = IntentStop(type="contact", value="Lisa")
        with pytest.raises(AttributeError):
            s.value = "Andrea"  # type: ignore[misc]

    def test_route_intent_default_waypoints_empty(self) -> None:
        intent = RouteIntent(
            origin=IntentStop(type="home", value=""),
            destination=IntentStop(type="contact", value="Lisa"),
        )
        assert intent.waypoints == ()
        assert intent.arrival_time_text == ""
