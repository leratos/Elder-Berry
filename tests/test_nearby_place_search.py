"""Tests fuer NearbyPlaceSearch -- distanz-korrekte, gefilterte Umkreissuche.

Phase 97 (E1). Alle Tests gegen Mock-httpx + Fake-Geocoder; Live-Calls
gegen die echte API macht Lera vor dem PR (Quota-bewusst).

Schwerpunkte (Konzept §6): searchText-Body (incl. FieldMask, KEIN openNow),
Client-Radius-Cap + Weitung-Clamp (Codex #2), Typ-/open_now-Filter (Codex #1),
Distanz-Sort, 0-Treffer-Retry, GeocoderConfigError-Durchreichen (R2-C3),
Draft.to_query()-Validierung (R2-C1/C2).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from elder_berry.tools.google_geocoder import GeocoderConfigError, LatLng
from elder_berry.tools.nearby_place_search import (
    PLACES_URL,
    NearbyPlaceError,
    NearbyPlaceSearch,
    NearbyQuery,
    NearbyQueryDraft,
)

API_KEY = "test-key"
CENTER = LatLng(lat=51.34, lng=12.37)  # Leipzig


# ---------------------------------------------------------------------------
# Fakes / Helfer
# ---------------------------------------------------------------------------


class _FakeGeocoder:
    def __init__(
        self,
        result: LatLng | None = CENTER,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[str] = []

    def geocode(self, location_text: str) -> LatLng | None:
        self.calls.append(location_text)
        if self._error is not None:
            raise self._error
        return self._result


def _place(
    name: str,
    lat: float,
    lng: float,
    *,
    place_id: str = "p",
    rating: float | None = None,
    open_now: bool | None = None,
    types: tuple[str, ...] = (),
    primary: str | None = None,
    attributions: list[Any] | None = None,
) -> dict[str, Any]:
    place: dict[str, Any] = {
        "id": place_id,
        "displayName": {"text": name},
        "formattedAddress": f"{name}-Adr",
        "location": {"latitude": lat, "longitude": lng},
        "types": list(types),
    }
    if rating is not None:
        place["rating"] = rating
    if primary is not None:
        place["primaryType"] = primary
    if open_now is not None:
        place["currentOpeningHours"] = {"openNow": open_now}
    if attributions is not None:
        place["attributions"] = attributions
    return place


def _body(*places: dict[str, Any]) -> dict[str, Any]:
    return {"places": list(places)}


def _make_client(*responses: tuple[int, dict[str, Any]]) -> MagicMock:
    """Mock-httpx.Client; verbraucht ``responses`` der Reihe nach pro POST.

    Gepostete Bodies/Header werden ueber ``client.post.call_args_list``
    inspiziert (siehe ``_sent_json`` / ``_sent_headers`` / ``_sent_url``).
    """
    client = MagicMock(spec=httpx.Client)
    seq = list(responses) or [(200, _body())]

    def _post(url: str, json: dict[str, Any], headers: dict[str, str]) -> MagicMock:
        status, payload = seq.pop(0) if seq else (200, _body())
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status
        resp.json.return_value = payload
        if status >= 400 and status not in (400, 401, 403, 429):
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "boom", request=MagicMock(), response=resp,
            )
        else:
            resp.raise_for_status.return_value = None
        return resp

    client.post.side_effect = _post
    return client


def _sent_json(client: MagicMock, idx: int = 0) -> dict[str, Any]:
    return client.post.call_args_list[idx].kwargs["json"]


def _sent_headers(client: MagicMock, idx: int = 0) -> dict[str, str]:
    return client.post.call_args_list[idx].kwargs["headers"]


def _sent_url(client: MagicMock, idx: int = 0) -> str:
    return client.post.call_args_list[idx].args[0]


def _query(
    *,
    search_query: str = "Rockerbar",
    included_type: str | None = None,
    exclude_types: tuple[str, ...] = (),
    travel_mode: str = "driving",
    open_now: bool = True,
) -> NearbyQuery:
    return NearbyQuery(
        subject="Rockerbar",
        search_query=search_query,
        included_type=included_type,
        exclude_types=exclude_types,
        location_text="Karl-Liebknecht-Str. 12, Leipzig",
        travel_mode=travel_mode,
        open_now=open_now,
    )


# Koordinaten in definierten Distanzen von CENTER (1 Grad Lat ~ 111 km):
_NEAR = (51.35, 12.38)        # ~1.3 km
_MID = (51.39, 12.40)         # ~5.8 km
_FAR_45KM = (51.745, 12.37)   # ~45 km (innerhalb 50 km, ausserhalb 40 km)
_FAR_60KM = (51.88, 12.37)    # ~60 km


# ---------------------------------------------------------------------------
# Konstruktor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            NearbyPlaceSearch(api_key="", geocoder=_FakeGeocoder())

    def test_close_only_closes_owned_client(self) -> None:
        injected = _make_client()
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=injected)
        search.close()
        injected.close.assert_not_called()


# ---------------------------------------------------------------------------
# searchText-Body (Konzept §6)
# ---------------------------------------------------------------------------


class TestRequestBody:
    def test_core_body_fields_always_present(self) -> None:
        client = _make_client((200, _body(_place("Bar", *_NEAR))))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        search.search(_query())

        body = _sent_json(client)
        assert body["textQuery"] == "Rockerbar"
        assert body["pageSize"] == 20
        assert body["rankPreference"] == "DISTANCE"
        circle = body["locationBias"]["circle"]
        assert circle["center"] == {"latitude": 51.34, "longitude": 12.37}
        assert circle["radius"] == 40000.0  # driving
        # KEIN openNow an die API (Codex #1).
        assert "openNow" not in body

    def test_headers_field_mask_complete(self) -> None:
        client = _make_client((200, _body(_place("Bar", *_NEAR))))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        search.search(_query())

        headers = _sent_headers(client)
        assert headers["X-Goog-Api-Key"] == API_KEY
        mask = headers["X-Goog-FieldMask"]
        for field in (
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.types",
            "places.primaryType",
            "places.currentOpeningHours",
            "places.rating",
            "places.attributions",
        ):
            assert field in mask

    def test_valid_included_type_sends_strict_filter(self) -> None:
        client = _make_client((200, _body(_place("Bar", *_NEAR))))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        search.search(_query(included_type="bar"))

        body = _sent_json(client)
        assert body["includedType"] == "bar"
        assert body["strictTypeFiltering"] is True

    def test_no_included_type_means_text_only(self) -> None:
        client = _make_client((200, _body(_place("Bar", *_NEAR))))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        search.search(_query(included_type=None))

        body = _sent_json(client)
        assert "includedType" not in body
        assert "strictTypeFiltering" not in body

    def test_posts_to_places_url(self) -> None:
        client = _make_client((200, _body(_place("Bar", *_NEAR))))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        search.search(_query())
        assert _sent_url(client) == PLACES_URL


# ---------------------------------------------------------------------------
# Client-Radius-Cap + Weitung (Codex #2)
# ---------------------------------------------------------------------------


class TestRadiusCapAndWiden:
    def test_far_place_beyond_radius_is_dropped(self) -> None:
        client = _make_client(
            (200, _body(_place("Nah", *_NEAR), _place("Fern", *_FAR_60KM))),
            (200, _body(_place("Nah", *_NEAR), _place("Fern", *_FAR_60KM))),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(travel_mode="driving"))  # 40 km
        names = [c.name for c in results]
        assert "Nah" in names
        assert "Fern" not in names  # 60 km > 40 km

    def test_widen_retry_when_zero_results(self) -> None:
        # walking=6km. Erster Call: nur ein 5.8km-Treffer? Nein -- MID ist
        # ~5.8 km, also drin. Nimm FAR-45 (raus bei 6 km) -> 0 Treffer ->
        # weiten auf min(12000,50000)=12000 -> immer noch raus -> bleibt leer.
        far = _place("Fern", *_FAR_45KM)
        client = _make_client((200, _body(far)), (200, _body(far)))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(travel_mode="walking"))
        assert results == []
        # Zwei Calls (Original + Weitung), zweiter Radius geclampt korrekt.
        assert client.post.call_count == 2
        assert _sent_json(client, 1)["locationBias"]["circle"]["radius"] == 12000.0

    def test_driving_widen_clamped_to_50km(self) -> None:
        # driving=40km, 45km-Treffer -> erster Call filtert ihn raus (0) ->
        # weiten auf min(80000,50000)=50000 -> jetzt drin.
        place = _place("Fast", *_FAR_45KM)
        client = _make_client((200, _body(place)), (200, _body(place)))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(travel_mode="driving"))
        assert [c.name for c in results] == ["Fast"]
        assert _sent_json(client, 1)["locationBias"]["circle"]["radius"] == 50000.0


# ---------------------------------------------------------------------------
# Typ- + open_now-Filter (Codex #1)
# ---------------------------------------------------------------------------


class TestClientFilters:
    def test_exclude_by_primary_type(self) -> None:
        client = _make_client(
            (200, _body(
                _place("Eine Bar", *_NEAR, place_id="b", primary="bar", types=("bar",)),
                _place("Ein Laden", *_NEAR, place_id="s", primary="store", types=("store",)),
            )),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(exclude_types=("bar",)))
        names = [c.name for c in results]
        assert names == ["Ein Laden"]  # bar raus, store bleibt

    def test_exclude_bar_also_drops_hookah_bar(self) -> None:
        # Codex-Review PR #302: hookah_bar OHNE generischen bar-Typ -> via
        # expand_exclude_types trotzdem raus.
        client = _make_client(
            (200, _body(
                _place("Shisha Lounge", *_NEAR, place_id="h",
                       primary="hookah_bar", types=("hookah_bar",)),
                _place("Tabakladen", *_NEAR, place_id="t",
                       primary="store", types=("store",)),
            )),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(exclude_types=("bar",)))
        assert [c.name for c in results] == ["Tabakladen"]

    def test_exclude_matches_secondary_type(self) -> None:
        client = _make_client(
            (200, _body(
                _place("Mischladen", *_NEAR, primary="store", types=("store", "bar")),
            )),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(exclude_types=("bar",)))
        assert results == []  # type "bar" in der types-Liste -> raus

    def test_known_closed_dropped_unknown_kept(self) -> None:
        client = _make_client(
            (200, _body(
                _place("Zu", *_NEAR, place_id="zu", open_now=False),
                _place("Auf", *_MID, place_id="auf", open_now=True),
                _place("Unklar", *_NEAR, place_id="un"),  # keine Oeffnungszeiten
            )),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(open_now=True))
        names = {c.name for c in results}
        assert "Zu" not in names         # bekannt geschlossen raus
        assert "Auf" in names
        assert "Unklar" in names         # unbekannt BLEIBT (Codex #1)

    def test_open_now_false_disables_filter(self) -> None:
        client = _make_client(
            (200, _body(_place("Zu", *_NEAR, open_now=False))),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(open_now=False))
        assert [c.name for c in results] == ["Zu"]


# ---------------------------------------------------------------------------
# Parsing / Sort / Top-N / Attribution
# ---------------------------------------------------------------------------


class TestMisc:
    def test_close_owned_client_no_error(self) -> None:
        NearbyPlaceSearch(API_KEY, _FakeGeocoder()).close()

    def test_displayname_as_string_is_dropped(self) -> None:
        bad = {
            "id": "x",
            "displayName": "Roh-String statt Objekt",
            "location": {"latitude": 51.35, "longitude": 12.38},
        }
        client = _make_client((200, _body(bad)), (200, _body(bad)))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        assert search.search(_query()) == []


class TestParsingAndSort:
    def test_sorted_by_distance(self) -> None:
        client = _make_client(
            (200, _body(
                _place("Mid", *_MID, place_id="m"),
                _place("Near", *_NEAR, place_id="n"),
            )),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query())
        assert [c.name for c in results] == ["Near", "Mid"]
        assert results[0].distance_m < results[1].distance_m

    def test_max_results_caps_output(self) -> None:
        places = [_place(f"P{i}", 51.341 + i * 0.0001, 12.37, place_id=str(i)) for i in range(10)]
        client = _make_client((200, _body(*places)))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        results = search.search(_query(), max_results=3)
        assert len(results) == 3

    def test_candidate_fields_parsed(self) -> None:
        client = _make_client(
            (200, _body(_place(
                "Bar X", *_NEAR, place_id="abc", rating=4.5, open_now=True,
                types=("bar", "point_of_interest"), primary="bar",
                attributions=[{"provider": "Quelle A"}, "Roh-String"],
            ))),
        )
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        cand = search.search(_query())[0]
        assert cand.name == "Bar X"
        assert cand.place_id == "abc"
        assert cand.rating == 4.5
        assert cand.open_now is True
        assert cand.primary_type == "bar"
        assert "bar" in cand.types
        assert cand.attributions == ("Quelle A", "Roh-String")
        assert cand.distance_m > 0

    def test_place_without_location_dropped(self) -> None:
        bad = {"id": "x", "displayName": {"text": "Ohne Koords"}, "types": []}
        client = _make_client((200, _body(bad)), (200, _body(bad)))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        assert search.search(_query()) == []

    def test_place_without_name_dropped(self) -> None:
        bad = {"id": "x", "location": {"latitude": 51.35, "longitude": 12.38}}
        client = _make_client((200, _body(bad)), (200, _body(bad)))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        assert search.search(_query()) == []


# ---------------------------------------------------------------------------
# Geocoder-Pfade (R2-C3)
# ---------------------------------------------------------------------------


class TestGeocoderPaths:
    def test_zero_results_geocode_returns_empty(self) -> None:
        client = _make_client((200, _body(_place("Bar", *_NEAR))))
        geocoder = _FakeGeocoder(result=None)  # ZERO_RESULTS
        search = NearbyPlaceSearch(API_KEY, geocoder, client=client)
        assert search.search(_query()) == []
        client.post.assert_not_called()  # ohne Center kein Places-Call

    def test_geocoder_config_error_propagates(self) -> None:
        client = _make_client((200, _body()))
        geocoder = _FakeGeocoder(error=GeocoderConfigError("denied"))
        search = NearbyPlaceSearch(API_KEY, geocoder, client=client)
        with pytest.raises(GeocoderConfigError):
            search.search(_query())


# ---------------------------------------------------------------------------
# Places-API-Fehler
# ---------------------------------------------------------------------------


class TestApiErrors:
    @pytest.mark.parametrize("status", [401, 403, 429, 400])
    def test_api_error_status_raises(self, status: int) -> None:
        client = _make_client((status, {}))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        with pytest.raises(NearbyPlaceError):
            search.search(_query())

    def test_http_500_propagates(self) -> None:
        client = _make_client((500, {}))
        search = NearbyPlaceSearch(API_KEY, _FakeGeocoder(), client=client)
        with pytest.raises(httpx.HTTPStatusError):
            search.search(_query())


# ---------------------------------------------------------------------------
# NearbyQueryDraft.to_query() (R2-C1/C2, Codex #4)
# ---------------------------------------------------------------------------


def _draft(
    *,
    location_text: str | None,
    travel_mode: str | None,
    included_type: str | None = None,
    exclude_types: tuple[str, ...] = (),
) -> NearbyQueryDraft:
    return NearbyQueryDraft(
        subject="Shisha-Kopf",
        search_query="Shisha-Kopf kaufen",
        included_type=included_type,
        exclude_types=exclude_types,
        location_text=location_text,
        travel_mode=travel_mode,
    )


class TestDraftToQuery:
    def test_complete_draft_resolves(self) -> None:
        q = _draft(location_text="Leipzig", travel_mode="auto").to_query()
        assert q is not None
        assert q.travel_mode == "driving"  # Synonym normalisiert (R2-C2)
        assert q.location_text == "Leipzig"

    def test_missing_location_returns_none(self) -> None:
        assert _draft(location_text=None, travel_mode="driving").to_query() is None
        assert _draft(location_text="  ", travel_mode="driving").to_query() is None

    def test_missing_mode_returns_none(self) -> None:
        assert _draft(location_text="Leipzig", travel_mode=None).to_query() is None

    def test_unknown_mode_returns_none(self) -> None:
        # Synonym/Unbekanntes -> None (R2-C2), kein KeyError spaeter.
        assert _draft(location_text="Leipzig", travel_mode="teleport").to_query() is None

    def test_invalid_included_type_becomes_none(self) -> None:
        q = _draft(
            location_text="Leipzig", travel_mode="walking", included_type="shisha_shop",
        ).to_query()
        assert q is not None
        assert q.included_type is None  # R2-C1: nicht gesendet

    def test_valid_included_type_kept(self) -> None:
        q = _draft(
            location_text="Leipzig", travel_mode="walking", included_type="bar",
        ).to_query()
        assert q is not None
        assert q.included_type == "bar"

    def test_exclude_types_preserved(self) -> None:
        q = _draft(
            location_text="Leipzig", travel_mode="walking",
            exclude_types=("bar", "restaurant"),
        ).to_query()
        assert q is not None
        assert q.exclude_types == ("bar", "restaurant")
