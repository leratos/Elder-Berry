"""Tests fuer MultiStopRouteCommandHandler -- Turn-Sequencing.

Phase 92 (E4). Alle externen Dependencies werden gemockt:
- RouteIntentParser.parse (Sonnet)
- GoogleMapsRoutePlanner.plan / finalize_with_poi
- ContactStore.find_by_group / search
- RouteSessionStore (echter SQLite-Store in tmp_path)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.multi_stop_route_commands import (
    MultiStopRouteCommandHandler,
)
from elder_berry.tools.google_maps_route_planner import (
    MultiStopRouteResult,
    POICandidate,
    PlannedRoute,
    RouteError,
    Stop,
)
from elder_berry.tools.maps_link_builder import MapsLinkBuilder
from elder_berry.tools.route_intent_parser import (
    IntentStop,
    RouteIntent,
    RouteIntentExtractionError,
)
from elder_berry.tools.route_session_store import RouteSessionStore

USER_ID = "@test:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _contact(name: str, address: str = "") -> MagicMock:
    c = MagicMock()
    c.name = name
    c.address = address
    return c


@pytest.fixture
def contact_store() -> MagicMock:
    store = MagicMock()
    # Default: Home-Kontakt vorhanden, Lisa eindeutig
    store.find_by_group.return_value = [
        _contact("Zuhause", "Musterstr. 5, 12345 Berlin"),
    ]
    store.search.return_value = []
    return store


@pytest.fixture
def planner() -> MagicMock:
    p = MagicMock()
    # Default: plan() liefert eine 2-Leg-Route ohne POI
    default_route = MultiStopRouteResult(
        ordered_stops=(
            Stop("Musterstr. 5, Berlin", "Zuhause"),
            Stop("Hauptstr. 12, Leipzig", "Lisa"),
        ),
        total_duration_seconds=4800,
        total_duration_text="1 Stunde 20 Minuten",
        total_distance_text="85,3 km",
        leg_durations_seconds=(4800,),
        encoded_polyline="POLYLINE",
    )
    p.plan.return_value = PlannedRoute(route=default_route)
    p.finalize_with_poi.return_value = default_route
    return p


@pytest.fixture
def intent_parser() -> MagicMock:
    return MagicMock()


@pytest.fixture
def session_store(tmp_path: Path) -> RouteSessionStore:
    return RouteSessionStore(db_path=tmp_path / "sessions.db")


@pytest.fixture
def handler(
    intent_parser: MagicMock,
    planner: MagicMock,
    contact_store: MagicMock,
    session_store: RouteSessionStore,
) -> MultiStopRouteCommandHandler:
    return MultiStopRouteCommandHandler(
        intent_parser=intent_parser,
        route_planner=planner,
        contact_store=contact_store,
        session_store=session_store,
        link_builder=MapsLinkBuilder(),
        default_user_id=USER_ID,
    )


def _intent(
    *,
    origin: IntentStop | None = None,
    destination: IntentStop | None = None,
    waypoints: tuple[IntentStop, ...] = (),
    arrival_time_text: str = "",
) -> RouteIntent:
    return RouteIntent(
        origin=origin or IntentStop(type="home", value=""),
        destination=destination or IntentStop(type="contact", value="Leipzig Hbf"),
        waypoints=waypoints,
        arrival_time_text=arrival_time_text,
    )


# ---------------------------------------------------------------------------
# Pattern-Vorfilter / Fallthrough
# ---------------------------------------------------------------------------


class TestFallthrough:
    def test_unknown_command_returns_fallthrough(
        self,
        handler: MultiStopRouteCommandHandler,
    ) -> None:
        result = handler.execute("nonsense", "...")
        assert result.fallthrough is True

    def test_single_stop_text_fallthrough(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
    ) -> None:
        """'Plane fahrt zu Lisa' ohne Multi-Stop-Hint -> Phase 43 nimmt's."""
        result = handler.execute(
            "multi_stop_route",
            "Plane meine fahrt zu Lisa",
        )
        assert result.fallthrough is True
        intent_parser.parse.assert_not_called()


# ---------------------------------------------------------------------------
# Turn 1: Sonnet + Resolving
# ---------------------------------------------------------------------------


