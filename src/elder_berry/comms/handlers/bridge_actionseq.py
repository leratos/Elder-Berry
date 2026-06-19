"""BridgeMessageHandler-Mixin: Multi-Action-Sequencing (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``message_handlers.py`` ausgelagert
(Phase-82-Block, Sequenz-Engine). Die eigentliche Sub-Command-Ausführung
liegt im ``SubCommandMixin``; ``self`` ist mit ``BridgeMessageHandler``
typisiert (Vererbung), damit der Cross-Block-Aufruf auflöst.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from elder_berry.comms.action_sequence import (
    ALLOWED_STEP_ACTIONS,
    ActionSequenceResult,
    ActionStep,
    StepOutcome,
    normalize_on_failure,
    parse_steps,
)
from elder_berry.comms.handlers._bridge_base import BridgeHandlerBase

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import IncomingMessage
    from elder_berry.core.assistant import AssistantResult

logger = logging.getLogger(__name__)


class ActionSequenceMixin(BridgeHandlerBase):
    """Führt LLM-emittierte action_sequence-Steps sequentiell aus."""

    async def _handle_action_sequence(
        self,
        msg: IncomingMessage,
        llm_result: AssistantResult,
    ) -> None:
        """LLM hat action_sequence gewaehlt -> Steps sequentiell ausfuehren.

        Nutzt den gleichen Silent-Execution-Pfad wie der Multi-Line-Quick-
        Fix (``_remote_commands.execute()`` direkt), kein neuer Routing-
        Mechanismus. Etappe 1 erlaubt nur Steps mit
        ``action: "remote_command"`` (Allowlist, siehe action_sequence.py).
        """
        # Routing-Caller filtert _remote_commands; action_sequence kann
        # nur ausgewaehlt werden wenn Commands konfiguriert sind.
        assert self._remote_commands is not None

        # LLM-Ankuendigungstext zuerst senden (analog _handle_llm_remote_command).
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)
        await self._audio.send_audio_if_available(msg.room_id, llm_result, None)

        # Phase 82 PR-Review (Codex P2): action_params kann grundsaetzlich
        # alles sein, was der LLM emittiert -- Liste, String, None. Andere
        # Action-Pfade (multi_step, list_pick) machen denselben Check, hier
        # darf .get() nicht mit AttributeError fliegen, bevor der freundliche
        # parse_steps-Guard greift.
        raw_params = llm_result.action_params
        if not isinstance(raw_params, dict):
            logger.warning(
                "action_sequence: params kein dict (%s), Sequenz abgebrochen",
                type(raw_params).__name__,
            )
            await self._channel.send_text(
                msg.room_id,
                "Konnte die Aktions-Sequenz nicht lesen -- "
                "sag mir nochmal genauer was ich tun soll.",
            )
            return
        steps = parse_steps(raw_params.get("steps"))
        on_failure = normalize_on_failure(raw_params.get("on_failure"))

        # Guard 1: Top-Level-Form kaputt (kein Listentyp / Step ohne action /
        # Step ohne dict-params). Sequenz abgebrochen, User informieren.
        if steps is None:
            logger.warning(
                "action_sequence: ungueltige steps-Form von Saleria, "
                "Sequenz abgebrochen"
            )
            await self._channel.send_text(
                msg.room_id,
                "Konnte die Aktions-Sequenz nicht lesen -- "
                "sag mir nochmal genauer was ich tun soll.",
            )
            return

        # Guard 2: leere Liste.
        if not steps:
            logger.info("action_sequence: leere steps-Liste")
            await self._channel.send_text(
                msg.room_id,
                "Keine Aktionen in der Sequenz -- sag mir genauer was du willst.",
            )
            return

        # Recursion-Guard: verhindert dass ein Step der ueber den LLM-Pfad
        # zurueckkommt erneut process() triggert (siehe Quick-Fix Analog).
        self._in_llm_command.add(msg.sender)
        try:
            sequence_result = await self._execute_action_sequence(
                steps,
                on_failure,
                msg,
            )
        finally:
            self._in_llm_command.discard(msg.sender)

        body = self._format_sequence_response(sequence_result)
        try:
            await self._channel.send_text(msg.room_id, body)
        except Exception as exc:  # pragma: no cover - defensiv
            logger.error(
                "action_sequence: Sammel-Antwort konnte nicht gesendet werden: %s",
                exc,
            )

    async def _execute_action_sequence(
        self,
        steps: list[ActionStep],
        on_failure: str,
        msg: IncomingMessage,
    ) -> ActionSequenceResult:
        """Fuehrt die Steps sequentiell aus, sammelt Outcomes.

        Die eigentliche Step-Ausfuehrung delegiert an
        ``_execute_single_step`` -- separat damit Tests einzelne Steps
        gezielt patchen koennen, ohne den Loop zu duplizieren.

        Phase 82 PR-Review: ``msg`` (frueher nur ``sender``) wird
        durchgereicht, damit Step-Side-Effects (image_path, file_path,
        ...) den richtigen room_id treffen.
        """
        assert self._remote_commands is not None

        outcomes: list[StepOutcome] = []
        succeeded = 0
        failed = 0
        skipped = 0
        stop_remaining = False

        for index, step in enumerate(steps):
            if stop_remaining:
                outcomes.append(
                    StepOutcome(
                        index=index,
                        status="skipped",
                        summary=self._step_summary_label(step),
                        reason="vorheriger Step gescheitert (on_failure=stop)",
                    )
                )
                skipped += 1
                continue

            # Phase 82.1: ein Step kann mehrere Outcomes liefern, wenn
            # sein command-String Multi-Line ist (Sub-Calls werden
            # transparent gesplittet, analog Top-Level-Quick-Fix).
            step_outcomes = await self._execute_single_step(
                index, step, msg, on_failure
            )
            for outcome in step_outcomes:
                outcomes.append(outcome)
                if outcome.status == "success":
                    succeeded += 1
                elif outcome.status == "failure":
                    failed += 1
                    if on_failure == "stop":
                        stop_remaining = True
                else:  # skipped (durch Multi-Line-Step intern markiert)
                    skipped += 1

        return ActionSequenceResult(
            steps_total=len(steps),
            steps_succeeded=succeeded,
            steps_failed=failed,
            steps_skipped=skipped,
            outcomes=outcomes,
        )

    async def _execute_single_step(
        self,
        index: int,
        step: ActionStep,
        msg: IncomingMessage,
        on_failure: str,
    ) -> list[StepOutcome]:
        """Fuehrt einen Step aus, returnt eine Liste von Outcomes.

        Phase 82.1: Liste statt einzelnem Outcome, weil Multi-Line-
        commands transparent in Sub-Calls gesplittet werden (jeder
        Sub-Call -> 1 Outcome). Single-Line-commands liefern eine
        Ein-Element-Liste; das vereinheitlicht den Caller-Loop.

        Validierungs-Reihenfolge (Step-Ebene, vor Splittung):
        1. Recursion-Guard (action == "action_sequence").
        2. Allowlist (action in ALLOWED_STEP_ACTIONS).
        3. Command-Text vorhanden.

        Wenn Validierung passt: Multi-Line-Detection -> entweder
        ``_execute_multi_line_step`` (mit on_failure-Stop-Logik
        innerhalb der Sub-Calls) oder ein einzelner
        ``_execute_sub_command``-Call.
        """
        label = self._step_summary_label(step)

        # 1. Recursion-Guard
        if step.action == "action_sequence":
            return [
                StepOutcome(
                    index=index,
                    status="failure",
                    summary=label,
                    reason="nested action_sequence nicht erlaubt",
                )
            ]

        # 2. Allowlist (Etappe 1: nur remote_command)
        if step.action not in ALLOWED_STEP_ACTIONS:
            return [
                StepOutcome(
                    index=index,
                    status="failure",
                    summary=label,
                    reason=f"step-action '{step.action}' nicht erlaubt",
                )
            ]

        command_text = step.params.get("command", "")
        if not isinstance(command_text, str) or not command_text.strip():
            return [
                StepOutcome(
                    index=index,
                    status="failure",
                    summary=label,
                    reason="leerer command",
                )
            ]

        # Phase 82.1: Multi-Line-Detection -- aber nur splitten wenn alle
        # non-empty Lines einzeln als bekanntes Command parsen (konsistent
        # mit Top-Level-Quick-Fix in _try_parse_multi_line). Sonst behandeln
        # wir den ganzen Text als legitimen Multi-Line-Payload (z.B. clip:
        # mit re.DOTALL, langer Notiz-Text mit eingebetteten Newlines) und
        # geben ihn in EINEM execute-Call an parse_command/execute weiter.
        # Phase-82.1-PR-Review (Codex P2): unbedingtes Splitten zerstoerte
        # vorher genau diese Multi-Line-Payload-Commands.
        if "\n" in command_text:
            multi_parsed = self._try_parse_multi_line(command_text)
            if multi_parsed is not None:
                return await self._execute_multi_line_step(
                    index, multi_parsed, msg, on_failure
                )
            # Fallback: ein- oder mehrere Lines parsen nicht einzeln ->
            # Single-Path mit dem rohen Multi-Line-Text.

        outcome = await self._execute_sub_command(index, command_text, msg)
        return [outcome]

    async def _execute_multi_line_step(
        self,
        index: int,
        multi_parsed: list[tuple[str, str]],
        msg: IncomingMessage,
        on_failure: str,
    ) -> list[StepOutcome]:
        """Fuehrt einen via ``_try_parse_multi_line`` validierten Multi-
        Line-Step als einzelne Sub-Commands aus.

        Phase 82.1: Saleria packt gleichartige Items oft als Newline-
        separierten command-String in einen einzigen Step (z.B. 3 Todos).
        Der Konzept-§3.2 wurde geaendert -- Multi-Line wird jetzt
        transparent gesplittet, analog zum Top-Level-Multi-Line-Quick-Fix.

        Phase 82.1 PR-Review (Codex P2): Der Caller
        (``_execute_single_step``) prueft VORHER via
        ``_try_parse_multi_line``, ob jede non-empty Line einzeln als
        Command parst. Wenn nicht -> single-call mit dem ganzen Text
        (legitimer Multi-Line-Payload, z.B. ``clip:`` mit re.DOTALL).
        Diese Methode hier wird nur aufgerufen, wenn das Gate
        durchlaufen ist.

        on_failure='stop' wird auch INNERHALB des Multi-Line-Steps
        respektiert: nach erstem Sub-Failure werden restliche Sub-
        Commands als 'skipped' markiert (mit Reason). Der Outer-Loop
        (``_execute_action_sequence``) sieht das Failure-Outcome und
        setzt seinerseits stop_remaining fuer die naechsten Top-Steps --
        konsistente Stop-Semantik auf beiden Ebenen.

        Alle Sub-Outcomes tragen denselben ``index`` (= Top-Step-Index).
        """
        outcomes: list[StepOutcome] = []
        stop_subs = False
        for raw_line, _ in multi_parsed:
            if stop_subs:
                outcomes.append(
                    StepOutcome(
                        index=index,
                        status="skipped",
                        summary=raw_line,
                        reason=("vorheriger Sub-Step gescheitert (on_failure=stop)"),
                    )
                )
                continue

            # _execute_sub_command parst defensiv erneut (konsistent mit
            # dem Single-Line-Pfad). parse_command ist guenstig; das
            # Doppel-Parsen vermeidet eine zweite Code-Linie.
            outcome = await self._execute_sub_command(index, raw_line, msg)
            outcomes.append(outcome)
            if outcome.status == "failure" and on_failure == "stop":
                stop_subs = True

        return outcomes

    @staticmethod
    def _step_summary_label(step: ActionStep) -> str:
        """Kurzlabel fuer Outcomes wenn der echte Command-Text fehlt."""
        cmd = step.params.get("command")
        if isinstance(cmd, str) and cmd.strip():
            return cmd
        return f"<{step.action}>"

    @staticmethod
    def _format_sequence_response(result: ActionSequenceResult) -> str:
        """Erzeugt die Sammel-Antwort an den User.

        Format ist konsistent zum Multi-Line-Quick-Fix
        (``_execute_multi_line_commands``) -- Bilanz-Zeile mit
        ✅ / ❌ / ⏭, dann Detail-Block.
        """
        bilanz_parts = [f"✅ {result.steps_succeeded} ausgefuehrt"]
        if result.steps_failed:
            bilanz_parts.append(f"❌ {result.steps_failed} fehlgeschlagen")
        if result.steps_skipped:
            bilanz_parts.append(f"⏭ {result.steps_skipped} uebersprungen")
        body = " · ".join(bilanz_parts)

        successes = [o for o in result.outcomes if o.status == "success"]
        failures = [o for o in result.outcomes if o.status == "failure"]
        skips = [o for o in result.outcomes if o.status == "skipped"]

        if successes:
            details = "\n".join(f"  - {o.summary}" for o in successes)
            body += f"\n\n{details}"
        if failures:
            fail_lines = "\n".join(f"  - {o.summary}: {o.reason}" for o in failures)
            body += f"\n\nFehler:\n{fail_lines}"
        if skips:
            skip_lines = "\n".join(f"  - {o.summary}" for o in skips)
            body += f"\n\nUebersprungen:\n{skip_lines}"
        return body

    def _try_parse_multi_line(
        self, command_text: str
    ) -> list[tuple[str, str]] | None:
        """Pruefe ob ``command_text`` ein Multi-Line-Batch ist.

        Returns:
            Liste ``[(line, parsed_cmd), ...]`` wenn alle nicht-leeren
            Zeilen sich als Commands parsen lassen UND es mehr als eine
            Zeile gibt. Sonst None (Single-Line oder gemischt -- dann
            faellt der Caller auf den Single-Path zurueck).
        """
        if self._remote_commands is None:
            return None
        lines = [line.strip() for line in command_text.split("\n") if line.strip()]
        if len(lines) <= 1:
            return None
        parsed: list[tuple[str, str]] = []
        for line in lines:
            line_cmd = self._remote_commands.parse_command(line)
            if not line_cmd:
                return None
            parsed.append((line, line_cmd))
        return parsed
