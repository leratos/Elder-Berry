"""SystemCommandHandler -- System, Media, Volume, Avatar, Screenshot, Restart.

Extrahiert aus remote_commands.py (Refactoring).
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.actions.base import ActionController
    from elder_berry.avatar.base import AvatarRenderer
    from elder_berry.core.tower_agent import TowerAgent
    from elder_berry.system.info import SystemMonitor

logger = logging.getLogger(__name__)

# Media-Key-Mapping: Command -> pyautogui Key-Name
MEDIA_KEYS = {
    "pause": "playpause",
    "play": "playpause",
    "skip": "nexttrack",
    "next": "nexttrack",
    "prev": "prevtrack",
    "previous": "prevtrack",
}

# Regex fuer Volume-Command: "volume 50", "vol 75", "lautstaerke 30"
VOLUME_PATTERN = re.compile(
    r"(?:volume|vol|lautst\u00e4rke|lautstarke)\s+(\d{1,3})\b",
    re.IGNORECASE,
)

# Regex fuer Avatar mit Emotion: "selfie angry", "avatar cheerful"
AVATAR_EMOTION_PATTERN = re.compile(
    r"^(?:avatar|selfie)\s+(\w+)$",
    re.IGNORECASE,
)

# Gueltige Emotionen fuer Avatar-Rendering (lowercase -> Emotion-Name)
AVATAR_EMOTIONS = {
    "neutral", "cheerful", "angry", "sarcastic", "motivated",
    "thoughtful", "whisper", "shy", "depressed", "sad",
}


class SystemCommandHandler(CommandHandler):
    """Handler fuer System-, Media-, Volume-, Avatar- und Screenshot-Commands."""

    def __init__(
        self,
        system_monitor: SystemMonitor | None = None,
        controller: ActionController | None = None,
        avatar_renderer: AvatarRenderer | None = None,
        tower_agent: TowerAgent | None = None,
    ) -> None:
        self._monitor = system_monitor
        self._controller = controller
        self._avatar_renderer = avatar_renderer
        self._tower_agent = tower_agent

    @property
    def simple_commands(self) -> set[str]:
        return (
            {"status", "systemstatus", "screenshot", "screen",
             "avatar", "selfie", "restart", "neustart"}
            | set(MEDIA_KEYS)
        )

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (VOLUME_PATTERN, "volume", False, True),
            (AVATAR_EMOTION_PATTERN, "avatar", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "status: Systemstatus (CPU, RAM, GPU, Disk, Top-Prozesse)",
            "screenshot: Screenshot vom Bildschirm",
            "pause / play: Musik pausieren / fortsetzen",
            "skip / prev: Nächster / vorheriger Track",
            "volume <0-100>: Lautstärke setzen",
            "selfie [emotion]: Bild von Saleria senden",
            "restart: Bot neu starten",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "screenshot": [
                "screenshot", "bildschirmfoto", "bildschirm zeig",
                "mach ein foto vom bildschirm", "zeig mir den bildschirm",
                "was ist auf dem bildschirm",
            ],
            "status": [
                "systemstatus", "systemzustand", "pc status", "pc-status",
                "wie geht es dem pc", "wie l\u00e4uft der pc", "cpu auslastung",
                "ram auslastung", "speicherverbrauch",
            ],
            "pause": [
                "pausier", "stopp musik", "musik stopp", "musik aus",
                "musik pausieren", "halt die musik an",
            ],
            "play": [
                "musik an", "weiterspielen", "abspielen",
                "musik weiter", "spiel weiter",
            ],
            "skip": [
                "n\u00e4chster song", "n\u00e4chstes lied", "\u00fcberspringen",
                "n\u00e4chster track",
            ],
            "prev": [
                "vorheriger song", "vorheriges lied", "lied zur\u00fcck",
                "vorheriger track", "song zur\u00fcck",
            ],
            "volume": [
                "lautst\u00e4rke", "leiser", "lauter", "ton leiser", "ton lauter",
            ],
            "avatar": [
                "zeig dich", "wie siehst du aus", "bild von dir",
                "schick ein bild von dir", "selfie",
            ],
            "hilfe": [
                "was kannst du", "was geht", "welche befehle",
                "welche commands", "zeig mir die befehle",
            ],
            "restart": [
                "starte neu", "neustart", "restart dich",
                "bitte neustarten", "starte dich neu",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command in ("status", "systemstatus"):
            return self._cmd_status()

        if command in ("screenshot", "screen"):
            return self._cmd_screenshot()

        if command in MEDIA_KEYS:
            return self._cmd_media(command)

        if command == "volume":
            return self._cmd_volume(raw_text)

        if command in ("avatar", "selfie"):
            return self._cmd_avatar(raw_text)

        if command in ("restart", "neustart"):
            return self._cmd_restart()

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    # ------------------------------------------------------------------
    # Tier 1: Status, Screenshot, Media, Volume (bestehend)
    # ------------------------------------------------------------------

    def _cmd_status(self) -> CommandResult:
        """Systemstatus abfragen – Tower bevorzugt, Server als Fallback."""
        # Versuch 1: Tower-Status (zeigt GPU, PC-Auslastung)
        tower_result = self._status_tower()
        if tower_result:
            return tower_result

        # Versuch 2: Lokaler Status
        return self._status_local()

    def _status_tower(self) -> CommandResult | None:
        """Systemstatus vom Tower via HTTP. None wenn nicht verfügbar."""
        if not self._tower_agent:
            return None

        try:
            import httpx
            r = httpx.get(
                f"http://{self._tower_agent.host}/system",
                timeout=5.0,
            )
            r.raise_for_status()
            data = r.json()

            cpu = data.get("cpu", {})
            ram = data.get("ram", {})
            lines = [
                f"🖥️ Tower ({data.get('platform', '?')})",
                f"CPU: {cpu.get('usage_percent', '?')}% "
                f"({cpu.get('core_count', '?')} Kerne, "
                f"{cpu.get('thread_count', '?')} Threads"
                + (f", {cpu['freq_mhz']:.0f} MHz" if cpu.get("freq_mhz") else "")
                + ")",
                f"RAM: {ram.get('used_mb', 0):.0f} / "
                f"{ram.get('total_mb', 0):.0f} MB "
                f"({ram.get('usage_percent', '?')}% belegt)",
            ]

            for gpu in data.get("gpus", []):
                lines.append(
                    f"GPU: {gpu['name']} – {gpu['gpu_util_percent']}% Auslastung, "
                    f"VRAM {gpu['vram_used_mb']:.0f}/{gpu['vram_total_mb']:.0f} MB, "
                    f"{gpu['temperature_c']}°C"
                )

            procs = data.get("top_processes", [])
            if procs:
                lines.append("Top-Prozesse (CPU):")
                for p in procs:
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
            logger.debug("Tower-Status nicht verfügbar: %s", e)
            return None

    def _status_local(self) -> CommandResult:
        """Lokaler Systemstatus (Server oder Tower wenn lokal)."""
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
                    f"{gpu.temperature_c}°C"
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
        """Screenshot aufnehmen und als PNG speichern.

        Strategie:
        1. Lokales mss (Windows/Tower) – weckt Monitor bei Bedarf
        2. TowerAgent (Server → Tower via SSH-Tunnel)
        """
        # Versuch 1: Lokales mss
        result = self._screenshot_local()
        if result:
            return result

        # Versuch 2: TowerAgent (Remote-Screenshot vom Tower)
        result = self._screenshot_tower()
        if result:
            return result

        return CommandResult(
            command="screenshot",
            success=False,
            text="Screenshot nicht möglich: weder mss noch TowerAgent verfügbar.",
        )

    def _screenshot_local(self) -> CommandResult | None:
        """Screenshot via lokales mss. Gibt None zurück wenn nicht verfügbar."""
        try:
            import mss
            import mss.tools
        except ImportError:
            return None

        self._wake_monitor()

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)

                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", prefix="screenshot_", delete=False,
                )
                tmp_path = Path(tmp.name)
                tmp.close()

                mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(tmp_path))

            return CommandResult(
                command="screenshot",
                success=True,
                text="Screenshot aufgenommen.",
                image_path=tmp_path,
            )
        except Exception as e:
            logger.error("Lokaler Screenshot fehlgeschlagen: %s", e)
            return None

    def _screenshot_tower(self) -> CommandResult | None:
        """Screenshot via TowerAgent (synchroner HTTP-Call).

        Gibt None zurück wenn nicht verfügbar.
        """
        if not self._tower_agent:
            return None

        try:
            import httpx
            r = httpx.get(
                f"http://{self._tower_agent.host}/screenshot",
                timeout=10.0,
            )
            r.raise_for_status()
            png_bytes = r.content

            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="screenshot_tower_", delete=False,
            )
            tmp_path = Path(tmp.name)
            tmp.write(png_bytes)
            tmp.close()

            logger.info("Screenshot via TowerAgent: %d bytes", len(png_bytes))
            return CommandResult(
                command="screenshot",
                success=True,
                text="Screenshot aufgenommen (via Tower).",
                image_path=tmp_path,
            )
        except Exception as e:
            logger.error("Tower-Screenshot fehlgeschlagen: %s", e)
            return None

    def _cmd_media(self, command: str) -> CommandResult:
        """Media-Key senden (play/pause/skip/next/prev)."""
        if not self._controller:
            return CommandResult(
                command=command,
                success=False,
                text="ActionController nicht verf\u00fcgbar.",
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
        """Lautst\u00e4rke setzen (0-100)."""
        if not self._controller:
            return CommandResult(
                command="volume",
                success=False,
                text="ActionController nicht verf\u00fcgbar.",
            )

        match = VOLUME_PATTERN.search(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="volume",
                success=False,
                text="Ung\u00fcltiges Format. Beispiel: volume 50",
            )

        level_percent = int(match.group(1))
        if level_percent > 100:
            return CommandResult(
                command="volume",
                success=False,
                text="Lautst\u00e4rke muss zwischen 0 und 100 liegen.",
            )

        level = level_percent / 100.0

        try:
            self._controller.set_volume(level)
            return CommandResult(
                command="volume",
                success=True,
                text=f"Lautst\u00e4rke: {level_percent}%",
            )
        except Exception as e:
            logger.error("Volume-Command fehlgeschlagen: %s", e)
            return CommandResult(
                command="volume",
                success=False,
                text=f"Lautst\u00e4rke setzen fehlgeschlagen: {e}",
            )

    def _cmd_avatar(self, raw_text: str) -> CommandResult:
        """Avatar-Bild rendern – lokal oder via TowerAgent."""
        # Emotion aus Befehl extrahieren (optional)
        emotion_str = "neutral"
        match = AVATAR_EMOTION_PATTERN.match(raw_text.strip())
        if match:
            parsed = match.group(1).lower()
            if parsed in AVATAR_EMOTIONS:
                emotion_str = parsed

        # Versuch 1: Lokal (pygame verfügbar)
        result = self._avatar_local(emotion_str)
        if result:
            return result

        # Versuch 2: Via TowerAgent
        result = self._avatar_tower(emotion_str)
        if result:
            return result

        return CommandResult(
            command="avatar",
            success=False,
            text="Avatar nicht verfügbar: weder lokal noch via Tower möglich.",
        )

    def _avatar_local(self, emotion_str: str) -> CommandResult | None:
        """Avatar lokal rendern. None wenn kein Renderer."""
        if not self._avatar_renderer:
            return None

        from elder_berry.character.base import Emotion
        try:
            emotion = Emotion(emotion_str)
        except ValueError:
            emotion = Emotion.NEUTRAL

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
        except NotImplementedError as e:
            logger.error("Lokales Avatar-Rendering fehlgeschlagen: %s", e)
            return CommandResult(
                command="avatar",
                success=False,
                text="Avatar Datei-Rendering ist lokal nicht implementiert.",
            )
        except Exception as e:
            logger.error("Lokales Avatar-Rendering fehlgeschlagen: %s", e)
            return CommandResult(
                command="avatar",
                success=False,
                text=f"Avatar-Rendering fehlgeschlagen: {e}",
            )

    def _avatar_tower(self, emotion_str: str) -> CommandResult | None:
        """Avatar via TowerAgent rendern. None wenn nicht verfügbar."""
        if not self._tower_agent:
            return None

        try:
            import httpx
            r = httpx.get(
                f"http://{self._tower_agent.host}/avatar",
                params={"emotion": emotion_str},
                timeout=10.0,
            )
            r.raise_for_status()
            png_bytes = r.content

            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="avatar_tower_", delete=False,
            )
            tmp_path = Path(tmp.name)
            tmp.write(png_bytes)
            tmp.close()

            logger.info("Avatar via TowerAgent: %s, %d bytes", emotion_str, len(png_bytes))
            return CommandResult(
                command="avatar",
                success=True,
                text=f"Saleria ({emotion_str}) (via Tower)",
                image_path=tmp_path,
            )
        except Exception as e:
            logger.error("Tower-Avatar fehlgeschlagen: %s", e)
            return None

    @staticmethod
    def _cmd_restart() -> CommandResult:
        """Signalisiert der Bridge einen Neustart."""
        return CommandResult(
            command="restart",
            success=True,
            text="Starte neu... Bis gleich! \U0001f504",
            restart=True,
        )
