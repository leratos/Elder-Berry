"""ProposalNotifier -- Matrix-Notification fuer Plugin-Vorschlaege (Phase 78).

Wird vom `ProposalIntentAggregator` gerufen, sobald ein Proposal die
Threshold-Schwelle erreicht (3x in 7 Tagen, siehe Konzept §3.5/§3.7).

Pattern:
- Reine Notification-Komponente, keine Threshold-Logik.
- DI: `MessageChannel` + Ziel-Room-ID + Dashboard-Base-URL.
- Aktuell ein Raum (Hauptraum als Default). Erweiterbar fuer Themen-
  Routing (separate Raeume fuer updates, selfcheck, proposals etc).
"""

from __future__ import annotations

import logging

from elder_berry.comms.message_channel import MessageChannel
from elder_berry.tools.proposal_store import Proposal

logger = logging.getLogger(__name__)


class ProposalNotifier:
    """Matrix-Direktnachricht beim Erreichen des Vorschlags-Thresholds.

    Threshold-Pruefung erfolgt im Aggregator -- der Notifier liefert nur
    die Nachricht aus.
    """

    def __init__(
        self,
        channel: MessageChannel,
        room_id: str,
        dashboard_base_url: str = "https://fern.last-strawberry.com",
    ) -> None:
        """
        Args:
            channel: Aktiver MessageChannel (typischerweise MatrixChannel).
            room_id: Ziel-Raum fuer die Notification. Sollte der DM-/Proposal-
                Raum sein; Fallback in der Composition-Wurzel ist der
                Hauptraum.
            dashboard_base_url: URL-Praefix fuer den Detail-Link im
                Dashboard (Konzept §3.7). Ohne abschliessenden Slash.
        """
        self._channel = channel
        self._room_id = room_id
        self._dashboard_base_url = dashboard_base_url.rstrip("/")

    async def notify(self, proposal: Proposal, recent_count: int, days: int) -> bool:
        """Sendet die Threshold-Notification fuer den Proposal.

        Args:
            proposal: Der Vorschlag, der die Schwelle gerissen hat.
            recent_count: Anzahl Trigger im aktuellen Fenster (typ. 3).
            days: Fensterlaenge in Tagen (typ. 7).

        Returns:
            True wenn die Nachricht erfolgreich an den Channel
            uebergeben wurde. False bei Send-Fehler -- der Aggregator
            soll dann ``mark_notified`` NICHT setzen, damit beim
            naechsten Trigger ein Retry stattfindet.

        Format laut Konzept §3.7. Fehler beim Versand werden geloggt,
        aber nicht weitergeworfen -- eine fehlgeschlagene Notification
        soll den Aggregator-Flow nicht abbrechen.
        """
        body = self._format(proposal, recent_count, days)
        try:
            await self._channel.send_text(self._room_id, body)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ProposalNotifier: Versand fehlgeschlagen fuer %s: %s",
                proposal.id,
                exc,
            )
            return False

    def _format(self, proposal: Proposal, recent_count: int, days: int) -> str:
        url = f"{self._dashboard_base_url}/proposals/{proposal.id}"
        return (
            f"💡 Plugin-Vorschlag: {proposal.title} "
            f"({recent_count}x in {days} Tagen)\n\n"
            f"Du hast wiederholt nach Funktionen in diesem Bereich gefragt. "
            f"Ich denke, das waere ein Plugin-Kandidat.\n\n"
            f"Details: {url}"
        )
