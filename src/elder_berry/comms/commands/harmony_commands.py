"""HarmonyCommandHandler -- Sprachbefehle fuer Harmony Hub.

Patterns:
  "fernsehen an" / "tv an" / "musik an"   → start_activity()
  "alles aus" / "harmony aus"              → power_off()
  "mach lauter" / "lauter"                 → send_command(Receiver, VolumeUp)
  "mach leiser" / "leiser"                 → send_command(Receiver, VolumeDown)
  "stummschalten" / "stumm"                → send_command(Receiver, Mute)
  "was laeuft" / "was ist an"              → get_current_activity()
  "harmony aktivitaeten"                   → list_activities()
  "harmony geraete"                        → list_devices()
  "harmony befehle <geraet>"               → list_commands(device)
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

# Geraet fuer Lautstaerke-Befehle (Samsung TV steuert Denon via ARC/CEC)
_VOLUME_DEVICE = "Samsung TV"

# -- Patterns -------------------------------------------------------------- #

ACTIVITY_ON_PATTERN = re.compile(
    r"^(?:starte?\s+)?(?P<activity>fernsehen|tv|musik|radio|gaming|"
    r"film|kino)\s+an$",
    re.IGNORECASE,
)
ALL_OFF_PATTERN = re.compile(
    r"^(?:alles?\s+aus|harmony\s+aus|schalte?\s+alles?\s+aus)$",
    re.IGNORECASE,
)
VOLUME_UP_PATTERN = re.compile(r"^(?:mach\s+)?lauter$", re.IGNORECASE)
VOLUME_DOWN_PATTERN = re.compile(r"^(?:mach\s+)?leiser$", re.IGNORECASE)
MUTE_PATTERN = re.compile(r"^(?:stummschalten|stumm)$", re.IGNORECASE)
CURRENT_PATTERN = re.compile(
    r"^(?:was\s+(?:l[äa]uft|ist\s+an)|harmony\s+status)$",
    re.IGNORECASE,
)
LIST_ACTIVITIES_PATTERN = re.compile(
    r"^harmony\s+aktivit[äa]ten$", re.IGNORECASE,
)
LIST_DEVICES_PATTERN = re.compile(
    r"^harmony\s+ger[äa]te$", re.IGNORECASE,
)
LIST_COMMANDS_PATTERN = re.compile(
    r"^harmony\s+befehle\s+(?P<device>.+)$", re.IGNORECASE,
)
SCENE_START_PATTERN = re.compile(
    r"^(?:starte?\s+)?szene\s+(?P<scene>.+)$", re.IGNORECASE,
)
SCENE_LIST_PATTERN = re.compile(
    r"^szenen(?:\s+liste)?$", re.IGNORECASE,
)


class HarmonyCommandHandler(CommandHandler):
    """Handler fuer Harmony-Hub-Befehle via Matrix."""

    def __init__(self, robot_client: RobotClient | None = None) -> None:
        self._robot = robot_client

    @property
    def simple_commands(self) -> set[str]:
        return set()

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (ACTIVITY_ON_PATTERN, "harmony_activity_on", False, False),
            (ALL_OFF_PATTERN, "harmony_all_off", False, False),
            (VOLUME_UP_PATTERN, "harmony_volume_up", False, False),
            (VOLUME_DOWN_PATTERN, "harmony_volume_down", False, False),
            (MUTE_PATTERN, "harmony_mute", False, False),
            (CURRENT_PATTERN, "harmony_current", False, False),
            (LIST_ACTIVITIES_PATTERN, "harmony_list_activities", False, False),
            (LIST_DEVICES_PATTERN, "harmony_list_devices", False, False),
            (LIST_COMMANDS_PATTERN, "harmony_list_commands", False, False),
            (SCENE_START_PATTERN, "harmony_scene_start", False, False),
            (SCENE_LIST_PATTERN, "harmony_scene_list", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "harmony_activity_on": [
                "fernsehen an", "tv an", "musik an",
                "radio an", "gaming an", "film an", "kino an",
            ],
            "harmony_all_off": [
                "alles aus", "harmony aus", "schalte alles aus",
            ],
            "harmony_volume_up": ["lauter", "mach lauter"],
            "harmony_volume_down": ["leiser", "mach leiser"],
            "harmony_mute": ["stummschalten", "stumm"],
            "harmony_current": [
                "was läuft", "was ist an", "harmony status",
            ],
            "harmony_list_activities": ["harmony aktivitäten"],
            "harmony_list_devices": ["harmony geräte"],
            "harmony_list_commands": ["harmony befehle"],
            "harmony_scene_start": [
                "starte szene", "szene starten",
            ],
            "harmony_scene_list": ["szenen", "szenen liste"],
        }

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "<aktivität> an: Harmony-Aktivität starten (z.B. fernsehen an, musik an)",
            "alles aus / harmony aus: Alle Geräte ausschalten",
            "lauter / mach lauter: Lautstärke erhöhen (Receiver)",
            "leiser / mach leiser: Lautstärke senken (Receiver)",
            "stummschalten / stumm: Receiver stummschalten",
            "was läuft / harmony status: Aktuelle Aktivität anzeigen",
            "harmony aktivitäten: Alle Aktivitäten auflisten",
            "harmony geräte: Alle Geräte auflisten",
            "harmony befehle <gerät>: Verfügbare Befehle für ein Gerät",
            "starte szene <name> / szene <name>: Harmony-Szene starten",
            "szenen / szenen liste: Alle Szenen auflisten",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if not self._robot:
            return CommandResult(
                command=command, success=False,
                text="RobotClient nicht verfügbar (RPi5 nicht verbunden).",
            )

        if command == "harmony_activity_on":
            return self._cmd_activity_on(raw_text)
        if command == "harmony_all_off":
            return self._cmd_all_off()
        if command == "harmony_volume_up":
            return self._cmd_volume("VolumeUp", "Lauter")
        if command == "harmony_volume_down":
            return self._cmd_volume("VolumeDown", "Leiser")
        if command == "harmony_mute":
            return self._cmd_volume("Mute", "Stumm")
        if command == "harmony_current":
            return self._cmd_current()
        if command == "harmony_list_activities":
            return self._cmd_list_activities()
        if command == "harmony_list_devices":
            return self._cmd_list_devices()
        if command == "harmony_list_commands":
            return self._cmd_list_commands(raw_text)
        if command == "harmony_scene_start":
            return self._cmd_scene_start(raw_text)
        if command == "harmony_scene_list":
            return self._cmd_scene_list()

        return CommandResult(
            command=command, success=False,
            text=f"Unbekannter Harmony-Command: {command}",
        )

    # -- Commands ---------------------------------------------------------- #

    def _cmd_activity_on(self, raw_text: str) -> CommandResult:
        normalized = raw_text.strip().lower()
        match = ACTIVITY_ON_PATTERN.match(normalized)
        if not match:
            return CommandResult(
                command="harmony_activity_on", success=False,
                text="Aktivität nicht erkannt.",
            )

        activity = match.group("activity")
        # Mapping Kurzformen → Harmony-Aktivitaetsnamen
        activity_map = {
            "fernsehen": "Fernsehen",
            "tv": "Fernsehen",
            "musik": "Musik",
            "radio": "Musik",
            "gaming": "Gaming",
            "film": "Fernsehen",
            "kino": "Fernsehen",
        }
        activity_name = activity_map.get(activity, activity.title())

        try:
            success = self._robot.harmony_start_activity(activity_name)
            if success:
                return CommandResult(
                    command="harmony_activity_on", success=True,
                    text=f"Aktivität '{activity_name}' gestartet.",
                )
            return CommandResult(
                command="harmony_activity_on", success=False,
                text=f"Aktivität '{activity_name}' nicht gefunden oder Fehler.",
            )
        except Exception as e:
            return CommandResult(
                command="harmony_activity_on", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_all_off(self) -> CommandResult:
        try:
            success = self._robot.harmony_power_off()
            if success:
                return CommandResult(
                    command="harmony_all_off", success=True,
                    text="Alle Geräte ausgeschaltet.",
                )
            return CommandResult(
                command="harmony_all_off", success=False,
                text="Power-Off fehlgeschlagen.",
            )
        except Exception as e:
            return CommandResult(
                command="harmony_all_off", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_volume(self, command: str, label: str) -> CommandResult:
        try:
            success = self._robot.harmony_send_command(
                _VOLUME_DEVICE, command,
            )
            if success:
                return CommandResult(
                    command=f"harmony_{command.lower()}", success=True,
                    text=f"{label}.",
                )
            return CommandResult(
                command=f"harmony_{command.lower()}", success=False,
                text=f"{label} fehlgeschlagen.",
            )
        except Exception as e:
            return CommandResult(
                command=f"harmony_{command.lower()}", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_current(self) -> CommandResult:
        try:
            status = self._robot.harmony_status()
            activity = status.get("current_activity")
            connected = status.get("connected", False)
            if not connected:
                return CommandResult(
                    command="harmony_current", success=False,
                    text="Harmony Hub nicht verbunden.",
                )
            if activity:
                return CommandResult(
                    command="harmony_current", success=True,
                    text=f"Aktuelle Aktivität: {activity}",
                )
            return CommandResult(
                command="harmony_current", success=True,
                text="Keine Aktivität aktiv (alles aus).",
            )
        except Exception as e:
            return CommandResult(
                command="harmony_current", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_list_activities(self) -> CommandResult:
        try:
            config = self._robot.harmony_config()
            activities = config.get("activities", [])
            if not activities:
                return CommandResult(
                    command="harmony_list_activities", success=True,
                    text="Keine Aktivitäten konfiguriert.",
                )
            text = "Harmony-Aktivitäten:\n" + "\n".join(
                f"  • {a}" for a in activities
            )
            return CommandResult(
                command="harmony_list_activities", success=True,
                text=text,
            )
        except Exception as e:
            return CommandResult(
                command="harmony_list_activities", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_list_devices(self) -> CommandResult:
        try:
            config = self._robot.harmony_config()
            devices = config.get("devices", [])
            if not devices:
                return CommandResult(
                    command="harmony_list_devices", success=True,
                    text="Keine Geräte konfiguriert.",
                )
            text = "Harmony-Geräte:\n" + "\n".join(
                f"  • {d}" for d in devices
            )
            return CommandResult(
                command="harmony_list_devices", success=True,
                text=text,
            )
        except Exception as e:
            return CommandResult(
                command="harmony_list_devices", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_list_commands(self, raw_text: str) -> CommandResult:
        normalized = raw_text.strip().lower()
        match = LIST_COMMANDS_PATTERN.match(normalized)
        if not match:
            return CommandResult(
                command="harmony_list_commands", success=False,
                text="Gerätename nicht erkannt. Syntax: harmony befehle <gerät>",
            )

        device_name = match.group("device").strip()

        # Wir nutzen harmony_config um Geräte zu prüfen, aber
        # list_commands braucht den Server-Endpoint (noch nicht vorhanden).
        # Vorerst Hinweis geben.
        config = self._robot.harmony_config()
        devices = config.get("devices", [])
        device_lower = device_name.lower()

        found = None
        for d in devices:
            if d.lower() == device_lower:
                found = d
                break

        if not found:
            return CommandResult(
                command="harmony_list_commands", success=False,
                text=f"Gerät '{device_name}' nicht gefunden.",
            )

        return CommandResult(
            command="harmony_list_commands", success=True,
            text=f"Befehle für '{found}' – nutze die PWA oder die API direkt "
                 f"(GET /harmony/config für Details).",
        )

    def _cmd_scene_start(self, raw_text: str) -> CommandResult:
        # Originaltext fuer Szenennamen (case-sensitiv), Pattern auf lowercase
        match = SCENE_START_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="harmony_scene_start", success=False,
                text="Szenenname nicht erkannt. Syntax: starte szene <name>",
            )

        scene_name = match.group("scene").strip()

        try:
            result = self._robot.harmony_start_scene(scene_name)
            if result.get("success"):
                ok = result.get("steps_ok", 0)
                total = result.get("steps_total", 0)
                return CommandResult(
                    command="harmony_scene_start", success=True,
                    text=f"Szene '{scene_name}' gestartet ({ok}/{total} OK).",
                )
            error = result.get("error", "Unbekannter Fehler")
            return CommandResult(
                command="harmony_scene_start", success=False,
                text=f"Szene '{scene_name}': {error}",
            )
        except Exception as e:
            return CommandResult(
                command="harmony_scene_start", success=False,
                text=f"Fehler: {e}",
            )

    def _cmd_scene_list(self) -> CommandResult:
        try:
            scenes = self._robot.harmony_scenes()
            if not scenes:
                return CommandResult(
                    command="harmony_scene_list", success=True,
                    text="Keine Szenen konfiguriert.",
                )
            names = [s.get("name", "?") for s in scenes]
            text = "Harmony-Szenen:\n" + "\n".join(
                f"  • {n}" for n in names
            )
            return CommandResult(
                command="harmony_scene_list", success=True,
                text=text,
            )
        except Exception as e:
            return CommandResult(
                command="harmony_scene_list", success=False,
                text=f"Fehler: {e}",
            )
