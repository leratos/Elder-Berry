"""Tests fuer RouteSessionStore + RouteSession-Serialisierung.

Phase 92 (E3). SQLite-Tests in tmp_path -- keine Cleanup-Sorgen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from elder_berry.tools.google_maps_route_planner import POICandidate, POIRequest
from elder_berry.tools.route_session_store import (
    ResolvedStop,
    RouteSession,
    RouteSessionStore,
)


USER_ID = "@test:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> RouteSessionStore:
    return RouteSessionStore(db_path=tmp_path / "sessions.db")


def _stop(
    label: str,
    address: str | None = None,
    intent_type: str = "contact",
) -> ResolvedStop:
    return ResolvedStop(
        label=label,
        intent_type=intent_type,
        intent_value=label,
        address=address,
    )


def _session(
    *,
    user_id: str = USER_ID,
    raw_text: str = "Fahrt zu Lisa",
    origin: ResolvedStop | None = None,
    destination: ResolvedStop | None = None,
    waypoints: list[ResolvedStop] | None = None,
    arrival: str = "",
    poi_request: POIRequest | None = None,
    poi_candidates: list[POICandidate] | None = None,
    chosen_poi: POICandidate | None = None,
) -> RouteSession:
    return RouteSession(
        user_id=user_id,
        raw_text=raw_text,
        origin=origin or _stop("Home", "Musterstr. 5, Berlin", "home"),
        destination=destination or _stop("Lisa", "Hauptstr. 12, Leipzig", "contact"),
        waypoints=waypoints or [],
        arrival_time_text=arrival,
        poi_request=poi_request,
        poi_candidates=poi_candidates or [],
        chosen_poi=chosen_poi,
    )


# ---------------------------------------------------------------------------
# ResolvedStop
# ---------------------------------------------------------------------------


class TestResolvedStop:
    def test_resolved(self) -> None:
        stop = _stop("Lisa", "Hauptstr. 12")
        assert stop.is_resolved is True
        assert stop.is_ambiguous is False

    def test_unresolved_no_candidates(self) -> None:
        stop = _stop("Unbekannt", None)
        assert stop.is_resolved is False
        assert stop.is_ambiguous is False

    def test_ambiguous(self) -> None:
        stop = ResolvedStop(
            label="Lisa",
            intent_type="contact",
            intent_value="Lisa",
            address=None,
            candidate_names=["Lisa Müller", "Lisa Schmidt"],
            candidate_addresses=["Adr1", "Adr2"],
        )
        assert stop.is_ambiguous is True
        assert stop.is_resolved is False


# ---------------------------------------------------------------------------
# RouteSession
# ---------------------------------------------------------------------------


class TestRouteSession:
    def test_next_open_disambiguation_none(self) -> None:
        session = _session()
        assert session.next_open_disambiguation() is None

    def test_next_open_disambiguation_origin_first(self) -> None:
        ambig = ResolvedStop(
            label="Home",
            intent_type="home",
            intent_value="",
            candidate_names=["Home A", "Home B"],
            candidate_addresses=["Adr1", "Adr2"],
        )
        session = _session(origin=ambig)
        kind, stop = session.next_open_disambiguation()  # type: ignore[misc]
        assert kind == "origin"
        assert stop is ambig

    def test_next_open_disambiguation_destination_when_origin_ok(self) -> None:
        ambig_dest = ResolvedStop(
            label="Lisa",
            intent_type="contact",
            intent_value="Lisa",
            candidate_names=["Lisa M", "Lisa S"],
            candidate_addresses=["A1", "A2"],
        )
        session = _session(destination=ambig_dest)
        kind, _ = session.next_open_disambiguation()  # type: ignore[misc]
        assert kind == "destination"

    def test_next_open_disambiguation_waypoint_index(self) -> None:
        wp_ok = _stop("Andrea", "Adr-A", "contact")
        wp_ambig = ResolvedStop(
            label="Lisa",
            intent_type="contact",
            intent_value="Lisa",
            candidate_names=["A", "B"],
            candidate_addresses=["x", "y"],
        )
        session = _session(waypoints=[wp_ok, wp_ambig])
        kind, _ = session.next_open_disambiguation()  # type: ignore[misc]
        assert kind == "waypoint_1"

    def test_all_resolved_true_when_no_waypoints(self) -> None:
        assert _session().all_resolved() is True

    def test_all_resolved_false_when_origin_open(self) -> None:
        session = _session(origin=_stop("Home", None, "home"))
        assert session.all_resolved() is False

    def test_all_resolved_ignores_poi_waypoints(self) -> None:
        """POI-Slots zaehlen NICHT zu all_resolved -- die werden ueber
        poi_candidates/chosen_poi getrennt aufgeloest."""
        poi_wp = ResolvedStop(
            label="Kaufland",
            intent_type="poi",
            intent_value="Kaufland",
            address=None,
            poi_category="supermarket",
        )
        session = _session(waypoints=[poi_wp])
        assert session.all_resolved() is True

    def test_people_stops_filters_poi(self) -> None:
        contact = _stop("Lisa", "X")
        poi = ResolvedStop(
            label="Kaufland",
            intent_type="poi",
            intent_value="Kaufland",
        )
        session = _session(waypoints=[contact, poi])
        ppl = session.people_stops()
        assert len(ppl) == 1
        assert ppl[0].label == "Lisa"


# ---------------------------------------------------------------------------
# Serialisierung
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip_minimal(self) -> None:
        session = _session()
        data = session.to_dict()
        restored = RouteSession.from_dict(data)
        assert restored.user_id == session.user_id
        assert restored.origin.address == session.origin.address
        assert restored.destination.label == "Lisa"

    def test_roundtrip_with_ambiguity(self) -> None:
        ambig = ResolvedStop(
            label="Lisa",
            intent_type="contact",
            intent_value="Lisa",
            candidate_names=["Lisa M", "Lisa S"],
            candidate_addresses=["A1", "A2"],
        )
        session = _session(destination=ambig)
        restored = RouteSession.from_dict(session.to_dict())
        assert restored.destination.candidate_names == ["Lisa M", "Lisa S"]
        assert restored.destination.candidate_addresses == ["A1", "A2"]
        assert restored.destination.is_ambiguous is True

    def test_roundtrip_with_poi_request(self) -> None:
        session = _session(
            poi_request=POIRequest(
                category="Kaufland",
                name_hint="Gruenau",
                max_results=8,
                max_detour_seconds=300,
            ),
        )
        restored = RouteSession.from_dict(session.to_dict())
        assert restored.poi_request is not None
        assert restored.poi_request.category == "Kaufland"
        assert restored.poi_request.max_detour_seconds == 300

    def test_roundtrip_with_poi_candidates(self) -> None:
        cand = POICandidate(
            name="K-A",
            address="X",
            place_id="ChIJ1",
            detour_seconds=120,
            rating=4.2,
        )
        session = _session(poi_candidates=[cand])
        restored = RouteSession.from_dict(session.to_dict())
        assert len(restored.poi_candidates) == 1
        assert restored.poi_candidates[0].place_id == "ChIJ1"

    def test_roundtrip_with_chosen_poi(self) -> None:
        cand = POICandidate(
            name="K",
            address="X",
            place_id="ChIJ",
            detour_seconds=60,
            rating=None,
        )
        session = _session(chosen_poi=cand)
        restored = RouteSession.from_dict(session.to_dict())
        assert restored.chosen_poi is not None
        assert restored.chosen_poi.rating is None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class TestStore:
    def test_set_and_get(self, store: RouteSessionStore) -> None:
        session = _session()
        store.set(USER_ID, session)
        loaded = store.get(USER_ID)
        assert loaded is not None
        assert loaded.user_id == USER_ID
        assert loaded.destination.label == "Lisa"

    def test_get_missing_returns_none(self, store: RouteSessionStore) -> None:
        assert store.get("@nobody:matrix.org") is None

    def test_set_overwrites_existing(self, store: RouteSessionStore) -> None:
        store.set(USER_ID, _session(raw_text="erste"))
        store.set(USER_ID, _session(raw_text="zweite"))
        loaded = store.get(USER_ID)
        assert loaded is not None
        assert loaded.raw_text == "zweite"

    def test_clear(self, store: RouteSessionStore) -> None:
        store.set(USER_ID, _session())
        store.clear(USER_ID)
        assert store.get(USER_ID) is None

    def test_clear_missing_is_noop(self, store: RouteSessionStore) -> None:
        store.clear("@nobody:matrix.org")  # darf nicht crashen

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions.db"
        first = RouteSessionStore(db_path=path)
        first.set(USER_ID, _session(raw_text="erste"))
        first.close()
        # Neue Instanz auf derselben DB
        second = RouteSessionStore(db_path=path)
        loaded = second.get(USER_ID)
        assert loaded is not None
        assert loaded.raw_text == "erste"

    def test_set_empty_user_raises(self, store: RouteSessionStore) -> None:
        with pytest.raises(ValueError, match="user_id"):
            store.set("", _session())

    def test_zero_ttl_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="ttl"):
            RouteSessionStore(
                db_path=tmp_path / "x.db",
                ttl=timedelta(seconds=0),
            )

    def test_ttl_eviction(self, tmp_path: Path) -> None:
        # Frozen clock: erst t0, dann t0 + 2h
        now = [datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)]

        def fake_clock() -> datetime:
            return now[0]

        store = RouteSessionStore(
            db_path=tmp_path / "ttl.db",
            ttl=timedelta(hours=1),
            clock=fake_clock,
        )
        store.set(USER_ID, _session())
        # 2 Stunden spaeter -> abgelaufen
        now[0] = now[0] + timedelta(hours=2)
        assert store.get(USER_ID) is None

    def test_evict_expired_removes_stale(self, tmp_path: Path) -> None:
        now = [datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)]

        def fake_clock() -> datetime:
            return now[0]

        store = RouteSessionStore(
            db_path=tmp_path / "evict.db",
            ttl=timedelta(hours=1),
            clock=fake_clock,
        )
        store.set("a", _session(user_id="a"))
        store.set("b", _session(user_id="b"))
        now[0] = now[0] + timedelta(hours=2)
        removed = store.evict_expired()
        assert removed == 2
        assert store.get("a") is None
        assert store.get("b") is None

    def test_get_after_set_refreshes_expiry(self, tmp_path: Path) -> None:
        """set() schreibt expires_at neu; nach set() lebt sie wieder TTL lang."""
        now = [datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)]

        def fake_clock() -> datetime:
            return now[0]

        store = RouteSessionStore(
            db_path=tmp_path / "refresh.db",
            ttl=timedelta(hours=1),
            clock=fake_clock,
        )
        store.set(USER_ID, _session())
        # 30min vergehen -> noch da
        now[0] = now[0] + timedelta(minutes=30)
        assert store.get(USER_ID) is not None
        # set() refresht expires_at
        store.set(USER_ID, _session(raw_text="refresh"))
        # weitere 50min vergehen -> innerhalb des neuen TTL-Fensters
        now[0] = now[0] + timedelta(minutes=50)
        loaded = store.get(USER_ID)
        assert loaded is not None
        assert loaded.raw_text == "refresh"

    def test_corrupt_row_is_dropped(
        self,
        store: RouteSessionStore,
        tmp_path: Path,
    ) -> None:
        """Korrupter JSON-Blob -> get() liefert None und cleart die Row."""
        # Manuelles INSERT eines kaputten Blobs
        store._conn.execute(
            "INSERT INTO route_sessions "
            "(user_id, data, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                USER_ID,
                "not-json{",
                "2026-05-20T10:00:00+00:00",
                "2026-05-20T10:00:00+00:00",
                "2099-01-01T00:00:00+00:00",
            ),
        )
        store._conn.commit()
        assert store.get(USER_ID) is None
        # Row sollte weg sein
        row = store._conn.execute(
            "SELECT 1 FROM route_sessions WHERE user_id = ?",
            (USER_ID,),
        ).fetchone()
        assert row is None
