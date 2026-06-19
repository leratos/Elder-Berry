"""ConfirmationHandler-Mixin: Nextcloud-Setup + Bulk-Delete (Phase 50).

Phase 106 (Modul-Entflechtung): aus ``confirmation_handlers.py`` ausgelagert.
Reiner Methoden-Umzug; Dependencies über ``self._p``.
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


class ConfirmationActionsMixin(ConfirmationMixinBase):
    """Führt bestätigtes Nextcloud-Setup und Bulk-Löschungen aus."""

    async def _execute_nextcloud_setup(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Führt das bestätigte Nextcloud-Setup aus (löschen + Ordner anlegen)."""
        if not self._p._nc_files:
            await self._p._channel.send_text(
                msg.room_id,
                "Nextcloud nicht konfiguriert.",
            )
            self._p._pending.clear(msg.sender)
            return

        to_delete: list[str] = action.data.get("to_delete", [])
        to_create: list[str] = action.data.get("to_create", [])

        await self._p._channel.send_text(
            msg.room_id,
            "Nextcloud-Setup wird ausgeführt …",
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
                            None,
                            self._p._nc_files.delete,
                            name,
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
                            None,
                            self._p._nc_files.mkdir,
                            path,
                        ),
                        timeout=10.0,
                    )
                    if is_new:
                        created.append(path)
                except NextcloudError as e:
                    errors.append(f"mkdir '{path}': {e}")
                except asyncio.TimeoutError:
                    errors.append(f"mkdir '{path}': Timeout")

            lines = ["✅ Nextcloud-Setup abgeschlossen.\n"]
            if deleted:
                lines.append(f"Gelöscht: {', '.join(deleted)}")
            if created:
                lines.append(f"Erstellt: {len(created)} Ordner")
            if errors:
                lines.append(f"\n⚠️ Fehler ({len(errors)}):")
                for err in errors:
                    lines.append(f"  • {err}")

            self._p._pending.clear(msg.sender)
            await self._p._channel.send_text(msg.room_id, "\n".join(lines))

            self._p._chat_history.add(msg.sender, "user", "ja")
            self._p._chat_history.add(
                msg.sender,
                "assistant",
                f"Nextcloud-Setup: {len(deleted)} gelöscht, "
                f"{len(created)} Ordner erstellt",
            )

        except Exception as e:
            logger.error("Nextcloud-Setup fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Nextcloud-Setup fehlgeschlagen: {type(e).__name__}",
            )
            self._p._pending.clear(msg.sender)

    async def _execute_bulk_delete(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Führt eine bestätigte Bulk-Löschung aus (Termine/Todos/Erinnerungen)."""
        self._p._pending.clear(msg.sender)
        self._p._chat_history.add(msg.sender, "user", "ja")

        rc = self._p._remote_commands
        if not rc:
            await self._p._channel.send_text(msg.room_id, "❌ Interner Fehler.")
            return

        try:
            loop = asyncio.get_running_loop()

            if action.action_type == "bulk_delete_events":
                handler = getattr(rc, "_calendar", None)
                if not handler:
                    await self._p._channel.send_text(
                        msg.room_id,
                        "❌ Kalender nicht verfügbar.",
                    )
                    return
                event_ids = action.data.get("event_ids", [])
                result = await loop.run_in_executor(
                    None,
                    handler.execute_delete_all_events,
                    event_ids,
                )

            elif action.action_type == "bulk_delete_todos":
                handler = getattr(rc, "_todos", None)
                if not handler:
                    await self._p._channel.send_text(
                        msg.room_id,
                        "❌ Aufgabenliste nicht verfügbar.",
                    )
                    return
                result = await loop.run_in_executor(
                    None,
                    handler.execute_cleanup,
                )

            elif action.action_type == "bulk_delete_reminders":
                handler = getattr(rc, "_weather", None)
                if not handler:
                    await self._p._channel.send_text(
                        msg.room_id,
                        "❌ Erinnerungen nicht verfügbar.",
                    )
                    return
                result = await loop.run_in_executor(
                    None,
                    handler.execute_delete_all_reminders,
                )
            else:
                await self._p._channel.send_text(
                    msg.room_id,
                    f"❌ Unbekannter Bulk-Delete-Typ: {action.action_type}",
                )
                return

            await self._p._channel.send_text(msg.room_id, result.text)
            self._p._chat_history.add(msg.sender, "assistant", result.text)

        except Exception as e:
            logger.error("Bulk-Delete fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Löschen fehlgeschlagen: {type(e).__name__}",
            )
