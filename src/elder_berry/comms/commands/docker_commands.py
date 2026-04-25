"""DockerCommandHandler – Docker-Befehle via Matrix (Whitelist).

Verwaltet:
- docker ps → Laufende Container
- docker restart <name> → Container neustarten
- docker logs <name> → Container-Logs
"""
from __future__ import annotations

import logging
import re
import subprocess

from elder_berry.comms.commands.base import CommandHandler, CommandResult, user_friendly_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns & Whitelists
# ---------------------------------------------------------------------------

DOCKER_PATTERN = re.compile(
    r"^docker\s+(ps|restart|logs)(?:\s+(\S+))?$",
    re.IGNORECASE,
)

DOCKER_WHITELIST = {"ps", "restart", "logs"}

# Erlaubt nur sichere Container-Namen: alphanumerisch, Bindestrich, Unterstrich, Punkt.
# Verhindert Flag-Injection wie --all, --no-trunc, --follow, --since=... usw.
_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]{0,127}$")


class DockerCommandHandler(CommandHandler):
    """Handler für Docker-Befehle (nur Whitelist)."""

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (DOCKER_PATTERN, "docker", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "docker ps / docker restart / docker logs: Docker-Befehle",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "docker":
            return self._cmd_docker(raw_text)
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Docker-Command: {command}",
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

        if subcmd in ("restart", "logs") and not container:
            return CommandResult(
                command="docker",
                success=False,
                text=f"Container-Name fehlt. Beispiel: docker {subcmd} synapse",
            )

        if subcmd in ("restart", "logs") and not _CONTAINER_NAME_RE.match(container):
            return CommandResult(
                command="docker",
                success=False,
                text=f"Ungültiger Container-Name '{container}'. "
                     "Erlaubt: Buchstaben, Ziffern, Bindestrich, Unterstrich, Punkt.",
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
                text=user_friendly_error(e, "Docker"),
            )
