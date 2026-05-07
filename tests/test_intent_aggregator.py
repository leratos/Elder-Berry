"""Tests: ProposalIntentAggregator -- Threshold + Filter (Phase 78 Etappe 2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from elder_berry.tools.intent_aggregator import ProposalIntentAggregator
from elder_berry.tools.proposal_store import ProposalStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ProposalStore:
    s = ProposalStore(db_path=tmp_path / "p.db")
    yield s
    s.close()


@pytest.fixture
def notifier() -> AsyncMock:
    n = AsyncMock()
    # Default: Send erfolgreich. Tests fuer Send-Fail-Pfad ueberschreiben das.
    n.notify = AsyncMock(return_value=True)
    return n


@pytest.fixture
def secret_store() -> MagicMock:
    """SecretStore-Mock mit funktionierendem get_or_none/set."""
    s = MagicMock()
    s._values = {}

    def _get_or_none(key: str) -> str | None:
        return s._values.get(key)

    def _set(key: str, value: str) -> None:
        s._values[key] = value

    s.get_or_none.side_effect = _get_or_none
    s.set.side_effect = _set
    return s


@pytest.fixture
def aggregator(
    store: ProposalStore,
    notifier: AsyncMock,
    secret_store: MagicMock,
) -> ProposalIntentAggregator:
    return ProposalIntentAggregator(
        store=store, notifier=notifier, secret_store=secret_store
    )


# ---------------------------------------------------------------------------
# Salt-Bootstrap
# ---------------------------------------------------------------------------


class TestSaltBootstrap:
    def test_uses_existing_salt(
        self, store: ProposalStore, notifier: AsyncMock, secret_store: MagicMock
    ) -> None:
        secret_store._values["proposal_sender_salt"] = "existing_salt_123"
        agg = ProposalIntentAggregator(store, notifier, secret_store)
        # Direkter Zugriff auf private Variable nur fuer Test-Zwecke
        assert agg._salt == "existing_salt_123"
        # Kein set() weil Salt schon existierte
        secret_store.set.assert_not_called()

    def test_generates_and_persists_when_missing(
        self, store: ProposalStore, notifier: AsyncMock, secret_store: MagicMock
    ) -> None:
        agg = ProposalIntentAggregator(store, notifier, secret_store)
        assert agg._salt
        assert len(agg._salt) >= 32
        secret_store.set.assert_called_once()
        key, value = secret_store.set.call_args.args
        assert key == "proposal_sender_salt"
        assert value == agg._salt

    def test_reuse_persisted_salt_on_reconstruct(
        self, store: ProposalStore, notifier: AsyncMock, secret_store: MagicMock
    ) -> None:
        agg1 = ProposalIntentAggregator(store, notifier, secret_store)
        first_salt = agg1._salt
        agg2 = ProposalIntentAggregator(store, notifier, secret_store)
        assert agg2._salt == first_salt


# ---------------------------------------------------------------------------
# Sender-Hashing
# ---------------------------------------------------------------------------


class TestSenderHash:
    @pytest.mark.asyncio
    async def test_sender_hashed_not_stored_plaintext(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="hi",
            sender="@alice:matrix.org",
            confidence=0.9,
        )
        triggers = store.get_triggers("x")
        assert len(triggers) == 1
        assert triggers[0].sender_hash != "@alice:matrix.org"
        # SHA256-Hex ist 64 Zeichen
        assert triggers[0].sender_hash is not None
        assert len(triggers[0].sender_hash) == 64

    @pytest.mark.asyncio
    async def test_same_sender_same_hash(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="a",
            sender="@alice:matrix.org",
            confidence=0.9,
        )
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="b",
            sender="@alice:matrix.org",
            confidence=0.9,
        )
        triggers = store.get_triggers("x")
        assert triggers[0].sender_hash == triggers[1].sender_hash

    @pytest.mark.asyncio
    async def test_different_senders_different_hashes(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="a",
            sender="@alice:matrix.org",
            confidence=0.9,
        )
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="b",
            sender="@bob:matrix.org",
            confidence=0.9,
        )
        triggers = store.get_triggers("x")
        hashes = {t.sender_hash for t in triggers}
        assert len(hashes) == 2


# ---------------------------------------------------------------------------
# Filter (Confidence + Smalltalk + leerer Intent)
# ---------------------------------------------------------------------------


class TestFilter:
    @pytest.mark.asyncio
    async def test_empty_intent_skipped(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="",
            title="X",
            description="d",
            sample="s",
            sender="@a:x",
            confidence=0.9,
        )
        assert store.list_by_status(None) == []

    @pytest.mark.asyncio
    async def test_smalltalk_intent_skipped(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="jokes",
            title="Witze",
            description="d",
            sample="erzaehl mal",
            sender="@a:x",
            confidence=0.9,
        )
        assert store.list_by_status(None) == []

    @pytest.mark.asyncio
    async def test_below_confidence_threshold_skipped(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s",
            sender="@a:x",
            confidence=0.5,
        )
        assert store.list_by_status(None) == []

    @pytest.mark.asyncio
    async def test_at_threshold_accepted(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s",
            sender="@a:x",
            confidence=0.7,
        )
        assert store.get_by_id("x") is not None


# ---------------------------------------------------------------------------
# Sample-Trim
# ---------------------------------------------------------------------------


class TestSampleTrim:
    @pytest.mark.asyncio
    async def test_short_sample_unchanged(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        sample = "kurzer text"
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample=sample,
            sender="@a:x",
            confidence=0.9,
        )
        triggers = store.get_triggers("x")
        assert triggers[0].sample_message == sample

    @pytest.mark.asyncio
    async def test_long_sample_trimmed(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        sample = "a" * 500
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample=sample,
            sender="@a:x",
            confidence=0.9,
        )
        triggers = store.get_triggers("x")
        assert len(triggers[0].sample_message) <= 200
        # Endet mit Ellipsis-Marker
        assert triggers[0].sample_message.endswith("…")


# ---------------------------------------------------------------------------
# Routing: Neuer Intent vs. bekannter Intent
# ---------------------------------------------------------------------------


class TestRouting:
    @pytest.mark.asyncio
    async def test_first_call_creates_pending(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="spotify_play_song",
            title="Spotify-Steuerung",
            description="Spielt Tracks ueber Spotify Web API.",
            sample="spiel was von Hans Zimmer",
            sender="@a:x",
            confidence=0.85,
            category="medien",
        )
        proposal = store.get_by_id("spotify_play_song")
        assert proposal is not None
        assert proposal.title == "Spotify-Steuerung"
        assert proposal.status == "in_pruefung"
        assert proposal.suggested_category == "medien"
        assert proposal.trigger_count == 1
        assert "Spotify Web API" in proposal.description_md
        assert "Hans Zimmer" in proposal.description_md

    @pytest.mark.asyncio
    async def test_empty_description_gets_placeholder(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="",
            sample="s",
            sender="@a:x",
            confidence=0.9,
        )
        proposal = store.get_by_id("x")
        assert proposal is not None
        assert "Beschreibung folgt" in proposal.description_md

    @pytest.mark.asyncio
    async def test_second_call_adds_trigger_no_duplicate(
        self, aggregator: ProposalIntentAggregator, store: ProposalStore
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="a",
            sender="@a:x",
            confidence=0.9,
        )
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="b",
            sender="@a:x",
            confidence=0.9,
        )
        proposal = store.get_by_id("x")
        assert proposal is not None
        assert proposal.trigger_count == 2
        assert len(store.get_triggers("x")) == 2


# ---------------------------------------------------------------------------
# Threshold-Notification
# ---------------------------------------------------------------------------


class TestThresholdNotification:
    @pytest.mark.asyncio
    async def test_below_threshold_no_notify(
        self, aggregator: ProposalIntentAggregator, notifier: AsyncMock
    ) -> None:
        for _ in range(2):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample="s",
                sender="@a:x",
                confidence=0.9,
            )
        notifier.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_at_threshold_notifies_once(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        for i in range(3):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample=f"s{i}",
                sender="@a:x",
                confidence=0.9,
            )
        notifier.notify.assert_awaited_once()
        # mark_notified gesetzt
        proposal = store.get_by_id("x")
        assert proposal is not None
        assert proposal.notified_at is not None

    @pytest.mark.asyncio
    async def test_no_renotify_after_threshold(
        self, aggregator: ProposalIntentAggregator, notifier: AsyncMock
    ) -> None:
        for i in range(5):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample=f"s{i}",
                sender="@a:x",
                confidence=0.9,
            )
        # Trotz 5 Aufrufen genau einmal benachrichtigt
        assert notifier.notify.await_count == 1

    @pytest.mark.asyncio
    async def test_old_triggers_excluded_from_window(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        """Alte Trigger ausserhalb des 7-Tage-Fensters loesen kein
        Notify aus, auch wenn lifetime trigger_count >= 3."""
        # Erster Trigger heute
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="recent",
            sender="@a:x",
            confidence=0.9,
        )
        # Zwei alte Trigger (30 Tage zurueck) direkt in DB einschleusen
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for i in range(2):
            store._conn.execute(  # type: ignore[attr-defined]
                "INSERT INTO plugin_proposal_triggers "
                "(proposal_id, triggered_at, sample_message, sender_hash, confidence) "
                "VALUES (?, ?, ?, ?, ?)",
                ("x", old_ts, f"old{i}", "h", 0.9),
            )
        store._conn.execute(  # type: ignore[attr-defined]
            "UPDATE plugin_proposals SET trigger_count = 3 WHERE id = ?",
            ("x",),
        )
        store._conn.commit()  # type: ignore[attr-defined]
        # Erneuter Aufruf: Window-Count ist nur 2 (recent + neue), die alten
        # zaehlen nicht mit
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="recent2",
            sender="@a:x",
            confidence=0.9,
        )
        # Nur recent + recent2 im 7-Tage-Fenster -> 2 < THRESHOLD_COUNT(3)
        notifier.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_in_bearbeitung_no_notify(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s",
            sender="@a:x",
            confidence=0.9,
        )
        store.update_status("x", "in_bearbeitung", "lera")
        for i in range(5):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample=f"s{i}",
                sender="@a:x",
                confidence=0.9,
            )
        notifier.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_abgelehnt_triggers_logged_no_notify(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s",
            sender="@a:x",
            confidence=0.9,
        )
        store.update_status("x", "abgelehnt", "lera", rejected_reason="nope")
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s2",
            sender="@a:x",
            confidence=0.9,
        )
        # Trigger wurde gezaehlt fuer Statistik
        assert store.get_by_id("x").trigger_count == 2  # type: ignore[union-attr]
        # Aber keine Notification
        notifier.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_fertiggestellt_triggers_logged_no_notify(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s",
            sender="@a:x",
            confidence=0.9,
        )
        store.update_status("x", "fertiggestellt", "lera")
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s2",
            sender="@a:x",
            confidence=0.9,
        )
        notifier.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_called_with_count_and_days(
        self,
        aggregator: ProposalIntentAggregator,
        notifier: AsyncMock,
    ) -> None:
        for i in range(3):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample=f"s{i}",
                sender="@a:x",
                confidence=0.9,
            )
        kwargs = notifier.notify.await_args.kwargs
        assert kwargs["recent_count"] == 3
        assert kwargs["days"] == 7

    @pytest.mark.asyncio
    async def test_notify_failure_does_not_mark_notified(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        """GitHub-Review P2: Wenn der Notifier-Send fehlschlaegt
        (returnt False), darf notified_at NICHT gesetzt werden -- sonst
        wuerde die Nachricht permanent verloren gehen, weil die
        nachfolgenden Trigger durch den notified_at-Check gefiltert
        werden."""
        notifier.notify = AsyncMock(return_value=False)
        for i in range(3):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample=f"s{i}",
                sender="@a:x",
                confidence=0.9,
            )
        # Send wurde versucht (3x reichen fuer Threshold)
        assert notifier.notify.await_count == 1
        # Aber notified_at bleibt None -- Retry beim naechsten Trigger
        proposal = store.get_by_id("x")
        assert proposal is not None
        assert proposal.notified_at is None

    @pytest.mark.asyncio
    async def test_notify_retry_on_next_trigger_when_send_failed(
        self,
        aggregator: ProposalIntentAggregator,
        store: ProposalStore,
        notifier: AsyncMock,
    ) -> None:
        """Nach Send-Fail beim ersten Threshold-Erreichen muss der
        naechste Trigger einen erneuten notify-Versuch ausloesen."""
        # 3 Trigger bei Send-Fehler
        notifier.notify = AsyncMock(return_value=False)
        for i in range(3):
            await aggregator.record(
                intent="x",
                title="X",
                description="d",
                sample=f"s{i}",
                sender="@a:x",
                confidence=0.9,
            )
        assert notifier.notify.await_count == 1
        # Send heilt sich -- naechster Trigger soll erneut versuchen
        notifier.notify = AsyncMock(return_value=True)
        await aggregator.record(
            intent="x",
            title="X",
            description="d",
            sample="s4",
            sender="@a:x",
            confidence=0.9,
        )
        assert notifier.notify.await_count == 1
        proposal = store.get_by_id("x")
        assert proposal is not None
        assert proposal.notified_at is not None