class TestTurn1:
    def test_single_pass_full_route_no_ambiguity(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="contact", value="Lisa"),
            waypoints=(
                IntentStop(
                    type="contact",
                    value="Andrea",
                    constraint="before_destination",
                ),
            ),
        )
        # Beide Kontakte eindeutig
        contact_store.search.side_effect = (
            lambda uid, name: [
                _contact("Lisa", "Hauptstr. 12, Leipzig"),
            ]
            if name == "Lisa"
            else [
                _contact("Andrea", "Mozartweg 4, Markranstaedt"),
            ]
        )
        # Routing-Mock: 3-Leg-Route
        planner.plan.return_value = PlannedRoute(
            route=MultiStopRouteResult(
                ordered_stops=(
                    Stop("Musterstr. 5, Berlin", "Zuhause"),
                    Stop("Mozartweg 4, Markranstaedt", "Andrea"),
                    Stop("Hauptstr. 12, Leipzig", "Lisa"),
                ),
                total_duration_seconds=4800,
                total_duration_text="1 Stunde 20 Minuten",
                total_distance_text="85,3 km",
                leg_durations_seconds=(2400, 2400),
                encoded_polyline="X",
            ),
        )
        result = handler.execute(
            "multi_stop_route",
            "Fahrt zu Lisa, vorher Andrea abholen",
        )
        assert result.success is True
        assert result.list_items is None
        assert "Route geplant" in (result.text or "")
        assert "google.com/maps/dir" in (result.text or "")

    def test_contact_ambiguity_creates_pick_list(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="contact", value="Leipzig Hbf"),
            waypoints=(IntentStop(type="contact", value="Lisa"),),
        )
        # Destination eindeutig (kein Treffer im Contact, wird als
        # Adresse uebernommen -- aber nicht im Pattern enthalten; um
        # das zu vereinfachen: stubbe als address-Intent)
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(
                type="address",
                value="Hauptbahnhof Leipzig",
            ),
            waypoints=(IntentStop(type="contact", value="Lisa"),),
        )
        # Lisa zweideutig
        contact_store.search.return_value = [
            _contact("Lisa Müller", "Adr-M"),
            _contact("Lisa Schmidt", "Adr-S"),
        ]
        result = handler.execute(
            "multi_stop_route",
            "Ich muss nach Hauptbahnhof Leipzig, vorher Lisa abholen",
        )
        assert result.success is True
        assert result.list_type == "route_contact_pick"
        assert result.list_items is not None
        assert len(result.list_items) == 2
        assert all(item["slot"] == "waypoint_0" for item in result.list_items)
        assert "Mehrere Treffer" in (result.text or "")

    def test_extraction_error_yields_user_hint(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
    ) -> None:
        intent_parser.parse.side_effect = RouteIntentExtractionError(
            "destination missing",
        )
        result = handler.execute(
            "multi_stop_route",
            "Fahr nach irgendwo, vorher tanken",
        )
        assert result.success is True
        assert "nicht ganz verstanden" in (result.text or "")

    def test_no_home_contact_yields_message(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="address", value="Leipzig Hbf"),
            waypoints=(IntentStop(type="contact", value="Lisa"),),
        )
        contact_store.find_by_group.return_value = []
        contact_store.search.return_value = [_contact("Lisa", "Adr-L")]
        result = handler.execute(
            "multi_stop_route",
            "Ich muss nach Leipzig Hbf, vorher Lisa abholen",
        )
        assert "keine Adresse finden" in (result.text or "")


# ---------------------------------------------------------------------------
# Turn 2..N: continue_with_pick
# ---------------------------------------------------------------------------


