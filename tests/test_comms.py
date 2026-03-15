"""Tests: MessageChannel ABC, IncomingMessage DTO, MatrixBridge."""
import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
from elder_berry.comms.bridge import MatrixBridge
from elder_berry.core.assistant import AssistantResult


# ---------------------------------------------------------------------------
# Helper: async in sync ausführen (kein pytest-asyncio nötig)
# ---------------------------------------------------------------------------

def run_async(coro):
    """Führt eine Coroutine synchron aus (für Tests ohne pytest-asyncio)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Mock-Implementierung des MessageChannel ABC
# ---------------------------------------------------------------------------

class MockChannel(MessageChannel):
    """Testbare Implementierung des MessageChannel."""

    def __init__(self):
        self._connected = False
        self._callbacks = []
        self._sent_texts: list[tuple[str, str]] = []
        self._sent_audios: list[tuple[str, Path]] = []
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

    def on_message(self, callback) -> None:
        self._callbacks.append(callback)

    async def sync_loop(self) -> None:
        await self._sync_event.wait()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def simulate_message(self, msg: IncomingMessage) -> None:
        """Simuliert eine eingehende Nachricht (für Tests)."""
        for cb in self._callbacks:
            await cb(msg)


# ---------------------------------------------------------------------------
# IncomingMessage DTO
# ---------------------------------------------------------------------------

class TestIncomingMessage:
    def test_creation(self):
        msg = IncomingMessage(
            sender="@user:example.com",
            room_id="!room:example.com",
            body="Hallo!",
            timestamp=1710500000.0,
        )
        assert msg.sender == "@user:example.com"
        assert msg.room_id == "!room:example.com"
        assert msg.body == "Hallo!"
        assert msg.timestamp == 1710500000.0
        assert msg.raw is None

    def test_frozen(self):
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="hi", timestamp=0.0,
        )
        with pytest.raises(AttributeError):
            msg.body = "changed"

    def test_with_raw_data(self):
        raw = {"event_id": "$abc123"}
        msg = IncomingMessage(
            sender="@u:x", room_id="!r:x", body="hi",
            timestamp=0.0, raw=raw,
        )
        assert msg.raw == {"event_id": "$abc123"}

    def test_equality(self):
        args = dict(sender="@u:x", room_id="!r:x", body="hi", timestamp=1.0)
        assert IncomingMessage(**args) == IncomingMessage(**args)

    def test_inequality(self):
        msg1 = IncomingMessage(sender="@a:x", room_id="!r:x", body="hi", timestamp=1.0)
        msg2 = IncomingMessage(sender="@b:x", room_id="!r:x", body="hi", timestamp=1.0)
        assert msg1 != msg2


# ---------------------------------------------------------------------------
# MessageChannel ABC
# ---------------------------------------------------------------------------

class TestMessageChannelABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            MessageChannel()

    def test_mock_channel_implements_interface(self):
        channel = MockChannel()
        assert isinstance(channel, MessageChannel)

    def test_connect_disconnect(self):
        async def _test():
            channel = MockChannel()
            assert not channel.is_connected
            await channel.connect()
            assert channel.is_connected
            await channel.disconnect()
            assert not channel.is_connected

        run_async(_test())

    def test_send_text(self):
        async def _test():
            channel = MockChannel()
            await channel.connect()
            await channel.send_text("!room:x", "Hallo!")
            assert channel._sent_texts == [("!room:x", "Hallo!")]

        run_async(_test())

    def test_send_audio(self):
        async def _test():
            channel = MockChannel()
            await channel.connect()
            await channel.send_audio("!room:x", Path("/tmp/voice.ogg"))
            assert channel._sent_audios == [("!room:x", Path("/tmp/voice.ogg"))]

        run_async(_test())

    def test_on_message_callback(self):
        async def _test():
            channel = MockChannel()
            received = []
            channel.on_message(lambda msg: received.append(msg))

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="test", timestamp=1.0,
            )
            for cb in channel._callbacks:
                result = cb(msg)
                if asyncio.iscoroutine(result):
                    await result

            assert len(received) == 1
            assert received[0].body == "test"

        run_async(_test())

    def test_multiple_callbacks(self):
        async def _test():
            channel = MockChannel()
            results_a = []
            results_b = []

            async def cb_a(msg):
                results_a.append(msg)

            async def cb_b(msg):
                results_b.append(msg)

            channel.on_message(cb_a)
            channel.on_message(cb_b)

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="multi", timestamp=1.0,
            )
            await channel.simulate_message(msg)

            assert len(results_a) == 1
            assert len(results_b) == 1

        run_async(_test())


# ---------------------------------------------------------------------------
# MatrixBridge
# ---------------------------------------------------------------------------

class TestMatrixBridge:
    def _make_assistant_mock(self, response_text="Antwort", emotion="neutral"):
        assistant = MagicMock()
        assistant.process.return_value = AssistantResult(
            response=response_text,
            action_executed=None,
            action_success=False,
            emotion=emotion,
        )
        return assistant

    def test_bridge_creation(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)
        assert not bridge.is_running

    def test_bridge_start_stop(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)

        bridge.start()
        assert bridge.is_running

        time.sleep(0.2)

        bridge.stop()
        time.sleep(0.3)
        assert not bridge.is_running

    def test_bridge_double_start(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)

        bridge.start()
        bridge.start()  # Darf nicht crashen
        assert bridge.is_running

        bridge.stop()
        time.sleep(0.3)

    def test_bridge_stop_when_not_running(self):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(channel=channel, assistant=assistant)
        bridge.stop()  # Darf nicht crashen

    def test_handle_message_calls_assistant(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("Hallo zurück!")
            bridge = MatrixBridge(channel=channel, assistant=assistant)

            await channel.connect()
            channel.on_message(bridge._handle_message)

            msg = IncomingMessage(
                sender="@user:x", room_id="!room:x", body="Hi Saleria",
                timestamp=time.time(),
            )
            await bridge._handle_message(msg)

            assistant.process.assert_called_once_with("Hi Saleria")
            assert ("!room:x", "Hallo zurück!") in channel._sent_texts

        run_async(_test())

    def test_handle_message_empty_response(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock("")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="test", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert len(channel._sent_texts) == 0

        run_async(_test())

    def test_handle_message_assistant_error(self):
        async def _test():
            channel = MockChannel()
            assistant = MagicMock()
            assistant.process.side_effect = RuntimeError("LLM down")
            bridge = MatrixBridge(channel=channel, assistant=assistant)
            await channel.connect()

            msg = IncomingMessage(
                sender="@u:x", room_id="!r:x", body="test", timestamp=1.0,
            )
            await bridge._handle_message(msg)

            assert len(channel._sent_texts) == 1
            assert "Fehler" in channel._sent_texts[0][1]
            assert "RuntimeError" in channel._sent_texts[0][1]

        run_async(_test())

    def test_find_latest_audio_no_dir(self, tmp_path):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(
            channel=channel, assistant=assistant,
            audio_dir=tmp_path / "nonexistent",
        )
        assert bridge._find_latest_audio() is None

    def test_find_latest_audio_empty_dir(self, tmp_path):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(
            channel=channel, assistant=assistant,
            audio_dir=tmp_path,
        )
        assert bridge._find_latest_audio() is None

    def test_find_latest_audio_picks_newest(self, tmp_path):
        channel = MockChannel()
        assistant = self._make_assistant_mock()
        bridge = MatrixBridge(
            channel=channel, assistant=assistant,
            audio_dir=tmp_path,
        )

        old = tmp_path / "old.ogg"
        old.write_bytes(b"old")
        time.sleep(0.05)
        new = tmp_path / "new.ogg"
        new.write_bytes(b"new")

        result = bridge._find_latest_audio()
        assert result == new

    def test_async_main_connects_channel(self):
        async def _test():
            channel = MockChannel()
            assistant = self._make_assistant_mock()
            bridge = MatrixBridge(channel=channel, assistant=assistant)

            channel._sync_event.set()

            await bridge._async_main()
            assert len(channel._callbacks) == 1

        run_async(_test())
