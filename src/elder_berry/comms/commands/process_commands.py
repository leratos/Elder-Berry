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

import logging
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
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

# Regex für Self-Update: "update", "update dich", "aktualisiere dich"
UPDATE_PATTERN = re.compile(
    r"^(?:update|aktualisier(?:e|en)?|updat(?:e|en)?)\s*(?:dich|saleria|mich)?$",
    re.IGNORECASE,
)

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
    ) -> None:
        self._secret_store = secret_store
        self._project_root = project_root

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"wol", "update"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (START_PROCESS_PATTERN, "start_process", False, False),
            (KILL_PROCESS_PATTERN, "kill_process", False, False),
            (GIT_PATTERN, "git", False, False),
            (DOCKER_PATTERN, "docker", False, False),
            (UPDATE_PATTERN, "update", False, False),
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "wol": ["weck tower", "tower aufwecken", "wake on lan", "tower starten"],
            "update": [
                "update dich", "aktualisiere dich", "neue funktionen",
                "schau dir deine neuen funktionen an", "mach ein update",
                "git pull und neustart", "update saleria",
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

        # --- Schritt 4: git pull ---
        old_hash = self._run_cmd(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            timeout=5,
        )

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
