"""NearbyPlaceSearch -- distanz-korrekte, gefilterte Umkreissuche (Phase 97).

EIN Such-Endpoint: ``places:searchText`` (Places API New), vom LLM
angereichert. Der Wert gegenueber Googles Consumer-UI sind die zwei Dinge,
die der Code GARANTIERT (keine LLM-Varianz im sicherheitsrelevanten Filter):

1. Nah-zuerst: ``rankPreference=DISTANCE`` + clientseitiger Haversine-Cap
   auf den Radius (``searchText`` kann nur einen WEICHEN ``locationBias``-
   Kreis, keinen harten -- daher der Client-Cap, Konzept §4.2).
2. Kategorie-Filter: optionaler ``includedType`` (+``strictTypeFiltering``)
   serverseitig PLUS clientseitiger ``exclude_types``-Filter (§4.1).

Der Standort kommt als Freitext -> ``GoogleGeocoder`` liefert den
Distanz-Bezugspunkt. ``GeocoderConfigError`` wird NICHT geschluckt
(R2-C3): Auth/Quota ist ein Dienstfehler, kein "Ort nicht gefunden".

Synchron via ``httpx.Client`` -- gleiches Muster wie
``GoogleMapsRoutePlanner`` (Header-FieldMask, ``X-Goog-Api-Key``).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import httpx

from elder_berry.tools.google_geocoder import GoogleGeocoder, LatLng
from elder_berry.tools.place_types import (
    expand_exclude_types,
    normalize_included_type,
    normalize_travel_mode,
)

logger = logging.getLogger(__name__)

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

# Radius je Reisemodus (Meter, Luftlinie) -- grobe "in ~1 h erreichbar"
# (Konzept §4.2). Keys MUESSEN VALID_TRAVEL_MODES entsprechen (Test).
RADIUS_BY_MODE: dict[str, int] = {
    "walking": 6_000,
    "transit": 15_000,
    "bicycling": 15_000,
    "driving": 40_000,
}

# searchText akzeptiert fuer den locationBias-Kreis max. 50.000 m -- die
# 0-Treffer-Weitung MUSS hierauf geclampt werden, sonst INVALID_REQUEST
# (Codex #2). Praktisch weitet "driving" also nur 40 -> 50 km.
_MAX_BIAS_RADIUS_M = 50_000

# Puffer fuer den Client-Filter: lieber 20 holen und clientseitig kappen,
# als per Pagination nachladen (jede Folgeseite = eigener Call, YAGNI/Codex #6).
_PAGE_SIZE = 20

# Vollstaendige FieldMask (Codex #5 + R2-C4). rating + currentOpeningHours
# loesen die Text-Search-Enterprise-SKU aus (akzeptiert, Konzept §7).
_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.types,places.primaryType,places.currentOpeningHours,"
    "places.rating,places.attributions,places.businessStatus"
)

# Places-businessStatus-Werte, die ein totes/geschlossenes Listing markieren.
_CLOSED_PERMANENTLY = "CLOSED_PERMANENTLY"
_CLOSED_TEMPORARILY = "CLOSED_TEMPORARILY"

_EARTH_RADIUS_M = 6_371_000.0


class NearbyPlaceError(Exception):
    """Fehler der Umkreissuche (Places-API-Status, HTTP-Fehler)."""


class LocationNotFoundError(Exception):
    """Der Standort-Freitext war nicht geocodebar (Geocoder ZERO_RESULTS).

    Bewusst getrennt vom leeren Ergebnis: ohne Geocode-Zentrum gibt es nichts
    zu weiten/zu zeigen -- der Handler fragt nach einem korrigierten Ort,
    statt "nichts in der Naehe gefunden" zu melden (Codex-Review PR #302).
    """

    def __init__(self, location_text: str) -> None:
        super().__init__(f"Ort nicht gefunden: {location_text}")
        self.location_text = location_text


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NearbyQuery:
    """Vollstaendig aufgeloeste Suchanfrage -- ``search()`` nimmt NUR das."""

    subject: str
    """Worum es dem Nutzer geht (fuer das Echo "Ich suche {subject} ...")."""
    search_query: str
    """Freitext fuer ``textQuery`` (traegt die Nuance, z.B. "Rockerbar")."""
    included_type: str | None
    """Table-A-validierter Typ oder ``None`` (dann nur Freitext)."""
    exclude_types: tuple[str, ...]
    """Clientseitig gegen ``types``/``primaryType`` angewandt."""
    location_text: str
    """Standort-Freitext -> Geocode-Bezugspunkt."""
    travel_mode: str
    """``driving``|``walking``|``bicycling``|``transit`` -> Radius."""
    open_now: bool = True
    """CLIENT-Flag (NICHT als ``openNow`` an die API, Codex #1)."""


@dataclass(frozen=True)
class NearbyQueryDraft:
    """Zwischenstand bis zur Disambiguierung (R2-C4/Codex #4).

    ``location_text``/``travel_mode`` optional, weil sie per Rueckfrage
    nachkommen koennen. ``subject``/``search_query``/``included_type``/
    ``exclude_types`` bleiben dabei erhalten (geht NICHT verloren).
    """

    subject: str
    search_query: str
    included_type: str | None
    exclude_types: tuple[str, ...]
    location_text: str | None
    travel_mode: str | None
    open_now: bool = True

    def to_query(self) -> NearbyQuery | None:
        """Vollstaendige + valide ``NearbyQuery`` oder ``None`` (-> Rueckfrage).

        ``None`` solange ``location_text``/``travel_mode`` fehlen ODER
        ``travel_mode`` nach ``normalize_travel_mode()`` nicht im Vokabular
        liegt (R2-C2: Synonyme wie car/foot/zu_fuss -> driving/walking;
        Unbekanntes -> None, KEIN spaeterer KeyError). ``included_type``
        wird via ``normalize_included_type()`` gegen Table-A geprueft;
        unbekannt -> ``None`` (R2-C1, reiner Freitext + exclude_types).
        """
        if not self.location_text or not self.location_text.strip():
            return None
        mode = normalize_travel_mode(self.travel_mode)
        if mode is None:
            return None
        return NearbyQuery(
            subject=self.subject,
            search_query=self.search_query,
            included_type=normalize_included_type(self.included_type),
            exclude_types=self.exclude_types,
            location_text=self.location_text,
            travel_mode=mode,
            open_now=self.open_now,
        )


@dataclass(frozen=True)
class PlaceCandidate:
    """Ein Treffer der Umkreissuche."""

    name: str
    address: str
    place_id: str
    rating: float | None
    open_now: bool | None
    """``None`` = unbekannt -> NICHT hart filtern (Codex #1)."""
    distance_m: int
    """Luftlinie vom Geocode-Punkt (Haversine)."""
    types: tuple[str, ...]
    primary_type: str | None
    attributions: tuple[str, ...]
    """Zurueckgegebene Places-Attributionen (R2-C4, Pflicht-Anzeige)."""
    business_status: str | None = None
    """``OPERATIONAL`` / ``CLOSED_TEMPORARILY`` / ``CLOSED_PERMANENTLY`` /
    ``None`` (unbekannt). Tote Listings werden gefiltert (Codex PR #302)."""


# ---------------------------------------------------------------------------
# Suche
# ---------------------------------------------------------------------------


class NearbyPlaceSearch:
    """Umkreissuche um einen Geocode-Punkt, distanz-korrekt + gefiltert."""

    def __init__(
        self,
        api_key: str,
        geocoder: GoogleGeocoder,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key darf nicht leer sein")
        self._api_key = api_key
        self._geocoder = geocoder
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def search(
        self,
        query: NearbyQuery,
        *,
        max_results: int = 20,
    ) -> list[PlaceCandidate]:
        """Geocode -> searchText -> Client-Cap/Filter/Sort -> Top-N.

        Returns:
            Bis zu ``max_results`` Kandidaten, distanz-sortiert. Leer,
            wenn der Ort nicht geocodebar ist (ZERO_RESULTS) oder nichts
            im (geweiteten) Radius liegt.

        Raises:
            LocationNotFoundError: Standort nicht geocodebar (ZERO_RESULTS).
            GeocoderConfigError: Geocoder-Auth/Quota (durchgereicht, R2-C3).
            NearbyPlaceError: Places-API-/HTTP-Fehler.
        """
        # 1. Geocode. None (ZERO_RESULTS) -> LocationNotFoundError (KEIN
        #    leeres Ergebnis: ohne Zentrum hilft Weiten/Anzeigen nicht);
        #    GeocoderConfigError NICHT fangen -> Dienstfehler (R2-C3).
        center = self._geocoder.geocode(query.location_text)
        if center is None:
            logger.info("Nearby: Ort '%s' nicht geocodebar", query.location_text)
            raise LocationNotFoundError(query.location_text)

        # 2. travel_mode ist durch to_query() Whitelist-validiert -> kein KeyError.
        radius = RADIUS_BY_MODE[query.travel_mode]

        # 3. + 4. Suche + Client-Filter.
        results = self._search_filtered(query, center, radius)

        # 0-Treffer: einmal weiten (Faktor 2, geclampt auf 50 km) + Retry.
        # BEWUSSTE GRENZE (Codex-Review PR #302, Konzept §8/§11.6): wenn die
        # ERSTE Seite vollstaendig wegfiltert (typloser Dichtefall, z.B.
        # "Shisha-Zubehoer" mit lauter bar-Treffern), paginieren wir NICHT
        # ueber nextPageToken (jede Folgeseite = eigener billbarer Call,
        # YAGNI/Kosten). Stattdessen pageSize=20-Puffer + Weitung; wenn das im
        # Smoketest nicht reicht -> Eskalation auf searchNearby+excludedTypes
        # (Plan B), das serverseitig vorfiltert.
        if not results:
            widened = min(radius * 2, _MAX_BIAS_RADIUS_M)
            if widened > radius:
                logger.info("Nearby: 0 Treffer in %d m -> weiten auf %d m", radius, widened)
                results = self._search_filtered(query, center, widened)

        # 5. Sort + Top-N.
        results.sort(key=lambda c: c.distance_m)
        return results[:max_results]

    def close(self) -> None:
        """HTTP-Client schliessen, falls wir ihn besitzen."""
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _search_filtered(
        self,
        query: NearbyQuery,
        center: LatLng,
        radius: int,
    ) -> list[PlaceCandidate]:
        """Ein searchText-Call + clientseitige PFLICHT-Filter (Bias ist weich)."""
        raw_places = self._call_search_text(query, center, radius)
        kept: list[PlaceCandidate] = []
        # Ausschluss um bekannte Unter-/Geschwistertypen erweitern (z.B.
        # bar -> hookah_bar), damit der Kategorie-Filter nicht an exakten
        # Type-Strings vorbeilaeuft (Codex-Review PR #302).
        exclude = set(expand_exclude_types(query.exclude_types))
        for place in raw_places:
            candidate = self._to_candidate(place, center)
            if candidate is None:
                continue
            if candidate.distance_m > radius:  # harter Cap (Haversine)
                continue
            if self._is_excluded(candidate, exclude):
                continue
            if self._is_dead_listing(candidate, query.open_now):
                continue
            if query.open_now and candidate.open_now is False:
                # bekannt geschlossen raus; unbekannt (None) BLEIBT (Codex #1).
                continue
            kept.append(candidate)
        return kept

    @staticmethod
    def _is_dead_listing(candidate: PlaceCandidate, open_now: bool) -> bool:
        """Permanent/temporaer geschlossene Listings (Codex PR #302).

        ``CLOSED_PERMANENTLY`` ist immer tot (raus). ``CLOSED_TEMPORARILY``
        nur raus, wenn der Nutzer aktuell Geoeffnetes will (``open_now``) --
        sonst koennte es wieder aufmachen. So rutschen tote Eintraege nicht
        durch, obwohl ``currentOpeningHours`` fehlt (= open_now unbekannt).
        """
        if candidate.business_status == _CLOSED_PERMANENTLY:
            return True
        if open_now and candidate.business_status == _CLOSED_TEMPORARILY:
            return True
        return False

    def _call_search_text(
        self,
        query: NearbyQuery,
        center: LatLng,
        radius: int,
    ) -> list[dict[str, Any]]:
        """POST places:searchText, liefert die rohe ``places``-Liste."""
        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _FIELD_MASK,
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "textQuery": query.search_query,
            # Hinweis: places:searchText (New) nutzt pageSize (Konzept §4,
            # Codex #6). Der aeltere GoogleMapsRoutePlanner verwendet noch
            # maxResultCount -- der Live-Smoketest (Lera) bestaetigt das Feld.
            "pageSize": _PAGE_SIZE,
            "rankPreference": "DISTANCE",
            "locationBias": {
                "circle": {
                    "center": {"latitude": center.lat, "longitude": center.lng},
                    "radius": float(radius),
                },
            },
            # KEIN openNow an die API (Codex #1) -- Client-Filter, unbekannt bleibt.
        }
        if query.included_type:  # bereits Table-A-validiert (R2-C1)
            body["includedType"] = query.included_type
            body["strictTypeFiltering"] = True

        resp = self._client.post(PLACES_URL, json=body, headers=headers)
        if resp.status_code == 429:
            raise NearbyPlaceError("Places API: Rate-Limit erreicht")
        if resp.status_code in (401, 403):
            raise NearbyPlaceError(
                f"Places API: API-Key ungueltig oder gesperrt ({resp.status_code})",
            )
        if resp.status_code == 400:
            raise NearbyPlaceError("Places API: ungueltige Anfrage (400)")
        if resp.status_code >= 400:
            # 500/502/503 als NearbyPlaceError, NICHT als roher
            # httpx.HTTPStatusError -- sonst generischer Bridge-Fehler bzw.
            # vom Intercept geschluckt (Codex-Review PR #302).
            raise NearbyPlaceError(f"Places API: HTTP {resp.status_code}")
        data = resp.json()
        places = data.get("places") or []
        return [p for p in places if isinstance(p, dict)]

    def _to_candidate(
        self,
        place: dict[str, Any],
        center: LatLng,
    ) -> PlaceCandidate | None:
        """Rohes Place-Dict -> ``PlaceCandidate`` (mit Distanz). None = unbrauchbar."""
        name = self._display_name(place)
        if not name:
            return None
        location = place.get("location") or {}
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is None or lng is None:
            # Ohne Koordinaten keine Distanz -> der Kernwert fehlt; raus.
            logger.debug("Nearby: Treffer '%s' ohne location -> verworfen", name)
            return None

        rating_raw = place.get("rating")
        rating = float(rating_raw) if rating_raw is not None else None

        opening = place.get("currentOpeningHours") or {}
        open_now = opening.get("openNow")
        open_now_bool = bool(open_now) if isinstance(open_now, bool) else None

        types = tuple(str(t) for t in (place.get("types") or []))
        primary = place.get("primaryType")
        primary_type = str(primary) if primary else None

        status = place.get("businessStatus")
        business_status = str(status) if status else None

        return PlaceCandidate(
            name=name,
            address=str(place.get("formattedAddress", "")),
            place_id=str(place.get("id", "")),
            rating=rating,
            open_now=open_now_bool,
            distance_m=int(_haversine_m(center, float(lat), float(lng))),
            types=types,
            primary_type=primary_type,
            attributions=self._attributions(place),
            business_status=business_status,
        )

    @staticmethod
    def _is_excluded(candidate: PlaceCandidate, exclude: set[str]) -> bool:
        """``True`` wenn primaryType ODER irgendein type in der Ausschlussliste."""
        if not exclude:
            return False
        if candidate.primary_type and candidate.primary_type.lower() in exclude:
            return True
        return any(t.lower() in exclude for t in candidate.types)

    @staticmethod
    def _display_name(place: dict[str, Any]) -> str:
        """Liest ``displayName.text`` (Fallback leerer String)."""
        display = place.get("displayName") or {}
        if isinstance(display, dict):
            return str(display.get("text", "")).strip()
        return ""

    @staticmethod
    def _attributions(place: dict[str, Any]) -> tuple[str, ...]:
        """Extrahiert die ``attributions``-Provider-Strings (R2-C4).

        Places liefert ``attributions`` als Liste von Objekten
        (``provider``/``providerUri``). Wir behalten die lesbaren
        Provider-Namen; reine Strings werden ebenfalls akzeptiert.
        """
        raw = place.get("attributions") or []
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                provider = str(item.get("provider", "")).strip()
                if provider:
                    out.append(provider)
            elif isinstance(item, str) and item.strip():
                out.append(item.strip())
        return tuple(out)


def _haversine_m(center: LatLng, lat: float, lng: float) -> float:
    """Luftlinie in Metern zwischen ``center`` und (lat, lng)."""
    lat1 = math.radians(center.lat)
    lat2 = math.radians(lat)
    dlat = math.radians(lat - center.lat)
    dlng = math.radians(lng - center.lng)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))
