"""Flow-Tests für die ConfirmationHandler-Shell-Dispatcher (Backlog #834).

Deckt die im Shell-Modul (``confirmation_handlers.py``) verbliebenen
Dispatcher ab: ``handle_modify`` (Filing-Korrektur-Routing + hint-Strip,
mail_reply-Redraft, nicht unterstützter Typ, Timeout, Exception),
``handle_filing_response`` (FILING_CONFIRM / FILING_SKIP inkl. Folge-Action,
Korrektur-Fallback, Handler fehlt) und ``handle_attachment_menu``
(``_MENU_*``-Routing).

Die eigentliche Ausführung der Aktionstypen lebt in den Mixins (eigene
Testdateien); hier wird das Routing geprüft, indem die geerbten Executor-
Methoden auf der Instanz durch AsyncMocks ersetzt werden. Muster sonst wie
Journal #839; Timeout via Patch von ``confirmation_handlers.asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.confirmation_handlers import ConfirmationHandler
from elder_berry.comms.pending_confirmation import PendingAction

_WAIT_FOR = "elder_berry.comms.confirmation_handlers.asyncio.wait_for"


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
# handle_modify
# ---------------------------------------------------------------------------


class TestHandleModify:
    async def test_filing_routes_to_correction_with_stripped_hint(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._execute_filing_correction = AsyncMock()
        action = PendingAction(action_type="filing", description="x", data={})
        msg = _make_msg(body="ändern: anderer Ordner")

        await handler.handle_modify(msg, action)

        handler._execute_filing_correction.assert_called_once()
        assert handler._execute_filing_correction.call_args.args[2] == "anderer Ordner"

    async def test_filing_uses_modify_instruction_when_present(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._execute_filing_correction = AsyncMock()
        action = PendingAction(
            action_type="filing",
            description="x",
            data={"modify_instruction": "neuer Name"},
        )

        await handler.handle_modify(_make_msg(body="egal"), action)

        assert handler._execute_filing_correction.call_args.args[2] == "neuer Name"

    async def test_unsupported_action_type(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        action = PendingAction(action_type="nextcloud_setup", description="x", data={})

        await handler.handle_modify(_make_msg(), action)

        assert any("nicht unterstützt" in p for p in _payloads(parent))

    async def test_missing_modify_instruction(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        action = PendingAction(action_type="mail_reply", description="x", data={})

        await handler.handle_modify(_make_msg(), action)

        assert any("Format: ändern:" in p for p in _payloads(parent))

    async def test_mail_reply_redraft_success(self):
        parent = _make_parent()
        parent._remote_commands.execute.return_value = CommandResult(
            command="mail_reply_modify",
            success=True,
            text="Neuer Draft",
            pending_data={"to": "x@y.de", "subject": "Re", "draft_text": "..."},
        )
        handler = ConfirmationHandler(parent)
        action = PendingAction(
            action_type="mail_reply",
            description="x",
            data={"modify_instruction": "formeller", "msg_id": "42"},
        )
        msg = _make_msg(body="ändern: formeller")

        await handler.handle_modify(msg, action)

        parent._remote_commands.execute.assert_called_once()
        parent._pending.set.assert_called_once()
        new_action = parent._pending.set.call_args.args[1]
        assert new_action.action_type == "mail_reply"
        assert new_action.data == {"to": "x@y.de", "subject": "Re", "draft_text": "..."}
        assert any("Neuer Draft" in p for p in _payloads(parent))
        assert parent._chat_history.add.call_count == 2

    async def test_mail_reply_redraft_failure(self):
        parent = _make_parent()
        parent._remote_commands.execute.return_value = CommandResult(
            command="mail_reply_modify",
            success=False,
            text="Konnte Draft nicht ändern",
        )
        handler = ConfirmationHandler(parent)
        action = PendingAction(
            action_type="mail_reply",
            description="x",
            data={"modify_instruction": "formeller", "msg_id": "42"},
        )

        await handler.handle_modify(_make_msg(), action)

        parent._pending.set.assert_not_called()
        assert any("Konnte Draft nicht ändern" in p for p in _payloads(parent))

    async def test_mail_reply_timeout(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        action = PendingAction(
            action_type="mail_reply",
            description="x",
            data={"modify_instruction": "formeller", "msg_id": "42"},
        )

        with patch(_WAIT_FOR, side_effect=asyncio.TimeoutError):
            await handler.handle_modify(_make_msg(), action)

        assert any("Zeitüberschreitung" in p for p in _payloads(parent))

    async def test_mail_reply_exception(self):
        parent = _make_parent()
        parent._remote_commands.execute.side_effect = RuntimeError("boom")
        handler = ConfirmationHandler(parent)
        action = PendingAction(
            action_type="mail_reply",
            description="x",
            data={"modify_instruction": "formeller", "msg_id": "42"},
        )

        await handler.handle_modify(_make_msg(), action)

        assert any("Änderung fehlgeschlagen: RuntimeError" in p for p in _payloads(parent))


# ---------------------------------------------------------------------------
# handle_filing_response
# ---------------------------------------------------------------------------


def _filing_action() -> PendingAction:
    return PendingAction(
        action_type="filing",
        description="Rechnung.pdf",
        data={"source_path": "/Eingang/Rechnung.pdf"},
    )


class TestHandleFilingResponse:
    async def test_handler_not_available(self):
        parent = _make_parent()
        parent._remote_commands = None
        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="ja")

        await handler.handle_filing_response(msg, _filing_action())

        assert any("Filing-Handler nicht verfügbar" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_confirm_routes_to_execute_confirm(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._execute_filing_confirm = AsyncMock()

        await handler.handle_filing_response(_make_msg(body="ja"), _filing_action())

        handler._execute_filing_confirm.assert_called_once()

    async def test_skip_success(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_skip.return_value = CommandResult(
            command="filing", success=True, text="Übersprungen."
        )
        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="überspringen")

        await handler.handle_filing_response(msg, _filing_action())

        parent._remote_commands._filing.handle_skip.assert_called_once()
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert any("Übersprungen" in p for p in _payloads(parent))
        assert parent._chat_history.add.call_count == 2

    async def test_skip_with_followup_action(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_skip.return_value = CommandResult(
            command="filing",
            success=True,
            text="Nächste Datei?",
            pending_confirmation=True,
            pending_data={"source_path": "/Eingang/Zweite.pdf"},
        )
        handler = ConfirmationHandler(parent)

        await handler.handle_filing_response(
            _make_msg(body="weiter"), _filing_action()
        )

        parent._pending.set.assert_called_once()
        assert parent._pending.set.call_args.args[1].action_type == "filing"

    async def test_skip_exception(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_skip.side_effect = RuntimeError("x")
        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="skip")

        await handler.handle_filing_response(msg, _filing_action())

        assert any("Fehler: RuntimeError" in p for p in _payloads(parent))
        # clear wird im Erfolg UND im except erneut gerufen -> mind. einmal.
        parent._pending.clear.assert_called_with(msg.sender)

    async def test_other_text_routes_to_correction(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._execute_filing_correction = AsyncMock()
        msg = _make_msg(body="lieber in den Vertragsordner")

        await handler.handle_filing_response(msg, _filing_action())

        handler._execute_filing_correction.assert_called_once()
        assert (
            handler._execute_filing_correction.call_args.args[2]
            == "lieber in den Vertragsordner"
        )


# ---------------------------------------------------------------------------
# handle_attachment_menu
# ---------------------------------------------------------------------------


def _menu_action() -> PendingAction:
    return PendingAction(
        action_type="attachment_menu",
        description="menu",
        data={"pdf_local_paths": []},
    )


class TestHandleAttachmentMenu:
    async def test_summarize_routing(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._attachment_summarize = AsyncMock()

        await handler.handle_attachment_menu(_make_msg(body="zusammenfassen"), _menu_action())

        handler._attachment_summarize.assert_called_once()

    async def test_file_routing(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._attachment_file = AsyncMock()

        await handler.handle_attachment_menu(_make_msg(body="ablegen"), _menu_action())

        handler._attachment_file.assert_called_once()

    async def test_delete_routing(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        handler._attachment_delete = AsyncMock()

        await handler.handle_attachment_menu(_make_msg(body="löschen"), _menu_action())

        handler._attachment_delete.assert_called_once()

    async def test_skip_cleans_up_and_clears(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)
        msg = _make_msg(body="nichts")

        await handler.handle_attachment_menu(msg, _menu_action())

        parent._pending.clear.assert_called_once_with(msg.sender)
        assert any("bleiben in Nextcloud" in p for p in _payloads(parent))

    async def test_unknown_choice(self):
        parent = _make_parent()
        handler = ConfirmationHandler(parent)

        await handler.handle_attachment_menu(_make_msg(body="häh?"), _menu_action())

        assert any("Bitte wähle" in p for p in _payloads(parent))
