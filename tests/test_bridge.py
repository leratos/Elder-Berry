"""Tests für MatrixBridge – Lifecycle, Dispatch, Filtering, Scheduler, ErrorAlerting.

test_comms.py deckt bereits ab: Basis-Lifecycle (start/stop/double), Command-Routing,
ClaudeAgent-Routing, extract_claude_message, Assistant-Aufrufe, Audio-Converter.

Dieser Testfile fokussiert sich auf:
- Alte-Nachricht-Filterung (timestamp <= _start_time)
- Sender-Whitelist
- Audio/File-Dispatch an AudioPipeline
- Pending-Confirmation-Intercept (confirm, cancel, modify, pending)
- _setup_error_alerting
- Scheduler-Manager-Integration
- Properties (_audio_to_matrix, is_running)
- _shutdown / _run_loop Fehlerbehandlung
- Restart-Erkennung in _async_main
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


from elder_berry.comms.bridge import MatrixBridge
from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
from elder_berry.comms.pending_confirmation import (
    PendingAction,
    PendingConfirmationStore,
)
from elder_berry.core.assistant import AssistantResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_async(coro):
    """Führt eine Coroutine synchron aus."""
    return asyncio.run(coro)


class MockChannel(MessageChannel):
    """Testbare Implementierung des MessageChannel."""

    def __init__(self):
        self._connected = False
        self._callbacks = []
        self._sent_texts: list[tuple[str, str]] = []
        self._sent_audios: list[tuple[str, Path]] = []
        self._sent_images: list[tuple[str, Path]] = []
        self._sent_files: list[tuple[str, Path]] = []
        self._sync_event = asyncio.Event()

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._sync_event.set()

    async def send_text(self, room_id: str, text: str) -> None:
        self._sent_texts.append((room_id, text))

    async def send_audio(self, room_id: str, audio_path: Path) -> None:
        self._sent_audios.append((room_id, audio_path))

    async def send_image(self, room_id: str, image_path: Path) -> None:
        self._sent_images.append((room_id, image_path))

    async def send_file(self, room_id: str, file_path: Path) -> None:
        self._sent_files.append((room_id, file_path))

    def on_message(self, callback) -> None:
        self._callbacks.append(callback)

    async def sync_loop(self) -> None:
        await self._sync_event.wait()

    @property
    def is_connected(self) -> bool:
        return self._connected


def _make_assistant(response: str = "Antwort", emotion: str = "neutral") -> MagicMock:
    assistant = MagicMock()
    assistant.process.return_value = AssistantResult(
        response=response,
        action_executed=None,
        action_success=False,
        emotion=emotion,
    )
    return assistant


def _make_msg(
    body: str = "Hallo",
    sender: str = "@user:x",
    room_id: str = "!r:x",
    timestamp: float | None = None,
    audio_data: bytes | None = None,
    file_data: bytes | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        sender=sender,
        room_id=room_id,
        body=body,
        timestamp=timestamp if timestamp is not None else time.time(),
        audio_data=audio_data,
        file_data=file_data,
    )


# Phase 57.4: Sentinel für den _make_bridge-Default, damit Tests einen
# explizit ``None`` als "kein Whitelist übergeben"-Signal reinreichen
# können (für die Fail-Closed-Regression-Tests), während der normale
# Default eine populated Menge ist, die alle Test-Sender enthält.
_UNSET = object()
_DEFAULT_TEST_SENDERS = frozenset({"@user:x", "@admin:x"})


def _make_bridge(
    channel: MockChannel | None = None,
    assistant: MagicMock | None = None,
    allowed_senders=_UNSET,
    pending_store: PendingConfirmationStore | None = None,
    **kwargs,
) -> tuple[MockChannel, MatrixBridge]:
    ch = channel or MockChannel()
    ast = assistant or _make_assistant()
    if allowed_senders is _UNSET:
        allowed_senders = _DEFAULT_TEST_SENDERS
    bridge = MatrixBridge(
        channel=ch,
        assistant=ast,
        allowed_senders=allowed_senders,
        pending_store=pending_store,
        **kwargs,
    )
    return ch, bridge


# ---------------------------------------------------------------------------
# Alte-Nachricht-Filterung
# ---------------------------------------------------------------------------


class TestOldMessageFiltering:
    def test_old_message_ignored(self):
        """Nachrichten mit timestamp <= _start_time werden ignoriert."""

        async def _test():
            ch, bridge = _make_bridge()
            bridge._start_time = 1000.0
            await ch.connect()
            ch.on_message(bridge._handle_message)

            msg = _make_msg(body="alte Nachricht", timestamp=999.0)
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 0

        run_async(_test())

    def test_exact_start_time_ignored(self):
        """Nachricht mit exaktem _start_time wird auch ignoriert (<=)."""

        async def _test():
            ch, bridge = _make_bridge()
            bridge._start_time = 1000.0

            msg = _make_msg(timestamp=1000.0)
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 0

        run_async(_test())

    def test_newer_message_processed(self):
        """Nachrichten nach _start_time werden verarbeitet."""

        async def _test():
            ch, bridge = _make_bridge()
            bridge._start_time = 1000.0

            msg = _make_msg(body="Hallo", timestamp=1001.0)
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) >= 1

        run_async(_test())

    def test_zero_timestamp_not_filtered(self):
        """Timestamp 0 wird nicht gefiltert (Sonderfall: timestamp > 0 Prüfung)."""

        async def _test():
            ch, bridge = _make_bridge()
            bridge._start_time = 1000.0

            msg = _make_msg(timestamp=0.0)
            await bridge._handle_message(msg)

            # Timestamp 0 passiert den Filter (> 0 ist False)
            assert len(ch._sent_texts) >= 1

        run_async(_test())


# ---------------------------------------------------------------------------
# Sender-Whitelist
# ---------------------------------------------------------------------------


class TestSenderWhitelist:
    def test_allowed_sender_processed(self):
        async def _test():
            ch, bridge = _make_bridge(
                allowed_senders=frozenset({"@user:x"}),
            )
            bridge._start_time = 0.0

            msg = _make_msg(sender="@user:x", timestamp=time.time())
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) >= 1

        run_async(_test())

    def test_unknown_sender_rejected(self):
        async def _test():
            ch, bridge = _make_bridge(
                allowed_senders=frozenset({"@user:x"}),
            )
            bridge._start_time = 0.0

            msg = _make_msg(sender="@hacker:evil.com", timestamp=time.time())
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 0

        run_async(_test())

    def test_no_whitelist_rejects_all(self):
        """Phase 57.4: strikt fail-closed.

        Frühere Design-Entscheidung (Phase 32): leere/None allowed_senders
        deaktivierte den Filter. Mit Phase 57.4 ist das umgekehrt – die
        Bridge lehnt jede Nachricht ab, wenn die Whitelist fehlt oder leer
        ist. Der Startup-Code in start_saleria.py stellt zusätzlich sicher,
        dass die Bridge in Produktion gar nicht erst mit None gebaut wird,
        aber Dev-/Test-Pfade erreichen diesen Zustand direkt.
        """

        async def _test():
            ch, bridge = _make_bridge(allowed_senders=None)
            bridge._start_time = 0.0

            msg = _make_msg(sender="@anyone:x", timestamp=time.time())
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 0

        run_async(_test())

    def test_empty_whitelist_rejects_all(self):
        """Phase 57.4: leere Menge ist genauso streng wie None."""

        async def _test():
            ch, bridge = _make_bridge(allowed_senders=frozenset())
            bridge._start_time = 0.0

            msg = _make_msg(sender="@anyone:x", timestamp=time.time())
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 0

        run_async(_test())

    def test_multiple_allowed_senders(self):
        """Mehrere erlaubte Sender: beide werden akzeptiert."""

        async def _test():
            ch, bridge = _make_bridge(
                allowed_senders=frozenset({"@user:x", "@admin:x"}),
            )
            bridge._start_time = 0.0

            msg1 = _make_msg(sender="@user:x", timestamp=time.time())
            msg2 = _make_msg(sender="@admin:x", timestamp=time.time())
            await bridge._handle_message(msg1)
            await bridge._handle_message(msg2)

            assert len(ch._sent_texts) == 2

        run_async(_test())


# ---------------------------------------------------------------------------
# Audio-Dispatch
# ---------------------------------------------------------------------------


class TestAudioDispatch:
    def test_audio_message_dispatched_to_pipeline(self):
        """Nachrichten mit audio_data gehen an AudioPipeline."""

        async def _test():
            ch, bridge = _make_bridge()
            bridge._start_time = 0.0
            bridge._audio.handle_audio_message = AsyncMock()

            msg = _make_msg(audio_data=b"\x00\x01\x02", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._audio.handle_audio_message.assert_called_once_with(msg)

        run_async(_test())

    def test_audio_message_not_sent_to_assistant(self):
        """Audio-Nachrichten werden NICHT an den Assistant delegiert."""

        async def _test():
            assistant = _make_assistant()
            ch, bridge = _make_bridge(assistant=assistant)
            bridge._start_time = 0.0
            bridge._audio.handle_audio_message = AsyncMock()

            msg = _make_msg(audio_data=b"audio", timestamp=time.time())
            await bridge._handle_message(msg)

            assistant.process.assert_not_called()

        run_async(_test())


# ---------------------------------------------------------------------------
# File-Dispatch
# ---------------------------------------------------------------------------


class TestFileDispatch:
    def test_file_message_dispatched_to_pipeline(self):
        """Nachrichten mit file_data gehen an AudioPipeline.handle_file_message."""

        async def _test():
            ch, bridge = _make_bridge()
            bridge._start_time = 0.0
            bridge._audio.handle_file_message = AsyncMock()

            msg = _make_msg(file_data=b"%PDF", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._audio.handle_file_message.assert_called_once_with(msg)

        run_async(_test())

    def test_file_message_not_sent_to_assistant(self):
        """File-Nachrichten werden NICHT an den Assistant delegiert."""

        async def _test():
            assistant = _make_assistant()
            ch, bridge = _make_bridge(assistant=assistant)
            bridge._start_time = 0.0
            bridge._audio.handle_file_message = AsyncMock()

            msg = _make_msg(file_data=b"data", timestamp=time.time())
            await bridge._handle_message(msg)

            assistant.process.assert_not_called()

        run_async(_test())


# ---------------------------------------------------------------------------
# Pending-Confirmation-Intercept
# ---------------------------------------------------------------------------


class TestPendingConfirmation:
    def _make_pending_store(
        self, response_type: str, action: PendingAction | None = None
    ):
        store = MagicMock(spec=PendingConfirmationStore)
        store.check_response.return_value = (response_type, action)
        return store

    def _default_action(self) -> PendingAction:
        return PendingAction(
            action_type="mail_reply",
            description="Draft für #4523",
            data={"to": "info@firma.de", "draft_text": "Danke!"},
        )

    def test_confirm_routes_to_handler(self):
        """'ja' bei pending → handle_pending_confirm."""

        async def _test():
            action = self._default_action()
            store = self._make_pending_store("confirm", action)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0
            bridge._handler.handle_pending_confirm = AsyncMock()

            msg = _make_msg(body="ja", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._handler.handle_pending_confirm.assert_called_once_with(msg, action)

        run_async(_test())

    def test_cancel_sends_verworfen(self):
        """'nein' bei pending → Verworfen-Text."""

        async def _test():
            action = self._default_action()
            store = self._make_pending_store("cancel", action)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0

            msg = _make_msg(body="nein", timestamp=time.time())
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 1
            assert "Verworfen" in ch._sent_texts[0][1]

        run_async(_test())

    def test_modify_routes_to_handler(self):
        """'ändern:' bei pending → handle_pending_modify."""

        async def _test():
            action = self._default_action()
            store = self._make_pending_store("modify", action)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0
            bridge._handler.handle_pending_modify = AsyncMock()

            msg = _make_msg(body="ändern: kürzer bitte", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._handler.handle_pending_modify.assert_called_once_with(msg, action)

        run_async(_test())

    def test_pending_state_sends_hint(self):
        """Andere Nachricht bei pending → Hinweis auf offene Aktion."""

        async def _test():
            action = self._default_action()
            store = self._make_pending_store("pending", action)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0

            msg = _make_msg(body="irgendwas anderes", timestamp=time.time())
            await bridge._handle_message(msg)

            assert len(ch._sent_texts) == 1
            text = ch._sent_texts[0][1]
            assert "offene Aktion" in text
            assert "mail_reply" in text

        run_async(_test())

    def test_no_pending_passes_through(self):
        """Ohne pending → weiter an Command/LLM."""

        async def _test():
            store = self._make_pending_store("none", None)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0

            msg = _make_msg(body="Hallo", timestamp=time.time())
            await bridge._handle_message(msg)

            # Sollte bei LLM-Fallback landen
            assert len(ch._sent_texts) >= 1

        run_async(_test())


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestBridgeProperties:
    def test_is_running_initially_false(self):
        _, bridge = _make_bridge()
        assert bridge.is_running is False

    def test_is_running_after_start(self):
        ch, bridge = _make_bridge()
        bridge.start()
        try:
            assert bridge.is_running is True
        finally:
            bridge.stop()
            time.sleep(0.3)

    def test_audio_to_matrix_delegates(self):
        """_audio_to_matrix delegiert an AudioPipeline.audio_to_matrix property."""
        _, bridge = _make_bridge()
        # audio_to_matrix ist eine Property → Mock auf Instanz-Level
        with patch.object(
            type(bridge._audio),
            "audio_to_matrix",
            new_callable=lambda: property(lambda self: True),
        ):
            assert bridge._audio_to_matrix is True
        with patch.object(
            type(bridge._audio),
            "audio_to_matrix",
            new_callable=lambda: property(lambda self: False),
        ):
            assert bridge._audio_to_matrix is False


# ---------------------------------------------------------------------------
# extract_claude_message (ergänzende Edge Cases zu test_comms.py)
# ---------------------------------------------------------------------------


class TestExtractClaudeMessageEdgeCases:
    def test_claude_mixed_case(self):
        result = MatrixBridge.extract_claude_message('ClAuDe "test"')
        assert result == "test"

    def test_claude_in_middle_of_word(self):
        # "claude" muss als Substring vorkommen
        result = MatrixBridge.extract_claude_message('preCLAUDEpost "test"')
        assert result == "test"

    def test_multiple_quotes_takes_first(self):
        result = MatrixBridge.extract_claude_message(
            'Claude "erster" ignoriert "zweiter"'
        )
        assert result == "erster"

    def test_unicode_in_quotes(self):
        result = MatrixBridge.extract_claude_message('Claude "Schöne Grüße 🎉"')
        assert result == "Schöne Grüße 🎉"


# ---------------------------------------------------------------------------
# Lifecycle – _run_loop & _shutdown
# ---------------------------------------------------------------------------


class TestBridgeLifecycle:
    def test_start_sets_running(self):
        ch, bridge = _make_bridge()
        bridge.start()
        assert bridge._running is True
        assert bridge._thread is not None
        bridge.stop()
        time.sleep(0.3)

    def test_stop_clears_state(self):
        ch, bridge = _make_bridge()
        bridge.start()
        time.sleep(0.2)
        bridge.stop()
        time.sleep(0.3)
        assert bridge._running is False
        assert bridge._loop is None
        assert bridge._thread is None

    def test_double_stop_safe(self):
        ch, bridge = _make_bridge()
        bridge.stop()  # nicht gestartet
        bridge.stop()  # nochmal

    def test_run_loop_catches_exception(self):
        """_run_loop fängt Exceptions und setzt _running auf False."""
        ch, bridge = _make_bridge()
        bridge._running = True

        with patch.object(bridge, "_async_main", side_effect=RuntimeError("boom")):
            bridge._run_loop()

        assert bridge._running is False

    def test_shutdown_disconnects_channel(self):
        async def _test():
            ch, bridge = _make_bridge()
            await ch.connect()
            assert ch.is_connected

            await bridge._shutdown()
            assert not ch.is_connected

        run_async(_test())

    def test_shutdown_disconnect_error_ignored(self):
        """Fehler beim Disconnect werden ignoriert."""

        async def _test():
            ch, bridge = _make_bridge()
            ch.disconnect = AsyncMock(side_effect=RuntimeError("disconnect failed"))

            # Darf nicht crashen
            await bridge._shutdown()

        run_async(_test())


# ---------------------------------------------------------------------------
# _async_main – Restart-Erkennung
# ---------------------------------------------------------------------------


class TestAsyncMainRestart:
    def test_normal_start_without_restart_flag(self):
        """Ohne Restart-Flag: _start_time ≈ now, kein Cooldown."""

        async def _test():
            ch, bridge = _make_bridge()
            ch._sync_event.set()  # sync_loop sofort beenden

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
                before = time.time()
                await bridge._async_main()
                after = time.time()

            # Float-Toleranz: _start_time sollte im Bereich [before-1, after+1] liegen
            assert before - 1 <= bridge._start_time <= after + 1
            assert bridge._restart_cooldown_until == 0.0

        run_async(_test())

    def test_restart_with_server_timestamp(self):
        """Mit Restart-Flag + server_ts: _start_time = server_ts, Cooldown aktiv."""

        async def _test():
            ch, bridge = _make_bridge()
            ch._sync_event.set()

            with (
                patch(
                    "elder_berry.comms.bridge.RESTART_FLAG_FILE",
                    MagicMock(exists=MagicMock(return_value=True)),
                ),
                patch(
                    "elder_berry.comms.bridge.read_restart_timestamp",
                    return_value=1700000.0,
                ),
                patch(
                    "elder_berry.comms.bridge.send_restart_notification",
                    new_callable=AsyncMock,
                ),
            ):
                await bridge._async_main()

            assert bridge._start_time == 1700000.0
            assert bridge._restart_cooldown_until > 0.0

        run_async(_test())

    def test_restart_without_server_timestamp(self):
        """Restart-Flag aber kein server_ts: _start_time = now + 10."""

        async def _test():
            ch, bridge = _make_bridge()
            ch._sync_event.set()

            with (
                patch(
                    "elder_berry.comms.bridge.RESTART_FLAG_FILE",
                    MagicMock(exists=MagicMock(return_value=True)),
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
                before = time.time()
                await bridge._async_main()

            # start_time sollte ca. now + 10 sein
            assert bridge._start_time >= before + 9

        run_async(_test())


# ---------------------------------------------------------------------------
# _setup_error_alerting
# ---------------------------------------------------------------------------


class TestErrorAlerting:
    def test_setup_with_collector_handler(self):
        """Error-Alerting wird korrekt verdrahtet wenn ErrorCollectorHandler existiert."""
        from elder_berry.core.error_collector import ErrorCollectorHandler

        ch, bridge = _make_bridge()
        bridge._alert_room_id = "!alerts:x"
        bridge._loop = asyncio.new_event_loop()

        collector = ErrorCollectorHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(collector)

        try:
            bridge._setup_error_alerting()
            assert collector._alert_callback is not None
        finally:
            root_logger.removeHandler(collector)
            bridge._loop.close()

    def test_setup_without_collector_handler(self):
        """Ohne ErrorCollectorHandler im Root-Logger passiert nichts."""
        ch, bridge = _make_bridge()
        bridge._alert_room_id = "!alerts:x"
        bridge._loop = asyncio.new_event_loop()

        try:
            # Darf nicht crashen
            bridge._setup_error_alerting()
        finally:
            bridge._loop.close()


# ---------------------------------------------------------------------------
# Scheduler-Manager-Integration
# ---------------------------------------------------------------------------


class TestSchedulerManagerIntegration:
    def test_async_main_creates_scheduler_manager(self):
        """_async_main erstellt und startet den SchedulerManager."""

        async def _test():
            ch, bridge = _make_bridge()
            ch._sync_event.set()

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

            assert bridge._scheduler_mgr is not None

        run_async(_test())

    def test_stop_calls_scheduler_stop_all(self):
        """stop() ruft scheduler_mgr.stop_all() auf."""
        ch, bridge = _make_bridge()
        bridge._running = True
        mock_mgr = MagicMock()
        bridge._scheduler_mgr = mock_mgr

        bridge.stop()
        mock_mgr.stop_all.assert_called_once()

    def test_scheduler_with_alert_monitor(self):
        """AlertMonitor wird im SchedulerManager registriert."""

        async def _test():
            alert_monitor = MagicMock()
            alert_monitor.is_running = False

            ch, bridge = _make_bridge(
                alert_monitor=alert_monitor,
                alert_room_id="!alerts:x",
            )
            ch._sync_event.set()

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

            mgr = bridge._scheduler_mgr
            # AlertMonitor sollte registriert sein
            assert mgr is not None
            registered_names = [name for name, _ in mgr._schedulers]
            assert "AlertMonitor" in registered_names

        run_async(_test())

    def test_scheduler_with_reminder(self):
        """ReminderScheduler wird registriert wenn vorhanden."""

        async def _test():
            reminder = MagicMock()
            reminder.is_running = False

            ch, bridge = _make_bridge(reminder_scheduler=reminder)
            ch._sync_event.set()

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

            registered_names = [name for name, _ in bridge._scheduler_mgr._schedulers]
            assert "ReminderScheduler" in registered_names

        run_async(_test())


# ---------------------------------------------------------------------------
# Dispatch-Priorität (Reihenfolge der Checks)
# ---------------------------------------------------------------------------


class TestDispatchPriority:
    def test_audio_before_pending(self):
        """Audio-Nachrichten werden VOR dem Pending-Check dispatcht."""

        async def _test():
            store = MagicMock(spec=PendingConfirmationStore)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0
            bridge._audio.handle_audio_message = AsyncMock()

            msg = _make_msg(audio_data=b"audio", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._audio.handle_audio_message.assert_called_once()
            store.check_response.assert_not_called()

        run_async(_test())

    def test_file_before_pending(self):
        """File-Nachrichten werden VOR dem Pending-Check dispatcht."""

        async def _test():
            store = MagicMock(spec=PendingConfirmationStore)
            ch, bridge = _make_bridge(pending_store=store)
            bridge._start_time = 0.0
            bridge._audio.handle_file_message = AsyncMock()

            msg = _make_msg(file_data=b"pdf", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._audio.handle_file_message.assert_called_once()
            store.check_response.assert_not_called()

        run_async(_test())

    def test_pending_before_command(self):
        """Pending-Confirm wird VOR dem Command-Router geprüft."""

        async def _test():
            action = PendingAction(
                action_type="mail_reply",
                description="Draft",
                data={},
            )
            store = MagicMock(spec=PendingConfirmationStore)
            store.check_response.return_value = ("confirm", action)

            remote = MagicMock()
            ch, bridge = _make_bridge(
                pending_store=store,
                remote_commands=remote,
            )
            bridge._start_time = 0.0
            bridge._handler.handle_pending_confirm = AsyncMock()

            msg = _make_msg(body="ja", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._handler.handle_pending_confirm.assert_called_once()
            remote.parse_command.assert_not_called()

        run_async(_test())

    def test_command_before_claude(self):
        """Commands haben Priorität vor Claude-Agent."""

        async def _test():
            remote = MagicMock()
            remote.parse_command.return_value = "status"

            claude = MagicMock()

            ch, bridge = _make_bridge(
                remote_commands=remote,
                claude_agent=claude,
            )
            bridge._start_time = 0.0
            bridge._handler.handle_remote_command = AsyncMock()

            msg = _make_msg(body="status", timestamp=time.time())
            await bridge._handle_message(msg)

            bridge._handler.handle_remote_command.assert_called_once()
            claude.process.assert_not_called()

        run_async(_test())
