"""GoogleMapsRoutePlanner -- Multi-Stop-Routing + POI-Suche entlang
einer Route.

Phase 92 (E1): Konkrete Klasse, kein ABC. Begruendung im Konzept
§"Warum kein RouteProvider-Interface" -- bei realistischer Nutzung
(1-2 Anfragen/Monat) lohnt sich keine Provider-Abstraktion. Falls je
ein Wechsel noetig wird, sind die Datacontracts (``Stop``,
``MultiStopRouteResult``, ``POICandidate``, ``PlannedRoute``) bereits
provider-agnostisch.

Kapselt zwei Google-APIs:

- Directions API (v1, Maps Platform): Multi-Waypoint-Routing mit
  ``waypoints=optimize:true``. Liefert ``waypoint_order``, daraus die
  optimierte Reihenfolge ableiten.
- Places API (New, ``places:searchText`` mit
  ``searchAlongRouteParameters``): POI-Suche entlang der Basis-Route.
  Liefert ``routingSummaries`` mit Detour-Sekunden pro POI.

Beide Calls synchron via ``httpx.Client`` (passt zum
CommandHandler-Pattern, vgl. RoutePlanner aus Phase 43).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

# Default-Cap fuer POI-Ergebnisse, die der User in der Liste sieht.
_POI_RESULT_CAP = 5

# Field-Mask fuer Places API (NEW). Ohne diese koennten wir die
# Antwort nicht filtern -- die API liefert sonst alle moeglichen Felder
# und das ist teurer und wir kriegen nicht die routingSummaries.
_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.rating,routingSummaries"
)


class RouteError(Exception):
    """Fehler bei der Multi-Stop-Routenberechnung (API-Status != OK,
    leere Routes, ungueltige Konfiguration).

    Eigene Klasse statt aus ``route_planner.py``-Importieren, damit
    Single- und Multi-Stop-Fehlerpfade unabhaengig bleiben (der
    Single-Stop-Handler reicht ``RouteError`` an ``user_friendly_error``
    durch -- der Multi-Stop-Handler hat dafuer eigene Antwort-Texte).
    """


@dataclass(frozen=True)
class Stop:
    """Ein Stop in der Route (Adresse + Anzeigename)."""

    address: str
    label: str = ""


@dataclass(frozen=True)
class MultiStopRouteResult:
    """Ergebnis einer Multi-Stop-Routenabfrage."""

    ordered_stops: tuple[Stop, ...]
    """Reihenfolge nach Optimierung (origin + people_stops + destination).
    Origin und Destination werden NIE getauscht; nur die Waypoints
    dazwischen werden sortiert."""

    total_duration_seconds: int
    total_duration_text: str
    """Lesbar, z.B. ``"1 Stunde 12 Minuten"``."""

    total_distance_text: str
    """Lesbar, z.B. ``"48,2 km"``."""

    leg_durations_seconds: tuple[int, ...]
    """Pro Leg eine Dauer (len = len(ordered_stops) - 1)."""

    encoded_polyline: str
    """Overview-Polyline der Gesamtroute. Wird fuer die POI-Search-
    Along-Route gebraucht."""


@dataclass(frozen=True)
class POICandidate:
    """Ein POI-Kandidat entlang einer Route."""

    name: str
    """``"Kaufland Gruenau"``."""
    address: str
    place_id: str
    """Google-Place-ID, fuer den finalen Routing-Call wiederverwendet."""
    detour_seconds: int
    """Umweg gegenueber Direktroute in Sekunden."""
    rating: float | None
    """Optional, Google-Rating 1-5 oder ``None``."""


@dataclass(frozen=True)
class POIRequest:
    """Anfrage-Parameter fuer die POI-Suche."""

    category: str
    """Freitext fuer ``textQuery`` (z.B. ``"Kaufland"``,
    ``"Supermarkt"``, ``"Tankstelle"``)."""
    name_hint: str | None = None
    """Optionaler Filter -- nur POIs, deren Name den Hint enthaelt
    (case-insensitive). Bei Sonnet-extracted ``Kaufland`` ist
    ``category=Kaufland`` und ``name_hint=None`` ueblich; bei
    ``Supermarkt`` mit Marken-Hint waere ``category="Supermarkt"``
    und ``name_hint="Lidl"``."""
    max_results: int = 10
    """Cap fuer die Places-Antwort (Pre-Filter)."""
    max_detour_seconds: int = 600
    """Filter: nur POIs mit Umweg <= dieser Schwelle. Default 10 Min."""


@dataclass(frozen=True)
class PlannedRoute:
    """Aggregat aus Basis-Route + POI-Kandidaten."""

    route: MultiStopRouteResult
    poi_candidates: tuple[POICandidate, ...] = field(default_factory=tuple)
    """Leer wenn ``POIRequest`` nicht gesetzt war oder keine POIs
    in Reichweite gefunden wurden."""


class GoogleMapsRoutePlanner:
    """Multi-Stop-Routing via Google Directions + POI via Places API v1."""

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key darf nicht leer sein")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        origin: Stop,
        people_stops: list[Stop],
        destination: Stop,
        poi_request: POIRequest | None = None,
    ) -> PlannedRoute:
        """Zwei-Phasen-Routing.

        Schritt 1: Basis-Route (origin -> people_stops -> destination),
        optimiert via Directions API (``waypoints=optimize:true``).
        Origin und Destination werden NIE vertauscht.

        Schritt 2 (nur wenn ``poi_request``): POI-Suche entlang der
        Basis-Route via Places API v1
        (``searchAlongRouteParameters``). Detour-Filter
        ``<= max_detour_seconds``, sortiert aufsteigend, max 5
        Kandidaten.

        Raises:
            RouteError: API-Status != OK oder leere Route.
        """
        route = self._call_directions(origin, people_stops, destination)
        if poi_request is None:
            return PlannedRoute(route=route)
        candidates = self._call_places_along_route(
            poi_request,
            route.encoded_polyline,
        )
        return PlannedRoute(route=route, poi_candidates=candidates)

    def finalize_with_poi(
        self,
        origin: Stop,
        people_stops: list[Stop],
        destination: Stop,
        chosen_poi: POICandidate,
    ) -> MultiStopRouteResult:
        """Finale Route mit POI als zusaetzlichem Waypoint.

        Der POI wird ans ENDE der people_stops gehaengt; Google
        optimiert dann erneut. ``optimize:true`` ist gesetzt, damit
        die finale Reihenfolge fahrzeit-optimal ist."""
        poi_stop = Stop(
            address=chosen_poi.address or f"place_id:{chosen_poi.place_id}",
            label=chosen_poi.name,
        )
        extended = [*people_stops, poi_stop]
        return self._call_directions(origin, extended, destination)

    def close(self) -> None:
        """HTTP-Client schliessen, falls wir ihn besitzen."""
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Provider-spezifische Helfer
    # ------------------------------------------------------------------

    def _call_directions(
        self,
        origin: Stop,
        waypoints: list[Stop],
        destination: Stop,
    ) -> MultiStopRouteResult:
        """Directions-API-Call (synchron)."""
        params: dict[str, str] = {
            "origin": origin.address,
            "destination": destination.address,
            "key": self._api_key,
            "language": "de",
            "units": "metric",
            "mode": "driving",
        }
        if waypoints:
            wp_addresses = [wp.address for wp in waypoints]
            params["waypoints"] = "optimize:true|" + "|".join(wp_addresses)

        resp = self._client.get(DIRECTIONS_URL, params=params)
        resp.raise_for_status()
        return self._parse_directions(resp.json(), origin, waypoints, destination)

    def _parse_directions(
        self,
        data: dict[str, Any],
        origin: Stop,
        waypoints: list[Stop],
        destination: Stop,
    ) -> MultiStopRouteResult:
        """Parst die Directions-Response und wendet ``waypoint_order`` an."""
        status = data.get("status", "UNKNOWN")
        if status != "OK":
            raise RouteError(f"Directions API: {status}")
        routes = data.get("routes")
        if not routes:
            raise RouteError("Directions API: Keine Route gefunden")

        route = routes[0]
        legs = route.get("legs", [])
        if not legs:
            raise RouteError("Directions API: Keine Legs in der Route")

        # Optimierte Waypoint-Reihenfolge anwenden (origin + dest bleiben).
        order = route.get("waypoint_order") or list(range(len(waypoints)))
        ordered_waypoints = [waypoints[i] for i in order]
        ordered_stops = (origin, *ordered_waypoints, destination)

        # Leg-Dauern und Summen aus den einzelnen Legs.
        leg_secs = tuple(int(leg["duration"]["value"]) for leg in legs)
        total_secs = sum(leg_secs)
        total_meters = sum(int(leg["distance"]["value"]) for leg in legs)

        # Polyline aus overview_polyline (oder leer falls fehlt).
        overview = route.get("overview_polyline") or {}
        polyline = str(overview.get("points", ""))

        return MultiStopRouteResult(
            ordered_stops=ordered_stops,
            total_duration_seconds=total_secs,
            total_duration_text=self._format_duration(total_secs),
            total_distance_text=self._format_distance(total_meters),
            leg_durations_seconds=leg_secs,
            encoded_polyline=polyline,
        )

    def _call_places_along_route(
        self,
        poi_request: POIRequest,
        encoded_polyline: str,
    ) -> tuple[POICandidate, ...]:
        """Places-API-Call (POST) mit ``searchAlongRouteParameters``."""
        if not encoded_polyline:
            logger.warning(
                "POI-Search uebersprungen: encoded_polyline ist leer",
            )
            return ()

        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _PLACES_FIELD_MASK,
            "Content-Type": "application/json",
        }
        body = {
            "textQuery": poi_request.category,
            "searchAlongRouteParameters": {
                "polyline": {"encodedPolyline": encoded_polyline},
            },
            "maxResultCount": poi_request.max_results,
        }

        resp = self._client.post(PLACES_URL, json=body, headers=headers)
        if resp.status_code == 429:
            raise RouteError("Places API: Rate-Limit erreicht")
        if resp.status_code in (401, 403):
            raise RouteError(
                f"Places API: API-Key ungueltig oder gesperrt ({resp.status_code})",
            )
        resp.raise_for_status()
        return self._parse_places(resp.json(), poi_request)

    def _parse_places(
        self,
        data: dict[str, Any],
        poi_request: POIRequest,
    ) -> tuple[POICandidate, ...]:
        """Parst die Places-Response, filtert + sortiert nach Detour."""
        places = data.get("places") or []
        if not places:
            return ()
        # routingSummaries ist parallel zu places (gleicher Index).
        summaries = data.get("routingSummaries") or []

        candidates: list[POICandidate] = []
        for idx, place in enumerate(places):
            name = self._extract_display_name(place)
            if not name:
                continue
            if poi_request.name_hint and (
                poi_request.name_hint.lower() not in name.lower()
            ):
                continue
            detour = self._extract_detour_seconds(summaries, idx)
            if detour is None:
                continue
            if detour > poi_request.max_detour_seconds:
                continue
            rating = place.get("rating")
            candidates.append(
                POICandidate(
                    name=name,
                    address=str(place.get("formattedAddress", "")),
                    place_id=str(place.get("id", "")),
                    detour_seconds=detour,
                    rating=float(rating) if rating is not None else None,
                ),
            )

        candidates.sort(key=lambda c: c.detour_seconds)
        return tuple(candidates[:_POI_RESULT_CAP])

    # ------------------------------------------------------------------
    # Reine Hilfsfunktionen
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_display_name(place: dict[str, Any]) -> str:
        """Liest ``places.displayName.text`` oder Fallback auf ``name``."""
        display = place.get("displayName") or {}
        if isinstance(display, dict):
            text = display.get("text")
            if text:
                return str(text)
        return str(place.get("name") or "")

    @staticmethod
    def _extract_detour_seconds(
        summaries: list[dict[str, Any]],
        idx: int,
    ) -> int | None:
        """Liest ``routingSummaries[idx].legs[0].duration`` als Sekunden.

        Google liefert die Duration als String mit Suffix ``s``
        (z.B. ``"312s"``). Falls anders/fehlt -> ``None``, der POI
        wird verworfen (kein Detour-Wert = kein Vergleich moeglich).
        """
        if idx >= len(summaries):
            return None
        summary = summaries[idx] or {}
        legs = summary.get("legs") or []
        if not legs:
            return None
        duration = legs[0].get("duration")
        if duration is None:
            return None
        try:
            if isinstance(duration, str):
                return int(duration.rstrip("s"))
            return int(duration)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _format_duration(seconds: int) -> str:
        """Lesbarer deutscher Dauer-String."""
        if seconds < 60:
            return f"{seconds} Sekunden"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} Minuten"
        hours = minutes // 60
        rem_min = minutes % 60
        h_label = "Stunde" if hours == 1 else "Stunden"
        if rem_min == 0:
            return f"{hours} {h_label}"
        return f"{hours} {h_label} {rem_min} Minuten"

    @staticmethod
    def _format_distance(meters: int) -> str:
        """Lesbarer deutscher Distanz-String."""
        if meters < 1000:
            return f"{meters} m"
        km = meters / 1000.0
        return f"{km:.1f} km".replace(".", ",")