class TestContinueWithPick:
    def _prepare_ambig_session(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="address", value="Leipzig Hbf"),
            waypoints=(IntentStop(type="contact", value="Lisa"),),
        )
        contact_store.search.return_value = [
            _contact("Lisa Müller", "Adr-M"),
            _contact("Lisa Schmidt", "Adr-S"),
        ]
        handler.execute(
            "multi_stop_route",
            "Ich muss nach Leipzig Hbf, vorher Lisa abholen",
        )

    def test_pick_resolves_and_routes(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        self._prepare_ambig_session(handler, intent_parser, contact_store)
        # Pick: Lisa Müller
        result = handler.continue_with_pick(
            "route_contact_pick",
            {"slot": "waypoint_0", "name": "Lisa Müller", "address": "Adr-M"},
        )
        assert result.success is True
        assert result.list_items is None
        planner.plan.assert_called_once()
        # Adresse muss im plan-Call vorgekommen sein
        call_args = planner.plan.call_args
        people = call_args.kwargs.get("people_stops") or call_args.args[1]
        assert any(s.address == "Adr-M" for s in people)

    def test_pick_with_no_session_returns_hint(
        self,
        handler: MultiStopRouteCommandHandler,
    ) -> None:
        result = handler.continue_with_pick(
            "route_contact_pick",
            {"slot": "waypoint_0", "name": "Lisa", "address": "X"},
        )
        assert "keine offene Routenanfrage" in (result.text or "")

    def test_pick_with_unknown_list_type(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
    ) -> None:
        self._prepare_ambig_session(handler, intent_parser, contact_store)
        result = handler.continue_with_pick(
            "unknown_type",
            {"slot": "waypoint_0", "name": "x", "address": "y"},
        )
        assert "kenne ich nicht" in (result.text or "")

    def test_pick_with_invalid_slot(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
    ) -> None:
        self._prepare_ambig_session(handler, intent_parser, contact_store)
        result = handler.continue_with_pick(
            "route_contact_pick",
            {"slot": "waypoint_99", "name": "Lisa", "address": "X"},
        )
        assert "passt nicht mehr" in (result.text or "")

    def test_session_key_uses_handler_default_user_id(
        self,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
        session_store: RouteSessionStore,
    ) -> None:
        """Codex-Review-Finding 2026-05-20:
        Wenn der Handler mit ``default_user_id="@bot:matrix.org"``
        konstruiert wird, schreibt Turn 1 die Session unter
        ``"@bot:matrix.org"``. Folge-Picks duerfen die Session
        ueber den Handler finden, ohne dass ein anderer Sender den
        Key verbiegt -- denn der Bridge-Dispatch wird msg.sender
        gar nicht mehr durchreichen.
        """
        bot_uid = "@bot:matrix.org"
        handler = MultiStopRouteCommandHandler(
            intent_parser=intent_parser,
            route_planner=planner,
            contact_store=contact_store,
            session_store=session_store,
            link_builder=MapsLinkBuilder(),
            default_user_id=bot_uid,
        )
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="address", value="Leipzig Hbf"),
            waypoints=(IntentStop(type="contact", value="Lisa"),),
        )
        contact_store.search.return_value = [
            _contact("Lisa Müller", "Adr-M"),
            _contact("Lisa Schmidt", "Adr-S"),
        ]
        handler.execute(
            "multi_stop_route",
            "Fahrt nach Leipzig Hbf, vorher Lisa abholen",
        )
        # Session liegt unter bot_uid -- NICHT unter dem leeren default
        assert session_store.get(bot_uid) is not None
        assert session_store.get("") is None

        # continue_with_pick nutzt keinen user_id-Param mehr und liest
        # ueber self._user_id korrekt aus.
        result = handler.continue_with_pick(
            "route_contact_pick",
            {"slot": "waypoint_0", "name": "Lisa Müller", "address": "Adr-M"},
        )
        assert result.success is True
        assert "keine offene Routenanfrage" not in (result.text or "")


# ---------------------------------------------------------------------------
# POI-Pfade
# ---------------------------------------------------------------------------


