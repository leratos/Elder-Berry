"""WolCommandHandler – Wake-on-LAN via Matrix.

Verwaltet:
- wol → Magic Packet an Tower senden
"""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandResult,
    user_friendly_error,
)

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)


class WolCommandHandler(CommandHandler):
    """Handler für Wake-on-LAN Magic Packet."""

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self._secret_store = secret_store

    @property
    def simple_commands(self) -> set[str]:
        return {"wol"}

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "wol: Wake-on-LAN (Tower aufwecken)",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "wol": [
                "weck tower",
                "tower aufwecken",
                "wake on lan",
                "tower starten",
                "pc aufwecken",
                "rechner wecken",
                "tower wecken",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "wol":
            return self._cmd_wol()
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter WoL-Command: {command}",
        )

    def _cmd_wol(self) -> CommandResult:
        """Wake-on-LAN Magic Packet senden."""
        if not self._secret_store:
            return CommandResult(
                command="wol",
                success=False,
                text="SecretStore nicht verfügbar. MAC-Adresse kann nicht geladen werden.",
            )

        try:
            mac_str = self._secret_store.get("tower_mac_address")
        except Exception:
            return CommandResult(
                command="wol",
                success=False,
                text="MAC-Adresse 'tower_mac_address' nicht im SecretStore hinterlegt.\n"
                "Speichern mit: SecretStore().set('tower_mac_address', 'AA:BB:CC:DD:EE:FF')",
            )

        # MAC-Adresse validieren und normalisieren
        mac_clean = mac_str.replace(":", "").replace("-", "").replace(".", "")
        if len(mac_clean) != 12:
            return CommandResult(
                command="wol",
                success=False,
                text=f"Ungültige MAC-Adresse: {mac_str}",
            )

        try:
            int(mac_clean, 16)
        except ValueError:
            return CommandResult(
                command="wol",
                success=False,
                text=f"Ungültige MAC-Adresse (nicht hexadezimal): {mac_str}",
            )

        # Magic Packet: 6× 0xFF + 16× MAC-Adresse
        mac_bytes = bytes.fromhex(mac_clean)
        magic_packet = b"\xff" * 6 + mac_bytes * 16

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic_packet, ("<broadcast>", 9))
            sock.close()

            return CommandResult(
                command="wol",
                success=True,
                text=f"Wake-on-LAN Paket gesendet an {mac_str}.",
            )
        except Exception as e:
            logger.error("Wake-on-LAN fehlgeschlagen: %s", e)
            return CommandResult(
                command="wol",
                success=False,
                text=user_friendly_error(e, "Wake-on-LAN"),
            )
