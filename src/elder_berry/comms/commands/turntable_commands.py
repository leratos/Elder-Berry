"""TurntableCommandHandler -- Drehteller-Befehle."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

DEFAULT_ROTATION_DEGREES = 90.0

# "dreh dich um 90 grad (nach links/rechts)"
ROTATE_BY_PATTERN = re.compile(
    r"^dreh\s+dich\s+(?:um\s+)?(\d+)\s*(?:grad|°)"
    r"(?:\s+(?:nach\s+)?(links|rechts))?$",
    re.IGNORECASE,
)

# "dreh dich auf 45 grad" / "dreh auf position 90"
ROTATE_TO_PATTERN = re.compile(
    r"^dreh\s+(?:dich\s+)?auf\s+(?:position\s+)?(-?\d+)\s*(?:grad|°)?$",
    re.IGNORECASE,
)

# "dreh dich nach links/rechts"
ROTATE_DIRECTION_PATTERN = re.compile(
    r"^dreh\s+dich\s+nach\s+(links|rechts)$",
    re.IGNORECASE,
)

# "schau nach links/rechts"
LOOK_DIRECTION_PATTERN = re.compile(
    r"^schau\s+nach\s+(links|rechts)$",
    re.IGNORECASE,
)


class TurntableCommandHandler(CommandHandler):
    """Handler fuer Drehteller-Befehle."""

    def __init__(self, robot_client: RobotClient | None = None) -> None:
        self._robot = robot_client

    @property
    def simple_commands(self) -> set[str]:
        return {"drehteller home", "drehteller stopp", "drehteller status"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (ROTATE_BY_PATTERN, "turntable_rotate_by", False, False),
            (ROTATE_TO_PATTERN, "turntable_rotate_to", False, False),
            (ROTATE_DIRECTION_PATTERN, "turntable_rotate_dir", False, False),
            (LOOK_DIRECTION_PATTERN, "turntable_look_dir", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "turntable_rotate_dir": [
                "dreh dich",
                "schau nach links", "schau nach rechts",
                "guck nach links", "guck nach rechts",
                "dreh nach links", "dreh nach rechts",
            ],
            "drehteller home": [
                "home position", "heimposition",
                "drehteller home", "drehteller zurück",
            ],
            "drehteller stopp": [
                "drehteller stopp", "drehteller stop",
                "hör auf zu drehen",
            ],
            "drehteller status": [
                "drehteller status", "drehteller position",
                "wo schaust du hin", "in welche richtung",
            ],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "drehteller home: Drehteller auf Home-Position fahren",
            "dreh dich um <grad> [nach links/rechts]: Drehteller relativ drehen",
            "dreh dich nach links/rechts: 90 Grad in Richtung drehen",
            "dreh dich auf <grad>: Drehteller auf Position fahren",
            "drehteller stopp: Rotation sofort abbrechen",
            "drehteller status: Aktuelle Position anzeigen",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if not self._robot:
            return CommandResult(
                command=command, success=False,
                text="RobotClient nicht verfügbar (RPi5 nicht verbunden).",
            )
        if command == "drehteller home":
            return self._cmd_home()
        if command == "drehteller stopp":
            return self._cmd_stop()
        if command == "drehteller status":
            return self._cmd_status()
        if command in (
            "turntable_rotate_by", "turntable_rotate_to",
            "turntable_rotate_dir", "turntable_look_dir",
        ):
            return self._cmd_rotate(command, raw_text)
        return CommandResult(
            command=command, success=False,
            text=f"Unbekannter Command: {command}",
        )

    def _cmd_home(self) -> CommandResult:
        try:
            resp = self._robot.home_turntable()
            return CommandResult(
                command="drehteller home",
                success=resp.success, text=resp.message,
            )
        except Exception as e:
            return CommandResult(
                command="drehteller home", success=False,
                text=f"Homing fehlgeschlagen: {e}",
            )

    def _cmd_stop(self) -> CommandResult:
        try:
            resp = self._robot.stop_turntable()
            return CommandResult(
                command="drehteller stopp",
                success=resp.success, text=resp.message,
            )
        except Exception as e:
            return CommandResult(
                command="drehteller stopp", success=False,
                text=f"Stopp fehlgeschlagen: {e}",
            )

    def _cmd_status(self) -> CommandResult:
        try:
            status = self._robot.turntable_status()
            if not status.get("available"):
                return CommandResult(
                    command="drehteller status",
                    success=False, text="Drehteller nicht verfügbar.",
                )
            homed = status.get("is_homed", False)
            moving = status.get("is_moving", False)
            pos = status.get("position_degrees", 0)
            parts = []
            if not homed:
                parts.append("Nicht gehomed")
            else:
                parts.append(f"Position: {pos:.1f} Grad")
            if moving:
                parts.append("Dreht sich gerade")
            return CommandResult(
                command="drehteller status",
                success=True, text=" | ".join(parts),
            )
        except Exception as e:
            return CommandResult(
                command="drehteller status", success=False,
                text=f"Status-Abfrage fehlgeschlagen: {e}",
            )

    def _cmd_rotate(self, command: str, raw_text: str) -> CommandResult:
        normalized = raw_text.strip().lower()

        # "dreh dich nach links/rechts" oder "schau nach links/rechts"
        if command in ("turntable_rotate_dir", "turntable_look_dir"):
            match = (ROTATE_DIRECTION_PATTERN.match(normalized)
                     or LOOK_DIRECTION_PATTERN.match(normalized))
            if not match:
                return CommandResult(
                    command=command, success=False,
                    text="Richtung nicht erkannt.",
                )
            direction = match.group(1)
            degrees = DEFAULT_ROTATION_DEGREES
            if direction == "links":
                degrees = -degrees
            return self._execute_rotate_by(degrees)

        # "dreh dich um 90 grad (nach links/rechts)"
        if command == "turntable_rotate_by":
            match = ROTATE_BY_PATTERN.match(normalized)
            if not match:
                return CommandResult(
                    command=command, success=False,
                    text="Grad-Angabe nicht erkannt.",
                )
            degrees = float(match.group(1))
            direction = match.group(2)  # "links" / "rechts" / None
            if direction == "links":
                degrees = -degrees
            return self._execute_rotate_by(degrees)

        # "dreh dich auf 45 grad"
        if command == "turntable_rotate_to":
            match = ROTATE_TO_PATTERN.match(normalized)
            if not match:
                return CommandResult(
                    command=command, success=False,
                    text="Position nicht erkannt.",
                )
            degrees = float(match.group(1))
            return self._execute_rotate_to(degrees)

        return CommandResult(
            command=command, success=False,
            text=f"Rotation-Command nicht erkannt: {command}",
        )

    def _execute_rotate_by(self, degrees: float) -> CommandResult:
        try:
            resp = self._robot.rotate_turntable(relative_degrees=degrees)
            return CommandResult(
                command="turntable_rotate",
                success=resp.success, text=resp.message,
            )
        except Exception as e:
            return CommandResult(
                command="turntable_rotate", success=False,
                text=f"Rotation fehlgeschlagen: {e}",
            )

    def _execute_rotate_to(self, degrees: float) -> CommandResult:
        try:
            resp = self._robot.rotate_turntable(target_degrees=degrees)
            return CommandResult(
                command="turntable_rotate",
                success=resp.success, text=resp.message,
            )
        except Exception as e:
            return CommandResult(
                command="turntable_rotate", success=False,
                text=f"Rotation fehlgeschlagen: {e}",
            )
