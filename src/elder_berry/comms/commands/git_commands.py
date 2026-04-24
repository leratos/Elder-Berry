"""GitCommandHandler – Git-Befehle via Matrix (Whitelist).

Verwaltet:
- git status → Aktueller Status
- git pull → Remote-Änderungen holen
- git log → Letzte Commits (mit engem Argument-Whitelist, Phase 65 M-2)
- git diff → Änderungen anzeigen (mit engem Argument-Whitelist, Phase 65 M-2)

Phase 65 (M-2): Zusatzargumente fuer ``log``/``diff`` werden nicht mehr
blind durch ``.split()`` an subprocess weitergegeben, sondern jedes
Token muss einem Whitelist-Pattern entsprechen. Subprocess laeuft mit
``shell=False``, daher ist klassisches Command-Injection ausgeschlossen;
die Whitelist verhindert aber, dass ein Matrix-User git-Flags mit Datei-
Schreibeffekt (``--output-*``, ``-o``) oder unerwartetem Verhalten
(``--exec``, ``-c core.pager=...``) nutzen kann.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from elder_berry.comms.commands.base import CommandHandler, CommandResult, user_friendly_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns & Whitelists
# ---------------------------------------------------------------------------

GIT_PATTERN = re.compile(
    r"^git\s+(status|pull|log|diff)(?:\s+(.*))?$",
    re.IGNORECASE,
)

GIT_WHITELIST = {"status", "pull", "log", "diff"}

# Phase 65 (M-2): Maximal so viele Extra-Argumente. Schuetzt gegen
# pathologische Input-Laengen.
MAX_EXTRA_ARGS = 10

# Shared patterns -- Commit-Hashes, HEAD-Notation, Plain-Integers.
_COMMIT_HASH_RE = re.compile(r"^[a-fA-F0-9]{4,40}$")
_HEAD_REF_RE = re.compile(r"^HEAD(~\d{1,4})?(\.\.HEAD(~\d{1,4})?)?$")

# log-spezifisch.
_GIT_LOG_ARG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^--oneline$"),
    re.compile(r"^--stat$"),
    re.compile(r"^--shortstat$"),
    re.compile(r"^--name-only$"),
    re.compile(r"^--name-status$"),
    re.compile(r"^--all$"),
    re.compile(r"^--decorate$"),
    re.compile(r"^--graph$"),
    re.compile(r"^-n$"),                                  # folgender Token = int
    re.compile(r"^-\d{1,4}$"),                            # Kurzform: -5
    re.compile(r"^--max-count=\d{1,4}$"),
    re.compile(r"^--since=[\w\- :.,T+Z]{1,40}$"),
    re.compile(r"^--until=[\w\- :.,T+Z]{1,40}$"),
    re.compile(r"^--before=[\w\- :.,T+Z]{1,40}$"),
    re.compile(r"^--after=[\w\- :.,T+Z]{1,40}$"),
    re.compile(r"^--author=[\w@.\- ]{1,64}$"),
    re.compile(r"^--grep=[\w\s\-.,:/()]{1,100}$"),
    re.compile(r"^\d{1,4}$"),                             # Wert nach -n
    _COMMIT_HASH_RE,
    _HEAD_REF_RE,
)

# diff-spezifisch (engere Whitelist -- keine Greps, keine Autoren).
_GIT_DIFF_ARG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^--stat$"),
    re.compile(r"^--shortstat$"),
    re.compile(r"^--name-only$"),
    re.compile(r"^--name-status$"),
    re.compile(r"^--cached$"),
    re.compile(r"^--staged$"),
    _COMMIT_HASH_RE,
    _HEAD_REF_RE,
)


def _validate_extra_args(
    subcmd: str, args: list[str],
) -> tuple[bool, str | None]:
    """Prueft jedes Token aus ``args`` gegen die Whitelist zum Subcommand.

    Returns:
        (True, None) wenn alle Tokens erlaubt sind.
        (False, bad_token) wenn irgendein Token nicht passt. ``bad_token``
        ist entweder das unzulaessige Argument oder ein Meta-Fehler-String
        (z.B. "zu viele Argumente").
    """
    if len(args) > MAX_EXTRA_ARGS:
        return False, f"zu viele Argumente (max {MAX_EXTRA_ARGS})"

    if subcmd == "log":
        patterns = _GIT_LOG_ARG_PATTERNS
    elif subcmd == "diff":
        patterns = _GIT_DIFF_ARG_PATTERNS
    else:
        # Kein Extra-Arg fuer andere Subcommands erlaubt.
        return (len(args) == 0), (args[0] if args else None)

    for arg in args:
        if not any(p.match(arg) for p in patterns):
            return False, arg
    return True, None


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

        # Phase 65 (M-2): Whitelist-Validierung statt blindem split().
        if extra_args and subcmd in ("log", "diff"):
            tokens = extra_args.split()
            ok, bad = _validate_extra_args(subcmd, tokens)
            if not ok:
                logger.warning(
                    "Git-Argument abgelehnt (subcmd=%s, bad=%r)", subcmd, bad,
                )
                return CommandResult(
                    command="git",
                    success=False,
                    text=(
                        f"Argument '{bad}' nicht erlaubt fuer git {subcmd}. "
                        f"Erlaubte Beispiele: --oneline, -n 5, --since=yesterday, "
                        f"--author=marcus, <commit-hash>, HEAD~3."
                    ),
                )
            cmd.extend(tokens)

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
                text=user_friendly_error(e, "Git"),
            )
