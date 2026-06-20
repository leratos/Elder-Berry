"""Flow-Tests für ConfirmationActionsMixin (Backlog #834).

Deckt ab: ``_execute_nextcloud_setup`` (Löschen + mkdir, ``NextcloudError``,
Timeout, nicht konfiguriert, äußere Exception) und ``_execute_bulk_delete``
(Termine / Todos / Erinnerungen, Handler fehlt, ``_remote_commands`` None,
unbekannter Typ, Exception).

Muster siehe Journal #839. Nextcloud-Setup wickelt jeden Einzel-Call in
``asyncio.wait_for(loop.run_in_executor(...))``; ``NextcloudError`` und
``asyncio.TimeoutError`` werden per ``side_effect`` auf dem ``_nc_files``-Mock
ausgelöst (sie propagieren durch ``wait_for`` und werden pro Element gefangen).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.confirmation_handlers import ConfirmationHandler
from elder_berry.comms.pending_confirmation import PendingAction
from elder_berry.tools.nextcloud_files import NextcloudError


def _make_parent() -> MagicMock:
    parent = MagicMock()
    parent._channel = MagicMock()
    parent._channel.send_text = AsyncMock()
    parent._pending = MagicMock()
    parent._chat_history = MagicMock()
    parent._remote_commands = MagicMock()
    parent._nc_files = MagicMock()
    parent._email_sender = MagicMock()
    parent._email_client = MagicMock()
    parent._scheduler_mgr = MagicMock()
    parent.restart_cooldown_until = 0.0
    parent._handle_llm_enrichment = AsyncMock()
    return parent


def _make_msg(
    body: str = "ja",
    sender: str = "@user:matrix.org",
    room_id: str = "!room:matrix.org",
) -> MagicMock:
    msg = MagicMock()
    msg.body = body
    msg.sender = sender
    msg.room_id = room_id
    msg.timestamp = time.time()
    return msg


def _payloads(parent: MagicMock) -> list[str]:
    return [c.args[1] for c in parent._channel.send_text.call_args_list]


# ---------------------------------------------------------------------------
# _execute_nextcloud_setup
# ---------------------------------------------------------------------------


def _nc_action() -> PendingAction:
    return PendingAction(
        action_type="nextcloud_setup",
        description="Setup",
        data={"to_delete": ["Alt"], "to_create": ["/Eingang/Neu"]},
    )


class TestExecuteNextcloudSetup:
    async def test_not_configured(self):
        parent = _make_parent()
        parent._nc_files = None

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_nextcloud_setup(msg, _nc_action())

        assert _payloads(parent) == ["Nextcloud nicht konfiguriert."]
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_success_delete_and_mkdir(self):
        parent = _make_parent()
        parent._nc_files.delete.return_value = None
        parent._nc_files.mkdir.return_value = True

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_nextcloud_setup(msg, _nc_action())

        parent._nc_files.delete.assert_called_once_with("Alt")
        parent._nc_files.mkdir.assert_called_once_with("/Eingang/Neu")
        parent._pending.clear.assert_called_once_with(msg.sender)
        joined = "\n".join(_payloads(parent))
        assert "Nextcloud-Setup wird ausgeführt" in joined
        assert "abgeschlossen" in joined
        assert "Gelöscht: Alt" in joined
        assert "Erstellt: 1 Ordner" in joined
        assert parent._chat_history.add.call_count == 2

    async def test_mkdir_not_new_is_not_counted(self):
        parent = _make_parent()
        parent._nc_files.delete.return_value = None
        parent._nc_files.mkdir.return_value = False  # Ordner existierte schon

        handler = ConfirmationHandler(parent)
        await handler._execute_nextcloud_setup(_make_msg(), _nc_action())

        joined = "\n".join(_payloads(parent))
        assert "Erstellt" not in joined

    async def test_delete_nextcloud_error_collected(self):
        parent = _make_parent()
        parent._nc_files.delete.side_effect = NextcloudError("permission denied")
        parent._nc_files.mkdir.return_value = True

        handler = ConfirmationHandler(parent)
        await handler._execute_nextcloud_setup(_make_msg(), _nc_action())

        joined = "\n".join(_payloads(parent))
        assert "abgeschlossen" in joined  # Setup läuft trotz Einzelfehler durch
        assert "⚠️ Fehler (1):" in joined
        assert "Löschen 'Alt': permission denied" in joined

    async def test_delete_timeout_collected(self):
        parent = _make_parent()
        parent._nc_files.delete.side_effect = asyncio.TimeoutError()
        parent._nc_files.mkdir.return_value = True

        handler = ConfirmationHandler(parent)
        await handler._execute_nextcloud_setup(_make_msg(), _nc_action())

        joined = "\n".join(_payloads(parent))
        assert "Löschen 'Alt': Timeout" in joined

    async def test_unexpected_exception_aborts_and_clears(self):
        parent = _make_parent()
        # ValueError ist weder NextcloudError noch TimeoutError -> äußerer Handler.
        parent._nc_files.delete.side_effect = ValueError("weird")

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_nextcloud_setup(msg, _nc_action())

        joined = "\n".join(_payloads(parent))
        assert "Nextcloud-Setup fehlgeschlagen: ValueError" in joined
        parent._pending.clear.assert_called_once_with(msg.sender)


# ---------------------------------------------------------------------------
# _execute_bulk_delete
# ---------------------------------------------------------------------------


def _bulk_action(action_type: str, data: dict | None = None) -> PendingAction:
    return PendingAction(
        action_type=action_type,
        description="Bulk",
        data=data or {},
    )


class TestExecuteBulkDelete:
    async def test_no_remote_commands(self):
        parent = _make_parent()
        parent._remote_commands = None

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_bulk_delete(msg, _bulk_action("bulk_delete_events"))

        assert _payloads(parent) == ["❌ Interner Fehler."]
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_events_success(self):
        parent = _make_parent()
        parent._remote_commands._calendar.execute_delete_all_events.return_value = (
            CommandResult(command="cal", success=True, text="3 Termine gelöscht")
        )

        handler = ConfirmationHandler(parent)
        action = _bulk_action("bulk_delete_events", {"event_ids": [1, 2, 3]})
        await handler._execute_bulk_delete(_make_msg(), action)

        call = parent._remote_commands._calendar.execute_delete_all_events.call_args
        assert call.args[0] == [1, 2, 3]
        assert any("3 Termine gelöscht" in p for p in _payloads(parent))

    async def test_events_handler_missing(self):
        parent = _make_parent()
        parent._remote_commands._calendar = None

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(_make_msg(), _bulk_action("bulk_delete_events"))

        assert any("Kalender nicht verfügbar" in p for p in _payloads(parent))

    async def test_todos_success(self):
        parent = _make_parent()
        parent._remote_commands._todos.execute_cleanup.return_value = CommandResult(
            command="todos", success=True, text="Aufgaben aufgeräumt"
        )

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(_make_msg(), _bulk_action("bulk_delete_todos"))

        parent._remote_commands._todos.execute_cleanup.assert_called_once()
        assert any("aufgeräumt" in p for p in _payloads(parent))

    async def test_todos_handler_missing(self):
        parent = _make_parent()
        parent._remote_commands._todos = None

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(_make_msg(), _bulk_action("bulk_delete_todos"))

        assert any("Aufgabenliste nicht verfügbar" in p for p in _payloads(parent))

    async def test_reminders_success(self):
        parent = _make_parent()
        parent._remote_commands._weather.execute_delete_all_reminders.return_value = (
            CommandResult(command="rem", success=True, text="Erinnerungen gelöscht")
        )

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(
            _make_msg(), _bulk_action("bulk_delete_reminders")
        )

        parent._remote_commands._weather.execute_delete_all_reminders.assert_called_once()
        assert any("Erinnerungen gelöscht" in p for p in _payloads(parent))

    async def test_reminders_handler_missing(self):
        parent = _make_parent()
        parent._remote_commands._weather = None

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(
            _make_msg(), _bulk_action("bulk_delete_reminders")
        )

        assert any("Erinnerungen nicht verfügbar" in p for p in _payloads(parent))

    async def test_unknown_bulk_type(self):
        parent = _make_parent()

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(_make_msg(), _bulk_action("bulk_delete_x"))

        assert any("Unbekannter Bulk-Delete-Typ" in p for p in _payloads(parent))

    async def test_exception_path(self):
        parent = _make_parent()
        parent._remote_commands._calendar.execute_delete_all_events.side_effect = (
            RuntimeError("boom")
        )

        handler = ConfirmationHandler(parent)
        await handler._execute_bulk_delete(
            _make_msg(), _bulk_action("bulk_delete_events", {"event_ids": [1]})
        )

        assert any("Löschen fehlgeschlagen: RuntimeError" in p for p in _payloads(parent))
