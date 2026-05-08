"""Tests fuer ConversationListStore (Phase 80 Etappe 1).

Akzeptanz aus Konzept §5.1 + §7:
- register, overwrite, TTL, out-of-range, cross-user-isolation,
  pop, list_ref-Format, Threading-Safety.

Clock wird ueber den Konstruktor-Hook injiziert -- keine time.sleep
Calls in den Tests, alle TTL-Tests sind deterministisch.
"""

from __future__ import annotations

import dataclasses
import re
import threading
from datetime import datetime, timedelta, timezone

import pytest

from elder_berry.tools.conversation_list_store import (
    ConversationListStore,
    ListEntry,
)

USER_A = "@lera:matrix.org"
USER_B = "@bob:matrix.org"


class _FakeClock:
    """Mutable Clock fuer deterministische TTL-Tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock(datetime(2026, 5, 8, 15, 0, 0, tzinfo=timezone.utc))


@pytest.fixture
def store(clock: _FakeClock) -> ConversationListStore:
    return ConversationListStore(ttl=timedelta(hours=1), clock=clock)


def _search_items() -> list[dict[str, str]]:
    return [
        {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": "..."}
        for i in range(1, 6)
    ]


# ---------------------------------------------------------------------------
# Konstruktor-Validierung
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_ttl_is_one_hour(self) -> None:
        s = ConversationListStore()
        assert s._ttl == timedelta(hours=1)

    def test_zero_ttl_rejected(self) -> None:
        with pytest.raises(ValueError, match="positiv"):
            ConversationListStore(ttl=timedelta(0))

    def test_negative_ttl_rejected(self) -> None:
        with pytest.raises(ValueError, match="positiv"):
            ConversationListStore(ttl=timedelta(seconds=-1))


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


class TestRegister:
    def test_returns_list_ref_with_expected_format(
        self, store: ConversationListStore
    ) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        # Format laut Konzept §3.3: {list_type}_{YYYYmmddTHHMMSS}_{4-hex}
        assert re.fullmatch(r"search_\d{8}T\d{6}_[0-9a-f]{4}", list_ref)

    def test_register_makes_list_active(self, store: ConversationListStore) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        active = store.get_active(USER_A, "search")
        assert active is not None
        assert active[0] == list_ref
        assert len(active[1]) == 5

    def test_empty_user_id_rejected(self, store: ConversationListStore) -> None:
        with pytest.raises(ValueError, match="user_id"):
            store.register("", "search", _search_items())

    def test_empty_list_type_rejected(self, store: ConversationListStore) -> None:
        with pytest.raises(ValueError, match="list_type"):
            store.register(USER_A, "", _search_items())

    def test_empty_items_allowed(self, store: ConversationListStore) -> None:
        list_ref = store.register(USER_A, "search", [])
        active = store.get_active(USER_A, "search")
        assert active == (list_ref, [])

    def test_items_stored_in_order(self, store: ConversationListStore) -> None:
        items = ["a", "b", "c"]
        store.register(USER_A, "search", items)
        active = store.get_active(USER_A, "search")
        assert active is not None
        assert active[1] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Overwrite-Verhalten
# ---------------------------------------------------------------------------


class TestOverwrite:
    def test_second_register_overwrites_first(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        first_ref = store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(seconds=5))
        second_ref = store.register(USER_A, "search", [{"title": "new", "url": "u"}])

        assert first_ref != second_ref
        active = store.get_active(USER_A, "search")
        assert active is not None
        assert active[0] == second_ref
        assert active[1] == [{"title": "new", "url": "u"}]

    def test_overwrite_logs_info(
        self,
        store: ConversationListStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store.register(USER_A, "search", _search_items())
        with caplog.at_level(
            "INFO", logger="elder_berry.tools.conversation_list_store"
        ):
            store.register(USER_A, "search", _search_items())
        assert any("ueberschrieben" in rec.message for rec in caplog.records)

    def test_overwrite_does_not_affect_other_list_type(
        self, store: ConversationListStore
    ) -> None:
        search_ref = store.register(USER_A, "search", _search_items())
        mail_ref = store.register(USER_A, "mail_inbox", [{"from": "x"}])
        # Ueberschreibe nur search
        new_search = store.register(USER_A, "search", [])

        assert store.get_active(USER_A, "search") == (new_search, [])
        mail = store.get_active(USER_A, "mail_inbox")
        assert mail is not None
        assert mail[0] == mail_ref
        assert search_ref != new_search


# ---------------------------------------------------------------------------
# get_item()
# ---------------------------------------------------------------------------


class TestGetItem:
    def test_index_one_returns_first_item(self, store: ConversationListStore) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        item = store.get_item(USER_A, list_ref, 1)
        assert item is not None
        assert item["title"] == "Result 1"

    def test_index_zero_returns_none(self, store: ConversationListStore) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        assert store.get_item(USER_A, list_ref, 0) is None

    def test_negative_index_returns_none(self, store: ConversationListStore) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        assert store.get_item(USER_A, list_ref, -1) is None

    def test_index_out_of_range_returns_none(
        self, store: ConversationListStore
    ) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        assert store.get_item(USER_A, list_ref, 6) is None

    def test_unknown_list_ref_returns_none(self, store: ConversationListStore) -> None:
        store.register(USER_A, "search", _search_items())
        assert store.get_item(USER_A, "search_nonexistent", 1) is None

    def test_list_ref_belongs_to_other_user(self, store: ConversationListStore) -> None:
        a_ref = store.register(USER_A, "search", _search_items())
        # User B kann mit A's list_ref nichts ausrichten
        assert store.get_item(USER_B, a_ref, 1) is None

    def test_get_item_extends_ttl(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        # Kurz vor Ablauf
        clock.advance(timedelta(minutes=59))
        assert store.get_item(USER_A, list_ref, 1) is not None
        # Weitere 59 Minuten -- ohne TTL-Refresh waere hier expired
        clock.advance(timedelta(minutes=59))
        assert store.get_item(USER_A, list_ref, 1) is not None


# ---------------------------------------------------------------------------
# TTL / Eviction
# ---------------------------------------------------------------------------


class TestTTL:
    def test_get_active_after_expiry_returns_none(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(hours=1, seconds=1))
        assert store.get_active(USER_A, "search") is None

    def test_exactly_at_ttl_is_evicted(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        # expires_at = now + ttl. Bei now == expires_at gilt: <=  -> evicted.
        store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(hours=1))
        assert store.get_active(USER_A, "search") is None

    def test_get_item_after_expiry_returns_none(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(hours=1, seconds=1))
        assert store.get_item(USER_A, list_ref, 1) is None

    def test_get_active_within_ttl_extends(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(minutes=30))
        # Touch -> TTL-Reset
        assert store.get_active(USER_A, "search") is not None
        clock.advance(timedelta(minutes=59))
        assert store.get_active(USER_A, "search") is not None

    def test_eviction_only_affects_expired_entries(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(minutes=30))
        store.register(USER_A, "mail_inbox", [{"from": "x"}])
        # 31 Min spaeter laeuft search ab (60 Min Total), mail_inbox aber nicht
        clock.advance(timedelta(minutes=31))
        assert store.get_active(USER_A, "search") is None
        assert store.get_active(USER_A, "mail_inbox") is not None


# ---------------------------------------------------------------------------
# pop_active()
# ---------------------------------------------------------------------------


class TestPopActive:
    def test_pop_returns_active(self, store: ConversationListStore) -> None:
        list_ref = store.register(USER_A, "search", _search_items())
        popped = store.pop_active(USER_A, "search")
        assert popped is not None
        assert popped[0] == list_ref
        assert len(popped[1]) == 5

    def test_pop_removes_entry(self, store: ConversationListStore) -> None:
        store.register(USER_A, "search", _search_items())
        store.pop_active(USER_A, "search")
        assert store.get_active(USER_A, "search") is None

    def test_pop_when_empty_returns_none(self, store: ConversationListStore) -> None:
        assert store.pop_active(USER_A, "search") is None

    def test_pop_after_expiry_returns_none(
        self, store: ConversationListStore, clock: _FakeClock
    ) -> None:
        store.register(USER_A, "search", _search_items())
        clock.advance(timedelta(hours=1, seconds=1))
        assert store.pop_active(USER_A, "search") is None


# ---------------------------------------------------------------------------
# Cross-User-Isolation
# ---------------------------------------------------------------------------


class TestCrossUserIsolation:
    def test_user_b_does_not_see_user_a_list(
        self, store: ConversationListStore
    ) -> None:
        store.register(USER_A, "search", _search_items())
        assert store.get_active(USER_B, "search") is None

    def test_users_can_have_independent_lists_of_same_type(
        self, store: ConversationListStore
    ) -> None:
        a_ref = store.register(USER_A, "search", [{"u": "a"}])
        b_ref = store.register(USER_B, "search", [{"u": "b"}])
        assert a_ref != b_ref

        a_active = store.get_active(USER_A, "search")
        b_active = store.get_active(USER_B, "search")
        assert a_active is not None and a_active[1] == [{"u": "a"}]
        assert b_active is not None and b_active[1] == [{"u": "b"}]

    def test_overwriting_user_a_does_not_touch_user_b(
        self, store: ConversationListStore
    ) -> None:
        store.register(USER_A, "search", [{"u": "a"}])
        b_ref = store.register(USER_B, "search", [{"u": "b"}])
        store.register(USER_A, "search", [{"u": "a2"}])

        b_active = store.get_active(USER_B, "search")
        assert b_active is not None
        assert b_active[0] == b_ref
        assert b_active[1] == [{"u": "b"}]


# ---------------------------------------------------------------------------
# list_ref-Format
# ---------------------------------------------------------------------------


class TestListRefFormat:
    def test_format_matches_concept(self, store: ConversationListStore) -> None:
        ref = store.register(USER_A, "note_search", [])
        assert re.fullmatch(r"note_search_\d{8}T\d{6}_[0-9a-f]{4}", ref)

    def test_two_consecutive_registers_yield_distinct_refs(
        self, store: ConversationListStore
    ) -> None:
        # Auch wenn die Sekunde gleich ist, soll der Hash-Suffix sie
        # unterscheiden.
        refs = {store.register(USER_A, "search", []) for _ in range(20)}
        assert len(refs) == 20


# ---------------------------------------------------------------------------
# Datenmodell -- Frozen-Dataclass-Sanity
# ---------------------------------------------------------------------------


class TestListEntry:
    def test_listentry_is_frozen(self) -> None:
        now = datetime.now(timezone.utc)
        entry = ListEntry(
            list_ref="search_x",
            list_type="search",
            user_id=USER_A,
            items=(1, 2, 3),
            created_at=now,
            last_accessed=now,
            expires_at=now + timedelta(hours=1),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.list_ref = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Immutability -- Caller darf den Store-Snapshot nicht aendern koennen
# ---------------------------------------------------------------------------


class TestImmutability:
    """Schutzversprechen: was Saleria dem User zeigt, bleibt im Store stabil.

    Codex-Review-Befund 2026-05-08: tuple(items) friert nur den Container
    ein, nicht die dict-Objekte. Ohne deepcopy koennte spaetere Mutation
    der Source-Liste oder des per get_item retournierten Items den
    Store-Snapshot aendern -- genau der Bug, den Phase 80 verhindern soll.
    """

    def test_mutating_source_list_does_not_affect_store(
        self, store: ConversationListStore
    ) -> None:
        items = [{"url": "https://original.de", "title": "orig"}]
        store.register(USER_A, "search", items)
        items[0]["url"] = "https://hijacked.de"
        items.append({"url": "https://injected.de"})

        active = store.get_active(USER_A, "search")
        assert active is not None
        assert len(active[1]) == 1
        assert active[1][0]["url"] == "https://original.de"

    def test_mutating_returned_get_active_items_does_not_affect_store(
        self, store: ConversationListStore
    ) -> None:
        store.register(USER_A, "search", [{"url": "https://original.de"}])
        active = store.get_active(USER_A, "search")
        assert active is not None
        active[1][0]["url"] = "https://hijacked.de"
        active[1].append({"url": "https://injected.de"})

        again = store.get_active(USER_A, "search")
        assert again is not None
        assert len(again[1]) == 1
        assert again[1][0]["url"] == "https://original.de"

    def test_mutating_returned_get_item_does_not_affect_store(
        self, store: ConversationListStore
    ) -> None:
        list_ref = store.register(USER_A, "search", [{"url": "https://original.de"}])
        item = store.get_item(USER_A, list_ref, 1)
        assert item is not None
        item["url"] = "https://hijacked.de"
        item["new_field"] = "injected"

        again = store.get_item(USER_A, list_ref, 1)
        assert again is not None
        assert again["url"] == "https://original.de"
        assert "new_field" not in again


# ---------------------------------------------------------------------------
# Threading-Safety (Smoke-Test)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_registers_do_not_crash(self) -> None:
        s = ConversationListStore(ttl=timedelta(minutes=10))
        errors: list[Exception] = []

        def worker(user: str) -> None:
            try:
                for i in range(50):
                    s.register(user, "search", [{"i": i}])
                    s.get_active(user, "search")
            except Exception as e:  # pragma: no cover - sanity catch
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"@user{i}:matrix.org",))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        # Jeder User hat genau eine aktive Liste
        for i in range(8):
            active = s.get_active(f"@user{i}:matrix.org", "search")
            assert active is not None

    def test_concurrent_register_same_user_yields_consistent_state(self) -> None:
        s = ConversationListStore(ttl=timedelta(minutes=10))
        N = 100

        def worker(start: int) -> None:
            for i in range(start, start + N):
                s.register(USER_A, "search", [{"i": i}])

        threads = [threading.Thread(target=worker, args=(k * N,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Genau ein Eintrag aktiv -- egal welcher gewonnen hat.
        active = s.get_active(USER_A, "search")
        assert active is not None
        assert len(active[1]) == 1
