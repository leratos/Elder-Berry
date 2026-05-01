"""Regression-Tests für Phase 57.4: matrix_allowed_senders strikt fail-closed.

Sichert die Design-Umkehrung gegenüber der alten Phase-32-Entscheidung ab,
dass eine leere oder fehlende ``matrix_allowed_senders``-Liste den Matrix-
Bridge-Filter deaktiviert. Nach Phase 57.4 ist jede Form von „keine Sender
konfiguriert" strikt fail-closed:

- Der Loader in ``scripts/start_saleria.py`` wirft ``ValueError``.
- Die ``MatrixBridge`` lehnt Nachrichten bei leerer/None-Whitelist ab
  (doppelte Verteidigungslinie für Dev-/Test-Pfade, die die Bridge
  direkt instanziieren).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.allowed_senders import load_allowed_senders
from elder_berry.comms.bridge import MatrixBridge
from elder_berry.comms.message_channel import IncomingMessage
from elder_berry.core.assistant import AssistantResult


# ---------------------------------------------------------------------------
# Loader-Tests (scripts/start_saleria.py::load_allowed_senders)
# ---------------------------------------------------------------------------


class TestLoadAllowedSenders:
    """Verhalten der Modul-Funktion ``load_allowed_senders``."""

    def _store_with(self, value: str | None):
        store = MagicMock()
        store.get_or_none.return_value = value
        return store

    def test_valid_single_sender_returns_frozenset(self):
        store = self._store_with("@user:matrix.example.com")
        result = load_allowed_senders(store)
        assert result == frozenset({"@user:matrix.example.com"})

    def test_valid_multiple_senders_split_and_stripped(self):
        store = self._store_with(
            " @user:matrix.example.com , @kollege:matrix.example.com ",
        )
        result = load_allowed_senders(store)
        assert result == frozenset(
            {"@user:matrix.example.com", "@kollege:matrix.example.com"},
        )

    def test_missing_key_raises_value_error(self):
        store = self._store_with(None)
        with pytest.raises(ValueError, match="matrix_allowed_senders"):
            load_allowed_senders(store)

    def test_empty_string_raises_value_error(self):
        store = self._store_with("")
        with pytest.raises(ValueError, match="matrix_allowed_senders"):
            load_allowed_senders(store)

    def test_whitespace_only_raises_value_error(self):
        store = self._store_with("   \n\t  ")
        with pytest.raises(ValueError, match="matrix_allowed_senders"):
            load_allowed_senders(store)

    def test_comma_only_raises_value_error(self):
        store = self._store_with(",,,")
        with pytest.raises(ValueError, match="matrix_allowed_senders"):
            load_allowed_senders(store)

    def test_comma_and_whitespace_only_raises_value_error(self):
        store = self._store_with(" , , ")
        with pytest.raises(ValueError, match="matrix_allowed_senders"):
            load_allowed_senders(store)

    def test_mixed_valid_and_empty_keeps_valid(self):
        store = self._store_with("@user:matrix.example.com,, ,@kollege:x")
        result = load_allowed_senders(store)
        assert result == frozenset(
            {"@user:matrix.example.com", "@kollege:x"},
        )


# ---------------------------------------------------------------------------
# Bridge-Filter-Tests (doppelte Verteidigungslinie)
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


class _RecordingChannel:
    """Minimaler MessageChannel-Stub – merkt sich nur, ob gesendet wurde."""

    def __init__(self):
        self._connected = False
        self._callbacks = []
        self._sent_texts: list[tuple[str, str]] = []
        self._sync_event = asyncio.Event()

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False
        self._sync_event.set()

    async def send_text(self, room_id, text):
        self._sent_texts.append((room_id, text))

    async def send_audio(self, room_id, audio_path):
        pass

    async def send_image(self, room_id, image_path):
        pass

    async def send_file(self, room_id, file_path):
        pass

    def on_message(self, callback):
        self._callbacks.append(callback)

    async def sync_loop(self):
        await self._sync_event.wait()

    @property
    def is_connected(self):
        return self._connected


def _make_bridge(allowed_senders):
    channel = _RecordingChannel()
    assistant = MagicMock()
    assistant.process.return_value = AssistantResult(
        response="Antwort",
        action_executed=None,
        action_success=False,
        emotion="neutral",
    )
    bridge = MatrixBridge(
        channel=channel,
        assistant=assistant,
        allowed_senders=allowed_senders,
    )
    bridge._start_time = 0.0
    return channel, bridge


def _make_msg(sender: str, body: str = "Hallo"):
    return IncomingMessage(
        sender=sender,
        room_id="!r:x",
        body=body,
        timestamp=time.time(),
        audio_data=None,
        file_data=None,
    )


class TestBridgeFailClosed:
    """Die Bridge selbst darf keine Nachricht durchlassen, wenn die
    Whitelist fehlt oder leer ist – auch dann nicht, wenn sie direkt
    ohne den Start-Code instanziiert wird."""

    def test_none_whitelist_rejects_any_sender(self):
        async def _test():
            channel, bridge = _make_bridge(allowed_senders=None)
            await bridge._handle_message(_make_msg("@anyone:x"))
            assert channel._sent_texts == []

        _run(_test())

    def test_empty_frozenset_rejects_any_sender(self):
        async def _test():
            channel, bridge = _make_bridge(allowed_senders=frozenset())
            await bridge._handle_message(_make_msg("@anyone:x"))
            assert channel._sent_texts == []

        _run(_test())

    def test_listed_sender_passes(self):
        async def _test():
            channel, bridge = _make_bridge(
                allowed_senders=frozenset({"@user:matrix.example.com"}),
            )
            await bridge._handle_message(
                _make_msg("@user:matrix.example.com"),
            )
            assert len(channel._sent_texts) == 1

        _run(_test())

    def test_unlisted_sender_rejected_even_with_populated_whitelist(self):
        async def _test():
            channel, bridge = _make_bridge(
                allowed_senders=frozenset({"@user:matrix.example.com"}),
            )
            await bridge._handle_message(_make_msg("@hacker:evil.com"))
            assert channel._sent_texts == []

        _run(_test())
