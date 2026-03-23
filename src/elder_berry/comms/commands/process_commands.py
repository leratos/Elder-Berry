"""ProcessCommandHandler – Prozess-, Git-, Docker- und WOL-Commands.

Verwaltet:
- starte <programm> → Prozess starten (Whitelist)
- kill <prozess> → Prozess beenden (Whitelist)
- wol → Wake-on-LAN Magic Packet
- git status/pull/log/diff → Git-Befehle (Whitelist)
- docker ps/restart/logs → Docker-Befehle (Whitelist)
- update → Self-Update: git pull + pip install + restart
"""
from __future__ import annotations

import json
import logging
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.robot.client import RobotClient

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

# Regex für Self-Update: "update", "update dich", "aktualisiere dich"
UPDATE_PATTERN = re.compile(
    r"^(?:update|aktualisier(?:e|en)?|updat(?:e|en)?)\s*(?:dich|saleria|mich)?$",
    re.IGNORECASE,
)

# Regex für Rollback: "rollback", "update zurücksetzen", "zurückrollen"
ROLLBACK_PATTERN = re.compile(
    r"^(?:rollback|update\s*zurück(?:setzen)?|zurückrollen)$",
    re.IGNORECASE,
)

# Regex für SelfCheck: "selfcheck", "systemcheck", "prüf dich", "alles ok"
SELFCHECK_PATTERN = re.compile(
    r"^(?:self\s*check|system\s*check|prüf\s*dich|alles\s*ok\??|gesundheitscheck)$",
    re.IGNORECASE,
)

# Regex für RPi-Update: "update rpi", "rpi update", "aktualisiere rpi"
UPDATE_RPI_PATTERN = re.compile(
    r"^(?:update\s+rpi|rpi\s+update|aktualisier(?:e)?\s+rpi)$",
    re.IGNORECASE,
)

# Regex für Alles-Update: "update alles", "alles updaten"
UPDATE_ALL_PATTERN = re.compile(
    r"^(?:update\s+alles|alles\s+update[n]?)$",
    re.IGNORECASE,
)

# Backup-Datei für Update-Rollback
DEFAULT_BACKUP_DIR = Path.home() / ".elder-berry"
BACKUP_FILENAME = "update_backup.json"

# ---------------------------------------------------------------------------
# Whitelists
# ---------------------------------------------------------------------------

GIT_WHITELIST = {"status", "pull", "log", "diff"}
DOCKER_WHITELIST = {"ps", "restart", "logs"}
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

_GIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{4,40}$", re.IGNORECASE)


def _is_valid_git_hash(value: str) -> bool:
    """Prüft ob ein String ein valider git-Hash (short oder full) ist."""
    return bool(_GIT_HASH_PATTERN.match(value))


@dataclass
class _CmdResult:
    """Internes Ergebnis-DTO für Shell-Befehle."""

    success: bool
    output: str


