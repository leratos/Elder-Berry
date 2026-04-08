"""ProcessCommandHandler – Prozess-Start/Kill via Matrix (Whitelist).

Verwaltet:
- starte <programm> → Prozess starten (Whitelist)
- kill <prozess> → Prozess beenden (Whitelist)

Weitere Commands wurden in eigene Handler ausgelagert:
- git_commands.py: Git-Befehle
- docker_commands.py: Docker-Befehle
- wol_commands.py: Wake-on-LAN
- update_commands.py: Self-Update, Rollback, Backup
- selfcheck_commands.py: Systemgesundheitsprüfung
"""
from __future__ import annotations

import logging
import re
import subprocess

from elder_berry.comms.commands.base import CommandHandler, CommandResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Negative Lookahead schließt Harmony-Aktivitäten und System-Keywords aus,
# damit "starte tv" → Harmony und "starte dich neu" → Restart gehen.
_HARMONY_ACTIVITIES = r"(?:fernsehen|tv|musik|radio|gaming|film|kino)"

START_PROCESS_PATTERN = re.compile(
    r"^(?:starte?|start|öffne|open)\s+"
    r"(?!" + _HARMONY_ACTIVITIES + r"(?:\s+(?:an|ein))?$"
    r"|(?:dich\s+)?neu$"       # → restart (SystemCommandHandler)
    r"|szene\s+"               # → harmony scene
    r")"
    r"(.+)$",
    re.IGNORECASE,
)

KILL_PROCESS_PATTERN = re.compile(
    r"^(?:kill|beende|stoppe?|schließe?)\s+(.+)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Whitelists
# ---------------------------------------------------------------------------

KILL_WHITELIST = {
    "blender", "chrome", "firefox", "edge", "notepad", "notepad++",
    "vlc", "spotify", "discord", "steam", "obs", "obs64",
    "gimp", "audacity", "handbrake", "qbittorrent",
}

START_WHITELIST = {
    "chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "notepad": "notepad",
    "notepad++": "notepad++",
    "explorer": "explorer",
    "calc": "calc",
    "vlc": "vlc",
    "spotify": "spotify",
    "discord": "discord",
    "blender": "blender",
    "obs": "obs64",
}


class ProcessCommandHandler(CommandHandler):
    """Handler für Prozess-Start/Kill (Whitelist-geschützt)."""

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (START_PROCESS_PATTERN, "start_process", False, False),
            (KILL_PROCESS_PATTERN, "kill_process", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "starte <programm>: Programm starten (Whitelist)",
            "kill <prozess>: Prozess beenden (Whitelist)",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "start_process":
            return self._cmd_start_process(raw_text)
        if command == "kill_process":
            return self._cmd_kill_process(raw_text)
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Process-Command: {command}",
        )

    def _cmd_start_process(self, raw_text: str) -> CommandResult:
        """Prozess starten (nur aus Whitelist)."""
        match = START_PROCESS_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="start_process",
                success=False,
                text="Ungültiges Format. Beispiel: starte chrome",
            )

        program = match.group(1).strip().lower()

        if program not in START_WHITELIST:
            allowed = ", ".join(sorted(START_WHITELIST.keys()))
            return CommandResult(
                command="start_process",
                success=False,
                text=f"'{program}' ist nicht in der Start-Whitelist.\n"
                     f"Erlaubt: {allowed}",
            )

        executable = START_WHITELIST[program]

        try:
            subprocess.Popen(
                [executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
            return CommandResult(
                command="start_process",
                success=True,
                text=f"Gestartet: {program}",
            )
        except FileNotFoundError:
            return CommandResult(
                command="start_process",
                success=False,
                text=f"'{executable}' nicht gefunden. Ist es installiert?",
            )
        except Exception as e:
            logger.error("Prozess starten fehlgeschlagen '%s': %s", program, e)
            return CommandResult(
                command="start_process",
                success=False,
                text=f"Starten fehlgeschlagen: {e}",
            )

    def _cmd_kill_process(self, raw_text: str) -> CommandResult:
        """Prozess beenden (nur aus Whitelist)."""
        match = KILL_PROCESS_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="kill_process",
                success=False,
                text="Ungültiges Format. Beispiel: kill blender",
            )

        process_name = match.group(1).strip().lower()

        if process_name not in KILL_WHITELIST:
            allowed = ", ".join(sorted(KILL_WHITELIST))
            return CommandResult(
                command="kill_process",
                success=False,
                text=f"'{process_name}' ist nicht in der Kill-Whitelist.\n"
                     f"Erlaubt: {allowed}",
            )

        try:
            import psutil
        except ImportError:
            return CommandResult(
                command="kill_process",
                success=False,
                text="psutil nicht installiert.",
            )

        killed = 0
        try:
            for proc in psutil.process_iter(["name"]):
                try:
                    pname = proc.info["name"]
                    if pname and pname.lower().startswith(process_name):
                        proc.terminate()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if killed == 0:
                return CommandResult(
                    command="kill_process",
                    success=False,
                    text=f"Kein laufender Prozess '{process_name}' gefunden.",
                )

            return CommandResult(
                command="kill_process",
                success=True,
                text=f"Beendet: {process_name} ({killed} Prozess{'e' if killed > 1 else ''})",
            )
        except Exception as e:
            logger.error("Prozess beenden fehlgeschlagen '%s': %s", process_name, e)
            return CommandResult(
                command="kill_process",
                success=False,
                text=f"Beenden fehlgeschlagen: {e}",
            )
