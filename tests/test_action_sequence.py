"""Tests: Phase 82 Multi-Action-Sequencing.

Testet sowohl die DTO-Schicht (parse_steps, normalize_on_failure) als
auch die Bridge-Integration (BridgeMessageHandler._handle_action_sequence).

Die Bridge-Tests fahren bewusst ueber den Handler direkt UND ueber
handle_assistant_message, damit beide Pfade abgedeckt sind (siehe
journal.txt 2026-05-09: list_pick-Phase 80 hatte einen Bug der nur
ueber handle_remote_command sichtbar wurde).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from elder_berry.comms.action_sequence import (
    ALLOWED_STEP_ACTIONS,
    ActionStep,
    normalize_on_failure,
    parse_steps,
)
from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.message_handlers import BridgeMessageHandler


def run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def channel():
    return AsyncMock()


@pytest.fixture
def assistant():
    return MagicMock()


@pytest.fixture
def audio_pipeline():
    ap = MagicMock()
    ap.audio_to_matrix = False
    ap.send_audio_if_available = AsyncMock()
    return ap


@pytest.fixture
def chat_history():
    return MagicMock()


@pytest.fixture
def pending():
    return MagicMock()


@pytest.fixture
def remote_commands():
    rc = MagicMock()
    # Default: parse_command nimmt den Command-Namen vor dem ersten ":"
    # (matcht Real-Verhalten halbwegs, Tests koennen das ueberschreiben).
    rc.parse_command.side_effect = lambda text: text.split(":", 1)[0].strip() or None
    return rc


@pytest.fixture
def handler(
    channel,
    assistant,
    audio_pipeline,
    chat_history,
    pending,
    remote_commands,
):
    return BridgeMessageHandler(
        channel=channel,
        assistant=assistant,
        audio_pipeline=audio_pipeline,
        chat_history=chat_history,
        pending=pending,
        remote_commands=remote_commands,
    )


def _make_msg(body="hallo", sender="@user:matrix.org", room_id="!room:matrix.org"):
    msg = MagicMock()
    msg.body = body
    msg.sender = sender
    msg.room_id = room_id
    msg.timestamp = time.time()
    msg.raw = {}
    return msg


def _llm_result(steps, on_failure="continue", response="Ok ich mache das."):
    """Baut ein AssistantResult-Mock mit action_sequence-Params."""
    res = MagicMock()
    res.action_executed = "action_sequence"
    res.action_success = True
    res.action_params = {"steps": steps, "on_failure": on_failure}
    res.response = response
    res.audio_path = None
    return res


# ---------------------------------------------------------------------------
# DTO-Schicht
# ---------------------------------------------------------------------------


class TestParseSteps:
    def test_valid_list_returns_action_steps(self):
        raw = [
            {"action": "remote_command", "params": {"command": "todo: A"}},
            {"action": "remote_command", "params": {"command": "notiz: x"}},
        ]
        result = parse_steps(raw)
        assert result is not None
        assert len(result) == 2
        assert isinstance(result[0], ActionStep)
        assert result[0].action == "remote_command"
        assert result[0].params == {"command": "todo: A"}

    def test_non_list_returns_none(self):
        assert parse_steps("nope") is None
        assert parse_steps({"steps": []}) is None
        assert parse_steps(None) is None

    def test_empty_list_returns_empty(self):
        assert parse_steps([]) == []

    def test_step_without_action_returns_none(self):
        assert parse_steps([{"params": {"command": "todo: A"}}]) is None

    def test_step_with_non_dict_returns_none(self):
        assert parse_steps(["just a string"]) is None

    def test_step_with_non_dict_params_returns_none(self):
        raw = [{"action": "remote_command", "params": "not a dict"}]
        assert parse_steps(raw) is None

    def test_step_without_params_defaults_empty_dict(self):
        result = parse_steps([{"action": "remote_command"}])
        assert result is not None
        assert result[0].params == {}


class TestNormalizeOnFailure:
    def test_stop(self):
        assert normalize_on_failure("stop") == "stop"

    def test_continue(self):
        assert normalize_on_failure("continue") == "continue"

    def test_unknown_defaults_to_continue(self):
        assert normalize_on_failure("explode") == "continue"
        assert normalize_on_failure(None) == "continue"
        assert normalize_on_failure("") == "continue"


def test_allowed_step_actions_etappe1():
    """Etappe 1 erlaubt strikt nur remote_command."""
    assert ALLOWED_STEP_ACTIONS == frozenset({"remote_command"})


# ---------------------------------------------------------------------------
# Bridge-Integration: _handle_action_sequence
# ---------------------------------------------------------------------------


class TestActionSequenceHandler:
    def test_all_steps_succeed(self, handler, channel, remote_commands):
        async def _test():
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="Todo: A angelegt"),
                CommandResult(command="notiz", success=True, text="Notiz gespeichert"),
                CommandResult(command="erinner", success=True, text="Reminder gesetzt"),
            ]
            steps = [
                {"action": "remote_command", "params": {"command": "todo: A"}},
                {"action": "remote_command", "params": {"command": "notiz: x"}},
                {"action": "remote_command", "params": {"command": "erinner mich Sa"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            # 2 send_text-Calls: response + Sammel-Antwort
            assert channel.send_text.call_count == 2
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 3 ausgefuehrt" in bilanz
            assert "❌" not in bilanz
            assert "Todo: A angelegt" in bilanz
            assert "Notiz gespeichert" in bilanz
            assert "Reminder gesetzt" in bilanz

        run_async(_test())

    def test_fail_continue_runs_remaining(self, handler, channel, remote_commands):
        async def _test():
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="OK A"),
                CommandResult(command="notiz", success=False, text="DB locked"),
                CommandResult(command="erinner", success=True, text="OK Reminder"),
            ]
            steps = [
                {"action": "remote_command", "params": {"command": "todo: A"}},
                {"action": "remote_command", "params": {"command": "notiz: x"}},
                {"action": "remote_command", "params": {"command": "erinner mich Sa"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(
                msg, _llm_result(steps, on_failure="continue")
            )

            # Step 3 muss trotzdem aufgerufen worden sein
            assert remote_commands.execute.call_count == 3
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 2 ausgefuehrt" in bilanz
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "DB locked" in bilanz

        run_async(_test())

    def test_fail_stop_skips_remaining(self, handler, channel, remote_commands):
        async def _test():
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="OK A"),
                CommandResult(command="notiz", success=False, text="DB locked"),
                # Step 3 darf NICHT aufgerufen werden -- wenn doch, side_effect-
                # Liste wird nicht aufgebraucht (kein Fehler), aber call_count
                # zeigt es.
            ]
            steps = [
                {"action": "remote_command", "params": {"command": "todo: A"}},
                {"action": "remote_command", "params": {"command": "notiz: x"}},
                {"action": "remote_command", "params": {"command": "erinner mich Sa"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(
                msg, _llm_result(steps, on_failure="stop")
            )

            # NUR 2 execute-Calls -- Step 3 wurde geskippt
            assert remote_commands.execute.call_count == 2
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 1 ausgefuehrt" in bilanz
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "⏭ 1 uebersprungen" in bilanz

        run_async(_test())

    def test_empty_steps_guard(self, handler, channel, remote_commands):
        async def _test():
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result([]))

            remote_commands.execute.assert_not_called()
            # Guard-Antwort + LLM-response = 2 Calls
            assert channel.send_text.call_count == 2
            guard = channel.send_text.call_args_list[1][0][1]
            assert "Keine Aktionen" in guard

        run_async(_test())

    def test_invalid_steps_form_guard(self, handler, channel, remote_commands):
        async def _test():
            res = _llm_result([])
            res.action_params = {"steps": "kaputt", "on_failure": "continue"}
            msg = _make_msg()
            await handler._handle_action_sequence(msg, res)

            remote_commands.execute.assert_not_called()
            guard = channel.send_text.call_args_list[1][0][1]
            assert "nicht lesen" in guard

        run_async(_test())

    def test_step_action_not_allowed(self, handler, channel, remote_commands):
        async def _test():
            remote_commands.execute.return_value = CommandResult(
                command="todo", success=True, text="OK A"
            )
            steps = [
                {"action": "remote_command", "params": {"command": "todo: A"}},
                {"action": "system_status", "params": {}},
                {"action": "remote_command", "params": {"command": "notiz: x"}},
            ]
            # Notiz: 2. erfolgreicher execute-Call
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="OK A"),
                CommandResult(command="notiz", success=True, text="OK Notiz"),
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            # NUR 2 echte execute-Calls (step 1 und 3)
            assert remote_commands.execute.call_count == 2
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 2 ausgefuehrt" in bilanz
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "system_status" in bilanz
            assert "nicht erlaubt" in bilanz

        run_async(_test())

    def test_nested_action_sequence_blocked(self, handler, channel, remote_commands):
        async def _test():
            steps = [
                {
                    "action": "action_sequence",
                    "params": {"steps": [{"action": "remote_command"}]},
                },
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            remote_commands.execute.assert_not_called()
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "nested" in bilanz

        run_async(_test())

    def test_pending_confirmation_step_fails(
        self, handler, channel, remote_commands, pending
    ):
        async def _test():
            remote_commands.execute.return_value = CommandResult(
                command="mail_reply",
                success=True,
                text="Draft generiert",
                pending_confirmation=True,
                pending_data={"draft": "..."},
            )
            steps = [
                {
                    "action": "remote_command",
                    "params": {"command": "antworte auf mail 3 mit hi"},
                },
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            # PendingAction muss verworfen worden sein
            pending.clear.assert_called_with(msg.sender)
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "Bestaetigung" in bilanz

        run_async(_test())

    def test_unknown_command_fails(self, handler, channel, remote_commands):
        async def _test():
            remote_commands.parse_command.side_effect = (
                lambda text: None if "blubb" in text else "todo"
            )
            remote_commands.execute.return_value = CommandResult(
                command="todo", success=True, text="OK A"
            )
            steps = [
                {"action": "remote_command", "params": {"command": "blubb foo"}},
                {"action": "remote_command", "params": {"command": "todo: A"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            assert remote_commands.execute.call_count == 1
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 1 ausgefuehrt" in bilanz
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "kein bekannter command" in bilanz

        run_async(_test())

    def test_multi_line_in_step_not_split(self, handler, channel, remote_commands):
        """Step mit Multi-Line-Command darf NICHT rekursiv gesplittet werden.

        Erwartung: parse_command + execute werden GENAU EINMAL aufgerufen,
        nicht zweimal (einmal pro Zeile). Dokumentiert das gewollte
        Verhalten -- Saleria sollte das vermeiden, aber wenn doch:
        kein Doppel-Splitten.
        """

        async def _test():
            remote_commands.execute.return_value = CommandResult(
                command="todo", success=True, text="OK A"
            )
            steps = [
                {
                    "action": "remote_command",
                    "params": {"command": "todo: A\ntodo: B"},
                },
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            assert remote_commands.execute.call_count == 1
            # Der RAW-Text mit dem Newline geht unveraendert in execute()
            execute_args = remote_commands.execute.call_args[0]
            assert "\n" in execute_args[1]

        run_async(_test())

    def test_recursion_guard_added_and_removed(self, handler, channel, remote_commands):
        """_in_llm_command muss waehrend Step-Lauf gesetzt UND danach geleert sein."""

        async def _test():
            sender = "@user:matrix.org"

            def _check_guard(*args, **kwargs):
                assert sender in handler._in_llm_command
                return CommandResult(command="todo", success=True, text="OK")

            remote_commands.execute.side_effect = _check_guard
            steps = [
                {"action": "remote_command", "params": {"command": "todo: A"}},
            ]
            msg = _make_msg(sender=sender)
            await handler._handle_action_sequence(msg, _llm_result(steps))

            # Nach Lauf wieder weg
            assert sender not in handler._in_llm_command

        run_async(_test())


# ---------------------------------------------------------------------------
# Bridge-Integration: Routing via handle_assistant_message
# ---------------------------------------------------------------------------


class TestRoutingViaAssistantMessage:
    def test_action_sequence_routed_before_remote_command(
        self,
        handler,
        channel,
        remote_commands,
        assistant,
        chat_history,
        audio_pipeline,
    ):
        """handle_assistant_message muss action_sequence vor dem Multi-Line-
        Quick-Fix dispatchen.

        Wir mocken handler._handle_action_sequence um den Dispatch zu
        verifizieren -- die Handler-Logik selbst ist anderswo getestet.
        """

        async def _test():
            steps = [
                {"action": "remote_command", "params": {"command": "todo: A"}},
            ]
            llm_res = _llm_result(steps, response="Ok.")
            assistant.process.return_value = llm_res

            handler._handle_action_sequence = AsyncMock()
            handler._handle_llm_remote_command = AsyncMock()

            msg = _make_msg()
            await handler.handle_assistant_message(msg)

            handler._handle_action_sequence.assert_awaited_once()
            handler._handle_llm_remote_command.assert_not_awaited()

        run_async(_test())
