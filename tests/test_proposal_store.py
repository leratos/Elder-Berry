"""Tests: ProposalStore -- Plugin-Vorschlags-Speicher (Phase 78 Etappe 1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from elder_berry.tools.proposal_store import (
    InvalidStatusError,
    Proposal,
    ProposalAlreadyExistsError,
    ProposalNotFoundError,
    ProposalStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ProposalStore:
    db = tmp_path / "test_proposals.db"
    s = ProposalStore(db_path=db)
    yield s
    s.close()


def _make_pending(
    store: ProposalStore,
    intent: str = "spotify_play_song",
    title: str = "Spotify-Steuerung",
    description_md: str = "# Spotify\nSpotify-Steuerung via Matrix.",
    sample_message: str = "spiel was von Hans Zimmer",
    sender_hash: str | None = "hash_alice",
    confidence: float | None = 0.8,
    suggested_category: str | None = "medien",
    suggested_priority: int | None = 50,
) -> Proposal:
    return store.create_pending(
        intent=intent,
        title=title,
        description_md=description_md,
        sample_message=sample_message,
        sender_hash=sender_hash,
        confidence=confidence,
        suggested_category=suggested_category,
        suggested_priority=suggested_priority,
    )


# ---------------------------------------------------------------------------
# DTO + Schema
# ---------------------------------------------------------------------------


class TestProposalDTO:
    def test_frozen(self, store: ProposalStore) -> None:
        proposal = _make_pending(store)
        with pytest.raises(AttributeError):
            proposal.title = "Anderer Title"  # type: ignore[misc]

    def test_initial_state(self, store: ProposalStore) -> None:
        proposal = _make_pending(store)
        assert proposal.id == "spotify_play_song"
        assert proposal.title == "Spotify-Steuerung"
        assert proposal.status == "in_pruefung"
        assert proposal.trigger_count == 1
        assert proposal.notified_at is None
        assert proposal.implemented_in is None
        assert proposal.rejected_reason is None
        assert proposal.last_confidence == 0.8
        assert proposal.suggested_category == "medien"
        assert proposal.suggested_priority == 50
        assert proposal.related_proposals == []
        assert proposal.created_at == proposal.updated_at == proposal.last_triggered_at


class TestSchemaSetup:
    def test_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "idempotent.db"
        s1 = ProposalStore(db_path=db)
        s1.close()
        # Zweite Instanz darf das Schema nicht zerstoeren / nicht crashen
        s2 = ProposalStore(db_path=db)
        try:
            assert s2.list_active() == []
        finally:
            s2.close()

    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = tmp_path / "subdir" / "proposals.db"
        s = ProposalStore(db_path=db)
        try:
            assert db.exists()
        finally:
            s.close()


# ---------------------------------------------------------------------------
# create_pending
# ---------------------------------------------------------------------------


class TestCreatePending:
    def test_returns_proposal(self, store: ProposalStore) -> None:
        proposal = _make_pending(store)
        assert proposal.status == "in_pruefung"
        assert proposal.trigger_count == 1

    def test_first_trigger_inserted(self, store: ProposalStore) -> None:
        _make_pending(store)
        triggers = store.get_triggers("spotify_play_song")
        assert len(triggers) == 1
        assert triggers[0].sample_message == "spiel was von Hans Zimmer"
        assert triggers[0].sender_hash == "hash_alice"
        assert triggers[0].confidence == 0.8

    def test_history_entry_for_creation(self, store: ProposalStore) -> None:
        _make_pending(store)
        history = store.get_history("spotify_play_song")
        assert len(history) == 1
        assert history[0].old_status is None
        assert history[0].new_status == "in_pruefung"
        assert history[0].changed_by == "saleria"

    def test_duplicate_raises(self, store: ProposalStore) -> None:
        _make_pending(store)
        with pytest.raises(ProposalAlreadyExistsError):
            _make_pending(store)

    def test_duplicate_does_not_pollute_state(self, store: ProposalStore) -> None:
        _make_pending(store)
        with pytest.raises(ProposalAlreadyExistsError):
            _make_pending(store, title="Anderer Title")
        # Erste Version bleibt unveraendert (Transaktion rollt zurueck)
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.title == "Spotify-Steuerung"
        assert len(store.get_triggers("spotify_play_song")) == 1
        assert len(store.get_history("spotify_play_song")) == 1

    def test_optional_fields_can_be_none(self, store: ProposalStore) -> None:
        store.create_pending(
            intent="minimal",
            title="Minimal",
            description_md="kurz",
            sample_message="test",
            sender_hash=None,
            confidence=None,
        )
        proposal = store.get_by_id("minimal")
        assert proposal is not None
        assert proposal.last_confidence is None
        assert proposal.suggested_category is None
        assert proposal.suggested_priority is None


# ---------------------------------------------------------------------------
# add_trigger
# ---------------------------------------------------------------------------


class TestAddTrigger:
    def test_increments_counter(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.add_trigger("spotify_play_song", "noch was Spotify", "hash_b", 0.7)
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.trigger_count == 2

    def test_inserts_trigger_row(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.add_trigger("spotify_play_song", "noch was Spotify", "hash_b", 0.7)
        triggers = store.get_triggers("spotify_play_song")
        assert len(triggers) == 2
        # Neueste zuerst (ORDER BY triggered_at DESC)
        assert triggers[0].sample_message == "noch was Spotify"

    def test_updates_last_confidence(self, store: ProposalStore) -> None:
        _make_pending(store, confidence=0.8)
        store.add_trigger("spotify_play_song", "noch", "hash_b", 0.95)
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.last_confidence == 0.95

    def test_keeps_last_confidence_when_none(self, store: ProposalStore) -> None:
        _make_pending(store, confidence=0.8)
        store.add_trigger("spotify_play_song", "noch", "hash_b", None)
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        # COALESCE haelt den alten Wert
        assert proposal.last_confidence == 0.8

    def test_unknown_proposal_raises(self, store: ProposalStore) -> None:
        with pytest.raises(ProposalNotFoundError):
            store.add_trigger("does_not_exist", "huh", None, None)

    def test_many_triggers_no_pk_collision(self, store: ProposalStore) -> None:
        """AUTOINCREMENT-PK statt (proposal_id, triggered_at) -- siehe Schema-Korrektur."""
        _make_pending(store)
        for i in range(50):
            store.add_trigger("spotify_play_song", f"sample {i}", "hash", 0.8)
        triggers = store.get_triggers("spotify_play_song", limit=100)
        assert len(triggers) == 51  # 1 aus create_pending + 50


# ---------------------------------------------------------------------------
# count_triggers_since (7-Tage-Window-Heuristik)
# ---------------------------------------------------------------------------


class TestCountTriggersSince:
    def test_only_first_trigger(self, store: ProposalStore) -> None:
        _make_pending(store)
        assert store.count_triggers_since("spotify_play_song", 7) == 1

    def test_multiple_recent(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.add_trigger("spotify_play_song", "a", None, None)
        store.add_trigger("spotify_play_song", "b", None, None)
        assert store.count_triggers_since("spotify_play_song", 7) == 3

    def test_old_triggers_excluded(self, store: ProposalStore) -> None:
        """Trigger aelter als das Fenster zaehlen nicht."""
        _make_pending(store)
        # Manuell einen alten Trigger einfuegen (Workaround fuer fehlende Time-Travel)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        store._conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO plugin_proposal_triggers "
            "(proposal_id, triggered_at, sample_message, sender_hash, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            ("spotify_play_song", old_ts, "alt", None, None),
        )
        store._conn.commit()  # type: ignore[attr-defined]

        # Im 7-Tage-Fenster: nur der Initial-Trigger.
        assert store.count_triggers_since("spotify_play_song", 7) == 1
        # Im 60-Tage-Fenster: beide.
        assert store.count_triggers_since("spotify_play_song", 60) == 2

    def test_unknown_proposal_returns_zero(self, store: ProposalStore) -> None:
        assert store.count_triggers_since("nope", 7) == 0


# ---------------------------------------------------------------------------
# mark_notified
# ---------------------------------------------------------------------------


class TestMarkNotified:
    def test_sets_timestamp(self, store: ProposalStore) -> None:
        _make_pending(store)
        before = datetime.now(timezone.utc)
        store.mark_notified("spotify_play_song")
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.notified_at is not None
        assert proposal.notified_at >= before

    def test_idempotent_no_re_notify(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.mark_notified("spotify_play_song")
        first = store.get_by_id("spotify_play_song")
        assert first is not None
        first_notified = first.notified_at

        store.mark_notified("spotify_play_song")
        second = store.get_by_id("spotify_play_song")
        assert second is not None
        # Bleibt beim alten Timestamp -- kein Re-Notify
        assert second.notified_at == first_notified

    def test_unknown_proposal_raises(self, store: ProposalStore) -> None:
        with pytest.raises(ProposalNotFoundError):
            store.mark_notified("nope")


# ---------------------------------------------------------------------------
# update_status + History-Audit
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_to_in_bearbeitung(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.update_status("spotify_play_song", "in_bearbeitung", "lera")
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.status == "in_bearbeitung"

    def test_history_entry_appended(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.update_status(
            "spotify_play_song", "in_bearbeitung", "lera", note="bin dran"
        )
        history = store.get_history("spotify_play_song")
        assert len(history) == 2
        assert history[1].old_status == "in_pruefung"
        assert history[1].new_status == "in_bearbeitung"
        assert history[1].changed_by == "lera"
        assert history[1].note == "bin dran"

    def test_rejected_with_reason(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.update_status(
            "spotify_play_song",
            "abgelehnt",
            "lera",
            note="zu speziell",
            rejected_reason="nutze ich nicht",
        )
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.status == "abgelehnt"
        assert proposal.rejected_reason == "nutze ich nicht"

    def test_rejected_reason_kept_on_status_revert(self, store: ProposalStore) -> None:
        """COALESCE-Verhalten: alter rejected_reason bleibt erhalten."""
        _make_pending(store)
        store.update_status(
            "spotify_play_song",
            "abgelehnt",
            "lera",
            rejected_reason="passt nicht",
        )
        store.update_status("spotify_play_song", "in_pruefung", "lera")
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        # Reason bleibt fuer Audit-Zwecke erhalten
        assert proposal.rejected_reason == "passt nicht"

    def test_no_op_when_same_status(self, store: ProposalStore) -> None:
        _make_pending(store)
        before = store.get_history("spotify_play_song")
        store.update_status("spotify_play_song", "in_pruefung", "lera")
        after = store.get_history("spotify_play_song")
        assert len(before) == len(after) == 1

    def test_invalid_status_raises(self, store: ProposalStore) -> None:
        _make_pending(store)
        with pytest.raises(InvalidStatusError):
            store.update_status(
                "spotify_play_song",
                "kaputt",
                "lera",  # type: ignore[arg-type]
            )

    def test_invalid_changed_by_raises(self, store: ProposalStore) -> None:
        _make_pending(store)
        with pytest.raises(InvalidStatusError):
            store.update_status(
                "spotify_play_song",
                "in_bearbeitung",
                "stranger",  # type: ignore[arg-type]
            )

    def test_unknown_proposal_raises(self, store: ProposalStore) -> None:
        with pytest.raises(ProposalNotFoundError):
            store.update_status("nope", "in_bearbeitung", "lera")


# ---------------------------------------------------------------------------
# set_implementation
# ---------------------------------------------------------------------------


class TestSetImplementation:
    def test_sets_path(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.set_implementation(
            "spotify_play_song",
            "src/elder_berry/comms/commands/spotify_commands.py",
        )
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert (
            proposal.implemented_in
            == "src/elder_berry/comms/commands/spotify_commands.py"
        )

    def test_unknown_proposal_raises(self, store: ProposalStore) -> None:
        with pytest.raises(ProposalNotFoundError):
            store.set_implementation("nope", "x.py")


# ---------------------------------------------------------------------------
# list_active / list_by_status
# ---------------------------------------------------------------------------


class TestListing:
    def test_list_active_only_active_statuses(self, store: ProposalStore) -> None:
        _make_pending(store, intent="a", title="A")
        _make_pending(store, intent="b", title="B")
        _make_pending(store, intent="c", title="C")
        store.update_status("b", "abgelehnt", "lera")
        store.update_status("c", "in_bearbeitung", "lera")

        active = store.list_active()
        ids = {p.id for p in active}
        assert "a" in ids
        assert "c" in ids
        assert "b" not in ids

    def test_list_active_sorted_by_last_triggered_desc(
        self, store: ProposalStore
    ) -> None:
        _make_pending(store, intent="old", title="Old")
        _make_pending(store, intent="new", title="New")
        store.add_trigger("old", "old reactivation", None, None)
        # 'old' hat nun den juengsten last_triggered_at
        active = store.list_active()
        assert active[0].id == "old"

    def test_list_active_respects_limit(self, store: ProposalStore) -> None:
        for i in range(20):
            _make_pending(store, intent=f"intent_{i}", title=f"T{i}")
        active = store.list_active(limit=5)
        assert len(active) == 5

    def test_list_by_status_filter(self, store: ProposalStore) -> None:
        _make_pending(store, intent="a", title="A")
        _make_pending(store, intent="b", title="B")
        store.update_status("b", "fertiggestellt", "lera")
        done = store.list_by_status("fertiggestellt")
        assert len(done) == 1
        assert done[0].id == "b"

    def test_list_by_status_none_returns_all(self, store: ProposalStore) -> None:
        _make_pending(store, intent="a", title="A")
        _make_pending(store, intent="b", title="B")
        all_p = store.list_by_status(None)
        assert len(all_p) == 2

    def test_list_by_status_invalid_raises(self, store: ProposalStore) -> None:
        with pytest.raises(InvalidStatusError):
            store.list_by_status("kaputt")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# search_similar (FTS5)
# ---------------------------------------------------------------------------


class TestSearchSimilar:
    def test_finds_by_title(self, store: ProposalStore) -> None:
        _make_pending(
            store,
            intent="spotify_play_song",
            title="Spotify-Steuerung",
            description_md="Spielt Tracks ueber die Spotify Web API.",
        )
        _make_pending(
            store,
            intent="pomodoro_timer",
            title="Pomodoro-Timer",
            description_md="Timer fuer Fokus-Zeiten.",
        )
        results = store.search_similar("Spotify")
        ids = [p.id for p in results]
        assert "spotify_play_song" in ids
        assert "pomodoro_timer" not in ids

    def test_finds_by_description(self, store: ProposalStore) -> None:
        _make_pending(
            store,
            intent="x",
            title="X",
            description_md="Fokus-Zeiten mit klarem Anfang und Ende.",
        )
        results = store.search_similar("Fokus")
        assert any(p.id == "x" for p in results)

    def test_empty_query_returns_empty(self, store: ProposalStore) -> None:
        _make_pending(store)
        assert store.search_similar("") == []
        assert store.search_similar("   ") == []

    def test_special_characters_dont_crash(self, store: ProposalStore) -> None:
        _make_pending(store)
        # FTS-Operatoren werden gestripped, kein OperationalError
        assert isinstance(store.search_similar('AND OR NOT "weird"'), list)

    def test_updated_description_reindexed(self, store: ProposalStore) -> None:
        """FTS muss auf UPDATE der description_md reagieren (Trigger plugin_proposals_au)."""
        proposal = _make_pending(
            store,
            description_md="Text ohne Marker.",
        )
        # description_md ueber raw SQL aendern (kein dedizierter Setter in API)
        store._conn.execute(  # type: ignore[attr-defined]
            "UPDATE plugin_proposals SET description_md = ? WHERE id = ?",
            ("Neu mit MarkerWort darin.", proposal.id),
        )
        store._conn.commit()  # type: ignore[attr-defined]
        results = store.search_similar("MarkerWort")
        assert any(p.id == proposal.id for p in results)


# ---------------------------------------------------------------------------
# get_triggers / get_history Reading
# ---------------------------------------------------------------------------


class TestReadHelpers:
    def test_get_triggers_orders_desc(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.add_trigger("spotify_play_song", "second", None, None)
        store.add_trigger("spotify_play_song", "third", None, None)
        triggers = store.get_triggers("spotify_play_song")
        # Neueste zuerst
        assert triggers[0].sample_message == "third"
        assert triggers[1].sample_message == "second"
        assert triggers[2].sample_message == "spiel was von Hans Zimmer"

    def test_get_triggers_limit(self, store: ProposalStore) -> None:
        _make_pending(store)
        for i in range(10):
            store.add_trigger("spotify_play_song", f"s{i}", None, None)
        triggers = store.get_triggers("spotify_play_song", limit=3)
        assert len(triggers) == 3

    def test_get_history_orders_asc(self, store: ProposalStore) -> None:
        _make_pending(store)
        store.update_status("spotify_play_song", "in_bearbeitung", "lera")
        store.update_status("spotify_play_song", "fertiggestellt", "lera")
        history = store.get_history("spotify_play_song")
        # Aelteste zuerst
        assert history[0].new_status == "in_pruefung"
        assert history[1].new_status == "in_bearbeitung"
        assert history[2].new_status == "fertiggestellt"

    def test_get_by_id_unknown_returns_none(self, store: ProposalStore) -> None:
        assert store.get_by_id("nope") is None
