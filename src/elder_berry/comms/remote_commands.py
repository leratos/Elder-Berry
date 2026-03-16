"""RemoteCommandHandler – Direkte Befehle via Matrix (kein LLM nötig).

Tier-1-Features:
- status / systemstatus → SystemMonitor → formatierter Text
- screenshot / screen → mss → PNG temp-Datei
- pause / play / skip / next → Media-Keys via ActionController
- volume <0-100> → ActionController.set_volume()

Tier-2-Features:
- clipboard → Clipboard lesen → Text an Matrix
- clip: <text> → Text in Clipboard schreiben
- schick mir <pfad> → Datei an Matrix senden
- starte <programm> → subprocess.Popen
- kill <prozess> → psutil Prozess beenden (Whitelist)
- wol / weck tower auf → Wake-on-LAN Magic Packet

Tier-3-Features:
- git status / git pull / git log → Whitelist-Git-Befehle
- docker ps / docker restart <name> / docker logs <name> → Whitelist
- download <url> → httpx GET → lokaler Download-Ordner

Verwendung:
    handler = RemoteCommandHandler(
        system_monitor=monitor,
        controller=action_ctrl,
        secret_store=store,
        project_root=Path("C:/Dev/Elder-Berry"),
    )
    cmd = handler.parse_command("status")
    if cmd:
        result = handler.execute(cmd, "status")
"""
from __future__ import annotations

import logging
import re
import socket
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.actions.base import ActionController
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.core.secret_store import SecretStore
    from elder_berry.system.info import SystemMonitor

logger = logging.getLogger(__name__)

# Media-Key-Mapping: Command → pyautogui Key-Name
MEDIA_KEYS = {
    "pause": "playpause",
    "play": "playpause",
    "skip": "nexttrack",
    "next": "nexttrack",
    "prev": "prevtrack",
    "previous": "prevtrack",
}

# Commands die erkannt werden (ohne Parameter)
SIMPLE_COMMANDS = (
    {"status", "systemstatus", "screenshot", "screen", "clipboard", "wol",
     "avatar", "selfie", "hilfe", "help"}
    | set(MEDIA_KEYS)
)

# Hilfe-Text: ALLE Commands hier auflisten!
# (siehe CLAUDE.md – bei neuen Features nachtragen)
HELP_TEXT = """Verfügbare Commands:

Basis:
  status / systemstatus – CPU, RAM, GPU, Disk, Top-Prozesse
  screenshot / screen – Screenshot als Bild
  hilfe / help – Diese Hilfe anzeigen

Medien:
  pause / play – Musik pausieren/fortsetzen
  skip / next – Nächster Track
  prev / previous – Vorheriger Track
  volume <0-100> – Lautstärke setzen

Avatar:
  selfie / avatar – Bild von Saleria senden
  selfie <emotion> – Mit Emotion (angry, cheerful, sad, ...)

Clipboard:
  clipboard – Zwischenablage lesen
  clip: <text> – Text in Zwischenablage schreiben

Dateien:
  schick mir <pfad> – Datei senden (max 50 MB)
  download <url> – Datei herunterladen

Prozesse:
  starte <programm> – Programm starten (Whitelist)
  kill <prozess> – Prozess beenden (Whitelist)

System:
  wol – Wake-on-LAN (Tower aufwecken)
  git status / git pull / git log / git diff
  docker ps / docker restart <name> / docker logs <name>

Claude-Agent:
  claude "<Auftrag>" – Komplexe Anfrage an Claude API"""

# Keyword-Erkennung: wenn eines dieser Wörter im Text vorkommt → Command
# Wird nur geprüft wenn kein exakter Match vorliegt
KEYWORD_MAP: dict[str, list[str]] = {
    "screenshot": ["screenshot", "bildschirmfoto", "bildschirm zeig"],
    "status": ["systemstatus", "systemzustand", "pc status", "pc-status"],
    "pause": ["pausier", "stopp musik", "musik stopp", "musik aus"],
    "play": ["musik an", "weiterspielen", "abspielen"],
    "skip": ["nächster song", "nächstes lied", "überspringen", "nächster track"],
    "clipboard": ["zwischenablage", "clipboard lesen", "was ist im clipboard"],
    "wol": ["weck tower", "tower aufwecken", "wake on lan", "tower starten"],
    "avatar": ["zeig dich", "wie siehst du aus", "bild von dir", "schick ein bild von dir", "selfie"],
    "hilfe": ["was kannst du", "was geht", "welche befehle", "welche commands"],
}

