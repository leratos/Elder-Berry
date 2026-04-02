"""SelfcheckCommandHandler – Systemgesundheitsprüfung via Matrix.

Verwaltet:
- selfcheck / systemcheck / prüf dich / alles ok? → Infra + Fähigkeiten-Check
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


# ---------------------------------------------------------------------------
# Service-Beschreibungen für die Ausgabe
# ---------------------------------------------------------------------------

_SERVICE_LABELS: dict[str, str] = {
    "anthropic_client": "Anthropic API",
    "calendar": "Kalender",
    "email_client": "IMAP (E-Mail Empfang)",
    "email_sender": "SMTP (E-Mail Versand)",
    "weather": "Wetter (Open-Meteo)",
    "search_client": "Web-Suche (Brave)",
    "nextcloud_files": "Nextcloud Files",
    "stirling_pdf": "Stirling-PDF",
    "carddav_sync": "CardDAV Sync",
    "robot_client": "RPi5 Robot",
    "gym_client": "Berry-Gym",
    "note_store": "Notizen-DB",
    "contact_store": "Kontakte-DB",
    "todo_store": "Aufgaben-DB",
    "reminder_store": "Erinnerungen-DB",
    "tts": "Sprachausgabe (TTS)",
    "stt": "Spracherkennung (STT)",
    "memory": "Gedächtnis (ChromaDB)",
    "avatar": "Avatar-Renderer",
    "document_reader": "Dokument-Reader",
    "computer_use": "Computer Use (Vision)",
    "web_fetcher": "Web-Fetcher",
    "audio_router": "Audio-Router",
}


class SelfcheckCommandHandler(CommandHandler):
    """Handler für Systemgesundheitsprüfung."""

    def __init__(
        self,
        project_root: Path | None = None,
        secret_store: SecretStore | None = None,
        services: dict[str, Any] | None = None,
    ) -> None:
        self._project_root = project_root
        self._secret_store = secret_store
        self._services = services or {}

    def register_service(self, key: str, service: Any) -> None:
        """Registriert einen Service nachträglich für den Healthcheck.

        Nützlich für Services die nicht im RemoteCommandHandler leben
        (z.B. TTS, STT, Memory, Avatar).
        """
        if service is not None:
            self._services[key] = service

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
            "selfcheck: Gesundheitsprüfung aller Komponenten + Fähigkeiten",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "selfcheck": [
                "systemcheck", "prüf dich", "alles ok", "gesundheitscheck",
                "funktionierst du", "bist du ok", "status check",
                "läuft alles", "geht alles", "healthcheck",
                "fähigkeiten prüfen", "was funktioniert",
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
        """Systemgesundheitsprüfung – Infrastruktur + Fähigkeiten."""
        checks: list[str] = []
        warnings = 0
        errors = 0

        # ================================================================
        # TEIL 1: Infrastruktur (bestehende Checks)
        # ================================================================
        checks.append("── Infrastruktur ──")

        w, e = self._check_git(checks)
        warnings += w
        errors += e

        # Python
        py_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}"
        )
        checks.append(f"✅ Python: {py_version}")

        w, e = self._check_disk(checks)
        warnings += w
        errors += e

        w, e = self._check_ram(checks)
        warnings += w
        errors += e

        w, e = self._check_ollama(checks)
        warnings += w
        errors += e

        w, e = self._check_secret_store(checks)
        warnings += w
        errors += e

        w, e = self._check_imports(checks)
        warnings += w
        errors += e

        w, e = self._check_pip(checks)
        warnings += w
        errors += e

        self._check_backup(checks)

        # ================================================================
        # TEIL 2: Fähigkeiten (Service-Connectivity)
        # ================================================================
        if self._services:
            checks.append("")
            checks.append("── Fähigkeiten ──")
            w, e = self._check_services(checks)
            warnings += w
            errors += e

        # ================================================================
        # Zusammenfassung
        # ================================================================
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

    # ------------------------------------------------------------------
    # Infrastruktur-Checks
    # ------------------------------------------------------------------

    def _check_git(self, checks: list[str]) -> tuple[int, int]:
        """Git-Status prüfen. Returns (warnings, errors)."""
        warnings = 0
        errors = 0

        if not self._project_root:
            checks.append("⚠️ Git: Projekt-Root nicht konfiguriert")
            return 1, 0

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
        return warnings, errors

    def _check_disk(self, checks: list[str]) -> tuple[int, int]:
        """Disk-Belegung prüfen."""
        try:
            import shutil
            usage = shutil.disk_usage(self._project_root or Path.home())
            pct = usage.used / usage.total * 100
            free_gb = usage.free / (1024 ** 3)
            if pct > 90:
                checks.append(
                    f"⚠️ Disk: {pct:.0f}% belegt ({free_gb:.1f} GB frei)"
                )
                return 1, 0
            checks.append(
                f"✅ Disk: {pct:.0f}% belegt ({free_gb:.1f} GB frei)"
            )
            return 0, 0
        except Exception as e:
            checks.append(f"❌ Disk: Prüfung fehlgeschlagen ({e})")
            return 0, 1

    def _check_ram(self, checks: list[str]) -> tuple[int, int]:
        """RAM-Auslastung prüfen."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent > 85:
                checks.append(f"⚠️ RAM: {mem.percent:.0f}% belegt")
                return 1, 0
            checks.append(f"✅ RAM: {mem.percent:.0f}% belegt")
            return 0, 0
        except ImportError:
            checks.append("⚠️ RAM: psutil nicht installiert")
            return 1, 0

    def _check_ollama(self, checks: list[str]) -> tuple[int, int]:
        """Ollama-Erreichbarkeit prüfen."""
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
                    checks.append(
                        f"✅ Ollama: erreichbar ({', '.join(models[:3])})"
                    )
                else:
                    checks.append(
                        "⚠️ Ollama: erreichbar, aber keine Modelle geladen"
                    )
                    return 1, 0
            return 0, 0
        except Exception:
            checks.append("❌ Ollama: nicht erreichbar")
            return 0, 1

    def _check_secret_store(self, checks: list[str]) -> tuple[int, int]:
        """SecretStore-Lesbarkeit prüfen."""
        if self._secret_store:
            try:
                self._secret_store.list_keys()
                checks.append("✅ SecretStore: lesbar")
                return 0, 0
            except Exception as e:
                checks.append(f"❌ SecretStore: {e}")
                return 0, 1
        checks.append("⚠️ SecretStore: nicht konfiguriert")
        return 1, 0

    def _check_imports(self, checks: list[str]) -> tuple[int, int]:
        """Kritische Module importieren."""
        errors = 0
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
        return 0, errors

    def _check_pip(self, checks: list[str]) -> tuple[int, int]:
        """pip check auf Dependency-Konflikte."""
        if not self._project_root:
            return 0, 0
        pip_check = run_cmd(
            [sys.executable, "-m", "pip", "check"],
            cwd=str(self._project_root),
            timeout=30,
        )
        if pip_check.success:
            checks.append("✅ Dependencies: keine Konflikte")
            return 0, 0
        lines = pip_check.output.strip().splitlines()[:3]
        detail = "\n".join(lines)
        checks.append(f"⚠️ Dependencies:\n{detail}")
        return 1, 0

    def _check_backup(self, checks: list[str]) -> None:
        """Backup-Status anzeigen (informativ, kein Warning/Error)."""
        backup_path = DEFAULT_BACKUP_DIR / BACKUP_FILENAME
        if backup_path.exists():
            try:
                backup_data = json.loads(
                    backup_path.read_text(encoding="utf-8")
                )
                if "hash" in backup_data:
                    checks.append(
                        f"💾 Update-Backup: {backup_data['hash'][:8]} "
                        f"({backup_data.get('timestamp', '?')[:10]})"
                    )
            except (json.JSONDecodeError, OSError):
                pass

    # ------------------------------------------------------------------
    # Fähigkeiten-Checks (Service-Connectivity)
    # ------------------------------------------------------------------

    def _check_services(self, checks: list[str]) -> tuple[int, int]:
        """Prüft alle übergebenen Services auf Erreichbarkeit.

        Unterscheidet:
        - ✅ Verfügbar (is_available/is_online == True)
        - ❌ Konfiguriert aber nicht erreichbar
        - ➖ Nicht konfiguriert (kein Service-Objekt übergeben)

        Returns:
            (warnings, errors) – nicht-konfigurierte Services sind keine
            Warnings, nur fehlgeschlagene Verbindungen zählen als Error.
        """
        warnings = 0
        errors = 0

        # Reihenfolge der Checks (gruppiert nach Kategorie)
        check_order = [
            # LLM
            "anthropic_client",
            # Kommunikation
            "calendar",
            "email_client",
            "email_sender",
            # Cloud & Dateien
            "nextcloud_files",
            "stirling_pdf",
            "carddav_sync",
            # Web & Suche
            "weather",
            "search_client",
            "web_fetcher",
            # Hardware
            "robot_client",
            # Ausgabe
            "tts",
            "stt",
            "avatar",
            "audio_router",
            # KI-Tools
            "memory",
            "computer_use",
            "document_reader",
            # Stores
            "note_store",
            "contact_store",
            "todo_store",
            "reminder_store",
            # Fitness
            "gym_client",
        ]

        for key in check_order:
            label = _SERVICE_LABELS.get(key, key)
            svc = self._services.get(key)

            if svc is None:
                checks.append(f"➖ {label}: nicht konfiguriert")
                continue

            ok, detail = self._probe_service(key, svc)
            if ok:
                suffix = f" ({detail})" if detail else ""
                checks.append(f"✅ {label}{suffix}")
            else:
                suffix = f": {detail}" if detail else ""
                checks.append(f"❌ {label}{suffix}")
                errors += 1

        return warnings, errors

    @staticmethod
    def _probe_service(key: str, svc: Any) -> tuple[bool, str]:
        """Prüft einen einzelnen Service auf Erreichbarkeit.

        Returns:
            (ok, detail) – ok=True wenn erreichbar, detail für Zusatzinfo.
        """
        try:
            # Services mit is_available()
            if hasattr(svc, "is_available"):
                if svc.is_available():
                    return True, _get_service_detail(key, svc)
                return False, "nicht erreichbar"

            # Services mit is_online() (RobotClient, AgentClient)
            if hasattr(svc, "is_online"):
                if svc.is_online():
                    return True, _get_service_detail(key, svc)
                return False, "nicht erreichbar"

            # Stores: prüfe ob DB-Datei existiert und lesbar ist
            if hasattr(svc, "_db_path"):
                db_path = svc._db_path
                if db_path.exists():
                    return True, str(db_path)
                return False, f"DB nicht gefunden: {db_path}"

            # AudioRouter, WebFetcher etc. – wenn vorhanden, dann OK
            return True, ""

        except Exception as e:
            return False, str(e)


