"""Flow-Tests für ConfirmationFilingMixin (Backlog #834).

Deckt ab: ``_execute_filing_confirm`` / ``_execute_filing_correction``
(Erfolg, pending_confirmation-Folge-Action, Handler nicht verfügbar,
Timeout, Exception), den Recipe-Lookup ``_get_recipe_handler`` und
``_execute_recipe_save``.

Muster siehe Journal #839: ConfirmationHandler(parent) mit MagicMock-parent
(ConfirmationParent-Protocol); Happy-Paths über die reale Event-Loop, Timeout
via Patch von ``confirmation_filing.asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from elder_berry.comms.commands.base import CommandResult
from elder_berry.comms.confirmation_handlers import ConfirmationHandler
from elder_berry.comms.pending_confirmation import PendingAction

_WAIT_FOR = "elder_berry.comms.handlers.confirmation_filing.asyncio.wait_for"


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


def _filing_action() -> PendingAction:
    return PendingAction(
        action_type="filing",
        description="Rechnung.pdf -> /Belege/",
        data={"source_path": "/Eingang/Rechnung.pdf"},
    )


def _payloads(parent: MagicMock) -> list[str]:
    return [c.args[1] for c in parent._channel.send_text.call_args_list]


# ---------------------------------------------------------------------------
# _execute_filing_confirm
# ---------------------------------------------------------------------------


class TestExecuteFilingConfirm:
    async def test_handler_not_available(self):
        parent = _make_parent()
        parent._remote_commands._filing = None

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_confirm(msg, _filing_action())

        assert _payloads(parent) == ["Filing-Handler nicht verfügbar."]
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_success(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_confirm.return_value = CommandResult(
            command="filing",
            success=True,
            text="✅ Abgelegt in /Belege/",
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_confirm(msg, _filing_action())

        parent._remote_commands._filing.handle_confirm.assert_called_once()
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert any("Abgelegt" in p for p in _payloads(parent))
        parent._pending.set.assert_not_called()
        assert parent._chat_history.add.call_count == 2

    async def test_success_with_followup_action(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_confirm.return_value = CommandResult(
            command="filing",
            success=True,
            text="Nächste Datei?",
            pending_confirmation=True,
            pending_data={"source_path": "/Eingang/Zweite.pdf"},
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_confirm(msg, _filing_action())

        parent._pending.set.assert_called_once()
        new_action = parent._pending.set.call_args.args[1]
        assert isinstance(new_action, PendingAction)
        assert new_action.action_type == "filing"
        assert new_action.data == {"source_path": "/Eingang/Zweite.pdf"}

    async def test_timeout(self):
        parent = _make_parent()

        handler = ConfirmationHandler(parent)
        with patch(_WAIT_FOR, side_effect=asyncio.TimeoutError):
            await handler._execute_filing_confirm(_make_msg(), _filing_action())

        assert any("Zeitüberschreitung" in p for p in _payloads(parent))
        parent._pending.clear.assert_not_called()

    async def test_generic_exception_clears_pending(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_confirm.side_effect = RuntimeError("x")

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_confirm(msg, _filing_action())

        assert any("Ablegen fehlgeschlagen" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)


# ---------------------------------------------------------------------------
# _execute_filing_correction
# ---------------------------------------------------------------------------


class TestExecuteFilingCorrection:
    async def test_handler_not_available(self):
        parent = _make_parent()
        parent._remote_commands._filing = None

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_correction(msg, _filing_action(), "neuer Name")

        assert _payloads(parent) == ["Filing-Handler nicht verfügbar."]
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_success_passes_hint(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_correction.return_value = CommandResult(
            command="filing",
            success=True,
            text="Neuer Vorschlag: /Vertraege/",
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_correction(msg, _filing_action(), "Verträge")

        call = parent._remote_commands._filing.handle_correction.call_args
        assert call.args[1] == "Verträge"
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert any("Vorschlag" in p for p in _payloads(parent))

    async def test_success_with_followup_action(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_correction.return_value = CommandResult(
            command="filing",
            success=True,
            text="Passt das?",
            pending_confirmation=True,
            pending_data={"source_path": "/Eingang/Rechnung.pdf"},
        )

        handler = ConfirmationHandler(parent)
        await handler._execute_filing_correction(_make_msg(), _filing_action(), "hint")

        parent._pending.set.assert_called_once()
        assert parent._pending.set.call_args.args[1].action_type == "filing"

    async def test_exception_clears_pending(self):
        parent = _make_parent()
        parent._remote_commands._filing.handle_correction.side_effect = RuntimeError("x")

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_filing_correction(msg, _filing_action(), "hint")

        assert any("Korrektur fehlgeschlagen" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)


# ---------------------------------------------------------------------------
# _get_recipe_handler
# ---------------------------------------------------------------------------


class TestGetRecipeHandler:
    def test_returns_handler_when_present(self):
        parent = _make_parent()
        sentinel = MagicMock()
        parent._remote_commands._recipe = sentinel

        handler = ConfirmationHandler(parent)
        assert handler._get_recipe_handler() is sentinel

    def test_returns_none_without_remote_commands(self):
        parent = _make_parent()
        parent._remote_commands = None

        handler = ConfirmationHandler(parent)
        assert handler._get_recipe_handler() is None


# ---------------------------------------------------------------------------
# _execute_recipe_save
# ---------------------------------------------------------------------------


def _recipe_action() -> PendingAction:
    return PendingAction(
        action_type="recipe_save",
        description="Pfannkuchen speichern",
        data={"recipe_json": {"name": "Pfannkuchen"}},
    )


class TestExecuteRecipeSave:
    async def test_handler_not_available(self):
        parent = _make_parent()
        parent._remote_commands._recipe = None

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_recipe_save(msg, _recipe_action())

        assert any("Recipe-Handler nicht verfuegbar" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_success(self):
        parent = _make_parent()
        parent._remote_commands._recipe.confirm_pending_recipe.return_value = (
            CommandResult(command="recipe", success=True, text="📒 Rezept gespeichert.")
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_recipe_save(msg, _recipe_action())

        parent._remote_commands._recipe.confirm_pending_recipe.assert_called_once()
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert any("gespeichert" in p for p in _payloads(parent))
        assert parent._chat_history.add.call_count == 2

    async def test_timeout(self):
        parent = _make_parent()

        handler = ConfirmationHandler(parent)
        with patch(_WAIT_FOR, side_effect=asyncio.TimeoutError):
            await handler._execute_recipe_save(_make_msg(), _recipe_action())

        assert any("Zeitueberschreitung" in p for p in _payloads(parent))

    async def test_exception_clears_pending(self):
        parent = _make_parent()
        parent._remote_commands._recipe.confirm_pending_recipe.side_effect = (
            RuntimeError("boom")
        )

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_recipe_save(msg, _recipe_action())

        assert any("Rezept-Speichern fehlgeschlagen" in p for p in _payloads(parent))
        parent._pending.clear.assert_called_once_with(msg.sender)
