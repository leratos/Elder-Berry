"""Integrationstests für den Initiativ-Followup-Flow (Phase 89, Pfad C).

Deckt den End-to-End-Pfad ab:
- Saleria emittiert ``propose_action`` -> PendingInitiative wird abgelegt.
- Kurze Bestätigung ("ja bitte") -> Bridge-Intercept führt den
  vorgeschlagenen Command über den normalen Command-Pfad aus.
- Absage / Nicht-Bestätigung -> Vorschlag wird verworfen.

Der Store-Wortschatz selbst ist in ``test_pending_initiative.py`` getestet.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from elder_berry.comms.bridge import MatrixBridge
from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
from elder_berry.comms.pending_initiative import (
    PendingInitiative,
    PendingInitiativeStore,
)
from elder_berry.core.assistant import AssistantResult

USER = "@user:x"
ROOM = "!r:x"
PROPOSED = "kalender erstelle Urlaub am 15.08. fuer 6 Naechte"


def run_async(coro):
    return asyncio.run(coro)


class MockChannel(MessageChannel):
    def __init__(self) -> None:
        self._sent_texts: list[tuple[str, str]] = []

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_text(self, room_id: str, text: str) -> None:
        self._sent_texts.append((room_id, text))

    async def send_audio(self, room_id: str, audio_path: Path) -> None: ...

    async def send_image(self, room_id: str, image_path: Path) -> None: ...

    async def send_file(self, room_id: str, file_path: Path) -> None: ...

    def on_message(self, callback) -> None: ...

    async def sync_loop(self) -> None: ...

    def is_connected(self) -> bool:
        return True


def _make_msg(body: str) -> IncomingMessage:
    return IncomingMessage(
        sender=USER,
        room_id=ROOM,
        body=body,
        timestamp=time.time(),
    )


def _propose_result() -> AssistantResult:
    return AssistantResult(
        response="Soll ich den Termin gleich eintragen?",
        action_executed="propose_action",
        action_success=True,
        action_params={
            "proposed_command": PROPOSED,
            "question": "Soll ich den Termin eintragen?",
        },
    )


def _assistant(result: AssistantResult) -> MagicMock:
    assistant = MagicMock()
    assistant.process.return_value = result
    return assistant


def _make_bridge(
    *,
    assistant: MagicMock | None = None,
    store: PendingInitiativeStore | None = None,
    remote_commands: MagicMock | None = None,
) -> tuple[MockChannel, MatrixBridge, PendingInitiativeStore]:
    ch = MockChannel()
    store = store or PendingInitiativeStore()
    bridge = MatrixBridge(
        channel=ch,
        assistant=assistant or _assistant(_propose_result()),
        allowed_senders=frozenset({USER}),
        remote_commands=remote_commands,
        pending_initiative_store=store,
    )
    bridge._start_time = 0.0
    return ch, bridge, store


# --- Vorschlag ablegen -----------------------------------------------------


def test_propose_action_stores_initiative_and_sends_question() -> None:
    async def _test() -> None:
        ch, bridge, store = _make_bridge()
        # Kein remote_commands -> Nachricht landet im LLM-Fallback.
        await bridge._handle_message(_make_msg("fasse die mail zusammen"))

        pending = store.get(USER)
        assert pending is not None
        assert pending.proposed_command == PROPOSED
        assert any("eintragen" in t.lower() for _, t in ch._sent_texts)

    run_async(_test())


def test_handle_propose_action_with_prefix_combines_text() -> None:
    # Enrichment-Pfad: der Command-Output (prefix) wird der Frage vorangestellt.
    async def _test() -> None:
        ch, bridge, store = _make_bridge()
        llm_result = _propose_result()
        await bridge._handler._handle_propose_action(
            _make_msg("egal"), llm_result, None, prefix="MAIL-HEADER"
        )
        sent = " ".join(t for _, t in ch._sent_texts)
        assert "MAIL-HEADER" in sent
        assert "eintragen" in sent.lower()
        assert store.get(USER) is not None

    run_async(_test())


def test_propose_action_in_enrichment_path_stores_and_prefixes() -> None:
    # Mail-/Web-/Doku-Zusammenfassung: _handle_llm_enrichment wertete Aktionen
    # bisher NICHT aus -- hier muss propose_action greifen (Trigger-Luecke).
    async def _test() -> None:
        ch, bridge, store = _make_bridge()  # assistant liefert propose_action
        cmd_result = CommandResult(
            command="mail_summary",
            success=True,
            text="Mail von Fewo-Direkt",
            history_text="Reservierungstext ...",
        )
        await bridge._handler._handle_mail_summary(_make_msg("fasse zusammen"), cmd_result)

        pending = store.get(USER)
        assert pending is not None
        assert pending.proposed_command == PROPOSED
        sent = " ".join(t for _, t in ch._sent_texts)
        assert "Mail von Fewo-Direkt" in sent  # Command-Output als Prefix
        assert "eintragen" in sent.lower()  # Saleria's Rueckfrage

    run_async(_test())


def test_handle_propose_action_prefix_only_when_no_response() -> None:
    # Leere LLM-Response, aber Prefix vorhanden -> nur der Prefix wird gesendet.
    async def _test() -> None:
        ch, bridge, store = _make_bridge()
        llm_result = AssistantResult(
            response="",
            action_executed="propose_action",
            action_success=True,
            action_params={"proposed_command": PROPOSED, "question": "Q"},
        )
        await bridge._handler._handle_propose_action(
            _make_msg("egal"), llm_result, None, prefix="NUR-PREFIX"
        )
        assert any("NUR-PREFIX" in t for _, t in ch._sent_texts)
        assert store.get(USER) is not None

    run_async(_test())


def test_confirm_without_remote_commands_reports_unavailable() -> None:
    # Bestaetigung, aber keine Commands verdrahtet -> klare Rueckmeldung,
    # kein stiller Fehlschlag.
    async def _test() -> None:
        store = PendingInitiativeStore()
        store.set(USER, PendingInitiative(proposed_command=PROPOSED, question="?"))
        ch, bridge, store = _make_bridge(store=store, remote_commands=None)

        await bridge._handle_message(_make_msg("ja bitte"))

        assert any("nicht ausfuehren" in t.lower() for _, t in ch._sent_texts)
        assert store.get(USER) is None

    run_async(_test())


def test_propose_action_without_command_stores_nothing() -> None:
    async def _test() -> None:
        ch, bridge, store = _make_bridge()
        llm_result = AssistantResult(
            response="Soll ich irgendwas tun?",
            action_executed="propose_action",
            action_success=True,
            action_params={},  # kein proposed_command
        )
        await bridge._handler._handle_propose_action(_make_msg("egal"), llm_result, None)
        assert store.get(USER) is None
        assert any("tun" in t.lower() for _, t in ch._sent_texts)

    run_async(_test())


# --- Bestätigung ausführen -------------------------------------------------


def test_confirm_executes_proposed_command_via_command_path() -> None:
    async def _test() -> None:
        store = PendingInitiativeStore()
        store.set(USER, PendingInitiative(proposed_command=PROPOSED, question="?"))
        remote = MagicMock()
        remote.parse_command.return_value = "calendar_create"
        ch, bridge, store = _make_bridge(store=store, remote_commands=remote)
        bridge._handler.handle_remote_command = AsyncMock()

        await bridge._handle_message(_make_msg("ja bitte"))

        bridge._handler.handle_remote_command.assert_called_once()
        called_msg, called_cmd = bridge._handler.handle_remote_command.call_args.args
        assert called_cmd == "calendar_create"
        assert called_msg.body == PROPOSED  # Command-Text, nicht "ja bitte"
        remote.parse_command.assert_called_once_with(PROPOSED)
        assert store.get(USER) is None  # nach Bestätigung geräumt

    run_async(_test())


def test_confirm_with_unparseable_command_falls_back_to_assistant() -> None:
    async def _test() -> None:
        store = PendingInitiativeStore()
        store.set(USER, PendingInitiative(proposed_command=PROPOSED, question="?"))
        remote = MagicMock()
        remote.parse_command.return_value = None  # kein direkter Command
        ch, bridge, store = _make_bridge(store=store, remote_commands=remote)
        bridge._handler.handle_assistant_message = AsyncMock()

        await bridge._handle_message(_make_msg("ja"))

        bridge._handler.handle_assistant_message.assert_called_once()
        called_msg = bridge._handler.handle_assistant_message.call_args.args[0]
        assert called_msg.body == PROPOSED
        assert store.get(USER) is None

    run_async(_test())


# --- Absage / Nicht-Bestätigung -------------------------------------------


def test_cancel_clears_and_acknowledges() -> None:
    async def _test() -> None:
        store = PendingInitiativeStore()
        store.set(USER, PendingInitiative(proposed_command=PROPOSED, question="?"))
        remote = MagicMock()
        ch, bridge, store = _make_bridge(store=store, remote_commands=remote)
        bridge._handler.handle_remote_command = AsyncMock()

        await bridge._handle_message(_make_msg("nein"))

        assert store.get(USER) is None
        assert any("lasse ich" in t.lower() for _, t in ch._sent_texts)
        remote.parse_command.assert_not_called()
        bridge._handler.handle_remote_command.assert_not_called()

    run_async(_test())


def test_other_discards_initiative_and_processes_normally() -> None:
    async def _test() -> None:
        store = PendingInitiativeStore()
        store.set(USER, PendingInitiative(proposed_command=PROPOSED, question="?"))
        remote = MagicMock()
        remote.parse_command.return_value = None
        remote.suggest_command.return_value = None
        ch, bridge, store = _make_bridge(store=store, remote_commands=remote)
        bridge._handler.handle_assistant_message = AsyncMock()

        await bridge._handle_message(_make_msg("wie spaet ist es"))

        # Vorschlag verworfen ...
        assert store.get(USER) is None
        # ... und die Nachricht ganz normal weiterverarbeitet.
        remote.parse_command.assert_called_once_with("wie spaet ist es")
        bridge._handler.handle_assistant_message.assert_called_once()

    run_async(_test())


# --- Round-Trip ------------------------------------------------------------


def test_full_round_trip_propose_then_confirm() -> None:
    async def _test() -> None:
        store = PendingInitiativeStore()
        remote = MagicMock()
        # Nur der vorgeschlagene Kalender-Command parst zu einem Command;
        # die Turn-1-Nachricht nicht.
        remote.parse_command.side_effect = lambda text: (
            "calendar_create" if "kalender" in text else None
        )
        remote.suggest_command.return_value = None
        ch, bridge, store = _make_bridge(
            assistant=_assistant(_propose_result()),
            store=store,
            remote_commands=remote,
        )
        bridge._handler.handle_remote_command = AsyncMock()

        # Turn 1: Saleria schlägt vor -> Initiative abgelegt
        await bridge._handle_message(_make_msg("fasse die mail zusammen"))
        assert store.get(USER) is not None

        # Turn 2: kurze Bestätigung -> Command läuft
        await bridge._handle_message(_make_msg("ja bitte"))
        bridge._handler.handle_remote_command.assert_called_once()
        _, called_cmd = bridge._handler.handle_remote_command.call_args.args
        assert called_cmd == "calendar_create"
        assert store.get(USER) is None

    run_async(_test())
