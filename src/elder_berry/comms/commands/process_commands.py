"""ProcessCommandHandler – Prozess-, Git-, Docker- und WOL-Commands.

Verwaltet:
- starte <programm> → Prozess starten (Whitelist)
- kill <prozess> → Prozess beenden (Whitelist)
- wol → Wake-on-LAN Magic Packet
- git status/pull/log/diff → Git-Befehle (Whitelist)
- docker ps/restart/logs → Docker-Befehle (Whitelist)
"""
from __future__ import annotations

import logging
import re
import socket
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Regex für Prozess starten: "starte chrome", "start notepad"
START_PROCESS_PATTERN = re.compile(
    r"^(?:starte?|start|öffne|open)\s+(\S+)$",
    re.IGNORECASE,
)

# Regex für Prozess beenden: "kill blender", "beende firefox"
KILL_PROCESS_PATTERN = re.compile(
    r"^(?:kill|beende|stoppe?|schließe?)\s+(\S+)$",
    re.IGNORECASE,
)

# Regex für Git-Befehle: "git status", "git pull", "git log"
GIT_PATTERN = re.compile(
    r"^git\s+(status|pull|log|diff)(?:\s+(.*))?$",
    re.IGNORECASE,
)

# Regex für Docker-Befehle: "docker ps", "docker restart synapse"
DOCKER_PATTERN = re.compile(
    r"^docker\s+(ps|restart|logs)(?:\s+(\S+))?$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Whitelists
# ---------------------------------------------------------------------------

GIT_WHITELIST = {"status", "pull", "log", "diff"}
DOCKER_WHITELIST = {"ps", "restart", "logs"}

# Prozesse die gekillt werden dürfen (lowercase)
KILL_WHITELIST = {
    "blender", "chrome", "firefox", "edge", "notepad", "notepad++",
    "vlc", "spotify", "discord", "steam", "obs", "obs64",
    "gimp", "audacity", "handbrake", "qbittorrent",
}

# Prozesse die gestartet werden dürfen (lowercase → Executable)
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
    """Handler für Prozess-, Git-, Docker- und WOL-Commands."""

    def __init__(
        self,
        secret_store: SecretStore | None = None,
        project_root: Path | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._project_root = project_root

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"wol"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (START_PROCESS_PATTERN, "start_process", False, False),
            (KILL_PROCESS_PATTERN, "kill_process", False, False),
            (GIT_PATTERN, "git", False, False),
            (DOCKER_PATTERN, "docker", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "wol": ["weck tower", "tower aufwecken", "wake on lan", "tower starten"],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Command aus."""
        if command == "start_process":
            return self._cmd_start_process(raw_text)
        if command == "kill_process":
            return self._cmd_kill_process(raw_text)
        if command == "wol":
            return self._cmd_wol()
        if command == "git":
            return self._cmd_git(raw_text)
        if command == "docker":
            return self._cmd_docker(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Process-Command: {command}",
        )

    # ------------------------------------------------------------------
    # Command-Implementierungen
    # ------------------------------------------------------------------

    def _cmd_start_process(self, raw_text: str) -> CommandResult:
        """Prozess starten (nur aus Whitelist)."""
        match = START_PROCESS_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="start_process",
                success=False,
                text="Ungültiges Format. Beispiel: starte chrome",
            )

        program = match.group(1).lower()

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

        process_name = match.group(1).lower()

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
                text=f"Wake-on-LAN fehlgeschlagen: {e}",
            )

    def _cmd_git(self, raw_text: str) -> CommandResult:
        """Git-Befehl ausführen (nur aus Whitelist, kein push/commit)."""
        match = GIT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="git",
                success=False,
                text="Ungültiges Format. Erlaubt: git status, git pull, git log, git diff",
            )

        subcmd = match.group(1).lower()
        extra_args = match.group(2).strip() if match.group(2) else ""

        if subcmd not in GIT_WHITELIST:
            return CommandResult(
                command="git",
                success=False,
                text=f"Git-Befehl '{subcmd}' nicht erlaubt. "
                     f"Erlaubt: {', '.join(sorted(GIT_WHITELIST))}",
            )

        cmd = ["git", subcmd]
        if subcmd == "log":
            # Limitiere Log-Output
            cmd.extend(["--oneline", "-20"])
        if extra_args and subcmd in ("log", "diff"):
            cmd.extend(extra_args.split())

        cwd = self._project_root or Path.cwd()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(cwd),
            )

            output = result.stdout or result.stderr or "(keine Ausgabe)"
            if len(output) > 4000:
                output = output[:4000] + "\n... (gekürzt)"

            return CommandResult(
                command="git",
                success=result.returncode == 0,
                text=f"$ {' '.join(cmd)}\n{output}",
            )
        except FileNotFoundError:
            return CommandResult(
                command="git",
                success=False,
                text="git nicht gefunden. Ist Git installiert?",
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                command="git",
                success=False,
                text="Git-Befehl Timeout (30s).",
            )
        except Exception as e:
            logger.error("Git-Befehl fehlgeschlagen: %s", e)
            return CommandResult(
                command="git",
                success=False,
                text=f"Git-Befehl fehlgeschlagen: {e}",
            )

    def _cmd_docker(self, raw_text: str) -> CommandResult:
        """Docker-Befehl ausführen (nur aus Whitelist)."""
        match = DOCKER_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="docker",
                success=False,
                text="Ungültiges Format. Erlaubt: docker ps, docker restart <name>, "
                     "docker logs <name>",
            )

        subcmd = match.group(1).lower()
        container = match.group(2) or ""

        if subcmd not in DOCKER_WHITELIST:
            return CommandResult(
                command="docker",
                success=False,
                text=f"Docker-Befehl '{subcmd}' nicht erlaubt. "
                     f"Erlaubt: {', '.join(sorted(DOCKER_WHITELIST))}",
            )

        # restart und logs brauchen Container-Name
        if subcmd in ("restart", "logs") and not container:
            return CommandResult(
                command="docker",
                success=False,
                text=f"Container-Name fehlt. Beispiel: docker {subcmd} synapse",
            )

        cmd = ["docker", subcmd]
        if container:
            cmd.append(container)
        if subcmd == "logs":
            cmd.extend(["--tail", "50"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = result.stdout or result.stderr or "(keine Ausgabe)"
            if len(output) > 4000:
                output = output[:4000] + "\n... (gekürzt)"

            return CommandResult(
                command="docker",
                success=result.returncode == 0,
                text=f"$ {' '.join(cmd)}\n{output}",
            )
        except FileNotFoundError:
            return CommandResult(
                command="docker",
                success=False,
                text="docker nicht gefunden. Ist Docker installiert?",
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                command="docker",
                success=False,
                text="Docker-Befehl Timeout (30s).",
            )
        except Exception as e:
            logger.error("Docker-Befehl fehlgeschlagen: %s", e)
            return CommandResult(
                command="docker",
                success=False,
                text=f"Docker-Befehl fehlgeschlagen: {e}",
            )
