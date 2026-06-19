"""BridgeMessageHandler-Mixin: Multi-Step + LLM→Remote-Command (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``message_handlers.py`` ausgelagert.
``self`` ist mit ``BridgeMessageHandler`` typisiert (Vererbung), damit
Cross-Block-Zugriffe (action_sequence-Helper, sub_command) auflösen.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from elder_berry.comms.handlers._bridge_base import BridgeHandlerBase

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import IncomingMessage
    from elder_berry.core.assistant import AssistantResult
    from elder_berry.core.task_chain import StepResult

logger = logging.getLogger(__name__)


class LlmFlowMixin(BridgeHandlerBase):
    """Multi-Step-Chain + LLM-getriebene Remote-Command-Ausführung (mit Retry)."""

    async def _handle_multi_step(
        self,
        msg: IncomingMessage,
        llm_result: AssistantResult,
        chat_context: str,
    ) -> None:
        """LLM hat multi_step gewählt → TaskChainRunner ausführen."""
        # Caller (handle_assistant_message dispatch) filtert
        # self._task_chain ist None implizit ueber action != "multi_step",
        # aber multi_step kann nur gewaehlt werden wenn TaskChain konfiguriert
        # ist. Defensive: assert vor lambda-Boundary.
        assert self._task_chain is not None
        task_chain = self._task_chain
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)

        await self._audio.send_audio_if_available(msg.room_id, llm_result, None)

        task_text = ""
        if llm_result.action_params and isinstance(llm_result.action_params, dict):
            task_text = llm_result.action_params.get("task", "")

        if not task_text:
            logger.warning("multi_step ohne task-Parameter")
            return

        logger.info("Multi-Step Chain gestartet: %s", task_text[:100])

        try:
            loop = asyncio.get_running_loop()
            step_messages: list[str] = []

            def on_step(step: StepResult) -> None:
                status = "✓" if step.success else "✗"
                step_messages.append(
                    f"Schritt {step.step_number}: {step.command} [{status}]"
                )

            chain_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: task_chain.run(
                        user_request=task_text,
                        chat_history=chat_context,
                        on_step=on_step,
                    ),
                ),
                timeout=300.0,
            )

            if step_messages:
                steps_text = "\n".join(step_messages)
                await self._channel.send_text(
                    msg.room_id,
                    f"📋 Schritte:\n{steps_text}",
                )

            if chain_result.final_summary:
                await self._channel.send_text(
                    msg.room_id,
                    chain_result.final_summary,
                )
                self._chat_history.add(
                    msg.sender,
                    "assistant",
                    chain_result.final_summary,
                )

            logger.info(
                "Multi-Step Chain abgeschlossen: %d Schritte, completed=%s",
                chain_result.step_count,
                chain_result.completed,
            )

        except asyncio.TimeoutError:
            logger.error("Timeout bei Multi-Step Chain (300s)")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung bei der Multi-Step-Verarbeitung.",
                )
            except Exception:
                # Best-effort: Timeout-Notification darf den Outer-Handler nicht crashen.
                pass
        except Exception as e:
            logger.error(
                "Multi-Step Chain fehlgeschlagen: %s",
                e,
                extra={"sender": msg.sender, "handler": "multi_step"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Multi-Step Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Multi-Step Fehlermeldung nicht senden")

    async def _handle_llm_remote_command(
        self,
        msg: IncomingMessage,
        llm_result: AssistantResult,
    ) -> None:
        """LLM hat remote_command Aktion gewählt → Command ausführen."""
        # Bridge filtert self._remote_commands; remote_command kann nur
        # gewaehlt werden wenn Commands konfiguriert sind.
        assert self._remote_commands is not None
        if llm_result.response:
            self._chat_history.add(msg.sender, "assistant", llm_result.response)
            await self._channel.send_text(msg.room_id, llm_result.response)

        await self._audio.send_audio_if_available(msg.room_id, llm_result, None)

        command_text = None
        if llm_result.action_params and isinstance(llm_result.action_params, dict):
            command_text = llm_result.action_params.get("command", "")

        if not command_text:
            logger.debug("LLM remote_command ohne command-Parameter")
            return

        logger.info("LLM → remote_command: %s", command_text)

        from elder_berry.comms.message_channel import IncomingMessage as IM

        # Multi-Line-Erkennung VOR dem Single-Command-Pfad.
        # Saleria emittiert manchmal natural-language-batched Commands
        # (Live-Befund 2026-05-08: 5x 'todo: ...' fuer eine Einkaufsliste).
        # Wenn JEDE Zeile ein parsbarer Command ist, alle nacheinander
        # ausfuehren mit Sammel-Antwort. Strikt: bei einem Fail -> Single-
        # Pfad (Saleria ist "verwirrt", Phase-81b-Plugin-Vorschlag ist
        # angemessen).
        multi_parsed = self._try_parse_multi_line(command_text)
        if multi_parsed is not None:
            self._in_llm_command.add(msg.sender)
            try:
                await self._execute_multi_line_commands(msg, multi_parsed)
            finally:
                self._in_llm_command.discard(msg.sender)
            return

        cmd = self._remote_commands.parse_command(command_text)
        if cmd:
            cmd_msg = IM(
                sender=msg.sender,
                room_id=msg.room_id,
                body=command_text,
                timestamp=msg.timestamp,
            )
            # Rekursions-Guard setzen: verhindert fallthrough → LLM → Endlosschleife
            self._in_llm_command.add(msg.sender)
            try:
                await self.handle_remote_command(cmd_msg, cmd)
            finally:
                self._in_llm_command.discard(msg.sender)
            return

        # Parse fehlgeschlagen → Retry mit Feedback
        logger.info(
            "LLM remote_command nicht erkannt: '%s' – starte Retry",
            command_text,
        )
        retry_cmd = await self._retry_llm_remote_command(msg, command_text)
        if retry_cmd:
            cmd_msg = IM(
                sender=msg.sender,
                room_id=msg.room_id,
                body=retry_cmd,
                timestamp=msg.timestamp,
            )
            parsed = self._remote_commands.parse_command(retry_cmd)
            if parsed:
                await self.handle_remote_command(cmd_msg, parsed)
                return

        logger.warning(
            "LLM remote_command nach Retry nicht erkannt: '%s'",
            command_text,
        )
        # Phase 81b: Im Fallback-Pfad versuchen wir, einen Plugin-Vorschlag
        # ueber die Phase-78-Pipeline anzulegen. Der Aggregator filtert
        # selbst (Smalltalk, confidence<0.7, abgelehnt nur Trigger-Zaehler);
        # wir checken zusaetzlich is_rejected vorher, um den User nicht
        # ueber bereits abgelehnte Features zu informieren.
        proposal_recorded = await self._propose_plugin_for_failed_command(
            msg, command_text
        )

        # Punkt 7: User-Feedback statt Schweigen.
        try:
            base = (
                f"Ich habe das als Befehl verstanden ('{command_text}'), "
                "konnte ihn aber keinem meiner Commands zuordnen."
            )
            note = (
                " Ich habe Marcus eine Notiz hinterlassen -- wenn das oefter "
                "vorkommt, kuemmert er sich darum."
                if proposal_recorded
                else ""
            )
            fallback = f"{base}{note} Tipp 'hilfe' fuer die Uebersicht."
            await self._channel.send_text(msg.room_id, fallback)
        except Exception as exc:  # pragma: no cover - reine Defensive
            logger.error("Fallback-Meldung konnte nicht gesendet werden: %s", exc)
