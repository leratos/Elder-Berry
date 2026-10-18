"""Tests für die Startmeldung der MatrixBridge (#1418 E1).

Die Startup-Summary wurde früher vor ``bridge.start()`` gesendet und scheiterte
systematisch mit "Nicht verbunden". Jetzt hinterlegt ``start_saleria`` sie per
``set_startup_message`` und ``_async_main`` sendet sie einmal nach ``connect()``.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from elder_berry.comms.bridge import MatrixBridge


def _make_channel(calls: list[str]) -> MagicMock:
    """Channel-Mock, der die Aufrufreihenfolge in ``calls`` protokolliert."""
    channel = MagicMock()

    async def _connect() -> None:
        calls.append("connect")

    async def _send_text(room_id: str, text: str) -> None:
        calls.append(f"send_text:{room_id}:{text}")

    async def _sync_loop() -> None:
        calls.append("sync_loop")

    channel.connect = AsyncMock(side_effect=_connect)
    channel.send_text = AsyncMock(side_effect=_send_text)
    channel.sync_loop = AsyncMock(side_effect=_sync_loop)
    return channel


def _make_bridge(channel: MagicMock) -> MatrixBridge:
    return MatrixBridge(
        channel=channel,
        assistant=MagicMock(),
        allowed_senders=frozenset({"@user:x"}),
    )


def _run_async_main(bridge: MatrixBridge) -> None:
    async def _test() -> None:
        bridge._loop = asyncio.get_running_loop()
        with (
            patch(
                "elder_berry.comms.bridge.RESTART_FLAG_FILE",
                MagicMock(exists=MagicMock(return_value=False)),
            ),
            patch(
                "elder_berry.comms.bridge.read_restart_timestamp",
                return_value=0.0,
            ),
            patch(
                "elder_berry.comms.bridge.send_restart_notification",
                new_callable=AsyncMock,
            ),
        ):
            await bridge._async_main()

    asyncio.run(_test())


class TestStartupMessage:
    def test_sent_once_after_connect(self):
        calls: list[str] = []
        channel = _make_channel(calls)
        bridge = _make_bridge(channel)
        bridge.set_startup_message("!room:x", "Saleria Startup\n\n✓ LLM: ok")

        _run_async_main(bridge)

        channel.send_text.assert_awaited_once_with(
            "!room:x", "Saleria Startup\n\n✓ LLM: ok"
        )
        send_call = "send_text:!room:x:Saleria Startup\n\n✓ LLM: ok"
        assert calls.index("connect") < calls.index(send_call)
        assert calls.index(send_call) < calls.index("sync_loop")

    def test_not_sent_before_start(self):
        """Das Hinterlegen allein darf nichts senden (Channel noch nicht verbunden)."""
        channel = _make_channel([])
        bridge = _make_bridge(channel)

        bridge.set_startup_message("!room:x", "Text")

        channel.send_text.assert_not_called()

    def test_send_failure_logs_warning_and_sync_loop_still_runs(self, caplog):
        calls: list[str] = []
        channel = _make_channel(calls)
        channel.send_text = AsyncMock(side_effect=RuntimeError("Nicht verbunden"))
        bridge = _make_bridge(channel)
        bridge.set_startup_message("!room:x", "Text")

        with caplog.at_level(logging.WARNING, logger="elder_berry.comms.bridge"):
            _run_async_main(bridge)

        assert "sync_loop" in calls
        assert any(
            "Startup-Summary an Matrix senden fehlgeschlagen" in r.getMessage()
            and r.levelno == logging.WARNING
            for r in caplog.records
        )

    def test_hanging_send_times_out_and_sync_loop_still_runs(self, caplog):
        """Ein haengendes room_send darf den Bridge-Start nicht blockieren
        (PR #388 Review): Timeout -> WARN, danach sync_loop."""
        calls: list[str] = []
        channel = _make_channel(calls)

        async def _hang(room_id: str, text: str) -> None:
            await asyncio.Event().wait()

        channel.send_text = AsyncMock(side_effect=_hang)
        bridge = _make_bridge(channel)
        bridge.set_startup_message("!room:x", "Text")

        with (
            patch("elder_berry.comms.bridge._STARTUP_MESSAGE_TIMEOUT_S", 0.05),
            caplog.at_level(logging.WARNING, logger="elder_berry.comms.bridge"),
        ):
            _run_async_main(bridge)

        assert "sync_loop" in calls
        assert any(
            "Startup-Summary an Matrix senden fehlgeschlagen: Timeout" in r.getMessage()
            for r in caplog.records
        )

    def test_no_message_set_sends_nothing(self):
        calls: list[str] = []
        channel = _make_channel(calls)
        bridge = _make_bridge(channel)

        _run_async_main(bridge)

        channel.send_text.assert_not_called()
        assert "sync_loop" in calls

    def test_sent_after_restart_notification(self):
        """Nach einem Saleria-Neustart kommen 'Bin wieder da!' UND die Summary."""
        order: list[str] = []
        channel = _make_channel(order)
        bridge = _make_bridge(channel)
        bridge.set_startup_message("!room:x", "Summary")

        async def _restart_notification(_channel) -> None:
            order.append("restart_notification")

        async def _test() -> None:
            bridge._loop = asyncio.get_running_loop()
            with (
                patch(
                    "elder_berry.comms.bridge.RESTART_FLAG_FILE",
                    MagicMock(exists=MagicMock(return_value=False)),
                ),
                patch(
                    "elder_berry.comms.bridge.read_restart_timestamp",
                    return_value=0.0,
                ),
                patch(
                    "elder_berry.comms.bridge.send_restart_notification",
                    side_effect=_restart_notification,
                ),
            ):
                await bridge._async_main()

        asyncio.run(_test())

        assert order.index("restart_notification") < order.index(
            "send_text:!room:x:Summary"
        )
