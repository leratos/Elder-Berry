"""Basis für die ConfirmationHandler-Mixins (Phase 106).

Die action-spezifischen Mixins (Mail, Filing, Restart, Nextcloud/Bulk,
Attachment) haben keinen eigenen ``__init__``. Diese Basis deklariert den
Parent-Ref ``_p`` und stellt den einen handler-übergreifend genutzten Lookup
``_get_filing_handler`` bereit (Filing-Mixin, Attachment-Mixin und der
Dispatcher im Shell-Modul brauchen ihn).

Der Parent ist zur Laufzeit ein ``BridgeMessageHandler``; getypt wird er aber
über das strukturelle ``ConfirmationParent``-Protocol (das genutzte Subset),
NICHT über einen Import der konkreten Klasse – sonst entsteht ein CodeQL
``py/unsafe-cyclic-import`` (gleiches Muster wie ``secrets_api._DashboardLike``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from elder_berry.comms.chat_history import ChatHistory
    from elder_berry.comms.commands.base import CommandResult
    from elder_berry.comms.commands.filing_commands import FilingCommandHandler
    from elder_berry.comms.message_channel import IncomingMessage, MessageChannel
    from elder_berry.comms.pending_confirmation import PendingConfirmationStore
    from elder_berry.comms.remote_commands import RemoteCommandHandler
    from elder_berry.comms.scheduler_manager import SchedulerManager
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.email_sender import EmailSender
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient


class ConfirmationParent(Protocol):
    """Strukturelles Subset des ``BridgeMessageHandler``, das die Confirmation-
    Mixins über ``self._p`` nutzen (Attribute + ``_handle_llm_enrichment``).

    Vermeidet den Import der konkreten Klasse und damit einen CodeQL
    ``py/unsafe-cyclic-import`` (analog ``secrets_api._DashboardLike``).
    """

    _channel: MessageChannel
    _pending: PendingConfirmationStore
    _chat_history: ChatHistory
    _remote_commands: RemoteCommandHandler | None
    _nc_files: NextcloudFilesClient | None
    _email_sender: EmailSender | None
    _email_client: IMAPEmailClient | None
    _scheduler_mgr: SchedulerManager | None
    restart_cooldown_until: float

    async def _handle_llm_enrichment(
        self,
        msg: IncomingMessage,
        result: CommandResult,
        prompt_intro: str,
        prompt_instruction: str,
        error_log_msg: str,
        error_fallback_suffix: str,
    ) -> None:
        pass


class ConfirmationMixinBase:
    """Gemeinsame Basis: Parent-Ref + handler-übergreifende Lookups."""

    _p: ConfirmationParent

    def _get_filing_handler(self) -> FilingCommandHandler | None:
        """Holt den FilingCommandHandler über den RemoteCommandHandler."""
        rc = self._p._remote_commands
        if rc and hasattr(rc, "_filing"):
            handler: FilingCommandHandler | None = rc._filing
            return handler
        return None
