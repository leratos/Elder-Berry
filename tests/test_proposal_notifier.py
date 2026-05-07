"""Tests: ProposalNotifier -- Matrix-Notification (Phase 78 Etappe 2)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from elder_berry.comms.proposal_notifier import ProposalNotifier
from elder_berry.tools.proposal_store import Proposal


def _make_proposal(
    id_: str = "spotify_play_song",
    title: str = "Spotify-Steuerung",
) -> Proposal:
    now = datetime.now(timezone.utc)
    return Proposal(
        id=id_,
        title=title,
        status="in_pruefung",
        description_md="kurz",
        suggested_category=None,
        suggested_priority=None,
        created_at=now,
        updated_at=now,
        trigger_count=3,
        last_triggered_at=now,
        notified_at=None,
        last_confidence=0.85,
        rejected_reason=None,
        implemented_in=None,
        related_proposals=[],
    )


class TestNotifyFormat:
    @pytest.mark.asyncio
    async def test_sends_to_configured_room(self) -> None:
        channel = AsyncMock()
        notifier = ProposalNotifier(
            channel=channel, room_id="!proposal_room:matrix.org"
        )
        await notifier.notify(_make_proposal(), recent_count=3, days=7)
        channel.send_text.assert_awaited_once()
        sent_room, sent_text = channel.send_text.await_args.args
        assert sent_room == "!proposal_room:matrix.org"
        assert "Spotify-Steuerung" in sent_text

    @pytest.mark.asyncio
    async def test_includes_count_and_window(self) -> None:
        channel = AsyncMock()
        notifier = ProposalNotifier(channel=channel, room_id="!r:x")
        await notifier.notify(_make_proposal(), recent_count=5, days=7)
        sent_text = channel.send_text.await_args.args[1]
        assert "5x in 7 Tagen" in sent_text

    @pytest.mark.asyncio
    async def test_dashboard_url_uses_proposal_id(self) -> None:
        channel = AsyncMock()
        notifier = ProposalNotifier(
            channel=channel,
            room_id="!r:x",
            dashboard_base_url="https://fern.example.com/",
        )
        await notifier.notify(_make_proposal("pomodoro_timer"), 3, 7)
        sent_text = channel.send_text.await_args.args[1]
        # Trailing slash in base_url wird gestripped, dann /proposals/<id>
        assert "https://fern.example.com/proposals/pomodoro_timer" in sent_text

    @pytest.mark.asyncio
    async def test_emoji_marker(self) -> None:
        channel = AsyncMock()
        notifier = ProposalNotifier(channel=channel, room_id="!r:x")
        await notifier.notify(_make_proposal(), 3, 7)
        sent_text = channel.send_text.await_args.args[1]
        assert sent_text.startswith("💡")


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_send_failure_does_not_raise(self) -> None:
        """Fehler beim Versand bricht den Aggregator-Flow nicht ab."""
        channel = AsyncMock()
        channel.send_text.side_effect = RuntimeError("matrix down")
        notifier = ProposalNotifier(channel=channel, room_id="!r:x")
        # Darf NICHT werfen
        await notifier.notify(_make_proposal(), 3, 7)

    @pytest.mark.asyncio
    async def test_send_failure_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        channel = AsyncMock()
        channel.send_text.side_effect = RuntimeError("matrix down")
        notifier = ProposalNotifier(channel=channel, room_id="!r:x")
        with caplog.at_level("ERROR"):
            await notifier.notify(_make_proposal("x"), 3, 7)
        assert any("ProposalNotifier" in rec.message for rec in caplog.records)
        assert any("matrix down" in rec.message for rec in caplog.records)
