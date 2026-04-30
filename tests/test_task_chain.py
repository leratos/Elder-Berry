"""Tests für TaskChainRunner – Multi-Step Task Chaining."""

import json
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.base import CommandResult
from elder_berry.core.task_chain import (
    ChainResult,
    StepResult,
    TaskChainRunner,
)
from elder_berry.llm.base import LLMClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def mock_commands():
    """Mock RemoteCommandHandler mit parse_command + execute."""
    handler = MagicMock()
    # Default: parse_command gibt den Command-String zurück (erkannt)
    handler.parse_command.side_effect = lambda cmd: cmd
    # Default: execute gibt Erfolg zurück
    handler.execute.return_value = CommandResult(
        command="test",
        success=True,
        text="OK",
    )
    return handler


@pytest.fixture
def runner(mock_llm, mock_commands):
    return TaskChainRunner(
        llm=mock_llm,
        remote_commands=mock_commands,
        max_steps=5,
        max_result_chars=2000,
    )


# ---------------------------------------------------------------------------
# Tests: StepResult / ChainResult Dataclasses
# ---------------------------------------------------------------------------


class TestStepResult:
    def test_creation(self):
        step = StepResult(
            step_number=1,
            command="mails",
            result_text="3 Mails",
            success=True,
            llm_response="Ich schaue nach...",
        )
        assert step.step_number == 1
        assert step.command == "mails"
        assert step.success is True

    def test_failed_step(self):
        step = StepResult(
            step_number=2,
            command="bad_cmd",
            result_text="Fehler",
            success=False,
            llm_response="Hmm...",
        )
        assert step.success is False


class TestChainResult:
    def test_empty(self):
        chain = ChainResult()
        assert chain.step_count == 0
        assert chain.all_success is True  # vacuous truth
        assert chain.completed is False

    def test_with_steps(self):
        chain = ChainResult(
            steps=[
                StepResult(1, "mails", "3 Mails", True, "Ok"),
                StepResult(2, "termin: X", "Erstellt", True, "Fertig"),
            ],
            final_summary="Alles erledigt.",
            completed=True,
        )
        assert chain.step_count == 2
        assert chain.all_success is True
        assert chain.completed is True

    def test_partial_failure(self):
        chain = ChainResult(
            steps=[
                StepResult(1, "mails", "3 Mails", True, "Ok"),
                StepResult(2, "bad", "Fehler", False, "Hmm"),
            ],
        )
        assert chain.all_success is False


# ---------------------------------------------------------------------------
# Tests: TaskChainRunner.run()
# ---------------------------------------------------------------------------


class TestTaskChainRunnerBasic:
    def test_single_step_done(self, runner, mock_llm):
        """LLM sagt sofort DONE → 0 Commands, nur Zusammenfassung."""
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "DONE",
                "response": "Das brauchte keinen Command.",
            }
        )

        result = runner.run("Was ist 2+2?")

        assert result.completed is True
        assert result.step_count == 0
        assert "keinen Command" in result.final_summary

    def test_one_step_then_done(self, runner, mock_llm, mock_commands):
        """Ein Command, dann DONE."""
        mock_llm.generate.side_effect = [
            json.dumps({"action": "mails", "response": "Schaue Mails..."}),
            json.dumps({"action": "DONE", "response": "Du hast 3 Mails."}),
        ]
        mock_commands.execute.return_value = CommandResult(
            command="mails",
            success=True,
            text="3 ungelesene Mails",
        )

        result = runner.run("Zeig mir meine Mails")

        assert result.completed is True
        assert result.step_count == 1
        assert result.steps[0].command == "mails"
        assert result.steps[0].success is True
        assert "3 Mails" in result.final_summary

    def test_multi_step_chain(self, runner, mock_llm, mock_commands):
        """Drei Commands: mails → mail suche → termin erstellen."""
        mock_llm.generate.side_effect = [
            json.dumps({"action": "mails", "response": "Schaue Mails..."}),
            json.dumps({"action": "mail suche Zahnarzt", "response": "Suche..."}),
            json.dumps(
                {
                    "action": "termin: Zahnarzt 2026-04-15 14:00",
                    "response": "Trage ein...",
                }
            ),
            json.dumps(
                {
                    "action": "DONE",
                    "response": "Zahnarzt am 15.04 um 14:00 eingetragen.",
                }
            ),
        ]
        mock_commands.execute.side_effect = [
            CommandResult(command="mails", success=True, text="3 Mails"),
            CommandResult(
                command="mail_search", success=True, text="Zahnarzt 15.04 14:00"
            ),
            CommandResult(command="create_event", success=True, text="Termin erstellt"),
        ]

        result = runner.run("Lies Mails und trag den Zahnarzttermin ein")

        assert result.completed is True
        assert result.step_count == 3
        assert result.steps[0].command == "mails"
        assert result.steps[1].command == "mail suche Zahnarzt"
        assert result.steps[2].command == "termin: Zahnarzt 2026-04-15 14:00"
        assert result.all_success is True
        assert "Zahnarzt" in result.final_summary

    def test_max_steps_reached(self, runner, mock_llm, mock_commands):
        """Chain bricht nach max_steps ab."""
        # LLM gibt immer einen neuen Command, nie DONE
        mock_llm.generate.side_effect = [
            json.dumps({"action": f"cmd_{i}", "response": f"Step {i}"})
            for i in range(10)
        ]

        result = runner.run("Endlos-Task")

        assert result.completed is False
        assert result.step_count == 5  # max_steps
        assert "Maximale Schrittanzahl" in result.final_summary


