"""ConfirmationHandler-Mixin: bestätigte Neustarts (Server / Tower / Sammelfall).

Phase 106 (Modul-Entflechtung): aus ``confirmation_handlers.py`` ausgelagert.
Reiner Methoden-Umzug; Dependencies über ``self._p``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from elder_berry.comms.handlers._confirmation_base import ConfirmationMixinBase

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import IncomingMessage
    from elder_berry.comms.pending_confirmation import PendingAction
    from elder_berry.core.tower_agent import TowerAgent

logger = logging.getLogger(__name__)


class ConfirmationRestartMixin(ConfirmationMixinBase):
    """Führt bestätigte Restart-/Update-Aktionen aus."""

    async def _execute_restart_confirm(
        self,
        msg: IncomingMessage,
        action: PendingAction,
    ) -> None:
        """Führt einen bestätigten Neustart aus.

        Unterstützte ``action.action_type``-Werte:
          - ``update`` / ``update_all`` / ``restart`` -> Server-Self-Restart
            (Bestand, ``perform_restart``).
          - ``restart_tower`` -> HTTP POST ``/system/update?force=true``
            an den Tower (Tower respawnt sich selbst, siehe
            tower/tower_server.py).
          - ``restart_all`` -> Liste aus ``action.data["actions"]``
            nacheinander dispatchen (Reihenfolge: rpi -> tower -> server).
        """
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

        # Sammelfall: Liste von Sub-Restarts in fester Reihenfolge.
        if action.action_type == "restart_all":
            sub_actions = action.data.get("actions", []) or []
            for sub in sub_actions:
                if isinstance(sub, str):
                    await self._dispatch_restart(msg, sub)
            return

        # Einzel-Tower-Restart.
        if action.action_type == "restart_tower":
            await self._dispatch_restart(msg, "restart_tower")
            return

        # Bestand: Server-Self-Restart.
        await self._dispatch_restart(msg, "restart")

    async def _dispatch_restart(
        self,
        msg: IncomingMessage,
        sub_action: str,
    ) -> None:
        """Dispatcht einen einzelnen Sub-Restart an die richtige Komponente."""
        if sub_action == "restart_tower":
            await self._restart_tower_via_http(msg)
            return

        if sub_action == "restart_rpi":
            # RPi nutzt systemd -- ein gewollter Restart ist ueber den
            # bestehenden 'update rpi'-Pfad bereits abgedeckt. Fuer den
            # Sammelfall (RPi ist aktuell, soll aber neu gestartet werden)
            # gibt es heute keine HTTP-Aktion -- explizit melden.
            await self._p._channel.send_text(
                msg.room_id,
                "ℹ RPi-Neustart manuell anstossen (z.B. via 'update rpi').",
            )
            return

        # sub_action == "restart" oder unbekannt -> Server-Self-Restart.
        await self._p._channel.send_text(msg.room_id, "🔄 Starte neu …")
        from elder_berry.comms.restart_manager import perform_restart

        await perform_restart(
            self._p._channel,
            self._p._scheduler_mgr,
            msg.room_id,
            msg_server_ts=msg.timestamp,
        )

    def _get_tower_agent(self) -> TowerAgent | None:
        """Holt den TowerAgent ueber den UpdateCommandHandler in remote_commands.

        Pfad: BridgeMessageHandler._remote_commands -> _update -> _tower.
        """
        rc = getattr(self._p, "_remote_commands", None)
        if rc is None or not hasattr(rc, "_update"):
            return None
        tower = getattr(rc._update, "_tower", None)
        if tower is None:
            return None
        return tower  # type: ignore[no-any-return]

    async def _restart_tower_via_http(self, msg: IncomingMessage) -> None:
        """POST /system/update?force=true an den Tower (fire-and-forget).

        Tower beendet sich nach ~3 s und respawnt sich selbst -- eine
        Response kommt evtl. nicht mehr zurueck. Timeout ist kurz, damit
        der Server nicht haengt; alle httpx-Exceptions werden geschluckt
        und nur geloggt, weil 'kein Response' der Erfolgsfall ist.
        """
        tower = self._get_tower_agent()
        if tower is None:
            await self._p._channel.send_text(
                msg.room_id,
                "❌ Tower nicht verbunden -- Restart nicht moeglich.",
            )
            return

        await self._p._channel.send_text(
            msg.room_id,
            "🔄 Tower-Neustart wird angestoßen ...",
        )
        try:
            import httpx

            headers: dict[str, str] = {}
            if hasattr(tower, "_auth_headers"):
                headers = tower._auth_headers()
            url = f"http://{tower.host}/system/update?force=true"
            try:
                r = httpx.post(url, timeout=5.0, headers=headers)
                r.raise_for_status()
            except httpx.RemoteProtocolError:
                # Tower hat sich beendet, bevor Response durch war -- erwartet.
                logger.info("Tower-Restart: kein Response (erwartet, Tower respawnt).")
            except httpx.ReadTimeout:
                logger.info("Tower-Restart: Timeout (erwartet, Tower respawnt).")
            await self._p._channel.send_text(
                msg.room_id,
                "✅ Tower-Restart eingeleitet. Etwa 5-10 Sek bis bereit.",
            )
        except Exception as e:
            logger.error("Tower-Restart fehlgeschlagen: %s", e)
            await self._p._channel.send_text(
                msg.room_id,
                f"❌ Tower-Restart fehlgeschlagen: {type(e).__name__}",
            )
