"""Shared utilities für shell-command-basierte Handler.

Stellt run_cmd() und CmdResult bereit, die von mehreren Command-Handlern
genutzt werden (Git, Docker, Update, SelfCheck).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class CmdResult:
    """Ergebnis-DTO für Shell-Befehle."""

    success: bool
    output: str


def run_cmd(
    cmd: list[str],
    cwd: str,
    timeout: int = 30,
) -> CmdResult:
    """Führt einen Shell-Befehl aus und gibt Ergebnis zurück.

    Args:
        cmd: Befehl als Liste (kein Shell-Interpolation).
        cwd: Arbeitsverzeichnis.
        timeout: Timeout in Sekunden.

    Returns:
        CmdResult mit success und output.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = result.stdout or result.stderr or ""
        return CmdResult(success=result.returncode == 0, output=output)
    except subprocess.TimeoutExpired:
        return CmdResult(success=False, output=f"Timeout ({timeout}s)")
    except FileNotFoundError:
        return CmdResult(
            success=False,
            output=f"Befehl nicht gefunden: {cmd[0]}",
        )
    except Exception as e:
        return CmdResult(success=False, output=str(e))
