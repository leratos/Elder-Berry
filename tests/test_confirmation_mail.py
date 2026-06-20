"""Flow-Tests für ConfirmationMailMixin._execute_mail_send (Backlog #834).

Deckt den bestätigten Mail-Reply-Versand ab: Erfolg inkl. best-effort
IMAP-Sent-Kopie, SMTP nicht konfiguriert, Sende-Fehlschlag,
``asyncio.TimeoutError`` und den generischen Exception-Pfad.

Muster: ``ConfirmationHandler(parent)`` mit einem MagicMock-parent, der das
``ConfirmationParent``-Protocol erfüllt. ``_channel.send_text`` ist ein
AsyncMock; die blockierenden Calls laufen über die reale Event-Loop
(asyncio_mode=auto) in ``loop.run_in_executor``. Für den Timeout-Pfad wird
``confirmation_mail.asyncio.wait_for`` gepatcht.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from elder_berry.comms.confirmation_handlers import ConfirmationHandler
from elder_berry.comms.pending_confirmation import PendingAction

_WAIT_FOR = "elder_berry.comms.handlers.confirmation_mail.asyncio.wait_for"


def _make_parent() -> MagicMock:
    """Baut einen MagicMock-parent gemäß ConfirmationParent-Protocol."""
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


def _mail_action() -> PendingAction:
    return PendingAction(
        action_type="mail_reply",
        description="Draft für #4523",
        data={
            "to": "info@firma.de",
            "subject": "Re: Anfrage",
            "draft_text": "Hallo, danke für Ihre Nachricht.",
            "msg_id": "4523",
            "in_reply_to": "<abc@firma.de>",
            "references": "<abc@firma.de>",
        },
    )


def _send_text_payloads(parent: MagicMock) -> list[str]:
    """Alle an _channel.send_text übergebenen Texte (2. Positional-Arg)."""
    return [c.args[1] for c in parent._channel.send_text.call_args_list]


class TestExecuteMailSend:
    async def test_success_sends_and_copies_to_sent(self):
        parent = _make_parent()
        result = MagicMock()
        result.success = True
        result.to = "info@firma.de"
        result.error = None
        result.raw_msg = b"raw-bytes"
        parent._email_sender.send_reply.return_value = result

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        action = _mail_action()

        await handler._execute_mail_send(msg, action)

        parent._email_sender.send_reply.assert_called_once()
        kwargs = parent._email_sender.send_reply.call_args.kwargs
        assert kwargs["to"] == "info@firma.de"
        assert kwargs["subject"] == "Re: Anfrage"

        parent._pending.clear.assert_called_once_with(msg.sender)
        payloads = _send_text_payloads(parent)
        assert any("gesendet" in p and "4523" in p for p in payloads)
        # Chat-History: user + assistant
        assert parent._chat_history.add.call_count == 2
        # Best-effort Kopie in den Gesendet-Ordner
        parent._email_client.copy_to_sent_folder.assert_called_once_with(b"raw-bytes")

    async def test_success_copy_failure_is_best_effort(self):
        parent = _make_parent()
        result = MagicMock()
        result.success = True
        result.to = "info@firma.de"
        result.error = None
        result.raw_msg = b"raw-bytes"
        parent._email_sender.send_reply.return_value = result
        parent._email_client.copy_to_sent_folder.side_effect = RuntimeError("imap down")

        handler = ConfirmationHandler(parent)
        msg = _make_msg()

        await handler._execute_mail_send(msg, _mail_action())

        # Trotz fehlgeschlagener Kopie: Erfolgsmeldung + pending geleert.
        parent._pending.clear.assert_called_once_with(msg.sender)
        assert any("gesendet" in p for p in _send_text_payloads(parent))

    async def test_success_without_email_client_skips_copy(self):
        parent = _make_parent()
        parent._email_client = None
        result = MagicMock()
        result.success = True
        result.to = "info@firma.de"
        result.error = None
        result.raw_msg = b"raw-bytes"
        parent._email_sender.send_reply.return_value = result

        handler = ConfirmationHandler(parent)
        await handler._execute_mail_send(_make_msg(), _mail_action())

        assert any("gesendet" in p for p in _send_text_payloads(parent))

    async def test_smtp_not_configured(self):
        parent = _make_parent()
        parent._email_sender = None

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_mail_send(msg, _mail_action())

        payloads = _send_text_payloads(parent)
        assert payloads == ["SMTP nicht konfiguriert."]
        parent._pending.clear.assert_called_once_with(msg.sender)

    async def test_send_failure_keeps_pending(self):
        parent = _make_parent()
        result = MagicMock()
        result.success = False
        result.error = "SMTP 550 rejected"
        parent._email_sender.send_reply.return_value = result

        handler = ConfirmationHandler(parent)
        await handler._execute_mail_send(_make_msg(), _mail_action())

        payloads = _send_text_payloads(parent)
        assert any("fehlgeschlagen" in p and "550" in p for p in payloads)
        # Fehlschlag (kein Crash): pending bleibt für Retry erhalten.
        parent._pending.clear.assert_not_called()

    async def test_timeout(self):
        parent = _make_parent()

        handler = ConfirmationHandler(parent)
        with patch(_WAIT_FOR, side_effect=asyncio.TimeoutError):
            await handler._execute_mail_send(_make_msg(), _mail_action())

        payloads = _send_text_payloads(parent)
        assert any("Zeitüberschreitung" in p for p in payloads)
        # Timeout-Pfad räumt pending NICHT (Retry mit 'ja' möglich).
        parent._pending.clear.assert_not_called()

    async def test_generic_exception_clears_pending(self):
        parent = _make_parent()
        parent._email_sender.send_reply.side_effect = RuntimeError("boom")

        handler = ConfirmationHandler(parent)
        msg = _make_msg()
        await handler._execute_mail_send(msg, _mail_action())

        payloads = _send_text_payloads(parent)
        assert any("Fehler beim Senden" in p and "RuntimeError" in p for p in payloads)
        parent._pending.clear.assert_called_once_with(msg.sender)
