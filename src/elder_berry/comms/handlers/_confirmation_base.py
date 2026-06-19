"""Basis für die ConfirmationHandler-Mixins (Phase 106).

Die action-spezifischen Mixins (Mail, Filing, Restart, Nextcloud/Bulk,
Attachment) haben keinen eigenen ``__init__``. Diese Basis deklariert den
Parent-Ref ``_p`` (``BridgeMessageHandler``) für den Type-Checker und stellt
den einen handler-übergreifend genutzten Lookup ``_get_filing_handler`` bereit
(Filing-Mixin, Attachment-Mixin und der Dispatcher im Shell-Modul brauchen ihn).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.comms.commands.filing_commands import FilingCommandHandler
    from elder_berry.comms.message_handlers import BridgeMessageHandler


class ConfirmationMixinBase:
    """Gemeinsame Basis: Parent-Ref + handler-übergreifende Lookups."""

    _p: BridgeMessageHandler

    def _get_filing_handler(self) -> FilingCommandHandler | None:
        """Holt den FilingCommandHandler über den RemoteCommandHandler."""
        rc = self._p._remote_commands
        if rc and hasattr(rc, "_filing"):
            handler: FilingCommandHandler | None = rc._filing
            return handler
        return None
