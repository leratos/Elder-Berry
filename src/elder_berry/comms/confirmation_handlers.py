"""ConfirmationHandler – Verarbeitung von Pending-Confirmation-Aktionen.

Kapselt die Logik für bestätigte Aktionen:
- Email-Reply Draft → Senden
- Filing (Dokument-Ablage) → Bestätigen / Überspringen / Korrigieren
- Restart nach Update
- Nextcloud-Setup

Greift auf Dependencies über den parent BridgeMessageHandler zu,
damit Änderungen an Referenzen (z.B. in Tests) konsistent bleiben.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from elder_berry.comms.pending_confirmation import PendingAction

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import IncomingMessage
    from elder_berry.comms.message_handlers import BridgeMessageHandler

logger = logging.getLogger(__name__)


class ConfirmationHandler:
    """Verarbeitet bestätigte PendingActions (Mail, Filing, Restart, Nextcloud).

    Greift auf Dependencies über den parent (BridgeMessageHandler) zu.
    """

    def __init__(self, parent: BridgeMessageHandler) -> None:
        self._p = parent

    async def handle_confirm(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt eine bestätigte PendingAction aus."""
        if action.action_type in ("mail_reply", "mail_reply_modify"):
            await self._execute_mail_send(msg, action)
        elif action.action_type == "nextcloud_setup":
            await self._execute_nextcloud_setup(msg, action)
        elif action.action_type in ("update", "update_all"):
            await self._execute_restart_confirm(msg, action)
        elif action.action_type == "filing":
            await self._execute_filing_confirm(msg, action)
        else:
            logger.warning("Unbekannter PendingAction-Typ: %s", action.action_type)
            await self._p._channel.send_text(
                msg.room_id, f"Unbekannte Aktion: {action.action_type}",
            )
            self._p._pending.clear(msg.sender)

    async def handle_modify(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Generiert einen neuen Draft basierend auf der Änderungsanweisung."""
        if action.action_type == "filing":
            hint = action.data.get("modify_instruction", "") or msg.body.strip()
            for prefix in ("ändern:", "Ändern:", "andern:", "ändern :", "Ändern :"):
                if hint.lower().startswith(prefix.lower()):
                    hint = hint[len(prefix):].strip()
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
                msg.room_id, "Format: ändern: <was soll anders sein>",
            )
            return

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
                    msg.room_id, new_result.text,
                )
                self._p._chat_history.add(msg.sender, "user", msg.body)
                self._p._chat_history.add(
                    msg.sender, "assistant", new_result.text or "",
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
                f"\u274c Änderung fehlgeschlagen: {type(e).__name__}",
            )

    async def handle_filing_response(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Verarbeitet Filing-Antworten die kein Standard-Confirm/Cancel sind."""
        from elder_berry.comms.commands.filing_commands import FILING_CONFIRM, FILING_SKIP

        filing_handler = self._get_filing_handler()
        if not filing_handler:
            await self._p._channel.send_text(msg.room_id, "Filing-Handler nicht verfügbar.")
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
                        None, filing_handler.handle_skip, action, msg.sender,
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
                    msg.sender, "assistant", result.text or "",
                )
            except Exception as e:
                logger.error("Filing-Skip fehlgeschlagen: %s", e)
                await self._p._channel.send_text(
                    msg.room_id, f"❌ Fehler: {type(e).__name__}",
                )
                self._p._pending.clear(msg.sender)
            return

        await self._execute_filing_correction(msg, action, msg.body.strip())

    # ------------------------------------------------------------------
    # Private Execution-Methoden
    # ------------------------------------------------------------------

    async def _execute_mail_send(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Sendet eine bestätigte Email-Antwort via SMTP."""
        if not self._p._email_sender:
            await self._p._channel.send_text(
                msg.room_id, "SMTP nicht konfiguriert.",
            )
            self._p._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._p._email_sender.send_reply(
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
                    f"\u2705 Antwort auf #{action.data['msg_id']} gesendet "
                    f"an {result.to}.",
                )
                self._p._chat_history.add(msg.sender, "user", "ja")
                self._p._chat_history.add(
                    msg.sender, "assistant",
                    f"Email-Antwort gesendet an {result.to}: "
                    f"{action.data['subject']}",
                )
            else:
                await self._p._channel.send_text(
                    msg.room_id,
                    f"\u274c Senden fehlgeschlagen: {result.error}\n"
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
                f"\u274c Fehler beim Senden: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)

    async def _execute_filing_confirm(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt eine bestätigte Filing-Aktion aus (Datei verschieben)."""
        filing_handler = self._get_filing_handler()
        if not filing_handler:
            await self._p._channel.send_text(msg.room_id, "Filing-Handler nicht verfügbar.")
            self._p._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, filing_handler.handle_confirm, action, msg.sender,
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
                msg.sender, "assistant", result.text or "",
            )
        except asyncio.TimeoutError:
            logger.error("Timeout bei Filing-Confirm (60s)")
            await self._p._channel.send_text(msg.room_id, "Zeitüberschreitung beim Ablegen.")
        except Exception as e:
            logger.error("Filing-Confirm fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id, f"❌ Ablegen fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)

    async def _execute_filing_correction(
        self, msg: IncomingMessage, action: PendingAction, hint: str,
    ) -> None:
        """Führt eine Filing-Korrektur aus (User gibt Hint/neuen Namen)."""
        filing_handler = self._get_filing_handler()
        if not filing_handler:
            await self._p._channel.send_text(msg.room_id, "Filing-Handler nicht verfügbar.")
            self._p._pending.clear(msg.sender)
            return

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    filing_handler.handle_correction, action, hint, msg.sender,
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
                msg.sender, "assistant", result.text or "",
            )
        except Exception as e:
            logger.error("Filing-Correction fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id, f"❌ Korrektur fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)

    def _get_filing_handler(self):
        """Holt den FilingCommandHandler über den RemoteCommandHandler."""
        rc = self._p._remote_commands
        if rc and hasattr(rc, "_filing"):
            return rc._filing
        return None

    async def _execute_restart_confirm(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt einen bestätigten Neustart aus (nach 'update' ohne neue Commits)."""
        self._p._pending.clear(msg.sender)
        self._p._chat_history.add(msg.sender, "user", "ja")
        self._p._chat_history.add(msg.sender, "assistant", "🔄 Neustart bestätigt.")

        if time.monotonic() < self._p.restart_cooldown_until:
            await self._p._channel.send_text(
                msg.room_id,
                "Restart-Cooldown aktiv – ich wurde gerade erst "
                "neu gestartet. Bitte warte noch etwas.",
            )
            return

        await self._p._channel.send_text(msg.room_id, "🔄 Starte neu …")
        from elder_berry.comms.restart_manager import perform_restart
        await perform_restart(
            self._p._channel, self._p._scheduler_mgr,
            msg.room_id, msg_server_ts=msg.timestamp,
        )

    async def _execute_nextcloud_setup(
        self, msg: IncomingMessage, action: PendingAction,
    ) -> None:
        """Führt das bestätigte Nextcloud-Setup aus (löschen + Ordner anlegen)."""
        if not self._p._nc_files:
            await self._p._channel.send_text(
                msg.room_id, "Nextcloud nicht konfiguriert.",
            )
            self._p._pending.clear(msg.sender)
            return

        to_delete: list[str] = action.data.get("to_delete", [])
        to_create: list[str] = action.data.get("to_create", [])

        await self._p._channel.send_text(
            msg.room_id, "Nextcloud-Setup wird ausgeführt …",
        )

        try:
            from elder_berry.tools.nextcloud_files import NextcloudError

            loop = asyncio.get_running_loop()
            deleted: list[str] = []
            created: list[str] = []
            errors: list[str] = []

            for name in to_delete:
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None, self._p._nc_files.delete, name,
                        ),
                        timeout=15.0,
                    )
                    deleted.append(name)
                except NextcloudError as e:
                    errors.append(f"Löschen '{name}': {e}")
                except asyncio.TimeoutError:
                    errors.append(f"Löschen '{name}': Timeout")

            for path in to_create:
                try:
                    is_new = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, self._p._nc_files.mkdir, path,
                        ),
                        timeout=10.0,
                    )
                    if is_new:
                        created.append(path)
                except NextcloudError as e:
                    errors.append(f"mkdir '{path}': {e}")
                except asyncio.TimeoutError:
                    errors.append(f"mkdir '{path}': Timeout")

            lines = ["\u2705 Nextcloud-Setup abgeschlossen.\n"]
            if deleted:
                lines.append(f"Gelöscht: {', '.join(deleted)}")
            if created:
                lines.append(f"Erstellt: {len(created)} Ordner")
            if errors:
                lines.append(f"\n\u26a0\ufe0f Fehler ({len(errors)}):")
                for err in errors:
                    lines.append(f"  • {err}")

            self._p._pending.clear(msg.sender)
            await self._p._channel.send_text(msg.room_id, "\n".join(lines))

            self._p._chat_history.add(msg.sender, "user", "ja")
            self._p._chat_history.add(
                msg.sender, "assistant",
                f"Nextcloud-Setup: {len(deleted)} gelöscht, "
                f"{len(created)} Ordner erstellt",
            )

        except Exception as e:
            logger.error("Nextcloud-Setup fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"\u274c Nextcloud-Setup fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)
