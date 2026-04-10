"""Tests für RouteCommandHandler – Routenplanung Commands."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.route_commands import (
    ROUTE_FROM_TO_PATTERN,
    ROUTE_PLAN_PATTERN,
    RouteCommandHandler,
    parse_arrival_time,
)
from elder_berry.tools.route_planner import RouteError, RouteResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_ID = "@test:matrix.org"


def _make_contact(
    name: str = "Lisa Müller",
    address: str = "Hauptstr. 12, 10115 Berlin",
    **kwargs,
) -> MagicMock:
    c = MagicMock()
    c.name = name
    c.address = address
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _make_route_result(**overrides) -> RouteResult:
    defaults = {
        "duration_seconds": 4800,
        "duration_text": "1 Stunde 20 Min.",
        "distance_text": "85,3 km",
        "summary": "A10",
        "start_address": "Musterstr. 5, 12345 Berlin",
        "end_address": "Hauptstr. 12, 10115 Berlin",
    }
    defaults.update(overrides)
    return RouteResult(**defaults)


@pytest.fixture
def contact_store() -> MagicMock:
    store = MagicMock()
    store.find_by_group.return_value = [
        _make_contact("Zuhause", "Musterstr. 5, 12345 Berlin"),
    ]
    store.search.return_value = [
        _make_contact("Lisa Müller", "Hauptstr. 12, 10115 Berlin"),
    ]
    return store


@pytest.fixture
def route_planner() -> MagicMock:
    planner = MagicMock()
    planner.get_route.return_value = _make_route_result()
    planner.buffer_minutes = 15
    planner.calculate_departure.return_value = datetime(2026, 4, 5, 14, 45)
    planner.generate_maps_link.return_value = (
        "https://www.google.com/maps/dir/?origin=A&destination=B"
    )
    return planner


@pytest.fixture
def handler(
    route_planner: MagicMock,
    contact_store: MagicMock,
) -> RouteCommandHandler:
    return RouteCommandHandler(
        route_planner=route_planner,
        contact_store=contact_store,
        default_user_id=USER_ID,
    )


# ---------------------------------------------------------------------------
# Pattern-Tests
# ---------------------------------------------------------------------------

class TestPatterns:
    @pytest.mark.parametrize("text", [
        "plane meine fahrt zu Lisa",
        "plane fahrt zu Lisa",
        "berechne route zu Lisa",
        "navigation zu Lisa",
        "wie komme ich zu Lisa",
        "wie fahre ich zu Lisa",
        "plane meine reise nach München",
        "navigiere zu Lisa",
    ])
    def test_route_plan_matches(self, text: str) -> None:
        assert ROUTE_PLAN_PATTERN.search(text.lower()) is not None

    @pytest.mark.parametrize("text", [
        "fahrt von Mama zu Lisa",
        "plane fahrt von Mama zu Lisa",
        "route von Berlin nach Hamburg",
        "berechne weg von Mama zu Lisa",
    ])
    def test_route_from_to_matches(self, text: str) -> None:
        assert ROUTE_FROM_TO_PATTERN.search(text.lower()) is not None

    def test_from_to_extracts_names(self) -> None:
        m = ROUTE_FROM_TO_PATTERN.search("fahrt von mama zu lisa")
        assert m is not None
        assert m.group(1).strip() == "mama"
        assert m.group(2).strip() == "lisa"

    def test_plan_extracts_dest(self) -> None:
        m = ROUTE_PLAN_PATTERN.search("plane fahrt zu lisa")
        assert m is not None
        assert m.group(1).strip() == "lisa"


# ---------------------------------------------------------------------------
# parse_arrival_time
# ---------------------------------------------------------------------------

class TestParseArrivalTime:
    def test_morgen_16_uhr(self) -> None:
        result = parse_arrival_time("morgen um 16 uhr")
        assert result is not None
        tomorrow = datetime.now().date() + timedelta(days=1)
        assert result.date() == tomorrow
        assert result.hour == 16
        assert result.minute == 0

    def test_uebermorgen_10_uhr(self) -> None:
        result = parse_arrival_time("übermorgen 10 uhr")
        assert result is not None
        day_after = datetime.now().date() + timedelta(days=2)
        assert result.date() == day_after
        assert result.hour == 10

    def test_heute_14_30(self) -> None:
        result = parse_arrival_time("um 14:30")
        assert result is not None
        assert result.date() == datetime.now().date()
        assert result.hour == 14
        assert result.minute == 30

    def test_no_time(self) -> None:
        result = parse_arrival_time("zu Lisa")
        assert result is None

    def test_weekday(self) -> None:
        result = parse_arrival_time("freitag um 9 uhr")
        assert result is not None
        assert result.weekday() == 4  # Freitag
        assert result.hour == 9

    def test_invalid_hour(self) -> None:
        result = parse_arrival_time("um 25 uhr")
        assert result is None

    def test_time_without_uhr(self) -> None:
        result = parse_arrival_time("morgen 16:30")
        assert result is not None
        assert result.hour == 16
        assert result.minute == 30


# ---------------------------------------------------------------------------
# Handler execute
# ---------------------------------------------------------------------------

class TestExecute:
    def test_plan_route_to_contact(
        self, handler: RouteCommandHandler,
    ) -> None:
        """'plane fahrt zu Lisa' → Route von Home zu Lisa."""
        result = handler.execute("route_plan", "plane fahrt zu Lisa")
        assert result.success
        assert "Lisa" in result.text
        assert "1 Stunde 20 Min." in result.text

    def test_plan_route_from_to(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """'fahrt von Mama zu Lisa' → Route Mama→Lisa."""
        # search liefert je nach Aufruf unterschiedliche Kontakte
        mama = _make_contact("Mama", "Am Park 3, 10999 Berlin")
        lisa = _make_contact("Lisa Müller", "Hauptstr. 12, 10115 Berlin")
        contact_store.search.side_effect = [[mama], [lisa]]

        result = handler.execute(
            "route_from_to", "fahrt von mama zu lisa",
        )
        assert result.success
        assert "lisa" in result.text.lower()

    def test_plan_route_with_arrival_time(
        self, handler: RouteCommandHandler,
        route_planner: MagicMock,
    ) -> None:
        """Ankunftszeit angegeben → Abfahrtszeit wird berechnet."""
        result = handler.execute(
            "route_plan",
            "plane fahrt zu Lisa, morgen um 16 uhr",
        )
        assert result.success
        assert "losfahren" in result.text
        route_planner.calculate_departure.assert_called_once()

    def test_plan_route_no_time(
        self, handler: RouteCommandHandler,
        route_planner: MagicMock,
    ) -> None:
        """Ohne Zeitangabe → keine Abfahrtszeit."""
        result = handler.execute("route_plan", "plane fahrt zu Lisa")
        assert result.success
        assert "losfahren" not in result.text
        route_planner.calculate_departure.assert_not_called()

    def test_contact_not_found(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """Unbekannter Kontakt → hilfreiche Fehlermeldung."""
        contact_store.search.return_value = []
        result = handler.execute("route_plan", "plane fahrt zu Unbekannt")
        assert result.success
        assert "keine adresse" in result.text.lower()

    def test_no_address_on_contact(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """Kontakt ohne Adresse → Hinweis."""
        contact_store.search.return_value = [
            _make_contact("Lisa", address=""),
        ]
        result = handler.execute("route_plan", "plane fahrt zu Lisa")
        assert result.success
        assert "keine adresse" in result.text.lower()

    def test_no_home_contact(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """Kein Home-Kontakt → Hinweis 'Gruppe home'."""
        contact_store.find_by_group.return_value = []
        result = handler.execute("route_plan", "plane fahrt zu Lisa")
        assert result.success
        assert "home" in result.text.lower()

    def test_api_error(
        self, handler: RouteCommandHandler,
        route_planner: MagicMock,
    ) -> None:
        """RouteError → Fehlermeldung."""
        route_planner.get_route.side_effect = RouteError("ZERO_RESULTS")
        result = handler.execute("route_plan", "plane fahrt zu Lisa")
        assert result.success
        assert "❌" in result.text and "Route" in result.text

    def test_maps_link_in_response(
        self, handler: RouteCommandHandler,
    ) -> None:
        """Antwort enthält Google Maps Link."""
        result = handler.execute("route_plan", "plane fahrt zu Lisa")
        assert result.success
        assert "google.com/maps" in result.text

    def test_plan_route_von_mir(
        self, handler: RouteCommandHandler,
    ) -> None:
        """'von mir zu Lisa' → 'mir' wird als Home aufgelöst."""
        result = handler.execute(
            "route_from_to", "plane fahrt von mir zu Lisa",
        )
        assert result.success
        assert "Lisa" in result.text

    def test_plan_route_ankunft_time(
        self, handler: RouteCommandHandler,
        route_planner: MagicMock,
    ) -> None:
        """'ankunft 13 uhr heute' → Abfahrtszeit berechnet."""
        result = handler.execute(
            "route_plan", "plane fahrt zu Lisa ankunft 13 uhr heute",
        )
        assert result.success
        assert "losfahren" in result.text
        route_planner.calculate_departure.assert_called_once()

    def test_unknown_command_fallthrough(
        self, handler: RouteCommandHandler,
    ) -> None:
        result = handler.execute("unknown_cmd", "irgendwas")
        assert not result.success
        assert result.fallthrough


# ---------------------------------------------------------------------------
# _resolve_address
# ---------------------------------------------------------------------------

class TestResolveAddress:
    def test_home(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """None → Home-Kontakt Adresse."""
        addr = handler._resolve_address(None)
        assert addr == "Musterstr. 5, 12345 Berlin"
        contact_store.find_by_group.assert_called_with(USER_ID, "home")

    @pytest.mark.parametrize("synonym", [
        "mir", "zuhause", "daheim", "home", "zu hause", "meiner",
    ])
    def test_home_synonyms(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
        synonym: str,
    ) -> None:
        """Home-Synonyme → Home-Kontakt Adresse."""
        addr = handler._resolve_address(synonym)
        assert addr == "Musterstr. 5, 12345 Berlin"
        contact_store.find_by_group.assert_called_with(USER_ID, "home")

    def test_by_name(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """'Lisa' → Fuzzy-Match → Adresse."""
        addr = handler._resolve_address("Lisa")
        assert addr == "Hauptstr. 12, 10115 Berlin"
        contact_store.search.assert_called_with(USER_ID, "Lisa")

    def test_not_found(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
    ) -> None:
        """Unbekannt → None."""
        contact_store.search.return_value = []
        addr = handler._resolve_address("Unbekannt")
        assert addr is None

    @pytest.mark.parametrize("raw_address", [
        "Am Brendegraben 21, 13127 Berlin",
        "Musterstr. 1, 12345 Berlin",
        "Hauptstraße 42",
        "10115 Berlin",
        '"Am Brendegraben 21 in 13127 Berlin"',
    ])
    def test_direct_address(
        self, handler: RouteCommandHandler,
        contact_store: MagicMock,
        raw_address: str,
    ) -> None:
        """Direkte Adresse (mit Ziffern) wird nicht im ContactStore gesucht."""
        addr = handler._resolve_address(raw_address)
        assert addr is not None
        # ContactStore.search darf NICHT aufgerufen werden
        contact_store.search.assert_not_called()

    def test_direct_address_strips_quotes(
        self, handler: RouteCommandHandler,
    ) -> None:
        """Anführungszeichen werden von direkten Adressen entfernt."""
        addr = handler._resolve_address('"Am Brendegraben 21, 13127 Berlin"')
        assert addr == "Am Brendegraben 21, 13127 Berlin"


# ---------------------------------------------------------------------------
# _strip_time_suffix
# ---------------------------------------------------------------------------

class TestStripTimeSuffix:
    @pytest.mark.parametrize("input_text,expected", [
        ("lisa, morgen um 16 uhr", "lisa"),
        ("lisa morgen 16 uhr", "lisa"),
        ("lisa, übermorgen 10 uhr", "lisa"),
        ("lisa um 14:30", "lisa"),
        ("lisa heute 15 uhr", "lisa"),
        ("lisa freitag um 9", "lisa"),
        ("lisa ankunft 13 uhr heute", "lisa"),
        ("lisa ankunft 13 uhr", "lisa"),
        ("lisa", "lisa"),
    ])
    def test_strip(self, input_text: str, expected: str) -> None:
        assert RouteCommandHandler._strip_time_suffix(input_text) == expected


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

class TestKeywords:
    def test_keywords_defined(self, handler: RouteCommandHandler) -> None:
        kw = handler.keywords
        assert "route_plan" in kw
        assert len(kw["route_plan"]) >= 5

    def test_command_descriptions(self, handler: RouteCommandHandler) -> None:
        descs = handler.command_descriptions
        assert len(descs) >= 3