class TestTaskChainRunnerErrors:
    def test_unrecognized_command(self, runner, mock_llm, mock_commands):
        """Command wird von parse_command nicht erkannt."""
        mock_commands.parse_command.side_effect = (
            None  # side_effect aus Fixture entfernen
        )
        mock_commands.parse_command.return_value = None  # nicht erkannt
        mock_llm.generate.side_effect = [
            json.dumps({"action": "gibberish", "response": "Hmm..."}),
            json.dumps({"action": "DONE", "response": "Konnte nicht ausführen."}),
        ]

        result = runner.run("Mach was undefiniertes")

        assert result.step_count == 1
        assert result.steps[0].success is False
        assert "nicht erkannt" in result.steps[0].result_text

    def test_command_execution_error(self, runner, mock_llm, mock_commands):
        """Command-Ausführung wirft Exception."""
        mock_commands.execute.side_effect = RuntimeError("Connection timeout")
        mock_llm.generate.side_effect = [
            json.dumps({"action": "mails", "response": "Schaue..."}),
            json.dumps({"action": "DONE", "response": "Hat nicht geklappt."}),
        ]

        result = runner.run("Zeig Mails")

        assert result.step_count == 1
        assert result.steps[0].success is False
        assert "RuntimeError" in result.steps[0].result_text

    def test_unparseable_llm_response(self, runner, mock_llm):
        """LLM gibt kein JSON zurück → Chain endet mit DONE-Fallback."""
        mock_llm.generate.return_value = "Das kann ich nicht als JSON."

        result = runner.run("Irgendwas")

        assert result.completed is True
        assert result.step_count == 0


class TestTaskChainRunnerContext:
    def test_result_truncation(self, runner, mock_llm, mock_commands):
        """Lange Command-Ergebnisse werden auf max_result_chars gekürzt."""
        runner._max_result_chars = 100
        long_text = "x" * 500
        mock_commands.execute.return_value = CommandResult(
            command="mails",
            success=True,
            text=long_text,
        )
        mock_llm.generate.side_effect = [
            json.dumps({"action": "mails", "response": "Schaue..."}),
            json.dumps({"action": "DONE", "response": "Fertig."}),
        ]

        result = runner.run("Mails")

        assert result.steps[0].success is True
        assert len(result.steps[0].result_text) < 200
        assert "gekürzt" in result.steps[0].result_text

    def test_history_text_preferred(self, runner, mock_llm, mock_commands):
        """history_text wird bevorzugt über text verwendet."""
        mock_commands.execute.return_value = CommandResult(
            command="mails",
            success=True,
            text="📧 3 Mails",
            history_text="Mail 1: Betreff A\nMail 2: Betreff B\nMail 3: Betreff C",
        )
        mock_llm.generate.side_effect = [
            json.dumps({"action": "mails", "response": "Schaue..."}),
            json.dumps({"action": "DONE", "response": "Fertig."}),
        ]

        result = runner.run("Mails")

        assert "Betreff A" in result.steps[0].result_text

    def test_on_step_callback(self, runner, mock_llm, mock_commands):
        """on_step Callback wird pro Schritt aufgerufen."""
        mock_llm.generate.side_effect = [
            json.dumps({"action": "mails", "response": "Step 1"}),
            json.dumps({"action": "termine", "response": "Step 2"}),
            json.dumps({"action": "DONE", "response": "Fertig."}),
        ]

        steps_received = []
        runner.run("Task", on_step=lambda s: steps_received.append(s))

        assert len(steps_received) == 2
        assert steps_received[0].step_number == 1
        assert steps_received[1].step_number == 2

    def test_chat_history_in_initial_context(self, runner, mock_llm):
        """Chat-History wird in den initialen Kontext eingebaut."""
        mock_llm.generate.return_value = json.dumps(
            {
                "action": "DONE",
                "response": "Ok.",
            }
        )

        runner.run("Mach was", chat_history="User: Hallo\nAssistant: Hi!")

        # Prüfe dass der LLM-Call den Chat-Verlauf enthält
        call_args = mock_llm.generate.call_args
        prompt = call_args[0][0]  # erstes positional arg
        assert "Hallo" in prompt