class TestPOIPath:
    def _prepare_poi_session(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
        *,
        candidates: list[POICandidate],
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="address", value="Leipzig Hbf"),
            waypoints=(
                IntentStop(
                    type="poi",
                    value="Kaufland",
                    poi_category="supermarket",
                    constraint="along_route",
                ),
            ),
        )
        planner.plan.return_value = PlannedRoute(
            route=MultiStopRouteResult(
                ordered_stops=(
                    Stop("Musterstr. 5, Berlin", "Zuhause"),
                    Stop("Hauptbahnhof Leipzig", "Hauptbahnhof Leipzig"),
                ),
                total_duration_seconds=4800,
                total_duration_text="1 Stunde 20 Minuten",
                total_distance_text="85,3 km",
                leg_durations_seconds=(4800,),
                encoded_polyline="POLY",
            ),
            poi_candidates=tuple(candidates),
        )
        handler.execute(
            "multi_stop_route",
            "Fahr nach Leipzig Hbf, unterwegs bei Kaufland einkaufen",
        )

    def test_poi_creates_pick_list(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        candidates = [
            POICandidate(
                name="Kaufland Markranstaedt",
                address="Mark-Adr",
                place_id="ChIJ1",
                detour_seconds=120,
                rating=4.0,
            ),
            POICandidate(
                name="Kaufland Gruenau",
                address="Gru-Adr",
                place_id="ChIJ2",
                detour_seconds=300,
                rating=4.2,
            ),
        ]
        self._prepare_poi_session(
            handler,
            intent_parser,
            contact_store,
            planner,
            candidates=candidates,
        )
        # Die Liste haengt im letzten execute-Result -- aber unsere
        # Helper-Methode swallowed das. Pruefen wir per Pick.
        session = handler._sessions.get(USER_ID)  # type: ignore[attr-defined]
        assert session is not None
        assert len(session.poi_candidates) == 2

    def test_poi_pick_routes_final(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        candidates = [
            POICandidate(
                name="Kaufland G",
                address="G-Adr",
                place_id="ChIJG",
                detour_seconds=200,
                rating=4.1,
            ),
        ]
        self._prepare_poi_session(
            handler,
            intent_parser,
            contact_store,
            planner,
            candidates=candidates,
        )
        # Auch bei n=1 muss der User pickern (Lera-Entscheidung)
        result = handler.continue_with_pick(
            "route_poi_pick",
            {
                "name": "Kaufland G",
                "address": "G-Adr",
                "place_id": "ChIJG",
                "detour_seconds": 200,
                "rating": 4.1,
            },
        )
        assert result.success is True
        planner.finalize_with_poi.assert_called_once()
        # Session clean nach finalem Routing
        assert handler._sessions.get(USER_ID) is None  # type: ignore[attr-defined]

    def test_poi_single_candidate_still_asks(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        """Lera-Entscheidung 2026-05-20: auch bei n=1 picken lassen,
        damit der User die Adresse sieht."""
        candidates = [
            POICandidate(
                name="Einziger Kaufland",
                address="X",
                place_id="ChIJX",
                detour_seconds=100,
                rating=None,
            ),
        ]
        self._prepare_poi_session(
            handler,
            intent_parser,
            contact_store,
            planner,
            candidates=candidates,
        )
        # finalize_with_poi darf NOCH NICHT aufgerufen worden sein
        planner.finalize_with_poi.assert_not_called()
        # Session existiert weiter und hat poi_candidates
        session = handler._sessions.get(USER_ID)  # type: ignore[attr-defined]
        assert session is not None
        assert len(session.poi_candidates) == 1
        assert session.chosen_poi is None

    def test_poi_zero_candidates_falls_back_to_route(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        self._prepare_poi_session(
            handler,
            intent_parser,
            contact_store,
            planner,
            candidates=[],
        )
        # Session geclearet (Route ist final geplant, mit Hinweis)
        assert handler._sessions.get(USER_ID) is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Routing-Fehler
# ---------------------------------------------------------------------------


class TestRouteErrors:
    def test_api_error_in_final_routing(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="address", value="Leipzig Hbf"),
            waypoints=(IntentStop(type="contact", value="Andrea"),),
        )
        contact_store.search.return_value = [
            _contact("Andrea", "Mozartweg 4, Markranstaedt"),
        ]
        planner.plan.side_effect = RouteError("ZERO_RESULTS")
        result = handler.execute(
            "multi_stop_route",
            "Ich muss nach Leipzig Hbf, vorher Andrea abholen",
        )
        assert "ZERO_RESULTS" in (result.text or "") or "Fehler" in (result.text or "")
        assert handler._sessions.get(USER_ID) is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Arrival-Time-Formatierung
# ---------------------------------------------------------------------------


class TestArrivalTime:
    def test_arrival_line_appears(
        self,
        handler: MultiStopRouteCommandHandler,
        intent_parser: MagicMock,
        contact_store: MagicMock,
        planner: MagicMock,
    ) -> None:
        intent_parser.parse.return_value = _intent(
            destination=IntentStop(type="address", value="Leipzig Hbf"),
            waypoints=(IntentStop(type="contact", value="Andrea"),),
            arrival_time_text="morgen um 16 uhr",
        )
        contact_store.search.return_value = [_contact("Andrea", "Adr-A")]
        result = handler.execute(
            "multi_stop_route",
            "Fahrt morgen um 16 uhr nach Leipzig Hbf, vorher Andrea abholen",
        )
        assert "Abfahrt" in (result.text or "")
        assert "Ankunft 16:00" in (result.text or "")


# ---------------------------------------------------------------------------
# Plugin-Manifest
# ---------------------------------------------------------------------------


class TestPlugin:
    def test_plugin_priority(self) -> None:
        from elder_berry.comms.commands.multi_stop_route_commands import PLUGIN

        assert PLUGIN.name == "multi_stop_route"
        assert PLUGIN.priority == 75
        assert PLUGIN.category == "web"

    def test_factory_returns_none_when_unconfigured(self) -> None:
        from elder_berry.comms.commands.base import HandlerContext
        from elder_berry.comms.commands.multi_stop_route_commands import PLUGIN

        # Komplett leerer Context -> Plugin liefert keinen Handler
        ctx = HandlerContext()
        assert PLUGIN.factory(ctx) is None

    def test_factory_returns_handler_when_configured(
        self,
        tmp_path: Path,
    ) -> None:
        from elder_berry.comms.commands.base import HandlerContext
        from elder_berry.comms.commands.multi_stop_route_commands import PLUGIN

        ctx = HandlerContext(
            anthropic_client=MagicMock(),
            contact_store=MagicMock(),
            multi_stop_route_planner=MagicMock(),
            route_session_store=RouteSessionStore(
                db_path=tmp_path / "x.db",
            ),
            default_user_id=USER_ID,
        )
        handler = PLUGIN.factory(ctx)
        assert isinstance(handler, MultiStopRouteCommandHandler)