class ProcessCommandHandler(CommandHandler):
    """Handler für Prozess-, Git-, Docker-, WOL- und Self-Update-Commands."""

    def __init__(
        self,
        secret_store: SecretStore | None = None,
        project_root: Path | None = None,
        robot_client: RobotClient | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._project_root = project_root
        self._robot = robot_client

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"wol", "update", "rollback", "selfcheck", "update rpi", "update alles"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (START_PROCESS_PATTERN, "start_process", False, False),
            (KILL_PROCESS_PATTERN, "kill_process", False, False),
            (GIT_PATTERN, "git", False, False),
            (DOCKER_PATTERN, "docker", False, False),
            (UPDATE_PATTERN, "update", False, False),
            (UPDATE_RPI_PATTERN, "update_rpi", False, False),
            (UPDATE_ALL_PATTERN, "update_all", False, False),
            (ROLLBACK_PATTERN, "rollback", False, False),
            (SELFCHECK_PATTERN, "selfcheck", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "starte <programm>: Programm starten (Whitelist)",
            "kill <prozess>: Prozess beenden (Whitelist)",
            "wol: Wake-on-LAN (Tower aufwecken)",
            "git status / git pull / git log / git diff: Git-Befehle",
            "docker ps / docker restart / docker logs: Docker-Befehle",
            "update: Git Pull + Dependencies + Neustart (Tower)",
            "update rpi: RPi5 aktualisieren (git pull + pip + restart)",
            "update alles: Tower + RPi5 nacheinander aktualisieren",
            "rollback: Auf Stand vor letztem Update zurücksetzen",
            "selfcheck: Gesundheitsprüfung aller Komponenten",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "wol": [
                "weck tower", "tower aufwecken", "wake on lan",
                "tower starten", "pc aufwecken", "rechner wecken",
                "tower wecken",
            ],
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
            "selfcheck": [
                "systemcheck", "prüf dich", "alles ok", "gesundheitscheck",
                "funktionierst du", "bist du ok", "status check",
                "läuft alles", "geht alles",
            ],
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
        if command == "update":
            return self._cmd_update()
        if command in ("update_rpi", "update rpi"):
            return self._cmd_update_rpi()
        if command in ("update_all", "update alles"):
            return self._cmd_update_all()
        if command == "rollback":
            return self._cmd_rollback()
        if command == "selfcheck":
            return self._cmd_selfcheck()

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

    def _cmd_update(self) -> CommandResult:
        """Self-Update: git pull + pip install (wenn nötig) + restart.

        Sequenz:
        1. git fetch origin
        2. Prüfe ob lokaler Branch hinter Remote ist
        3. Prüfe auf lokale Änderungen (uncommitted)
        4. git pull --ff-only
        5. Prüfe ob pyproject.toml geändert wurde
        6. pip install -e ".[extras]" wenn nötig
        7. Return restart=True

        Returns:
            CommandResult mit restart=True bei Erfolg.
        """
        if not self._project_root:
            return CommandResult(
                command="update",
                success=False,
                text="Projekt-Root nicht konfiguriert.",
            )

        cwd = str(self._project_root)
        steps: list[str] = []

        # --- Schritt 1: git fetch ---
        fetch = self._run_cmd(["git", "fetch", "origin"], cwd=cwd, timeout=30)
        if not fetch.success:
            return CommandResult(
                command="update",
                success=False,
                text=f"❌ Git Fetch fehlgeschlagen:\n{fetch.output}",
            )

        # --- Schritt 2: Prüfe ob Änderungen vorliegen ---
        behind = self._run_cmd(
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
                text="✅ Alles aktuell – kein Update nötig.",
            )

        steps.append(f"📥 {commits_behind} neue(r) Commit(s) verfügbar")

        # --- Schritt 3: Prüfe auf lokale Änderungen (uncommitted) ---
        status = self._run_cmd(
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
        old_hash = self._run_cmd(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            timeout=5,
        )
        old_hash_full = self._run_cmd(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            timeout=5,
        )
        branch = self._run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            timeout=5,
        )

        # Backup schreiben bevor pull
        if old_hash_full.success:
            self._write_backup(
                commit_hash=old_hash_full.output.strip(),
                branch=branch.output.strip() if branch.success else "unknown",
            )
            steps.append("💾 Backup gesichert (rollback möglich)")

        pull = self._run_cmd(["git", "pull", "--ff-only"], cwd=cwd, timeout=60)
        if not pull.success:
            return CommandResult(
                command="update",
                success=False,
                text=f"❌ Git Pull fehlgeschlagen:\n{pull.output}",
            )
        steps.append("✅ Code aktualisiert")

        new_hash = self._run_cmd(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            timeout=5,
        )
        if old_hash.success and new_hash.success:
            old_h = old_hash.output.strip()
            new_h = new_hash.output.strip()
            # Validate: git short-hash should only contain hex chars
            if _is_valid_git_hash(old_h) and _is_valid_git_hash(new_h):
                log = self._run_cmd(
                    ["git", "log", "--oneline", f"{old_h}..{new_h}"],
                    cwd=cwd,
                    timeout=10,
                )
                if log.success and log.output.strip():
                    steps.append(f"📋 Änderungen:\n{log.output.strip()}")

        # --- Schritt 5: Dependency-Check ---
        diff_files = _CmdResult(success=False, output="")
        if old_hash.success and new_hash.success:
            old_h = old_hash.output.strip()
            new_h = new_hash.output.strip()
            if _is_valid_git_hash(old_h) and _is_valid_git_hash(new_h):
                diff_files = self._run_cmd(
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
            pip = self._run_cmd(
                [sys.executable, "-m", "pip", "install", "-e",
                 ".[windows,tts-neural,avatar,matrix,remote,memory,stt]",
                 "--quiet"],
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
        """Tower + RPi5 nacheinander aktualisieren.

        1. RPi5 zuerst (kann im Hintergrund neustarten)
        2. Tower danach (restart=True)
        """
        steps: list[str] = []

        # RPi5 zuerst
        if self._robot:
            rpi_result = self._cmd_update_rpi()
            if rpi_result.success:
                steps.append(f"RPi5: {rpi_result.text}")
            else:
                steps.append(f"RPi5: {rpi_result.text}")
        else:
            steps.append("RPi5: nicht verbunden, uebersprungen")

        # Tower
        tower_result = self._cmd_update()
        steps.append(f"Tower: {tower_result.text}")

        return CommandResult(
            command="update_all",
            success=tower_result.success,
            text="\n\n".join(steps),
            restart=tower_result.restart,
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
        """Rollback: Setzt auf den Stand vor dem letzten Update zurück.

        Sequenz:
        1. Backup-Datei lesen
        2. git reset --hard <hash>
        3. pip install (falls nötig)
        4. Backup-Datei löschen
        5. restart=True
        """
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
        verify = self._run_cmd(
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
        reset = self._run_cmd(
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

        # Dependencies neu installieren (sicherheitshalber)
        steps.append("📦 Installiere Dependencies...")
        pip = self._run_cmd(
            [sys.executable, "-m", "pip", "install", "-e",
             ".[windows,tts-neural,avatar,matrix,remote,memory,stt]",
             "--quiet"],
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

    # ------------------------------------------------------------------
    # SelfCheck
    # ------------------------------------------------------------------

    def _cmd_selfcheck(self) -> CommandResult:
        """Systemgesundheitsprüfung – prüft alle kritischen Komponenten.

        Checks:
        1. Git: Branch, sauber, hinter Remote?
        2. Python-Version
        3. Disk-Nutzung
        4. RAM-Nutzung
        5. Ollama erreichbar?
        6. SecretStore lesbar?
        7. Kritische Module importierbar?
        8. pip check (broken dependencies)?
        """
        checks: list[str] = []
        warnings = 0
        errors = 0

        # --- 1. Git ---
        if self._project_root:
            cwd = str(self._project_root)
            branch = self._run_cmd(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd, timeout=5,
            )
            status = self._run_cmd(
                ["git", "status", "--porcelain", "-uno"],
                cwd=cwd, timeout=10,
            )
            # Fetch + behind-check
            self._run_cmd(["git", "fetch", "origin"], cwd=cwd, timeout=15)
            behind = self._run_cmd(
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
            pip_check = self._run_cmd(
                [sys.executable, "-m", "pip", "check"],
                cwd=str(self._project_root),
                timeout=30,
            )
            if pip_check.success:
                checks.append("✅ Dependencies: keine Konflikte")
            else:
                # Kürzen auf maximal 3 Zeilen
                lines = pip_check.output.strip().splitlines()[:3]
                detail = "\n".join(lines)
                checks.append(f"⚠️ Dependencies:\n{detail}")
                warnings += 1

        # --- Backup-Status ---
        backup = self._read_backup()
        if backup:
            checks.append(
                f"💾 Update-Backup: {backup['hash'][:8]} "
                f"({backup.get('timestamp', '?')[:10]})"
            )

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

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _run_cmd(
        self,
        cmd: list[str],
        cwd: str,
        timeout: int = 30,
    ) -> _CmdResult:
        """Führt einen Shell-Befehl aus und gibt Ergebnis zurück.

        Args:
            cmd: Befehl als Liste (kein Shell-Interpolation).
            cwd: Arbeitsverzeichnis.
            timeout: Timeout in Sekunden.

        Returns:
            _CmdResult mit success und output.
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
            return _CmdResult(success=result.returncode == 0, output=output)
        except subprocess.TimeoutExpired:
            return _CmdResult(success=False, output=f"Timeout ({timeout}s)")
        except FileNotFoundError:
            return _CmdResult(
                success=False,
                output=f"Befehl nicht gefunden: {cmd[0]}",
            )
        except Exception as e:
            return _CmdResult(success=False, output=str(e))
