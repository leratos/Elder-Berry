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

    def test_params_as_list_does_not_raise(self, handler, channel, remote_commands):
        """Phase 82 PR-Review (Codex P2): wenn der LLM action_sequence mit
        action_params=[...] (Liste statt dict) emittiert, darf .get() nicht
        mit AttributeError fliegen -- freundlicher Guard greift stattdessen.
        """

        async def _test():
            res = _llm_result([])
            res.action_params = ["step", "step", "step"]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, res)

            remote_commands.execute.assert_not_called()
            # 2 Calls: Ankuendigung + Guard-Antwort
            assert channel.send_text.call_count == 2
            guard = channel.send_text.call_args_list[1][0][1]
            assert "nicht lesen" in guard

        run_async(_test())

    def test_params_as_string_does_not_raise(self, handler, channel, remote_commands):
        """Gleicher Schutz fuer params=str (LLM-Halluzination).

        Other action handlers (multi_step, list_pick) haben denselben
        isinstance-Check -- action_sequence muss konsistent sein.
        """

        async def _test():
            res = _llm_result([])
            res.action_params = "todo: A"
            msg = _make_msg()
            await handler._handle_action_sequence(msg, res)

            remote_commands.execute.assert_not_called()
            assert channel.send_text.call_count == 2
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

    def test_multi_line_in_step_splits_to_subcalls(
        self, handler, channel, remote_commands
    ):
        """Phase 82.1: Step mit Multi-Line-command wird transparent in
        Sub-Calls gesplittet (umgekehrt zur urspruenglichen ��3.2-
        Entscheidung). Saleria packt 3 Todos oft in einen Step --
        das System soll das jetzt unterstuetzen.

        Erwartung: parse_command + execute werden ZWEIMAL aufgerufen
        (einmal pro Sub-Line, nicht einmal mit dem ganzen Multi-Line-
        Blob). Bilanz zeigt 2 Sub-Outcomes.
        """

        async def _test():
            remote_commands.execute.return_value = CommandResult(
                command="todo", success=True, text="OK"
            )
            steps = [
                {
                    "action": "remote_command",
                    "params": {"command": "todo: A\ntodo: B"},
                },
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            assert remote_commands.execute.call_count == 2
            # Die echten Sub-Lines (ohne Newline) gehen einzeln rein.
            call_texts = [c[0][1] for c in remote_commands.execute.call_args_list]
            assert "todo: A" in call_texts
            assert "todo: B" in call_texts
            # Bilanz zeigt 2 Sub-Outcomes als 2 Items.
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 2 ausgefuehrt" in bilanz

        run_async(_test())

    def test_smoketest_reproducer_3_todos_notiz_reminder(
        self, handler, channel, remote_commands
    ):
        """Phase 82.1 Smoketest-Reproducer (Lera 2026-05-11):
        '3 Todos UND Notiz UND Reminder' -> 5 Outcomes, alle ✅.

        Bevor Phase 82.1 ergab das ❌ 1 / ✅ 2 (3 Todos in 1 Step,
        FAILURE 'kein bekannter command'). Mit Multi-Line-Splittung:
        ✅ 5.
        """

        async def _test():
            # 5 erwartete execute-Calls: 3 Todo-Sub-Calls + Notiz + Reminder
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="Todo 1"),
                CommandResult(command="todo", success=True, text="Todo 2"),
                CommandResult(command="todo", success=True, text="Todo 3"),
                CommandResult(command="notiz", success=True, text="Notiz OK"),
                CommandResult(command="erinner", success=True, text="Reminder OK"),
            ]
            steps = [
                {
                    "action": "remote_command",
                    "params": {
                        "command": (
                            "todo: Zutaten kaufen\ntodo: Pizzateig\ntodo: Pizza backen"
                        )
                    },
                },
                {"action": "remote_command", "params": {"command": "notiz: Link"}},
                {
                    "action": "remote_command",
                    "params": {"command": "erinnere mich Sa 10:00: Pizza"},
                },
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            assert remote_commands.execute.call_count == 5
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 5 ausgefuehrt" in bilanz
            assert "❌" not in bilanz

        run_async(_test())

    def test_multi_line_step_subfailure_continue_runs_rest(
        self, handler, channel, remote_commands
    ):
        """Sub-Step 2 von 3 schlaegt fehl + on_failure='continue':
        Sub-Step 3 laeuft trotzdem, naechster Top-Step laeuft auch."""

        async def _test():
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="Todo 1"),
                CommandResult(command="todo", success=False, text="DB locked"),
                CommandResult(command="todo", success=True, text="Todo 3"),
                CommandResult(command="notiz", success=True, text="Notiz OK"),
            ]
            steps = [
                {
                    "action": "remote_command",
                    "params": {"command": "todo: A\ntodo: B\ntodo: C"},
                },
                {"action": "remote_command", "params": {"command": "notiz: x"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(
                msg, _llm_result(steps, on_failure="continue")
            )

            # Alle 4 execute-Calls (3 Sub + 1 Top)
            assert remote_commands.execute.call_count == 4
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 3 ausgefuehrt" in bilanz
            assert "❌ 1 fehlgeschlagen" in bilanz

        run_async(_test())

    def test_multi_line_step_subfailure_stop_skips_rest(
        self, handler, channel, remote_commands
    ):
        """Sub-Step 2 von 3 schlaegt fehl + on_failure='stop':
        Sub-Step 3 als skipped, naechster Top-Step auch als skipped."""

        async def _test():
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="Todo 1"),
                CommandResult(command="todo", success=False, text="DB locked"),
                # Sub-Step 3 darf NICHT ausgefuehrt werden -> kein 3. side_effect
            ]
            steps = [
                {
                    "action": "remote_command",
                    "params": {"command": "todo: A\ntodo: B\ntodo: C"},
                },
                {"action": "remote_command", "params": {"command": "notiz: x"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(
                msg, _llm_result(steps, on_failure="stop")
            )

            # Nur 2 execute-Calls (Sub 1+2, Sub 3 skipped, Top-Notiz skipped)
            assert remote_commands.execute.call_count == 2
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 1 ausgefuehrt" in bilanz
            assert "❌ 1 fehlgeschlagen" in bilanz
            # 2 skipped: Sub-Step 3 + Top-Step Notiz
            assert "⏭ 2 uebersprungen" in bilanz

        run_async(_test())

    def test_multi_line_step_ignores_empty_lines(
        self, handler, channel, remote_commands
    ):
        """'todo: A\\n\\ntodo: B' -> leere Mid-Line wird weggefiltert,
        2 Sub-Outcomes (nicht 3)."""

        async def _test():
            remote_commands.execute.side_effect = [
                CommandResult(command="todo", success=True, text="A"),
                CommandResult(command="todo", success=True, text="B"),
            ]
            steps = [
                {
                    "action": "remote_command",
                    "params": {"command": "todo: A\n\ntodo: B"},
                },
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            assert remote_commands.execute.call_count == 2
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 2 ausgefuehrt" in bilanz

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
# Phase 82 PR-Review (Codex P2): Step-Side-Effects nicht stillschweigend
# verwerfen, Restart in Sequenz als FAILURE markieren
# ---------------------------------------------------------------------------


class TestActionSequenceStepSideEffects:
    """Vor diesem Fix gingen image_path / file_path / file_paths / list_items
    in der Sequenz verloren -- der User sah Erfolg in der Sammel-Antwort,
    bekam aber nie das Foto / die Datei / die registrierte Liste.
    Ausserdem haette ein Restart-Step die Sammel-Antwort gekillt.
    """

    def test_step_with_image_path_sends_image(self, handler, channel, remote_commands):
        """Step liefert image_path -> channel.send_image wird aufgerufen,
        temp file wird hinterher geloescht."""

        async def _test():
            from pathlib import Path
            from unittest.mock import MagicMock as MM

            fake_image = MM(spec=Path)
            fake_image.exists.return_value = True
            remote_commands.execute.return_value = CommandResult(
                command="screenshot",
                success=True,
                text="Screenshot aufgenommen.",
                image_path=fake_image,
            )
            steps = [
                {"action": "remote_command", "params": {"command": "screenshot"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            channel.send_image.assert_awaited_once_with(msg.room_id, fake_image)
            fake_image.unlink.assert_called_once_with(missing_ok=True)

            # Sammel-Antwort meldet Erfolg
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "✅ 1 ausgefuehrt" in bilanz

        run_async(_test())

    def test_step_with_file_path_sends_file(self, handler, channel, remote_commands):
        """Step liefert file_path -> _send_file_via_nc_or_matrix wird
        aufgerufen."""

        async def _test():
            from pathlib import Path
            from unittest.mock import MagicMock as MM

            fake_file = MM(spec=Path)
            fake_file.exists.return_value = True
            remote_commands.execute.return_value = CommandResult(
                command="send_file",
                success=True,
                text="Datei gesendet.",
                file_path=fake_file,
            )

            handler._send_file_via_nc_or_matrix = AsyncMock()

            steps = [
                {"action": "remote_command", "params": {"command": "schick mir x"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            handler._send_file_via_nc_or_matrix.assert_awaited_once_with(
                msg.room_id, fake_file
            )

        run_async(_test())

    def test_step_with_file_paths_loops(self, handler, channel, remote_commands):
        """Step liefert file_paths (mehrere Dateien, kein mail_attachment)
        -> jede Datei einzeln per _send_file_via_nc_or_matrix mit cleanup."""

        async def _test():
            from pathlib import Path
            from unittest.mock import MagicMock as MM

            fake1 = MM(spec=Path)
            fake1.exists.return_value = True
            fake2 = MM(spec=Path)
            fake2.exists.return_value = True
            remote_commands.execute.return_value = CommandResult(
                command="other",  # NICHT mail_attachment -> Loop-Pfad
                success=True,
                text="2 Dateien gesendet.",
                file_paths=[fake1, fake2],
            )

            handler._send_file_via_nc_or_matrix = AsyncMock()

            steps = [
                {"action": "remote_command", "params": {"command": "x"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            assert handler._send_file_via_nc_or_matrix.await_count == 2

        run_async(_test())

    def test_step_restart_is_failure(self, handler, channel, remote_commands):
        """Restart-Step in Sequenz darf nicht ausgefuehrt werden -- die
        laufende asyncio-Schleife wuerde sonst sterben und der User saehe
        nie eine Sammel-Antwort. Stattdessen FAILURE mit klarer Reason.
        """

        async def _test():
            remote_commands.execute.return_value = CommandResult(
                command="restart",
                success=True,
                text="Bot startet neu.",
                restart=True,
            )
            steps = [
                {"action": "remote_command", "params": {"command": "restart"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            # Sammel-Antwort enthaelt Failure-Bilanz und die Reason
            bilanz = channel.send_text.call_args_list[1][0][1]
            assert "❌ 1 fehlgeschlagen" in bilanz
            assert "Restart darf nicht" in bilanz

        run_async(_test())

    def test_step_with_list_items_registered(self, handler, channel, remote_commands):
        """Step mit list_items soll die Liste im ConversationListStore
        registrieren -- damit ein folgendes ``list_pick`` (auch in einer
        spaeteren User-Anfrage) auf die Liste zugreifen kann.
        """

        async def _test():
            items = [
                {"label": "A", "payload": {}},
                {"label": "B", "payload": {}},
            ]
            remote_commands.execute.return_value = CommandResult(
                command="search",
                success=True,
                text="2 Treffer.",
                list_items=items,
            )

            handler._maybe_register_command_list = MagicMock()

            steps = [
                {"action": "remote_command", "params": {"command": "suche x"}},
            ]
            msg = _make_msg()
            await handler._handle_action_sequence(msg, _llm_result(steps))

            handler._maybe_register_command_list.assert_called_once()

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
