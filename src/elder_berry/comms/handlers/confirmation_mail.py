"""ConfirmationHandler-Mixin: bestätigte Mail-Reply-Drafts via SMTP senden.

Phase 106 (Modul-Entflechtung): aus ``confirmation_handlers.py`` ausgelagert.
Reiner Methoden-Umzug, kein Verhaltenswechsel; Dependencies weiterhin über
``self._p`` (parent BridgeMessageHandler).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from elder_berry.comms.handlers._confirmation_base import ConfirmationMixinBase

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import IncomingMessage
    from elder_berry.comms.pending_confirmation import PendingAction

logger = logging.getLogger(__name__)


class ConfirmationMailMixin(ConfirmationMixinBase):
    """Sendet bestätigte Email-Antworten (+ best-effort IMAP-Sent-Kopie)."""

    async def _execute_mail_send(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Sendet eine bestätigte Email-Antwort via SMTP."""
        if not self._p._email_sender:
            await self._p._channel.send_text(
                msg.room_id,
                "SMTP nicht konfiguriert.",
            )
            self._p._pending.clear(msg.sender)
            return

        # Lokal binden -- mypy verliert Narrowing ueber Lambda-Boundary.
        email_sender = self._p._email_sender
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: email_sender.send_reply(
                        to=action.data["to"],
                        subject=action.data["subject"],
                        body=action.data["draft_text"],
                        in_reply_to=action.data.get("in_reply_to", ""),
                        references=action.data.get("references", ""),
                    ),
                ),
                timeout=30.0,
            )

            if result.success:
                self._p._pending.clear(msg.sender)
                await self._p._channel.send_text(
                    msg.room_id,
                    f"✅ Antwort auf #{action.data['msg_id']} gesendet "
                    f"an {result.to}.",
                )
                self._p._chat_history.add(msg.sender, "user", "ja")
                self._p._chat_history.add(
                    msg.sender,
                    "assistant",
                    f"Email-Antwort gesendet an {result.to}: {action.data['subject']}",
                )
                # Best-effort: Kopie in IMAP Gesendet-Ordner
                if self._p._email_client and result.raw_msg:
                    try:
                        await loop.run_in_executor(
                            None,
                            self._p._email_client.copy_to_sent_folder,
                            result.raw_msg,
                        )
                    except Exception as e:
                        logger.warning(
                            "Kopie in Gesendet-Ordner fehlgeschlagen: %s",
                            e,
                        )
            else:
                await self._p._channel.send_text(
                    msg.room_id,
                    f"❌ Senden fehlgeschlagen: {result.error}\n"
                    f"Versuche es mit 'ja' erneut oder 'nein' zum Verwerfen.",
                )
        except asyncio.TimeoutError:
            logger.error("Timeout beim Email-Senden (30s)")
            await self._p._channel.send_text(
                msg.room_id,
                "Zeitüberschreitung beim Email-Senden.\n"
                "Versuche es mit 'ja' erneut oder 'nein' zum Verwerfen.",
            )
        except Exception as e:
            logger.error("Email senden fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Fehler beim Senden: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)
