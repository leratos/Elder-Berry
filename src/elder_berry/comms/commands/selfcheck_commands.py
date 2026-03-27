"""SelfcheckCommandHandler – Systemgesundheitsprüfung via Matrix.

Verwaltet:
- selfcheck / systemcheck / prüf dich / alles ok? → 8-Punkte-Check
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult
from elder_berry.comms.commands.cmd_utils import run_cmd
from elder_berry.comms.commands.update_commands import BACKUP_FILENAME, DEFAULT_BACKUP_DIR

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern
# ---------------------------------------------------------------------------

SELFCHECK_PATTERN = re.compile(
    r"^(?:self\s*check|system\s*check|prüf\s*dich|alles\s*ok\??|gesundheitscheck)$",
    re.IGNORECASE,
)


class SelfcheckCommandHandler(CommandHandler):
    """Handler für Systemgesundheitsprüfung."""

    def __init__(
        self,
        project_root: Path | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._project_root = project_root
        self._secret_store = secret_store

    @property
    def simple_commands(self) -> set[str]:
        return {"selfcheck"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (SELFCHECK_PATTERN, "selfcheck", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "selfcheck: Gesundheitsprüfung aller Komponenten",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "selfcheck": [
                "systemcheck", "prüf dich", "alles ok", "gesundheitscheck",
                "funktionierst du", "bist du ok", "status check",
                "läuft alles", "geht alles",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "selfcheck":
            return self._cmd_selfcheck()
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter SelfCheck-Command: {command}",
        )

    def _cmd_selfcheck(self) -> CommandResult:
        """Systemgesundheitsprüfung – prüft alle kritischen Komponenten."""
        checks: list[str] = []
        warnings = 0
        errors = 0

        # --- 1. Git ---
        if self._project_root:
            cwd = str(self._project_root)
            branch = run_cmd(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd, timeout=5,
            )
            status = run_cmd(
                ["git", "status", "--porcelain", "-uno"],
                cwd=cwd, timeout=10,
            )
            run_cmd(["git", "fetch", "origin"], cwd=cwd, timeout=15)
            behind = run_cmd(
                ["git", "rev-list", "--count", "HEAD..@{u}"],
                cwd=cwd, timeout=5,
            )

            branch_name = branch.output.strip() if branch.success else "?"
            is_dirty = status.success and status.output.strip()
            commits_behind = 0
            if behind.success and behind.output.strip().isdigit():
                commits_behind = int(behind.output.strip())

            git_parts = [f"Branch: {branch_name}"]
            if is_dirty:
                git_parts.append("uncommitted changes")
                warnings += 1
            else:
                git_parts.append("sauber")
            if commits_behind > 0:
                git_parts.append(f"{commits_behind} Commits hinter Remote")
                warnings += 1
            else:
                git_parts.append("aktuell")

            icon = "✅" if not is_dirty and commits_behind == 0 else "⚠️"
            checks.append(f"{icon} Git: {', '.join(git_parts)}")
        else:
            checks.append("⚠️ Git: Projekt-Root nicht konfiguriert")
            warnings += 1

        # --- 2. Python ---
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        checks.append(f"✅ Python: {py_version}")

        # --- 3. Disk ---
        try:
            import shutil
            usage = shutil.disk_usage(self._project_root or Path.home())
            pct = usage.used / usage.total * 100
            free_gb = usage.free / (1024 ** 3)
            if pct > 90:
                checks.append(f"⚠️ Disk: {pct:.0f}% belegt ({free_gb:.1f} GB frei)")
                warnings += 1
            else:
                checks.append(f"✅ Disk: {pct:.0f}% belegt ({free_gb:.1f} GB frei)")
        except Exception as e:
            checks.append(f"❌ Disk: Prüfung fehlgeschlagen ({e})")
            errors += 1

        # --- 4. RAM ---
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent > 85:
                checks.append(f"⚠️ RAM: {mem.percent:.0f}% belegt")
                warnings += 1
            else:
                checks.append(f"✅ RAM: {mem.percent:.0f}% belegt")
        except ImportError:
            checks.append("⚠️ RAM: psutil nicht installiert")
            warnings += 1

        # --- 5. Ollama ---
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://localhost:11434/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                if models:
                    checks.append(f"✅ Ollama: erreichbar ({', '.join(models[:3])})")
                else:
                    checks.append("⚠️ Ollama: erreichbar, aber keine Modelle geladen")
                    warnings += 1
        except Exception:
            checks.append("❌ Ollama: nicht erreichbar")
            errors += 1

        # --- 6. SecretStore ---
        if self._secret_store:
            try:
                self._secret_store.list_keys()
                checks.append("✅ SecretStore: lesbar")
            except Exception as e:
                checks.append(f"❌ SecretStore: {e}")
                errors += 1
        else:
            checks.append("⚠️ SecretStore: nicht konfiguriert")
            warnings += 1

        # --- 7. Kritische Imports ---
        critical_modules = [
            "elder_berry.core.assistant",
            "elder_berry.comms.bridge",
            "elder_berry.comms.remote_commands",
            "elder_berry.llm.router",
            "elder_berry.core.secret_store",
        ]
        import_ok = []
        import_fail = []
        for mod in critical_modules:
            try:
                __import__(mod)
                import_ok.append(mod.split(".")[-1])
            except Exception as e:
                import_fail.append(f"{mod.split('.')[-1]} ({e})")
                errors += 1

        if not import_fail:
            checks.append(f"✅ Imports: {len(import_ok)} kritische Module OK")
        else:
            checks.append(f"❌ Imports: {', '.join(import_fail)}")

        # --- 8. pip check ---
        if self._project_root:
            pip_check = run_cmd(
                [sys.executable, "-m", "pip", "check"],
                cwd=str(self._project_root),
                timeout=30,
            )
            if pip_check.success:
                checks.append("✅ Dependencies: keine Konflikte")
            else:
                lines = pip_check.output.strip().splitlines()[:3]
                detail = "\n".join(lines)
                checks.append(f"⚠️ Dependencies:\n{detail}")
                warnings += 1

        # --- Backup-Status ---
        backup_path = DEFAULT_BACKUP_DIR / BACKUP_FILENAME
        if backup_path.exists():
            try:
                backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
                if "hash" in backup_data:
                    checks.append(
                        f"💾 Update-Backup: {backup_data['hash'][:8]} "
                        f"({backup_data.get('timestamp', '?')[:10]})"
                    )
            except (json.JSONDecodeError, OSError):
                pass

        # --- Zusammenfassung ---
        header = "Systemcheck Saleria"
        if errors == 0 and warnings == 0:
            header += " – Alles in Ordnung! ✅"
        elif errors > 0:
            header += f" – {errors} Fehler, {warnings} Warnungen"
        else:
            header += f" – {warnings} Warnung{'en' if warnings != 1 else ''}"

        result_text = f"{header}\n\n" + "\n".join(checks)

        return CommandResult(
            command="selfcheck",
            success=errors == 0,
            text=result_text,
        )
