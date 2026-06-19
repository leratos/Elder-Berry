"""ConfirmationHandler-Mixin: Filing-Bestätigung/-Korrektur + Recipe-Save.

Phase 106 (Modul-Entflechtung): aus ``confirmation_handlers.py`` ausgelagert.
``_get_filing_handler`` lebt in der gemeinsamen Basis (handler-übergreifend
genutzt); hier liegen Filing-Confirm/Correction, der Recipe-Lookup und
Recipe-Save. Dependencies über ``self._p``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from elder_berry.comms.handlers._confirmation_base import ConfirmationMixinBase
from elder_berry.comms.pending_confirmation import PendingAction

if TYPE_CHECKING:
    from elder_berry.comms.commands.recipe_commands import RecipeCommandHandler
    from elder_berry.comms.message_channel import IncomingMessage

logger = logging.getLogger(__name__)


class ConfirmationFilingMixin(ConfirmationMixinBase):
    """Führt bestätigte Filing-Aktionen + Recipe-Speicherung aus."""

    async def _execute_filing_confirm(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Führt eine bestätigte Filing-Aktion aus (Datei verschieben)."""
        filing_handler = self._get_filing_handler()
        if not filing_handler:
            await self._p._channel.send_text(
                msg.room_id, "Filing-Handler nicht verfügbar."
            )
            self._p._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    filing_handler.handle_confirm,
                    action,
                    msg.sender,
                ),
                timeout=60.0,
            )
            self._p._pending.clear(msg.sender)
            if result.text:
                await self._p._channel.send_text(msg.room_id, result.text)
            if result.pending_confirmation and result.pending_data:
                new_action = PendingAction(
                    action_type="filing",
                    description=result.text or "",
                    data=result.pending_data,
                )
                self._p._pending.set(msg.sender, new_action)
            self._p._chat_history.add(msg.sender, "user", msg.body)
            self._p._chat_history.add(
                msg.sender,
                "assistant",
                result.text or "",
            )
        except asyncio.TimeoutError:
            logger.error("Timeout bei Filing-Confirm (60s)")
            await self._p._channel.send_text(
                msg.room_id, "Zeitüberschreitung beim Ablegen."
            )
        except Exception as e:
            logger.error("Filing-Confirm fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Ablegen fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)

    async def _execute_filing_correction(
        self,
        msg: IncomingMessage,
        action: PendingAction,
        hint: str,
    ) -> None:
        """Führt eine Filing-Korrektur aus (User gibt Hint/neuen Namen)."""
        filing_handler = self._get_filing_handler()
        if not filing_handler:
            await self._p._channel.send_text(
                msg.room_id, "Filing-Handler nicht verfügbar."
            )
            self._p._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    filing_handler.handle_correction,
                    action,
                    hint,
                    msg.sender,
                ),
                timeout=120.0,
            )
            self._p._pending.clear(msg.sender)
            if result.text:
                await self._p._channel.send_text(msg.room_id, result.text)
            if result.pending_confirmation and result.pending_data:
                new_action = PendingAction(
                    action_type="filing",
                    description=result.text or "",
                    data=result.pending_data,
                )
                self._p._pending.set(msg.sender, new_action)
            self._p._chat_history.add(msg.sender, "user", msg.body)
            self._p._chat_history.add(
                msg.sender,
                "assistant",
                result.text or "",
            )
        except Exception as e:
            logger.error("Filing-Correction fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Korrektur fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)

    def _get_recipe_handler(self) -> RecipeCommandHandler | None:
        """Holt den RecipeCommandHandler ueber den RemoteCommandHandler."""
        rc = self._p._remote_commands
        if rc and hasattr(rc, "_recipe"):
            handler: RecipeCommandHandler | None = rc._recipe
            return handler
        return None

    async def _execute_recipe_save(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Speichert ein bestaetigtes Recipe-Draft im Cookbook."""
        recipe_handler = self._get_recipe_handler()
        if not recipe_handler:
            await self._p._channel.send_text(
                msg.room_id,
                "Recipe-Handler nicht verfuegbar.",
            )
            self._p._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    recipe_handler.confirm_pending_recipe,
                    action,
                ),
                timeout=90.0,
            )
            self._p._pending.clear(msg.sender)
            if result.text:
                await self._p._channel.send_text(msg.room_id, result.text)
            self._p._chat_history.add(msg.sender, "user", msg.body)
            self._p._chat_history.add(msg.sender, "assistant", result.text or "")
        except asyncio.TimeoutError:
            logger.error("Timeout bei Recipe-Confirm (90s)")
            await self._p._channel.send_text(
                msg.room_id,
                "Zeitueberschreitung beim Speichern des Rezepts.",
            )
        except Exception as e:
            logger.error("Recipe-Confirm fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Rezept-Speichern fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)