def _get_service_detail(key: str, svc: Any) -> str:
    """Extrahiert eine kurze Info-Zeile aus dem Service-Objekt."""
    # Calendar: Typ anzeigen
    if key == "calendar":
        cls_name = type(svc).__name__
        if "CalDAV" in cls_name:
            return "Nextcloud CalDAV"
        if "Google" in cls_name:
            return "Google Calendar"
        return cls_name

    # Email: Host anzeigen
    if key == "email_client" and hasattr(svc, "_host"):
        return svc._host

    # Nextcloud: URL
    if key == "nextcloud_files" and hasattr(svc, "_base_url"):
        return svc._base_url

    # Stirling-PDF: URL
    if key == "stirling_pdf" and hasattr(svc, "_base_url"):
        return svc._base_url

    # Robot: URL
    if key == "robot_client" and hasattr(svc, "_base_url"):
        return svc._base_url

    # TTS: Engine-Typ
    if key == "tts":
        cls_name = type(svc).__name__
        return cls_name

    # STT: Engine-Typ
    if key == "stt":
        cls_name = type(svc).__name__
        return cls_name

    # Memory: Typ
    if key == "memory":
        cls_name = type(svc).__name__
        return cls_name

    # Gym: URL
    if key == "gym_client" and hasattr(svc, "_base_url"):
        return svc._base_url

    return ""
