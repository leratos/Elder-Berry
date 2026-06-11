"""Tests fuer NearbyPlaceCommandHandler (Phase 97, E4).

Schwerpunkte (Konzept §6): Fallthrough, Turn 1 + Echo, Ask-Ort, Ask-Modus,
Folge-Turn laedt Draft + setzt fort (R2-C5), Attribution in der Ausgabe
(R2-C4), GeocoderConfigError -> Dienstfehler (R2-C3), 0-Treffer-Fallback,
kein Key -> _factory None, Plugin-Manifest.

Alle Abhaengigkeiten (Parser/Search/Store) sind Fakes -- kein echter LLM-
oder HTTP-Call.
"""

from __future__ import annotations

from elder_berry.comms.commands.base import CommandResult, HandlerContext
from elder_berry.comms.commands.nearby_place_commands import (
    PLUGIN,
    NearbyPlaceCommandHandler,
    _factory,
)
from elder_berry.tools.google_geocoder import GeocoderConfigError
from elder_berry.tools.nearby_place_search import (
    NearbyPlaceError,
    NearbyQueryDraft,
    PlaceCandidate,
)

USER = "bot-user"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeParser:
    def __init__(
        self,
        draft: NearbyQueryDraft | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._draft = draft
        self._raise = raise_exc
        self.calls: list[str] = []

    def parse(self, text: str) -> NearbyQueryDraft | None:
        self.calls.append(text)
        if self._raise is not None:
            raise self._raise
        return self._draft


class _FakeSearch:
    def __init__(
        self,
        candidates: list[PlaceCandidate] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._candidates = candidates or []
        self._raise = raise_exc
        self.calls: list[object] = []

    def search(self, query: object, *, max_results: int = 20) -> list[PlaceCandidate]:
        self.calls.append(query)
        if self._raise is not None:
            raise self._raise
        return self._candidates


class _FakeStore:
    def __init__(self) -> None:
        self._d: dict[str, NearbyQueryDraft] = {}

    def get(self, user_id: str) -> NearbyQueryDraft | None:
        return self._d.get(user_id)

    def set(self, user_id: str, draft: NearbyQueryDraft) -> None:
        self._d[user_id] = draft

    def clear(self, user_id: str) -> None:
        self._d.pop(user_id, None)


def _draft(
    *,
    location: str | None = "Leipzig",
    mode: str | None = "driving",
    subject: str = "Rockerbar",
) -> NearbyQueryDraft:
    return NearbyQueryDraft(
        subject=subject,
        search_query=subject,
        included_type=None,
        exclude_types=("restaurant",),
        location_text=location,
        travel_mode=mode,
    )


def _cand(
    name: str = "Bar X",
    place_id: str = "p1",
    dist: int = 1200,
    *,
    attrib: tuple[str, ...] = ("Quelle A",),
) -> PlaceCandidate:
    return PlaceCandidate(
        name=name,
        address=f"{name}-Adr",
        place_id=place_id,
        rating=4.2,
        open_now=True,
        distance_m=dist,
        types=("bar",),
        primary_type="bar",
        attributions=attrib,
    )


def _handler(
    parser: _FakeParser,
    search: _FakeSearch,
    store: _FakeStore | None = None,
) -> NearbyPlaceCommandHandler:
    return NearbyPlaceCommandHandler(
        intent_parser=parser,  # type: ignore[arg-type]
        place_search=search,  # type: ignore[arg-type]
        draft_store=store or _FakeStore(),  # type: ignore[arg-type]
        default_user_id=USER,
    )


_NEARBY_TEXT = "kannst du mir eine Rockerbar nennen?"


# ---------------------------------------------------------------------------
# Fallthrough
# ---------------------------------------------------------------------------


class TestFallthrough:
    def test_wrong_command_falls_through(self) -> None:
        h = _handler(_FakeParser(), _FakeSearch())
        res = h.execute("other", _NEARBY_TEXT)
        assert res.fallthrough is True

    def test_non_nearby_text_falls_through(self) -> None:
        h = _handler(_FakeParser(), _FakeSearch())
        res = h.execute("nearby_place", "wie spaet ist es")
        assert res.fallthrough is True

    def test_parser_none_falls_through(self) -> None:
        # Vorfilter true, aber LLM erkennt keinen Intent -> Fallthrough.
        h = _handler(_FakeParser(draft=None), _FakeSearch())
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.fallthrough is True


# ---------------------------------------------------------------------------
# Turn 1
# ---------------------------------------------------------------------------


class TestTurn1:
    def test_complete_query_runs_search_and_lists(self) -> None:
        search = _FakeSearch(candidates=[_cand("Bar A", "a"), _cand("Bar B", "b", 800)])
        h = _handler(_FakeParser(draft=_draft()), search)
        res = h.execute("nearby_place", _NEARBY_TEXT)

        assert res.list_type == "nearby_place_pick"
        assert res.list_items is not None
        assert [i["place_id"] for i in res.list_items] == ["a", "b"]
        assert all("name" in i and "place_id" in i for i in res.list_items)
        # Echo der Absicht im Text.
        assert "Rockerbar" in (res.text or "")
        assert len(search.calls) == 1

    def test_attribution_in_output(self) -> None:
        search = _FakeSearch(candidates=[_cand(attrib=("Quelle A", "Quelle B"))])
        h = _handler(_FakeParser(draft=_draft()), search)
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert "Google" in (res.text or "")          # Pflicht-Attribution
        assert "Quelle A" in (res.text or "")
        assert "Quelle B" in (res.text or "")

    def test_ask_location_when_missing(self) -> None:
        store = _FakeStore()
        h = _handler(_FakeParser(draft=_draft(location=None)), _FakeSearch(), store)
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.list_items is None
        assert "wo bist du" in (res.text or "").lower()
        # Draft persistiert.
        assert store.get(USER) is not None

    def test_ask_mode_when_missing(self) -> None:
        store = _FakeStore()
        h = _handler(_FakeParser(draft=_draft(mode=None)), _FakeSearch(), store)
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.list_items is None
        assert "unterwegs" in (res.text or "").lower()
        assert store.get(USER) is not None

    def test_zero_results_fallback(self) -> None:
        h = _handler(_FakeParser(draft=_draft()), _FakeSearch(candidates=[]))
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.list_items is None
        assert "nichts" in (res.text or "").lower()


# ---------------------------------------------------------------------------
# Fehlerpfade
# ---------------------------------------------------------------------------


class TestErrors:
    def test_geocoder_config_error_is_service_error(self) -> None:
        # R2-C3: NICHT "Ort nicht gefunden".
        search = _FakeSearch(raise_exc=GeocoderConfigError("denied"))
        h = _handler(_FakeParser(draft=_draft()), search)
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.success is True
        text = (res.text or "").lower()
        assert "konfig" in text or "verfuegbar" in text or "verfügbar" in text
        assert "nicht gefunden" not in text or "kein" in text

    def test_places_error_is_reported(self) -> None:
        search = _FakeSearch(raise_exc=NearbyPlaceError("rate limit"))
        h = _handler(_FakeParser(draft=_draft()), search)
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.success is True
        assert "problem" in (res.text or "").lower()

    def test_llm_runtime_error_is_friendly(self) -> None:
        h = _handler(_FakeParser(raise_exc=RuntimeError("boom")), _FakeSearch())
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert res.success is True
        assert res.text


# ---------------------------------------------------------------------------
# Folge-Turn (R2-C5) via continue_with_answer
# ---------------------------------------------------------------------------


class TestFollowUpTurn:
    def test_has_pending_reflects_store(self) -> None:
        store = _FakeStore()
        h = _handler(_FakeParser(), _FakeSearch(), store)
        assert h.has_pending_draft() is False
        store.set(USER, _draft(mode=None))
        assert h.has_pending_draft() is True

    def test_mode_answer_completes_and_searches(self) -> None:
        store = _FakeStore()
        store.set(USER, _draft(location="Leipzig", mode=None))  # Modus fehlt
        search = _FakeSearch(candidates=[_cand()])
        h = _handler(_FakeParser(), search, store)

        res = h.continue_with_answer("zu Fuss")

        assert res.list_type == "nearby_place_pick"
        assert len(search.calls) == 1
        # Draft nach erfolgreicher Suche geraeumt.
        assert store.get(USER) is None

    def test_location_answer_completes(self) -> None:
        store = _FakeStore()
        store.set(USER, _draft(location=None, mode="walking"))  # Ort fehlt
        search = _FakeSearch(candidates=[_cand()])
        h = _handler(_FakeParser(), search, store)

        res = h.continue_with_answer("Karl-Liebknecht-Str. 12, Leipzig")
        assert res.list_type == "nearby_place_pick"
        assert store.get(USER) is None

    def test_subject_survives_followup(self) -> None:
        # R2-C5 Kern: subject/exclude bleiben ueber den Folge-Turn erhalten.
        store = _FakeStore()
        store.set(USER, _draft(location="Leipzig", mode=None, subject="Shisha-Kopf"))
        search = _FakeSearch(candidates=[_cand()])
        h = _handler(_FakeParser(), search, store)

        h.continue_with_answer("mit dem Auto")
        query = search.calls[0]
        assert query.subject == "Shisha-Kopf"          # type: ignore[attr-defined]
        assert query.exclude_types == ("restaurant",)  # type: ignore[attr-defined]
        assert query.travel_mode == "driving"          # type: ignore[attr-defined]

    def test_unrelated_answer_does_not_hijack(self) -> None:
        store = _FakeStore()
        store.set(USER, _draft(location="Leipzig", mode=None))
        search = _FakeSearch(candidates=[_cand()])
        h = _handler(_FakeParser(), search, store)

        res = h.continue_with_answer("wie spaet ist es?")
        assert res.fallthrough is True
        assert search.calls == []          # keine Suche
        assert store.get(USER) is not None  # Draft bleibt

    def test_new_nearby_query_replaces_draft(self) -> None:
        store = _FakeStore()
        store.set(USER, _draft(location=None, mode=None, subject="Altes"))
        search = _FakeSearch(candidates=[_cand()])
        # Neue, vollstaendige Anfrage -> Parser liefert kompletten Draft.
        parser = _FakeParser(draft=_draft(subject="Neues"))
        h = _handler(parser, search, store)

        res = h.continue_with_answer("kannst du mir eine Rockerbar nennen?")
        assert res.list_type == "nearby_place_pick"
        assert "Neues" in (res.text or "")
        assert parser.calls == ["kannst du mir eine Rockerbar nennen?"]


# ---------------------------------------------------------------------------
# Factory / Plugin
# ---------------------------------------------------------------------------


class TestFactoryAndPlugin:
    def test_factory_none_without_services(self) -> None:
        ctx = HandlerContext(default_user_id=USER)
        assert _factory(ctx) is None

    def test_factory_none_without_draft_store(self) -> None:
        ctx = HandlerContext(
            default_user_id=USER,
            nearby_place_search=_FakeSearch(),  # type: ignore[arg-type]
            nearby_draft_store=None,
        )
        assert _factory(ctx) is None

    def test_factory_builds_when_wired(self) -> None:
        ctx = HandlerContext(
            default_user_id=USER,
            anthropic_client=None,
            nearby_place_search=_FakeSearch(),  # type: ignore[arg-type]
            nearby_draft_store=_FakeStore(),  # type: ignore[arg-type]
        )
        handler = _factory(ctx)
        assert isinstance(handler, NearbyPlaceCommandHandler)

    def test_plugin_manifest(self) -> None:
        assert PLUGIN.name == "nearby_place"
        assert PLUGIN.priority == 74
        assert PLUGIN.category == "web"
        assert isinstance(_factory(HandlerContext()), type(None))

    def test_returns_command_result(self) -> None:
        h = _handler(_FakeParser(draft=_draft()), _FakeSearch(candidates=[_cand()]))
        res = h.execute("nearby_place", _NEARBY_TEXT)
        assert isinstance(res, CommandResult)