# Regex für Volume-Command: "volume 50", "vol 75", "lautstärke 30"
# \b am Ende verhindert Match auf "volume 1000" → nur 1-3 Ziffern ohne Folgeziffer
VOLUME_PATTERN = re.compile(
    r"(?:volume|vol|lautstärke|lautstarke)\s+(\d{1,3})\b",
    re.IGNORECASE,
)

# Regex für Clipboard-Write: "clip: text hier" oder "clip text hier"
CLIP_WRITE_PATTERN = re.compile(
    r"^clip[:\s]\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Regex für Datei senden: "schick mir C:\...\datei.pdf" oder "send file /path/to/file"
SEND_FILE_PATTERN = re.compile(
    r"(?:schick\s+mir|send\s+file|sende\s+mir|sende\s+(?:die\s+)?datei)\s+"
    r"([a-zA-Z]:\\[^\s]+|/[^\s]+)",
    re.IGNORECASE,
)

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

# Regex für Download: "download https://..."
DOWNLOAD_PATTERN = re.compile(
    r"^download\s+(https?://\S+)$",
    re.IGNORECASE,
)

# Regex für Avatar mit Emotion: "selfie angry", "avatar cheerful"
AVATAR_EMOTION_PATTERN = re.compile(
    r"^(?:avatar|selfie)\s+(\w+)$",
    re.IGNORECASE,
)

# Gültige Emotionen für Avatar-Rendering (lowercase → Emotion-Name)
AVATAR_EMOTIONS = {
    "neutral", "cheerful", "angry", "sarcastic", "motivated",
    "thoughtful", "whisper", "shy", "depressed", "sad",
}

# Whitelists für Sicherheit
GIT_WHITELIST = {"status", "pull", "log", "diff"}
DOCKER_WHITELIST = {"ps", "restart", "logs"}

# Prozesse die gekillt werden dürfen (lowercase)
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
    "cmd": "cmd",
    "terminal": "wt",
    "vlc": "vlc",
    "spotify": "spotify",
    "discord": "discord",
    "blender": "blender",
    "obs": "obs64",
}

# Maximale Dateigröße für send_file (50 MB)
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


@dataclass
class CommandResult:
    """Ergebnis eines ausgeführten Remote-Commands."""

    command: str
    """Name des erkannten Commands (z.B. 'status', 'screenshot')."""

    success: bool
    """True wenn der Command erfolgreich ausgeführt wurde."""

    text: str | None = None
    """Text-Antwort für den Nutzer (z.B. Systemstatus)."""

    image_path: Path | None = None
    """Pfad zum generierten Bild (z.B. Screenshot-PNG)."""

    file_path: Path | None = None
    """Pfad zur Datei die gesendet werden soll (z.B. PDF)."""


