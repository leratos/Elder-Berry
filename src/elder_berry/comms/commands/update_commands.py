"""UpdateCommandHandler – Self-Update, Rollback und Backup via Matrix.

Verwaltet:
- update → git pull + pip install + restart (Server oder Tower)
- update rpi → RPi5: git pull + pip + systemctl restart
- update alles → Server/Tower + RPi5 nacheinander
- rollback → Auf Stand vor letztem Update zurücksetzen
"""
from __future__ import annotations

import json
import logging
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.comms.commands.cmd_utils import CmdResult, run_cmd

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.robot.client import RobotClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

UPDATE_PATTERN = re.compile(
    r"^(?:update|aktualisier(?:e|en)?|updat(?:e|en)?)\s*(?:dich|saleria|mich)?$",
    re.IGNORECASE,
)

ROLLBACK_PATTERN = re.compile(
    r"^(?:rollback|update\s*zurück(?:setzen)?|zurückrollen)$",
    re.IGNORECASE,
)

UPDATE_RPI_PATTERN = re.compile(
    r"^(?:update\s+rpi|rpi\s+update|aktualisier(?:e)?\s+rpi)$",
    re.IGNORECASE,
)

UPDATE_ALL_PATTERN = re.compile(
    r"^(?:update\s+alles|alles\s+update[n]?)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Backup-Konstanten
# ---------------------------------------------------------------------------

DEFAULT_BACKUP_DIR = Path.home() / ".elder-berry"
BACKUP_FILENAME = "update_backup.json"

_GIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{4,40}$", re.IGNORECASE)


def _is_valid_git_hash(value: str) -> bool:
    """Prüft ob ein String ein valider git-Hash (short oder full) ist."""
    return bool(_GIT_HASH_PATTERN.match(value))


def _pip_install_groups() -> str:
    """Gibt den pip install Extra-String passend zur Plattform zurück.

    Windows (Tower): .[windows,tts-neural,avatar,matrix,remote,memory,stt]
    Linux (Server):  .[server]
    """
    if platform.system() == "Windows":
        return ".[windows,tts-neural,avatar,matrix,remote,memory,stt]"
    return ".[server]"


class UpdateCommandHandler(CommandHandler):
    """Handler für Self-Update, Rollback und Backup."""

    def __init__(
        self,
        project_root: Path | None = None,
        robot_client: RobotClient | None = None,
    ) -> None:
        self._project_root = project_root
        self._robot = robot_client

    @property
    def simple_commands(self) -> set[str]:
        return {"update", "rollback", "update rpi", "update alles"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (UPDATE_PATTERN, "update", False, False),
            (UPDATE_RPI_PATTERN, "update_rpi", False, False),
            (UPDATE_ALL_PATTERN, "update_all", False, False),
            (ROLLBACK_PATTERN, "rollback", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "update: Git Pull + Dependencies + Neustart (Tower)",
            "update rpi: RPi5 aktualisieren (git pull + pip + restart)",
            "update alles: Tower + RPi5 nacheinander aktualisieren",
            "rollback: Auf Stand vor letztem Update zurücksetzen",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "update": [
                "update dich", "aktualisiere dich", "neue funktionen",
                "schau dir deine neuen funktionen an", "mach ein update",
                "git pull und neustart", "update saleria",
            ],
            "update_rpi": [
                "update rpi", "rpi aktualisieren", "rpi updaten",
                "raspberry update", "aktualisiere den rpi",
            ],
            "update_all": [
                "update alles", "alles updaten", "alles aktualisieren",
                "update überall",
            ],
            "rollback": [
                "update zurücksetzen", "zurückrollen", "mach update rückgängig",
                "alten stand wiederherstellen",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "update":
            return self._cmd_update()
        if command in ("update_rpi", "update rpi"):
            return self._cmd_update_rpi()
        if command in ("update_all", "update alles"):
            return self._cmd_update_all()
        if command == "rollback":
            return self._cmd_rollback()
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Update-Command: {command}",
        )

    # ------------------------------------------------------------------
    # Update Tower
    # ------------------------------------------------------------------

    def _cmd_update(self) -> CommandResult:
        """Self-Update: git pull + pip install (wenn nötig) + restart."""
        if not self._project_root:
            return CommandResult(
                command="update",
                success=False,
                text="Projekt-Root nicht konfiguriert.",
            )

        cwd = str(self._project_root)
        steps: list[str] = []

        # --- Schritt 1: git fetch ---
        fetch = run_cmd(["git", "fetch", "origin"], cwd=cwd, timeout=30)
        if not fetch.success:
            return CommandResult(
                command="update",
                success=False,
                text=f"❌ Git Fetch fehlgeschlagen:\n{fetch.output}",
            )

        # --- Schritt 2: Prüfe ob Änderungen vorliegen ---
        behind = run_cmd(
            ["git", "rev-list", "--count", "HEAD..@{u}"],
            cwd=cwd, timeout=10,
        )
        commits_behind = 0
        if behind.success and behind.output.strip().isdigit():
            commits_behind = int(behind.output.strip())

        if commits_behind == 0:
            return CommandResult(
                command="update",
                success=True,
                text="✅ Alles aktuell – kein neuer Code.\n"
                     "Soll ich trotzdem neustarten? (ja/nein, 5 Min Timeout)",
                pending_confirmation=True,
                pending_data={"action": "restart"},
            )

        steps.append(f"📥 {commits_behind} neue(r) Commit(s) verfügbar")

        # --- Schritt 3: Prüfe auf lokale Änderungen (uncommitted) ---
        status = run_cmd(
            ["git", "status", "-uno", "--porcelain"],
            cwd=cwd, timeout=10,
        )
        if status.success and status.output.strip():
            return CommandResult(
                command="update",
                success=False,
                text=(
                    "⚠️ Lokale Änderungen vorhanden – Update abgebrochen.\n"
                    "Bitte erst committen oder stashen:\n"
                    f"```\n{status.output.strip()}\n```"
                ),
            )

        # --- Schritt 4: Backup + git pull ---
        old_hash = run_cmd(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, timeout=5,
        )
        old_hash_full = run_cmd(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, timeout=5,
        )
        branch = run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, timeout=5,
        )

        if old_hash_full.success:
            self._write_backup(
                commit_hash=old_hash_full.output.strip(),
                branch=branch.output.strip() if branch.success else "unknown",
            )
            steps.append("💾 Backup gesichert (rollback möglich)")

        pull = run_cmd(["git", "pull", "--ff-only"], cwd=cwd, timeout=60)
        if not pull.success:
            return CommandResult(
                command="update",
                success=False,
                text=f"❌ Git Pull fehlgeschlagen:\n{pull.output}",
            )
        steps.append("✅ Code aktualisiert")

        new_hash = run_cmd(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, timeout=5,
        )
        if old_hash.success and new_hash.success:
            old_h = old_hash.output.strip()
            new_h = new_hash.output.strip()
            if _is_valid_git_hash(old_h) and _is_valid_git_hash(new_h):
                log = run_cmd(
                    ["git", "log", "--oneline", f"{old_h}..{new_h}"],
                    cwd=cwd, timeout=10,
                )
                if log.success and log.output.strip():
                    steps.append(f"📋 Änderungen:\n{log.output.strip()}")

        # --- Schritt 5: Dependency-Check ---
        diff_files = CmdResult(success=False, output="")
        if old_hash.success and new_hash.success:
            old_h = old_hash.output.strip()
            new_h = new_hash.output.strip()
            if _is_valid_git_hash(old_h) and _is_valid_git_hash(new_h):
                diff_files = run_cmd(
                    ["git", "diff", "--name-only", f"{old_h}..{new_h}"],
                    cwd=cwd, timeout=10,
                )
        dep_files_changed = False
        if diff_files.success:
            changed = diff_files.output.strip().lower()
            dep_files_changed = (
                "pyproject.toml" in changed
                or "requirements" in changed
                or "setup.cfg" in changed
            )

        if dep_files_changed:
            steps.append("📦 Dependencies geändert – installiere...")
            pip = run_cmd(
                [sys.executable, "-m", "pip", "install", "-e",
                 _pip_install_groups(), "--quiet"],
                cwd=cwd, timeout=300,
            )
            if pip.success:
                steps.append("✅ Dependencies installiert")
            else:
                steps.append(f"⚠️ pip install Warnung:\n{pip.output[:500]}")
        else:
            steps.append("📦 Keine neuen Dependencies")

        steps.append("🔄 Starte neu...")

        return CommandResult(
            command="update",
            success=True,
            text="\n".join(steps),
            restart=True,
        )

    # ------------------------------------------------------------------
    # Update RPi5
    # ------------------------------------------------------------------

    def _cmd_update_rpi(self) -> CommandResult:
        """RPi5 aktualisieren: git pull + pip install + systemctl restart."""
        if not self._robot:
            return CommandResult(
                command="update_rpi",
                success=False,
                text="RobotClient nicht verfügbar (RPi5 nicht verbunden).",
            )
        try:
            resp = self._robot.update_rpi()
            return CommandResult(
                command="update_rpi",
                success=resp.success,
                text=f"RPi5 Update: {resp.message}",
            )
        except Exception as e:
            logger.error("RPi5 Update fehlgeschlagen: %s", e)
            return CommandResult(
                command="update_rpi",
                success=False,
                text=f"RPi5 Update fehlgeschlagen: {e}",
            )

    def _cmd_update_all(self) -> CommandResult:
        """Tower + RPi5 nacheinander aktualisieren."""
        steps: list[str] = []

        if self._robot:
            rpi_result = self._cmd_update_rpi()
            steps.append(f"RPi5: {rpi_result.text}")
        else:
            steps.append("RPi5: nicht verbunden, uebersprungen")

        tower_result = self._cmd_update()
        steps.append(f"Tower: {tower_result.text}")

        return CommandResult(
            command="update_all",
            success=tower_result.success,
            text="\n\n".join(steps),
            restart=tower_result.restart,
            pending_confirmation=tower_result.pending_confirmation,
            pending_data=tower_result.pending_data,
        )

    # ------------------------------------------------------------------
    # Backup / Rollback
    # ------------------------------------------------------------------

    def _get_backup_path(self) -> Path:
        """Pfad zur Backup-Datei."""
        return DEFAULT_BACKUP_DIR / BACKUP_FILENAME

    def _write_backup(self, commit_hash: str, branch: str) -> None:
        """Schreibt Backup-Daten vor einem Update."""
        backup_path = self._get_backup_path()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "hash": commit_hash,
            "branch": branch,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        backup_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Update-Backup geschrieben: %s → %s", commit_hash[:8], backup_path)

    def _read_backup(self) -> dict | None:
        """Liest Backup-Daten. None wenn nicht vorhanden."""
        backup_path = self._get_backup_path()
        if not backup_path.exists():
            return None
        try:
            data = json.loads(backup_path.read_text(encoding="utf-8"))
            if "hash" in data:
                return data
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Backup-Datei defekt: %s", e)
            return None

    def _cmd_rollback(self) -> CommandResult:
        """Rollback: Setzt auf den Stand vor dem letzten Update zurück."""
        if not self._project_root:
            return CommandResult(
                command="rollback",
                success=False,
                text="Projekt-Root nicht konfiguriert.",
            )

        backup = self._read_backup()
        if not backup:
            return CommandResult(
                command="rollback",
                success=False,
                text="Kein Update zum Zurücksetzen. "
                     "Backup-Datei nicht vorhanden.",
            )

        cwd = str(self._project_root)
        target_hash = backup["hash"]
        branch = backup.get("branch", "?")
        timestamp = backup.get("timestamp", "?")
        steps: list[str] = []

        steps.append(
            f"🔙 Rollback auf {target_hash[:8]} "
            f"(Branch: {branch}, Backup: {timestamp})"
        )

        # Prüfe ob Hash existiert
        verify = run_cmd(
            ["git", "cat-file", "-t", target_hash],
            cwd=cwd, timeout=5,
        )
        if not verify.success:
            return CommandResult(
                command="rollback",
                success=False,
                text=f"❌ Commit {target_hash[:8]} existiert nicht mehr im Repo. "
                     "Manuelles Eingreifen nötig.",
            )

        # git reset --hard
        reset = run_cmd(
            ["git", "reset", "--hard", target_hash],
            cwd=cwd, timeout=30,
        )
        if not reset.success:
            return CommandResult(
                command="rollback",
                success=False,
                text=f"❌ Git Reset fehlgeschlagen:\n{reset.output}",
            )
        steps.append("✅ Code zurückgesetzt")

        # Dependencies neu installieren
        steps.append("📦 Installiere Dependencies...")
        pip = run_cmd(
            [sys.executable, "-m", "pip", "install", "-e",
             _pip_install_groups(), "--quiet"],
            cwd=cwd, timeout=300,
        )
        if pip.success:
            steps.append("✅ Dependencies installiert")
        else:
            steps.append(f"⚠️ pip install Warnung:\n{pip.output[:500]}")

        # Backup-Datei löschen (einmaliger Rollback)
        try:
            self._get_backup_path().unlink(missing_ok=True)
        except OSError:
            pass

        steps.append("🔄 Starte neu...")

        return CommandResult(
            command="rollback",
            success=True,
            text="\n".join(steps),
            restart=True,
        )
