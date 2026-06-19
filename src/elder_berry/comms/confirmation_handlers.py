"""ConfirmationHandler – Verarbeitung von Pending-Confirmation-Aktionen.

Kapselt die Logik für bestätigte Aktionen:
- Email-Reply Draft → Senden
- Filing (Dokument-Ablage) → Bestätigen / Überspringen / Korrigieren
- Restart nach Update
- Nextcloud-Setup
- Anhang-Aktionsmenü (zusammenfassen / ablegen / löschen)

Greift auf Dependencies über den parent BridgeMessageHandler zu,
damit Änderungen an Referenzen (z.B. in Tests) konsistent bleiben.

Phase 106 (Modul-Entflechtung): Dieses Modul ist der dünne Dispatch-Shell.
Die action-spezifischen Ausführungs-Methoden wohnen als Mixins unter
``elder_berry.comms.handlers`` (Mail / Filing / Restart / Nextcloud+Bulk /
Attachment); ``ConfirmationHandler`` erbt sie. Der öffentliche Importpfad
(``elder_berry.comms.confirmation_handlers.ConfirmationHandler``) sowie
``logger`` und ``asyncio`` als Modul-Attribute bleiben unverändert.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from elder_berry.comms.handlers.confirmation_actions import ConfirmationActionsMixin
from elder_berry.comms.handlers.confirmation_attachment import (
    ConfirmationAttachmentMixin,
)
from elder_berry.comms.handlers.confirmation_filing import ConfirmationFilingMixin
from elder_berry.comms.handlers.confirmation_mail import ConfirmationMailMixin
from elder_berry.comms.handlers.confirmation_restart import ConfirmationRestartMixin
from elder_berry.comms.pending_confirmation import PendingAction

if TYPE_CHECKING:
    from elder_berry.comms.handlers._confirmation_base import ConfirmationParent
    from elder_berry.comms.message_channel import IncomingMessage

logger = logging.getLogger(__name__)


class ConfirmationHandler(
    ConfirmationMailMixin,
    ConfirmationFilingMixin,
    ConfirmationRestartMixin,
    ConfirmationActionsMixin,
    ConfirmationAttachmentMixin,
):
    """Verarbeitet bestätigte PendingActions (Mail, Filing, Restart, Nextcloud).

    Greift auf Dependencies über den parent (BridgeMessageHandler) zu. Die
    Ausführung der einzelnen Aktionstypen liegt in den geerbten Mixins; hier
    bleiben nur die öffentlichen Dispatch-Einstiege und das Anhang-Menü.
    """

    _MENU_SUMMARIZE = frozenset(
        {
            "zusammenfassen",
            "zusammenfassung",
            "fasse zusammen",
            "summary",
        }
    )
    _MENU_FILE = frozenset(
        {
            "ablegen",
            "einsortieren",
            "einordnen",
            "sortieren",
            "file",
        }
    )
    _MENU_DELETE = frozenset(
        {
            "löschen",
            "loeschen",
            "entfernen",
            "delete",
        }
    )
    _MENU_SKIP = frozenset(
        {
            "nichts",
            "nein",
            "nix",
            "lass",
            "skip",
            "überspringen",
        }
    )

    def __init__(self, parent: ConfirmationParent) -> None:
        self._p = parent

    async def handle_confirm(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Führt eine bestätigte PendingAction aus."""
        if action.action_type in ("mail_reply", "mail_reply_modify"):
            await self._execute_mail_send(msg, action)
        elif action.action_type == "nextcloud_setup":
            await self._execute_nextcloud_setup(msg, action)
        elif action.action_type in (
            "update",
            "update_all",
            "restart",
            "restart_tower",
            "restart_all",
        ):
            await self._execute_restart_confirm(msg, action)
        elif action.action_type == "filing":
            await self._execute_filing_confirm(msg, action)
        elif action.action_type in (
            "bulk_delete_events",
            "bulk_delete_todos",
            "bulk_delete_reminders",
        ):
            await self._execute_bulk_delete(msg, action)
        elif action.action_type == "recipe_save":
            await self._execute_recipe_save(msg, action)
        else:
            logger.warning("Unbekannter PendingAction-Typ: %s", action.action_type)
            await self._p._channel.send_text(
                msg.room_id,
                f"Unbekannte Aktion: {action.action_type}",
            )
            self._p._pending.clear(msg.sender)

    async def handle_modify(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Generiert einen neuen Draft basierend auf der Änderungsanweisung."""
        if action.action_type == "filing":
            hint = action.data.get("modify_instruction", "") or msg.body.strip()
            for prefix in ("ändern:", "Ändern:", "andern:", "ändern :", "Ändern :"):
                if hint.lower().startswith(prefix.lower()):
                    hint = hint[len(prefix) :].strip()
                    break
            await self._execute_filing_correction(msg, action, hint)
            return

        if action.action_type not in ("mail_reply", "mail_reply_modify"):
            await self._p._channel.send_text(
                msg.room_id,
                "Ändern wird für diesen Aktionstyp nicht unterstützt.",
            )
            return

        modify_instruction = action.data.get("modify_instruction", "")
        if not modify_instruction:
            await self._p._channel.send_text(
                msg.room_id,
                "Format: ändern: <was soll anders sein>",
            )
            return

        # mail_reply/mail_reply_modify werden nur erzeugt wenn
        # _remote_commands existiert -- _create_pending_mail_reply baut
        # die PendingAction. Hier ist self._p._remote_commands also nicht None.
        assert self._p._remote_commands is not None
        try:
            loop = asyncio.get_running_loop()
            new_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._p._remote_commands.execute,
                    "mail_reply_modify",
                    f"#{action.data['msg_id']} {modify_instruction}",
                ),
                timeout=120.0,
            )
            if new_result.success and new_result.pending_data:
                new_action = PendingAction(
                    action_type="mail_reply",
                    description=new_result.text or "",
                    data=new_result.pending_data,
                )
                self._p._pending.set(msg.sender, new_action)
                await self._p._channel.send_text(
                    msg.room_id,
                    new_result.text or "",
                )
                self._p._chat_history.add(msg.sender, "user", msg.body)
                self._p._chat_history.add(
                    msg.sender,
                    "assistant",
                    new_result.text or "",
                )
            else:
                await self._p._channel.send_text(
                    msg.room_id,
                    new_result.text or "Draft-Änderung fehlgeschlagen.",
                )
        except asyncio.TimeoutError:
            logger.error("Timeout bei Draft-Änderung (120s)")
            await self._p._channel.send_text(
                msg.room_id,
                "Zeitüberschreitung bei der Draft-Generierung.",
            )
        except Exception as e:
            logger.error("Draft-Änderung fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Änderung fehlgeschlagen: {type(e).__name__}",
            )

    async def handle_filing_response(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Verarbeitet Filing-Antworten die kein Standard-Confirm/Cancel sind."""
        from elder_berry.comms.commands.filing_commands import (
            FILING_CONFIRM,
            FILING_SKIP,
        )

        filing_handler = self._get_filing_handler()
        if not filing_handler:
            await self._p._channel.send_text(
                msg.room_id, "Filing-Handler nicht verfügbar."
            )
            self._p._pending.clear(msg.sender)
            return

        lower = msg.body.strip().lower()

        if lower in FILING_CONFIRM:
            await self._execute_filing_confirm(msg, action)
            return

        if lower in FILING_SKIP:
            try:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        filing_handler.handle_skip,
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
            except Exception as e:
                logger.error("Filing-Skip fehlgeschlagen: %s", e)
                await self._p._channel.send_text(
                    msg.room_id,
                    f"❌ Fehler: {type(e).__name__}",
                )
                self._p._pending.clear(msg.sender)
            return

        await self._execute_filing_correction(msg, action, msg.body.strip())

    async def handle_attachment_menu(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Verarbeitet Anhang-Aktionsmenü-Antworten."""
        choice = msg.body.strip().lower()

        if choice in self._MENU_SUMMARIZE:
            await self._attachment_summarize(msg, action)
        elif choice in self._MENU_FILE:
            await self._attachment_file(msg, action)
        elif choice in self._MENU_DELETE:
            await self._attachment_delete(msg, action)
        elif choice in self._MENU_SKIP:
            self._attachment_cleanup_temp(action)
            self._p._pending.clear(msg.sender)
            await self._p._channel.send_text(
                msg.room_id,
                "Alles klar, Anhänge bleiben in Nextcloud.",
            )
        else:
            await self._p._channel.send_text(
                msg.room_id,
                "Bitte wähle: zusammenfassen / ablegen / löschen / nichts",
            )
