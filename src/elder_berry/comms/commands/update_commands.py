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
from typing import TYPE_CHECKING, Any, cast

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)
from elder_berry.comms.commands.cmd_utils import CmdResult, run_cmd

if TYPE_CHECKING:
    from elder_berry.core.tower_agent import TowerAgent
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

UPDATE_TOWER_PATTERN = re.compile(
    r"^(?:update\s+tower|tower\s+update|aktualisier(?:e)?\s+tower)$",
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
        tower_agent: TowerAgent | None = None,
    ) -> None:
        self._project_root = project_root
        self._robot = robot_client
        self._tower = tower_agent

    @property
    def simple_commands(self) -> set[str]:
        return {"update", "rollback", "update rpi", "update tower", "update alles"}

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        return [
            (UPDATE_PATTERN, "update", False, False),
            (UPDATE_RPI_PATTERN, "update_rpi", False, False),
            (UPDATE_TOWER_PATTERN, "update_tower", False, False),
            (UPDATE_ALL_PATTERN, "update_all", False, False),
            (ROLLBACK_PATTERN, "rollback", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "update: Git Pull + Dependencies + Neustart (Server)",
            "update tower: Tower-PC aktualisieren (git pull + pip + restart)",
            "update rpi: RPi5 aktualisieren (git pull + pip + restart)",
            "update alles: Server + Tower + RPi5 nacheinander aktualisieren",
            "rollback: Auf Stand vor letztem Update zurücksetzen",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "update": [
                "update dich",
                "aktualisiere dich",
                "neue funktionen",
                "schau dir deine neuen funktionen an",
                "mach ein update",
                "git pull und neustart",
                "update saleria",
            ],
            "update_rpi": [
                "update rpi",
                "rpi aktualisieren",
                "rpi updaten",
                "raspberry update",
                "aktualisiere den rpi",
            ],
            "update_tower": [
                "update tower",
                "tower aktualisieren",
                "tower updaten",
                "aktualisiere den tower",
                "pc updaten",
            ],
            "update_all": [
                "update alles",
                "alles updaten",
                "alles aktualisieren",
                "update überall",
            ],
            "rollback": [
                "update zurücksetzen",
                "zurückrollen",
                "mach update rückgängig",
                "alten stand wiederherstellen",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "update":
            return self._cmd_update()
        if command in ("update_rpi", "update rpi"):
            return self._cmd_update_rpi()
        if command in ("update_tower", "update tower"):
            return self._cmd_update_tower()
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
                text="⚠ Projekt-Root nicht konfiguriert.",
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
            cwd=cwd,
            timeout=10,
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
            cwd=cwd,
            timeout=10,
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
            cwd=cwd,
            timeout=5,
        )
        old_hash_full = run_cmd(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            timeout=5,
        )
        branch = run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            timeout=5,
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
            cwd=cwd,
            timeout=5,
        )
        if old_hash.success and new_hash.success:
            old_h = old_hash.output.strip()
            new_h = new_hash.output.strip()
            if _is_valid_git_hash(old_h) and _is_valid_git_hash(new_h):
                log = run_cmd(
                    ["git", "log", "--oneline", f"{old_h}..{new_h}"],
                    cwd=cwd,
                    timeout=10,
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
                    cwd=cwd,
                    timeout=10,
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
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    _pip_install_groups(),
                    "--quiet",
                ],
                cwd=cwd,
                timeout=300,
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
                text=user_friendly_error(e, "RPi5 Update"),
            )

    # ------------------------------------------------------------------
    # Update Tower (remote via TowerAgent HTTP)
    # ------------------------------------------------------------------

    def _cmd_update_tower(self) -> CommandResult:
        """Tower-PC aktualisieren: git pull + pip install + Self-Respawn.

        Wenn der Tower bereits aktuell ist (HTTP-Antwort ``up_to_date=True``),
        wird *nicht* automatisch neu gestartet -- stattdessen liefern wir ein
        ``pending_confirmation`` mit ``action="restart_tower"`` zurueck, damit
        der User sich entscheiden kann (analog zum Server-Pfad).
        """
        if not self._tower:
            return CommandResult(
                command="update_tower",
                success=False,
                text="Tower-Agent nicht verfügbar (Tower nicht verbunden).",
            )
        try:
            import httpx

            headers = {}
            if hasattr(self._tower, "_auth_headers"):
                headers = self._tower._auth_headers()
            r = httpx.post(
                f"http://{self._tower.host}/system/update",
                timeout=120.0,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            success = data.get("success", False)
            message = data.get("message", "Keine Rückmeldung")
            up_to_date = bool(data.get("up_to_date", False))

            if success and up_to_date:
                return CommandResult(
                    command="update_tower",
                    success=True,
                    text=(
                        f"🖥️ Tower: {message}\n"
                        "Soll ich den Tower trotzdem neustarten? (ja/nein, 5 Min Timeout)"
                    ),
                    pending_confirmation=True,
                    pending_data={
                        "action_type": "restart_tower",
                        "action": "restart_tower",
                    },
                )

            return CommandResult(
                command="update_tower",
                success=success,
                text=f"🖥️ Tower Update: {message}",
            )
        except Exception as e:
            logger.error("Tower Update fehlgeschlagen: %s", e)
            return CommandResult(
                command="update_tower",
                success=False,
                text=user_friendly_error(e, "Tower Update"),
            )

    def _cmd_update_all(self) -> CommandResult:
        """Server + Tower + RPi5 nacheinander aktualisieren.

        Sammelfrage-Logik: Wenn Server frische Commits hat (``restart=True``),
        gewinnt der Server-Restart -- die Sammelfrage entfaellt, weil der
        Server-Bot beim Restart die Matrix-Connection killt.
        Sonst werden alle ``pending_confirmation``-Aktionen aus den drei
        Komponenten gesammelt und in einer ``restart_all``-PendingAction
        zusammengefasst (Reihenfolge: rpi -> tower -> server).
        """
        steps: list[str] = []
        rpi_result: CommandResult | None = None
        tower_result: CommandResult | None = None

        if self._robot:
            rpi_result = self._cmd_update_rpi()
            steps.append(f"RPi5: {rpi_result.text}")
        else:
            steps.append("RPi5: nicht verbunden, übersprungen")

        if self._tower:
            tower_result = self._cmd_update_tower()
            steps.append(f"Tower: {tower_result.text}")
        else:
            steps.append("Tower: nicht verbunden, übersprungen")

        server_result = self._cmd_update()
        steps.append(f"Server: {server_result.text}")

        # Server-Restart hat Vorrang -- Sammelfrage entfaellt, weil der
        # Server beim Restart eh die Matrix-Connection killt.
        if server_result.restart:
            return CommandResult(
                command="update_all",
                success=server_result.success,
                text="\n\n".join(steps),
                restart=True,
            )

        # Pendings sammeln (Reihenfolge: rpi -> tower -> server).
        pending_subs: list[CommandResult] = [
            sub
            for sub in (rpi_result, tower_result, server_result)
            if sub is not None and sub.pending_confirmation and sub.pending_data
        ]

        # Genau ein Pending -> direkt durchreichen (kein Sammel-Wrap).
        # Damit bleiben die Bestand-Pfade ("update alles" wenn nur Server
        # gepended ist, weil RPi+Tower nicht verbunden) unveraendert.
        if len(pending_subs) == 1:
            sub = pending_subs[0]
            return CommandResult(
                command="update_all",
                success=server_result.success,
                text="\n\n".join(steps),
                pending_confirmation=True,
                pending_data=sub.pending_data,
            )

        # Mehrere Pendings -> Sammelfrage mit restart_all-Action.
        if len(pending_subs) > 1:
            actions: list[str] = []
            for sub in pending_subs:
                pd = sub.pending_data or {}
                act = pd.get("action")
                if isinstance(act, str) and act:
                    actions.append(act)
            return CommandResult(
                command="update_all",
                success=server_result.success,
                text="\n\n".join(steps)
                + "\n\nSoll ich die übersprungenen neu starten? (ja/nein, 5 Min Timeout)",
                pending_confirmation=True,
                pending_data={
                    "action_type": "restart_all",
                    "action": "restart_all",
                    "actions": actions,
                },
            )

        return CommandResult(
            command="update_all",
            success=server_result.success,
            text="\n\n".join(steps),
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

    def _read_backup(self) -> dict[str, Any] | None:
        """Liest Backup-Daten. None wenn nicht vorhanden."""
        backup_path = self._get_backup_path()
        if not backup_path.exists():
            return None
        try:
            data = cast(
                dict[str, Any],
                json.loads(backup_path.read_text(encoding="utf-8")),
            )
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
                text="⚠ Projekt-Root nicht konfiguriert.",
            )

        backup = self._read_backup()
        if not backup:
            return CommandResult(
                command="rollback",
                success=False,
                text="Kein Update zum Zurücksetzen. Backup-Datei nicht vorhanden.",
            )

        cwd = str(self._project_root)
        target_hash = backup["hash"]
        branch = backup.get("branch", "?")
        timestamp = backup.get("timestamp", "?")
        steps: list[str] = []

        steps.append(
            f"🔙 Rollback auf {target_hash[:8]} (Branch: {branch}, Backup: {timestamp})"
        )

        # Prüfe ob Hash existiert
        verify = run_cmd(
            ["git", "cat-file", "-t", target_hash],
            cwd=cwd,
            timeout=5,
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
            cwd=cwd,
            timeout=30,
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
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-e",
                _pip_install_groups(),
                "--quiet",
            ],
            cwd=cwd,
            timeout=300,
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


# ---------------------------------------------------------------------------
# Phase 77: Plugin-Manifest
# ---------------------------------------------------------------------------

HELP_SECTION_UPDATE = """Self-Update:
  update / update dich -- Git Pull + Dependencies + Neustart
  update tower -- Tower-PC aktualisieren
  update rpi -- RPi5 aktualisieren
  update alles -- Server + Tower + RPi5 nacheinander
  rollback / update zuruecksetzen -- Auf Stand vor letztem Update"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    return UpdateCommandHandler(
        project_root=ctx.project_root,
        robot_client=ctx.robot_client,
        tower_agent=ctx.tower_agent,
    )


PLUGIN = CommandPlugin(
    name="update",
    priority=56,
    category="system",
    help_section=HELP_SECTION_UPDATE,
    factory=_factory,
)