class RemoteCommandHandler:
    """Verarbeitet direkte Befehle über Matrix (kein LLM nötig).

    Alle Dependencies sind optional – fehlende Dependencies führen zu
    graceful Degradation (Fehlertext statt Crash).
    """

    def __init__(
        self,
        system_monitor: SystemMonitor | None = None,
        controller: ActionController | None = None,
        secret_store: SecretStore | None = None,
        project_root: Path | None = None,
        download_dir: Path | None = None,
        avatar_renderer: AvatarRenderer | None = None,
    ) -> None:
        self._monitor = system_monitor
        self._controller = controller
        self._secret_store = secret_store
        self._project_root = project_root
        self._download_dir = download_dir or Path.home() / "Downloads"
        self._avatar_renderer = avatar_renderer

    def parse_command(self, text: str) -> str | None:
        """Prüft ob der Text ein direkter Command ist.

        Erkennung in mehreren Stufen:
        1. Exakter Match (z.B. "status", "screenshot", "pause", "clipboard")
        2. Volume-Pattern (z.B. "volume 50", "lautstärke 30")
        3. Clip-Write-Pattern (z.B. "clip: text hier")
        4. Send-File-Pattern (z.B. "schick mir C:\\datei.pdf")
        5. Prozess-Start/Kill-Pattern (z.B. "starte chrome", "kill blender")
        6. Git-Pattern (z.B. "git status")
        7. Docker-Pattern (z.B. "docker ps")
        8. Download-Pattern (z.B. "download https://...")
        9. Keyword-Suche in natürlicher Sprache

        Args:
            text: Nachrichtentext vom Nutzer.

        Returns:
            Normalisierter Command-Name oder None wenn kein Command erkannt.
        """
        normalized = text.strip().lower()

        # Stufe 1: Exakter Match
        if normalized in SIMPLE_COMMANDS:
            return normalized

        # Stufe 2: Volume-Pattern (auch in Sätzen: "setz lautstärke 50")
        if VOLUME_PATTERN.search(normalized):
            return "volume"

        # Stufe 3: Clip-Write-Pattern
        if CLIP_WRITE_PATTERN.match(normalized):
            return "clip_write"

        # Stufe 4: Send-File-Pattern – auf Originaltext prüfen (Pfad case-sensitiv)
        if SEND_FILE_PATTERN.search(text.strip()):
            return "send_file"

        # Stufe 5: Prozess-Start/Kill
        if START_PROCESS_PATTERN.match(normalized):
            return "start_process"
        if KILL_PROCESS_PATTERN.match(normalized):
            return "kill_process"

        # Stufe 6: Git-Befehle
        if GIT_PATTERN.match(normalized):
            return "git"

        # Stufe 7: Docker-Befehle
        if DOCKER_PATTERN.match(normalized):
            return "docker"

        # Stufe 8: Download
        if DOWNLOAD_PATTERN.match(normalized):
            return "download"

        # Stufe 8b: Avatar mit Emotion ("selfie angry", "avatar cheerful")
        if AVATAR_EMOTION_PATTERN.match(normalized):
            return "avatar"

        # Stufe 9: Keyword-Suche in natürlicher Sprache
        for command, keywords in KEYWORD_MAP.items():
            for keyword in keywords:
                if keyword in normalized:
                    return command

        return None

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Command aus.

        Args:
            command: Normalisierter Command-Name (von parse_command).
            raw_text: Originaler Nachrichtentext (für Parameter-Extraktion).

        Returns:
            CommandResult mit Ergebnis.
        """
        if command in ("hilfe", "help"):
            return CommandResult(command="hilfe", success=True, text=HELP_TEXT)

        if command in ("status", "systemstatus"):
            return self._cmd_status()

        if command in ("screenshot", "screen"):
            return self._cmd_screenshot()

        if command in MEDIA_KEYS:
            return self._cmd_media(command)

        if command == "volume":
            return self._cmd_volume(raw_text)

        if command == "clipboard":
            return self._cmd_clipboard_read()

        if command == "clip_write":
            return self._cmd_clipboard_write(raw_text)

        if command == "send_file":
            return self._cmd_send_file(raw_text)

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

        if command == "download":
            return self._cmd_download(raw_text)

        if command in ("avatar", "selfie"):
            return self._cmd_avatar(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    # ------------------------------------------------------------------
    # Tier 1: Status, Screenshot, Media, Volume (bestehend)
    # ------------------------------------------------------------------

    def _cmd_status(self) -> CommandResult:
        """Systemstatus abfragen."""
        if not self._monitor:
            return CommandResult(
                command="status",
                success=False,
                text="SystemMonitor nicht verfügbar.",
            )

        try:
            info = self._monitor.get_info(top_processes=5)
            lines = [
                f"CPU: {info.cpu.usage_percent}% "
                f"({info.cpu.core_count} Kerne, {info.cpu.thread_count} Threads"
                + (f", {info.cpu.freq_mhz:.0f} MHz" if info.cpu.freq_mhz else "")
                + ")",
                f"RAM: {info.ram.used_mb:.0f} / {info.ram.total_mb:.0f} MB "
                f"({info.ram.usage_percent}% belegt)",
            ]

            for gpu in info.gpus:
                lines.append(
                    f"GPU: {gpu.name} – {gpu.gpu_util_percent}% Auslastung, "
                    f"VRAM {gpu.vram_used_mb:.0f}/{gpu.vram_total_mb:.0f} MB, "
                    f"{gpu.temperature_c}\u00b0C"
                )

            # Disk-Info (psutil)
            try:
                import psutil
                for part in psutil.disk_partitions():
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        total_gb = usage.total / (1024 ** 3)
                        used_gb = usage.used / (1024 ** 3)
                        lines.append(
                            f"Disk {part.mountpoint}: "
                            f"{used_gb:.1f} / {total_gb:.1f} GB "
                            f"({usage.percent}% belegt)"
                        )
                    except PermissionError:
                        continue
            except ImportError:
                pass

            if info.top_processes:
                lines.append("Top-Prozesse (CPU):")
                for p in info.top_processes:
                    lines.append(
                        f"  {p['name']}: CPU {p['cpu_percent']}%, "
                        f"RAM {p['memory_percent']}%"
                    )

            return CommandResult(
                command="status",
                success=True,
                text="\n".join(lines),
            )
        except Exception as e:
            logger.error("Status-Abfrage fehlgeschlagen: %s", e)
            return CommandResult(
                command="status",
                success=False,
                text=f"Fehler bei Status-Abfrage: {e}",
            )

    @staticmethod
    def _wake_monitor() -> None:
        """Weckt den Monitor auf (Windows: SC_MONITORPOWER)."""
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            # WM_SYSCOMMAND + SC_MONITORPOWER + -1 (ON)
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, -1)
            import time
            time.sleep(1)  # Monitor braucht ~1s zum Aufwachen
        except Exception as e:
            logger.debug("Monitor-Aufwecken fehlgeschlagen (ignoriert): %s", e)

    def _cmd_screenshot(self) -> CommandResult:
        """Screenshot aufnehmen und als PNG speichern. Weckt Monitor bei Bedarf."""
        try:
            import mss
        except ImportError:
            return CommandResult(
                command="screenshot",
                success=False,
                text="mss nicht installiert (pip install mss).",
            )

        # Monitor aufwecken falls er schläft
        self._wake_monitor()

        try:
            with mss.mss() as sct:
                # Gesamter Bildschirm (Monitor 0 = alle, Monitor 1 = primär)
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)

                # In temp-Datei speichern (wird vom Aufrufer aufgeräumt)
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="screenshot_", delete=False,
                )
                tmp_path = Path(tmp.name)
                tmp.close()

                # mss speichert direkt als PNG
                mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(tmp_path))

            return CommandResult(
                command="screenshot",
                success=True,
                text="Screenshot aufgenommen.",
                image_path=tmp_path,
            )
        except Exception as e:
            logger.error("Screenshot fehlgeschlagen: %s", e)
            return CommandResult(
                command="screenshot",
                success=False,
                text=f"Screenshot fehlgeschlagen: {e}",
            )

    def _cmd_media(self, command: str) -> CommandResult:
        """Media-Key senden (play/pause/skip/next/prev)."""
        if not self._controller:
            return CommandResult(
                command=command,
                success=False,
                text="ActionController nicht verfügbar.",
            )

        key = MEDIA_KEYS.get(command)
        if not key:
            return CommandResult(
                command=command,
                success=False,
                text=f"Unbekannter Media-Command: {command}",
            )

        try:
            self._controller.press_key(key)
            return CommandResult(
                command=command,
                success=True,
                text=f"Media: {command}",
            )
        except Exception as e:
            logger.error("Media-Command '%s' fehlgeschlagen: %s", command, e)
            return CommandResult(
                command=command,
                success=False,
                text=f"Media-Command fehlgeschlagen: {e}",
            )

    def _cmd_volume(self, raw_text: str) -> CommandResult:
        """Lautstärke setzen (0-100)."""
        if not self._controller:
            return CommandResult(
                command="volume",
                success=False,
                text="ActionController nicht verfügbar.",
            )

        match = VOLUME_PATTERN.search(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="volume",
                success=False,
                text="Ungültiges Format. Beispiel: volume 50",
            )

        level_percent = int(match.group(1))
        if level_percent > 100:
            return CommandResult(
                command="volume",
                success=False,
                text="Lautstärke muss zwischen 0 und 100 liegen.",
            )

        level = level_percent / 100.0

        try:
            self._controller.set_volume(level)
            return CommandResult(
                command="volume",
                success=True,
                text=f"Lautstärke: {level_percent}%",
            )
        except Exception as e:
            logger.error("Volume-Command fehlgeschlagen: %s", e)
            return CommandResult(
                command="volume",
                success=False,
                text=f"Lautstärke setzen fehlgeschlagen: {e}",
            )

    # ------------------------------------------------------------------
    # Tier 2: Clipboard, Send File, Process Control, Wake-on-LAN
    # ------------------------------------------------------------------

    def _cmd_clipboard_read(self) -> CommandResult:
        """Clipboard-Inhalt lesen und zurückgeben."""
        try:
            import pyperclip
        except ImportError:
            return CommandResult(
                command="clipboard",
                success=False,
                text="pyperclip nicht installiert (pip install pyperclip).",
            )

        try:
            content = pyperclip.paste()
            if not content:
                return CommandResult(
                    command="clipboard",
                    success=True,
                    text="Clipboard ist leer.",
                )

            # Lange Inhalte kürzen
            if len(content) > 4000:
                content = content[:4000] + "\n... (gekürzt)"

            return CommandResult(
                command="clipboard",
                success=True,
                text=f"Clipboard:\n{content}",
            )
        except Exception as e:
            logger.error("Clipboard lesen fehlgeschlagen: %s", e)
            return CommandResult(
                command="clipboard",
                success=False,
                text=f"Clipboard lesen fehlgeschlagen: {e}",
            )

    def _cmd_clipboard_write(self, raw_text: str) -> CommandResult:
        """Text in Clipboard schreiben."""
        try:
            import pyperclip
        except ImportError:
            return CommandResult(
                command="clip_write",
                success=False,
                text="pyperclip nicht installiert (pip install pyperclip).",
            )

        match = CLIP_WRITE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="clip_write",
                success=False,
                text="Ungültiges Format. Beispiel: clip: text hier",
            )

        text = match.group(1).strip()
        if not text:
            return CommandResult(
                command="clip_write",
                success=False,
                text="Kein Text angegeben.",
            )

        try:
            pyperclip.copy(text)
            preview = text[:100] + "..." if len(text) > 100 else text
            return CommandResult(
                command="clip_write",
                success=True,
                text=f"In Clipboard kopiert: {preview}",
            )
        except Exception as e:
            logger.error("Clipboard schreiben fehlgeschlagen: %s", e)
            return CommandResult(
                command="clip_write",
                success=False,
                text=f"Clipboard schreiben fehlgeschlagen: {e}",
            )

    def _cmd_send_file(self, raw_text: str) -> CommandResult:
        """Datei zum Senden vorbereiten (Pfad validieren, Größe prüfen)."""
        match = SEND_FILE_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="send_file",
                success=False,
                text="Pfad nicht erkannt. Beispiel: schick mir C:\\Users\\datei.pdf",
            )

        file_path = Path(match.group(1))

        # Pfad auflösen (symlinks, relative Teile)
        try:
            file_path = file_path.resolve()
        except (OSError, ValueError) as e:
            return CommandResult(
                command="send_file",
                success=False,
                text=f"Ungültiger Pfad: {e}",
            )

        if not file_path.exists():
            return CommandResult(
                command="send_file",
                success=False,
                text=f"Datei nicht gefunden: {file_path}",
            )

        if not file_path.is_file():
            return CommandResult(
                command="send_file",
                success=False,
                text=f"Ist keine Datei: {file_path}",
            )

        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            return CommandResult(
                command="send_file",
                success=False,
                text=f"Datei zu groß: {size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB).",
            )

        return CommandResult(
            command="send_file",
            success=True,
            text=f"Datei wird gesendet: {file_path.name} "
                 f"({file_size / 1024:.1f} KB)",
            file_path=file_path,
        )

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

    def _cmd_avatar(self, raw_text: str) -> CommandResult:
        """Avatar-Bild rendern und als PNG zurückgeben."""
        if not self._avatar_renderer:
            return CommandResult(
                command="avatar",
                success=False,
                text="AvatarRenderer nicht verfügbar.",
            )

        # Emotion aus Befehl extrahieren (optional)
        from elder_berry.character.base import Emotion

        emotion = Emotion.NEUTRAL
        match = AVATAR_EMOTION_PATTERN.match(raw_text.strip())
        if match:
            emotion_str = match.group(1).lower()
            if emotion_str in AVATAR_EMOTIONS:
                try:
                    emotion = Emotion(emotion_str)
                except ValueError:
                    pass

        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="avatar_", delete=False,
            )
            tmp_path = Path(tmp.name)
            tmp.close()

            self._avatar_renderer.render_to_file(tmp_path, emotion)

            return CommandResult(
                command="avatar",
                success=True,
                text=f"Saleria ({emotion.value})",
                image_path=tmp_path,
            )
        except NotImplementedError:
            return CommandResult(
                command="avatar",
                success=False,
                text="Avatar-Renderer unterstützt kein Datei-Rendering.",
            )
        except Exception as e:
            logger.error("Avatar-Rendering fehlgeschlagen: %s", e)
            return CommandResult(
                command="avatar",
                success=False,
                text=f"Avatar-Rendering fehlgeschlagen: {e}",
            )

    # ------------------------------------------------------------------
    # Tier 3: Git, Docker, Download
    # ------------------------------------------------------------------

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

    def _cmd_download(self, raw_text: str) -> CommandResult:
        """Datei herunterladen (httpx GET)."""
        match = DOWNLOAD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="download",
                success=False,
                text="Ungültiges Format. Beispiel: download https://example.com/file.zip",
            )

        url = match.group(1)

        try:
            import httpx
        except ImportError:
            return CommandResult(
                command="download",
                success=False,
                text="httpx nicht installiert.",
            )

        # Dateiname aus URL extrahieren
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url)
        filename = unquote(parsed.path.split("/")[-1]) or "download"

        # Download-Verzeichnis sicherstellen
        self._download_dir.mkdir(parents=True, exist_ok=True)
        target = self._download_dir / filename

        # Namenskollision vermeiden
        counter = 1
        stem = target.stem
        suffix = target.suffix
        while target.exists():
            target = self._download_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
                resp.raise_for_status()

                # Größe prüfen (wenn Content-Length vorhanden)
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
                    size_mb = int(content_length) / (1024 * 1024)
                    return CommandResult(
                        command="download",
                        success=False,
                        text=f"Datei zu groß: {size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB).",
                    )

                downloaded = 0
                with open(target, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        downloaded += len(chunk)
                        if downloaded > MAX_FILE_SIZE_BYTES:
                            f.close()
                            target.unlink(missing_ok=True)
                            return CommandResult(
                                command="download",
                                success=False,
                                text=f"Download abgebrochen: Größenlimit "
                                     f"({MAX_FILE_SIZE_MB} MB) überschritten.",
                            )
                        f.write(chunk)

            size_kb = downloaded / 1024
            return CommandResult(
                command="download",
                success=True,
                text=f"Download abgeschlossen: {target.name} ({size_kb:.1f} KB)\n"
                     f"Pfad: {target}",
            )
        except httpx.HTTPStatusError as e:
            return CommandResult(
                command="download",
                success=False,
                text=f"HTTP-Fehler {e.response.status_code}: {url}",
            )
        except httpx.RequestError as e:
            return CommandResult(
                command="download",
                success=False,
                text=f"Download fehlgeschlagen: {e}",
            )
        except Exception as e:
            logger.error("Download fehlgeschlagen: %s", e)
            target.unlink(missing_ok=True)
            return CommandResult(
                command="download",
                success=False,
                text=f"Download fehlgeschlagen: {e}",
            )
