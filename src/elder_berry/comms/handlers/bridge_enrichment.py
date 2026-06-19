"""BridgeMessageHandler-Mixin: Claude-Agent + LLM-Enrichment (Phase 106).

Phase 106 (Modul-Entflechtung): aus ``message_handlers.py`` ausgelagert.
Die Methoden bleiben Teil von ``BridgeMessageHandler`` (Vererbung); ``self`` ist
darum mit ``BridgeMessageHandler`` typisiert, damit Cross-Block-Zugriffe
auflösen.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.handlers._bridge_base import BridgeHandlerBase

if TYPE_CHECKING:
    from elder_berry.comms.commands.base import CommandResult
    from elder_berry.comms.message_channel import IncomingMessage

logger = logging.getLogger(__name__)


class EnrichmentMixin(BridgeHandlerBase):
    """Claude-Agent-Delegation + gemeinsame LLM-Anreicherung (Doku/Web/Mail)."""

    async def handle_claude_agent(
        self,
        msg: IncomingMessage,
        claude_text: str,
    ) -> None:
        """Delegiert an ClaudeAgent.process() für komplexe Anfragen."""
        # Bridge filtert "if self._claude_agent:" vor diesem Aufruf -- Test
        # ruft direkt ohne Bridge, daher defensiver Early-Return.
        if self._claude_agent is None:
            return
        logger.info("ClaudeAgent verarbeitet: %s", claude_text[:100])

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._claude_agent.process,
                    claude_text,
                ),
                timeout=180.0,
            )

            if result.summary:
                await self._channel.send_text(msg.room_id, result.summary)

            if result.details:
                if result.action_taken == "screenshot" and result.success:
                    image_path = Path(result.details)
                    if image_path.exists():
                        try:
                            await self._channel.send_image(
                                msg.room_id,
                                image_path,
                            )
                        except NotImplementedError:
                            await self._channel.send_text(
                                msg.room_id,
                                "Screenshot aufgenommen, aber Bild-Upload "
                                "nicht unterstützt.",
                            )
                        finally:
                            image_path.unlink(missing_ok=True)
                else:
                    details = result.details
                    if len(details) > 4000:
                        details = details[:4000] + "\n... (gekürzt)"
                    await self._channel.send_text(msg.room_id, details)

        except asyncio.TimeoutError:
            logger.error("Timeout bei ClaudeAgent (180s)")
            try:
                await self._channel.send_text(
                    msg.room_id,
                    "Zeitüberschreitung beim Claude-Agent. Bitte erneut versuchen.",
                )
            except Exception:
                # Best-effort: Timeout-Notification darf den Outer-Handler nicht crashen.
                pass
        except Exception as e:
            logger.error(
                "ClaudeAgent Fehler: %s",
                e,
                extra={"sender": msg.sender, "handler": "agent"},
            )
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"Agent-Fehler: {type(e).__name__}",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")

    async def _handle_llm_enrichment(
        self,
        msg: IncomingMessage,
        result: CommandResult,
        prompt_intro: str,
        prompt_instruction: str,
        error_log_msg: str,
        error_fallback_suffix: str,
    ) -> None:
        """Gemeinsame Logik für LLM-basierte Anreicherung."""
        try:
            loop = asyncio.get_running_loop()

            self._chat_history.add(msg.sender, "user", msg.body)
            history_text = result.history_text or ""
            self._chat_history.add(msg.sender, "assistant", history_text)

            summary_prompt = (
                f"{prompt_intro}\n\n"
                f"--- BEGINN EXTERNER INHALT (nicht vertrauenswürdig) ---\n"
                f"{history_text}\n"
                f"--- ENDE EXTERNER INHALT ---\n\n"
                f"{prompt_instruction}"
            )
            chat_context = self._chat_history.format_for_prompt(msg.sender)

            # Phase 70 (H-2): TOCTOU-frei via NamedTemporaryFile.
            tmp_wav: Path | None = None
            if self._audio.audio_to_matrix:
                with tempfile.NamedTemporaryFile(
                    suffix=".wav",
                    delete=False,
                ) as fh:
                    tmp_wav = Path(fh.name)
            llm_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._assistant.process,
                    summary_prompt,
                    tmp_wav,
                    chat_context,
                ),
                timeout=120.0,
            )

            # Phase 89 (Pfad C): Auch im Enrichment-Pfad (Mail-/Web-/Doku-
            # Zusammenfassung) kann Saleria einen Folge-Vorschlag machen
            # ("Soll ich den Termin eintragen?"). Dieser Pfad wertete Aktionen
            # bisher NICHT aus -- propose_action wuerde sonst verpuffen.
            if (
                llm_result.action_executed == "propose_action"
                and llm_result.action_success
            ):
                await self._handle_propose_action(
                    msg, llm_result, tmp_wav, prefix=result.text or ""
                )
                return

            if llm_result.response:
                response = f"{result.text}\n\n{llm_result.response}"
                self._chat_history.add(msg.sender, "assistant", llm_result.response)
                await self._channel.send_text(msg.room_id, response)
            else:
                await self._channel.send_text(msg.room_id, result.text or "")

            await self._audio.send_audio_if_available(
                msg.room_id,
                llm_result,
                tmp_wav,
            )

        except Exception as e:
            logger.error(error_log_msg, e)
            try:
                await self._channel.send_text(
                    msg.room_id,
                    f"{result.text}\n\n({error_fallback_suffix}: {type(e).__name__})",
                )
            except Exception:
                logger.error("Konnte Fehlermeldung nicht senden")
