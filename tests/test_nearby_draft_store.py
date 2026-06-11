"""Tests fuer NearbyDraftStore -- persistenter Pending-Draft (Phase 97, E4).

Schwerpunkt (Konzept §6 / R2-C5): set/get/clear pro User; der zweite Turn
laedt den Draft und ergaenzt das fehlende Feld; TTL-Eviction; Round-Trip
inkl. tuple/None-Feldern.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from elder_berry.tools.nearby_draft_store import NearbyDraftStore
from elder_berry.tools.nearby_place_search import NearbyQueryDraft


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


def _draft(
    *,
    location_text: str | None = None,
    travel_mode: str | None = None,
) -> NearbyQueryDraft:
    return NearbyQueryDraft(
        subject="Shisha-Kopf",
        search_query="Shisha-Kopf kaufen",
        included_type=None,
        exclude_types=("bar", "restaurant"),
        location_text=location_text,
        travel_mode=travel_mode,
        open_now=True,
    )


@pytest.fixture
def store(tmp_path: Path) -> NearbyDraftStore:
    return NearbyDraftStore(db_path=tmp_path / "drafts.db")


class TestConstructor:
    def test_nonpositive_ttl_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="ttl"):
            NearbyDraftStore(db_path=tmp_path / "x.db", ttl=timedelta(0))

    def test_empty_user_id_raises(self, store: NearbyDraftStore) -> None:
        with pytest.raises(ValueError, match="user_id"):
            store.set("", _draft())


class TestRoundTrip:
    def test_set_get_roundtrip_with_tuple_and_none(
        self, store: NearbyDraftStore
    ) -> None:
        store.set("user-a", _draft(location_text=None, travel_mode=None))
        loaded = store.get("user-a")
        assert loaded is not None
        assert loaded.subject == "Shisha-Kopf"
        assert loaded.search_query == "Shisha-Kopf kaufen"
        assert loaded.exclude_types == ("bar", "restaurant")  # tuple erhalten
        assert loaded.included_type is None
        assert loaded.location_text is None
        assert loaded.travel_mode is None
        assert loaded.open_now is True

    def test_get_unknown_user_returns_none(self, store: NearbyDraftStore) -> None:
        assert store.get("niemand") is None

    def test_set_overwrites(self, store: NearbyDraftStore) -> None:
        store.set("user-a", _draft(location_text=None))
        store.set("user-a", _draft(location_text="Leipzig", travel_mode="driving"))
        loaded = store.get("user-a")
        assert loaded is not None
        assert loaded.location_text == "Leipzig"
        assert loaded.travel_mode == "driving"

    def test_clear(self, store: NearbyDraftStore) -> None:
        store.set("user-a", _draft())
        store.clear("user-a")
        assert store.get("user-a") is None

    def test_isolation_between_users(self, store: NearbyDraftStore) -> None:
        store.set("user-a", _draft(location_text="Leipzig"))
        store.set("user-b", _draft(location_text="Berlin"))
        a = store.get("user-a")
        b = store.get("user-b")
        assert a is not None and a.location_text == "Leipzig"
        assert b is not None and b.location_text == "Berlin"


class TestSecondTurnFlow:
    def test_second_turn_loads_and_fills_missing_field(
        self, store: NearbyDraftStore
    ) -> None:
        # Turn 1: nur subject/query/exclude, location+mode fehlen -> to_query None.
        store.set("bot-user", _draft(location_text=None, travel_mode=None))
        loaded = store.get("bot-user")
        assert loaded is not None
        assert loaded.to_query() is None

        # Folge-Turn: fehlende Felder ergaenzen (immutable -> neuer Draft),
        # subject/search_query/exclude_types bleiben erhalten.
        completed = NearbyQueryDraft(
            subject=loaded.subject,
            search_query=loaded.search_query,
            included_type=loaded.included_type,
            exclude_types=loaded.exclude_types,
            location_text="Karl-Liebknecht-Str. 12, Leipzig",
            travel_mode="auto",
            open_now=loaded.open_now,
        )
        store.set("bot-user", completed)

        again = store.get("bot-user")
        assert again is not None
        query = again.to_query()
        assert query is not None
        assert query.subject == "Shisha-Kopf"
        assert query.search_query == "Shisha-Kopf kaufen"
        assert query.exclude_types == ("bar", "restaurant")
        assert query.location_text == "Karl-Liebknecht-Str. 12, Leipzig"
        assert query.travel_mode == "driving"  # Synonym normiert


class TestTtl:
    def test_expired_draft_is_evicted(self, tmp_path: Path) -> None:
        clock = _Clock(datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc))
        store = NearbyDraftStore(
            db_path=tmp_path / "ttl.db", ttl=timedelta(hours=1), clock=clock
        )
        store.set("user-a", _draft())
        clock.advance(timedelta(hours=1, minutes=1))
        assert store.get("user-a") is None

    def test_evict_expired_counts(self, tmp_path: Path) -> None:
        clock = _Clock(datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc))
        store = NearbyDraftStore(
            db_path=tmp_path / "ttl2.db", ttl=timedelta(minutes=30), clock=clock
        )
        store.set("user-a", _draft())
        store.set("user-b", _draft())
        clock.advance(timedelta(hours=1))
        assert store.evict_expired() == 2
        assert store.get("user-a") is None


class TestCorruptRow:
    def test_corrupt_json_is_discarded(self, store: NearbyDraftStore) -> None:
        store.set("user-a", _draft())
        # Row direkt korrumpieren (Zugriff auf interne Connection nur im Test).
        store._conn.execute(
            "UPDATE nearby_drafts SET data = ? WHERE user_id = ?",
            ("{nicht json", "user-a"),
        )
        store._conn.commit()
        assert store.get("user-a") is None  # verworfen statt Crash
