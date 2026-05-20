"""MultiStopRouteCommandHandler -- Orchestrator fuer Multi-Stop-Routing.

Phase 92 (E4). Faengt Routenanfragen mit mehreren Stops oder POI-
Wuenschen ab. Pattern-Vorfilter laesst Single-Stop ohne LLM durch
(``fallthrough=True``). Multi-Stop-Pfade:

- Sonnet-Tool-Call (RouteIntentParser) extrahiert die strukturierte
  Anfrage.
- ContactAddressResolver loest origin/destination/people-Stops auf.
- Bei Mehrdeutigkeit: ConversationListStore + list_type=route_contact_pick
  -> User waehlt per Listen-Position (Phase 80).
- Wenn alles aufgeloest: GoogleMapsRoutePlanner.plan() laeuft. Bei
  POI-Request anschliessend list_type=route_poi_pick fuer die Wahl
  (auch bei n=1, Lera-Entscheidung 2026-05-20).
- Nach POI-Pick: finalize_with_poi + finale Antwort mit Maps-Link.

Session-State zwischen Turns liegt im RouteSessionStore (SQLite,
TTL=1h, Restart-fest).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)
from elder_berry.comms.commands.route_commands import parse_arrival_time
from elder_berry.tools.contact_address_resolver import (
    AddressResolution,
    resolve_contact_address,
)
from elder_berry.tools.google_maps_route_planner import (
    POICandidate,
    POIRequest,
    RouteError,
    Stop,
)
from elder_berry.tools.maps_link_builder import (
    Stop as LinkStop,
)
from elder_berry.tools.route_intent_parser import (
    IntentStop,
    RouteIntent,
    RouteIntentExtractionError,
    is_multi_stop_candidate,
)
from elder_berry.tools.route_session_store import (
    ResolvedStop,
    RouteSession,
)

if TYPE_CHECKING:
    from elder_berry.tools.contact_store import ContactStore
    from elder_berry.tools.google_maps_route_planner import (
        GoogleMapsRoutePlanner,
    )
    from elder_berry.tools.maps_link_builder import MapsLinkBuilder
    from elder_berry.tools.route_intent_parser import RouteIntentParser
    from elder_berry.tools.route_session_store import RouteSessionStore


logger = logging.getLogger(__name__)


# Default-Puffer-Minuten fuer die Abfahrtszeit-Berechnung. Identisch
# zum RoutePlanner-Default aus Phase 43 -- damit Single- und Multi-Stop
# konsistent sind, ohne den anderen Planner anzufassen.
_DEPARTURE_BUFFER_MINUTES = 15

# Default-Max-Umweg fuer POIs (10 Min). Lera kann das spaeter ueber
# einen optionalen Konstruktor-Parameter ueberschreiben -- aktuell
# hartkodiert (Konzept §"Offene Designentscheidung").
_DEFAULT_MAX_DETOUR_SECONDS = 600


# ---------------------------------------------------------------------------
# Pattern (Multi-Stop-Catch-All)
# ---------------------------------------------------------------------------

# Triggert nur, wenn der Pattern-Vorfilter zustimmt. Damit der Pattern-
# Konflikt-Check (Phase 77) nicht warnt, geben wir einen Catch-All-Regex
# mit weiter Mustertradition, der aber im ``execute`` bei
# ``is_multi_stop_candidate(text) is False`` direkt fallthrough geht.
_MULTI_STOP_PATTERN = re.compile(
    r"\b(plane|berechne|navig\w+|fahrt|fahr|fahre|route|"
    r"wie\s+komme\s+ich|wie\s+fahre\s+ich|muss\s+nach|will\s+nach)\b",
    re.IGNORECASE,
)


HELP_SECTION_MULTI_STOP_ROUTE = """Multi-Stop-Routenplanung:
  "Ich muss nach <Ziel>, vorher <Kontakt> abholen"
    -- Route mit Zwischenstop, ggf. Disambig-Liste
  "Fahr nach <Ziel>, unterwegs bei <Marke> einkaufen"
    -- Route + POI-Suche entlang des Weges, dann Pick aus Liste
  Disambiguierung laeuft per Listen-Position ("nimm Treffer 2")."""


class MultiStopRouteCommandHandler(CommandHandler):
    """Orchestriert Multi-Stop-Routenanfragen ueber Turns hinweg."""

    def __init__(
        self,
        intent_parser: RouteIntentParser,
        route_planner: GoogleMapsRoutePlanner,
        contact_store: ContactStore,
        session_store: RouteSessionStore,
        link_builder: MapsLinkBuilder,
        default_user_id: str = "",
        max_detour_seconds: int = _DEFAULT_MAX_DETOUR_SECONDS,
    ) -> None:
        self._parser = intent_parser
        self._planner = route_planner
        self._contacts = contact_store
        self._sessions = session_store
        self._link = link_builder
        self._user_id = default_user_id
        self._max_detour = max_detour_seconds

    # ------------------------------------------------------------------
    # CommandHandler-Schnittstelle
    # ------------------------------------------------------------------

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        return [
            (_MULTI_STOP_PATTERN, "multi_stop_route", False, True),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "multi_stop_route": [
                "vorher abholen",
                "auf dem weg",
                "unterwegs",
                "einkaufen",
                "tanken",
                "ueber",
                "via",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "plane fahrt zu <Ziel>, vorher <Kontakt>: Route mit Zwischenstop",
            "fahr zu <Ziel>, unterwegs <POI>: Route mit Einkaufs-/Tankstopp",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command != "multi_stop_route":
            return CommandResult(
                command=command,
                success=False,
                fallthrough=True,
            )
        return self._handle_turn1(raw_text)

    # ------------------------------------------------------------------
    # Turn 1: Erste Anfrage
    # ------------------------------------------------------------------

    def _handle_turn1(self, raw_text: str) -> CommandResult:
        """Erster Aufruf -- Pattern-Vorfilter, Sonnet, Resolving, Routing-
        oder-Disambig-Entscheidung."""
        if not is_multi_stop_candidate(raw_text):
            # Single-Stop -- Phase-43-Handler uebernimmt.
            return CommandResult(
                command="multi_stop_route",
                success=False,
                fallthrough=True,
            )

        try:
            intent = self._parser.parse(raw_text)
        except RouteIntentExtractionError as exc:
            logger.info("RouteIntent-Parsing fehlgeschlagen: %s", exc)
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=(
                    "Ich hab die Routenanfrage nicht ganz verstanden. "
                    "Kannst du sie anders formulieren? Beispiel: "
                    "'Fahr nach Leipzig Hbf, vorher Lisa abholen, "
                    "unterwegs bei Kaufland einkaufen.'"
                ),
            )
        except RuntimeError as exc:
            logger.error("Sonnet-Tool-Call fuer Routen-Intent kaputt: %s", exc)
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=user_friendly_error(exc, "Routen-Verstaendnis"),
            )

        session = self._build_session(raw_text, intent)
        self._sessions.set(self._user_id, session)
        return self._next_response(session)

    # ------------------------------------------------------------------
    # Folge-Turns: per list_pick-Dispatch aufgerufen
    # ------------------------------------------------------------------

    def continue_with_pick(
        self,
        user_id: str,
        list_type: str,
        item: dict[str, Any],
    ) -> CommandResult:
        """Wird vom message_handlers._dispatch_route_*_pick aufgerufen.

        Args:
            user_id: Sender-MXID.
            list_type: ``"route_contact_pick"`` oder ``"route_poi_pick"``.
            item: Listen-Eintrag aus dem ConversationListStore.
        """
        session = self._sessions.get(user_id)
        if session is None:
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=(
                    "Ich finde gerade keine offene Routenanfrage mehr "
                    "(vielleicht abgelaufen). Sag mir die Anfrage nochmal."
                ),
            )

        if list_type == "route_contact_pick":
            slot = str(item.get("slot", ""))
            updated = self._apply_contact_pick(session, slot, item)
            if not updated:
                return CommandResult(
                    command="multi_stop_route",
                    success=True,
                    text=(
                        "Der gewaehlte Eintrag passt nicht mehr zur "
                        "aktuellen Routenanfrage. Sag mir die Anfrage nochmal."
                    ),
                )
        elif list_type == "route_poi_pick":
            self._apply_poi_pick(session, item)
        else:
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=f"Listen-Typ '{list_type}' kenne ich nicht.",
            )

        self._sessions.set(user_id, session)
        return self._next_response(session)

    # ------------------------------------------------------------------
    # State-Maschine
    # ------------------------------------------------------------------

    def _next_response(self, session: RouteSession) -> CommandResult:
        """Liefert je nach Session-Zustand: Disambig-Liste, POI-Liste,
        finale Route, oder Fehler-Hinweis."""
        # 1. Offene Personen-Disambig?
        disambig = session.next_open_disambiguation()
        if disambig is not None:
            kind, stop = disambig
            return self._contact_pick_response(kind, stop)

        # 2. Sind alle Personen-Slots aufgeloest? (next_open_dis liefert
        # None auch wenn ein Stop ungeloest UND nicht ambig ist --
        # z.B. "konnte keine Adresse finden". Das checken wir separat.)
        not_resolved = self._first_unresolved_people_stop(session)
        if not_resolved is not None:
            self._sessions.clear(session.user_id)
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=(
                    f"Ich konnte fuer '{not_resolved.label}' keine Adresse "
                    "finden. Hinterleg eine Adresse beim Kontakt oder gib "
                    "die volle Adresse direkt an."
                ),
            )

        # 3. Wenn ein POI offen ist: erst Routing fuer Polyline, dann
        # POI-Suche.
        if session.poi_request is not None and not session.poi_candidates:
            return self._run_poi_search(session)

        # 4. POI-Liste schon befuellt aber noch keine Wahl getroffen?
        if session.poi_candidates and session.chosen_poi is None:
            return self._poi_pick_response(session)

        # 5. Alles aufgeloest -- finale Route.
        return self._finalize_route(session)

    # ------------------------------------------------------------------
    # Session-Aufbau aus RouteIntent
    # ------------------------------------------------------------------

    def _build_session(
        self,
        raw_text: str,
        intent: RouteIntent,
    ) -> RouteSession:
        origin = self._resolve_intent_stop(intent.origin, allow_home=True)
        destination = self._resolve_intent_stop(intent.destination)
        waypoints: list[ResolvedStop] = []
        poi_request: POIRequest | None = None
        for wp in intent.waypoints:
            if wp.type == "poi":
                # POI wird nicht hier aufgeloest -- erst nach Phase-1-
                # Routing per Places-API. Wir behalten die Wunsch-Kategorie
                # als poi_request, plus einen Marker-ResolvedStop in der
                # waypoints-Liste, damit die Reihenfolge in der Antwort
                # bewahrt bleibt (Konzept §3.5: "type=poi nur wenn der
                # User klar nach Kategorie sucht").
                if poi_request is None:
                    poi_request = POIRequest(
                        category=wp.value,
                        name_hint=None,
                        max_results=10,
                        max_detour_seconds=self._max_detour,
                    )
                waypoints.append(
                    ResolvedStop(
                        label=wp.value,
                        intent_type="poi",
                        intent_value=wp.value,
                        poi_category=wp.poi_category,
                    ),
                )
                continue
            waypoints.append(self._resolve_intent_stop(wp))
        return RouteSession(
            user_id=self._user_id,
            raw_text=raw_text,
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            arrival_time_text=intent.arrival_time_text,
            poi_request=poi_request,
        )

    def _resolve_intent_stop(
        self,
        intent_stop: IntentStop,
        *,
        allow_home: bool = False,
    ) -> ResolvedStop:
        """Loest einen IntentStop via ContactAddressResolver auf."""
        if intent_stop.type == "home" and allow_home:
            res: AddressResolution = resolve_contact_address(
                self._contacts,
                self._user_id,
                None,
            )
            return self._resolution_to_stop(
                label=intent_stop.value or "Zuhause",
                intent_type="home",
                intent_value=intent_stop.value,
                resolution=res,
            )
        if intent_stop.type == "address":
            # Direkte Adresse -- nicht im Store suchen.
            return ResolvedStop(
                label=intent_stop.value,
                intent_type="address",
                intent_value=intent_stop.value,
                address=intent_stop.value,
            )
        # Contact (oder Home als Kontaktname, falls allow_home=False)
        res = resolve_contact_address(
            self._contacts,
            self._user_id,
            intent_stop.value,
        )
        return self._resolution_to_stop(
            label=intent_stop.value,
            intent_type="contact",
            intent_value=intent_stop.value,
            resolution=res,
        )

    @staticmethod
    def _resolution_to_stop(
        *,
        label: str,
        intent_type: str,
        intent_value: str,
        resolution: AddressResolution,
    ) -> ResolvedStop:
        return ResolvedStop(
            label=label,
            intent_type=intent_type,
            intent_value=intent_value,
            address=resolution.address,
            candidate_names=list(resolution.ambiguous_matches),
            candidate_addresses=list(resolution.candidate_addresses),
        )

    @staticmethod
    def _first_unresolved_people_stop(
        session: RouteSession,
    ) -> ResolvedStop | None:
        """Liefert den ersten Stop, der nicht ambig aber auch nicht
        aufgeloest ist -- typisch: Kontakt ohne Adresse."""
        if not session.origin.is_resolved and not session.origin.is_ambiguous:
            return session.origin
        if not session.destination.is_resolved and not session.destination.is_ambiguous:
            return session.destination
        for wp in session.waypoints:
            if wp.intent_type == "poi":
                continue
            if not wp.is_resolved and not wp.is_ambiguous:
                return wp
        return None

    # ------------------------------------------------------------------
    # Disambig-Antworten
    # ------------------------------------------------------------------

    def _contact_pick_response(
        self,
        slot: str,
        stop: ResolvedStop,
    ) -> CommandResult:
        """Listet die Kandidaten + registriert list_items fuer den Pick."""
        lines = [f"Mehrere Treffer fuer '{stop.label}':"]
        items: list[dict[str, Any]] = []
        for idx, (name, addr) in enumerate(
            zip(stop.candidate_names, stop.candidate_addresses, strict=False),
            start=1,
        ):
            display_addr = addr or "(keine Adresse)"
            lines.append(f"  {idx}. {name} -- {display_addr}")
            items.append(
                {
                    "slot": slot,
                    "name": name,
                    "address": addr or "",
                },
            )
        lines.append('Welcher passt? Sag mir "Treffer 1" oder "die zweite".')
        return CommandResult(
            command="multi_stop_route",
            success=True,
            text="\n".join(lines),
            list_items=items,
            list_type="route_contact_pick",
        )

    def _poi_pick_response(self, session: RouteSession) -> CommandResult:
        """Listet die POI-Kandidaten + registriert list_items."""
        request = session.poi_request
        label = request.category if request else "POI"
        lines = [f"Treffer fuer '{label}' entlang der Route:"]
        items: list[dict[str, Any]] = []
        for idx, cand in enumerate(session.poi_candidates, start=1):
            detour_min = cand.detour_seconds // 60
            rating = f" ★{cand.rating:.1f}" if cand.rating is not None else ""
            lines.append(
                f"  {idx}. {cand.name} -- {cand.address} "
                f"(+{detour_min} Min Umweg{rating})",
            )
            items.append(
                {
                    "name": cand.name,
                    "address": cand.address,
                    "place_id": cand.place_id,
                    "detour_seconds": cand.detour_seconds,
                    "rating": cand.rating,
                },
            )
        lines.append('Welchen nehmen? "Treffer 1" oder die Nummer.')
        return CommandResult(
            command="multi_stop_route",
            success=True,
            text="\n".join(lines),
            list_items=items,
            list_type="route_poi_pick",
        )

    # ------------------------------------------------------------------
    # Pick-Anwendung
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_contact_pick(
        session: RouteSession,
        slot: str,
        item: dict[str, Any],
    ) -> bool:
        """Schreibt die Auswahl in den richtigen Slot. False wenn Slot
        unbekannt."""
        name = str(item.get("name", "")).strip()
        address = str(item.get("address", "")).strip()
        if not name or not address:
            return False
        target = MultiStopRouteCommandHandler._slot_to_stop(session, slot)
        if target is None:
            return False
        target.label = name
        target.address = address
        target.candidate_names = []
        target.candidate_addresses = []
        return True

    @staticmethod
    def _slot_to_stop(
        session: RouteSession,
        slot: str,
    ) -> ResolvedStop | None:
        if slot == "origin":
            return session.origin
        if slot == "destination":
            return session.destination
        if slot.startswith("waypoint_"):
            try:
                idx = int(slot.split("_", 1)[1])
            except (ValueError, IndexError):
                return None
            if 0 <= idx < len(session.waypoints):
                return session.waypoints[idx]
        return None

    @staticmethod
    def _apply_poi_pick(
        session: RouteSession,
        item: dict[str, Any],
    ) -> None:
        rating_raw = item.get("rating")
        rating: float | None
        rating = float(rating_raw) if rating_raw is not None else None
        session.chosen_poi = POICandidate(
            name=str(item.get("name", "")),
            address=str(item.get("address", "")),
            place_id=str(item.get("place_id", "")),
            detour_seconds=int(item.get("detour_seconds", 0)),
            rating=rating,
        )

    # ------------------------------------------------------------------
    # Routing-Phasen
    # ------------------------------------------------------------------

    def _run_poi_search(self, session: RouteSession) -> CommandResult:
        """Schritt: Phase-1-Routing zur Polyline + POI-Suche.

        Speichert die POI-Liste in der Session und geht in den
        Pick-State ueber (auch bei n=1, Lera-Entscheidung).
        Bei n=0: Hinweis + Route ohne POI fortfuehren.
        """
        try:
            planned = self._planner.plan(
                origin=Stop(
                    address=session.origin.address or "",
                    label=session.origin.label,
                ),
                people_stops=[
                    Stop(address=s.address or "", label=s.label)
                    for s in session.people_stops()
                ],
                destination=Stop(
                    address=session.destination.address or "",
                    label=session.destination.label,
                ),
                poi_request=session.poi_request,
            )
        except RouteError as exc:
            self._sessions.clear(session.user_id)
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=user_friendly_error(exc, "Routenberechnung"),
            )

        session.poi_candidates = list(planned.poi_candidates)
        if not session.poi_candidates:
            # Kein POI in Reichweite -- Hinweis + Route ohne POI.
            label = session.poi_request.category if session.poi_request else "POI"
            session.poi_request = None  # damit _finalize keine POI mehr erwartet
            self._sessions.set(session.user_id, session)
            final = self._finalize_route(session)
            hint = (
                f"Keinen '{label}' innerhalb von "
                f"{self._max_detour // 60} Min Umweg gefunden. "
                "Route trotzdem geplant:\n\n"
            )
            return CommandResult(
                command=final.command,
                success=final.success,
                text=hint + (final.text or ""),
            )
        # POI-Pick als naechster Turn
        self._sessions.set(session.user_id, session)
        return self._poi_pick_response(session)

    def _finalize_route(self, session: RouteSession) -> CommandResult:
        """Komplette Route ohne weitere Disambig -- Antwort + Maps-Link."""
        people = session.people_stops()
        # Destination ist der LETZTE People-Stop in der Liste fuer den
        # Phase-2-Routing-Call (people_stops enthaelt nur Waypoints,
        # nicht Destination). Wir haengen ggf. chosen_poi ans Ende der
        # Waypoints.
        origin_stop = Stop(
            address=session.origin.address or "",
            label=session.origin.label,
        )
        destination_stop = Stop(
            address=session.destination.address or "",
            label=session.destination.label,
        )
        people_waypoints = [
            Stop(address=s.address or "", label=s.label) for s in people
        ]

        try:
            if session.chosen_poi is not None:
                final = self._planner.finalize_with_poi(
                    origin=origin_stop,
                    people_stops=people_waypoints,
                    destination=destination_stop,
                    chosen_poi=session.chosen_poi,
                )
            else:
                # plan() ohne POI-Request -- nur Phase-1-Routing.
                planned = self._planner.plan(
                    origin=origin_stop,
                    people_stops=people_waypoints,
                    destination=destination_stop,
                    poi_request=None,
                )
                final = planned.route
        except RouteError as exc:
            self._sessions.clear(session.user_id)
            return CommandResult(
                command="multi_stop_route",
                success=True,
                text=user_friendly_error(exc, "Routenberechnung"),
            )

        link = self._link.build_multi_stop_link(
            origin=LinkStop(
                address=origin_stop.address,
                label=origin_stop.label,
            ),
            waypoints=[
                LinkStop(address=s.address, label=s.label)
                for s in final.ordered_stops[1:-1]
            ],
            destination=LinkStop(
                address=destination_stop.address,
                label=destination_stop.label,
            ),
        )

        text = self._format_final_response(session, final, link)
        self._sessions.clear(session.user_id)
        return CommandResult(
            command="multi_stop_route",
            success=True,
            text=text,
        )

    def _format_final_response(
        self,
        session: RouteSession,
        final: Any,  # MultiStopRouteResult; Any spart Import-Schleife
        link: str,
    ) -> str:
        """Antwort gemaess Konzept §"Antwort-Format" zusammenbauen."""
        lines = ["Route geplant:"]
        stops = final.ordered_stops
        for i in range(len(stops) - 1):
            a = stops[i].label or stops[i].address
            b = stops[i + 1].label or stops[i + 1].address
            extra = ""
            if (
                session.chosen_poi is not None
                and i + 1 == len(stops) - 2
                and stops[i + 1].label == session.chosen_poi.name
            ):
                # Vor dem POI-Stop: zeige Detour-Hint
                detour_min = session.chosen_poi.detour_seconds // 60
                extra = f" (+{detour_min} Min Umweg)"
            lines.append(f"  {i + 1}. {a} -> {b}{extra}")

        lines.append("")
        lines.append(
            f"Gesamt: {final.total_distance_text}, ca. {final.total_duration_text}",
        )

        if session.arrival_time_text:
            arrival = parse_arrival_time(session.arrival_time_text)
            if arrival is not None:
                departure = (
                    arrival
                    - timedelta(seconds=final.total_duration_seconds)
                    - timedelta(minutes=_DEPARTURE_BUFFER_MINUTES)
                )
                lines.append(
                    self._format_departure_line(arrival, departure),
                )

        lines.append("")
        lines.append(f"-> {link}")
        return "\n".join(lines)

    @staticmethod
    def _format_departure_line(
        arrival: datetime,
        departure: datetime,
    ) -> str:
        return (
            f"Abfahrt: spaetestens {departure.strftime('%H:%M')} "
            f"({_DEPARTURE_BUFFER_MINUTES} Min Puffer fuer Ankunft "
            f"{arrival.strftime('%H:%M')})"
        )


# ---------------------------------------------------------------------------
# Plugin-Manifest
# ---------------------------------------------------------------------------


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    if (
        ctx.multi_stop_route_planner is None
        or ctx.contact_store is None
        or ctx.route_session_store is None
        or ctx.anthropic_client is None
    ):
        return None
    from elder_berry.tools.maps_link_builder import MapsLinkBuilder
    from elder_berry.tools.route_intent_parser import RouteIntentParser

    return MultiStopRouteCommandHandler(
        intent_parser=RouteIntentParser(ctx.anthropic_client),
        route_planner=ctx.multi_stop_route_planner,
        contact_store=ctx.contact_store,
        session_store=ctx.route_session_store,
        link_builder=MapsLinkBuilder(),
        default_user_id=ctx.default_user_id,
    )


PLUGIN = CommandPlugin(
    name="multi_stop_route",
    priority=75,  # zwischen contacts (72) und route (76). niedriger = frueher.
    category="web",
    help_section=HELP_SECTION_MULTI_STOP_ROUTE,
    factory=_factory,
)
