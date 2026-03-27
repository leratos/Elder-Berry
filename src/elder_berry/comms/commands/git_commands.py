"""GitCommandHandler – Git-Befehle via Matrix (Whitelist).

Verwaltet:
- git status → Aktueller Status
- git pull → Remote-Änderungen holen
- git log → Letzte Commits
- git diff → Änderungen anzeigen
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from elder_berry.comms.commands.base import CommandHandler, CommandResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns & Whitelists
# ---------------------------------------------------------------------------

GIT_PATTERN = re.compile(
    r"^git\s+(status|pull|log|diff)(?:\s+(.*))?$",
    re.IGNORECASE,
)

GIT_WHITELIST = {"status", "pull", "log", "diff"}


class GitCommandHandler(CommandHandler):
    """Handler für Git-Befehle (nur Whitelist, kein push/commit)."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (GIT_PATTERN, "git", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "git status / git pull / git log / git diff: Git-Befehle",
        ]

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "git":
            return self._cmd_git(raw_text)
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Git-Command: {command}",
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
