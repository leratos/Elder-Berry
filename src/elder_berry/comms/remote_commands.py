"""RemoteCommandHandler – Direkte Befehle via Matrix (kein LLM nötig).

Tier-1-Features:
- status / systemstatus → SystemMonitor → formatierter Text
- screenshot / screen → mss → PNG temp-Datei
- pause / play / skip / next → Media-Keys via ActionController
- volume <0-100> → ActionController.set_volume()

Verwendung:
    handler = RemoteCommandHandler(
        system_monitor=monitor,
        controller=action_ctrl,
    )
    cmd = handler.parse_command("status")
    if cmd:
        result = handler.execute(cmd, "status")
"""
from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.actions.base import ActionController
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
SIMPLE_COMMANDS = {"status", "systemstatus", "screenshot", "screen"} | set(MEDIA_KEYS)

# Keyword-Erkennung: wenn eines dieser Wörter im Text vorkommt → Command
# Wird nur geprüft wenn kein exakter Match vorliegt
KEYWORD_MAP: dict[str, list[str]] = {
    "screenshot": ["screenshot", "bildschirmfoto", "bildschirm zeig"],
    "status": ["systemstatus", "systemzustand", "pc status", "pc-status"],
    "pause": ["pausier", "stopp musik", "musik stopp", "musik aus"],
    "play": ["musik an", "weiterspielen", "abspielen"],
    "skip": ["nächster song", "nächstes lied", "überspringen", "nächster track"],
}

# Regex für Volume-Command: "volume 50", "vol 75", "lautstärke 30"
# \b am Ende verhindert Match auf "volume 1000" → nur 1-3 Ziffern ohne Folgeziffer
VOLUME_PATTERN = re.compile(
    r"(?:volume|vol|lautstärke|lautstarke)\s+(\d{1,3})\b",
    re.IGNORECASE,
)


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


class RemoteCommandHandler:
    """Verarbeitet direkte Befehle über Matrix (kein LLM nötig).

    Alle Dependencies sind optional – fehlende Dependencies führen zu
    graceful Degradation (Fehlertext statt Crash).
    """

    def __init__(
        self,
        system_monitor: SystemMonitor | None = None,
        controller: ActionController | None = None,
    ) -> None:
        self._monitor = system_monitor
        self._controller = controller

    def parse_command(self, text: str) -> str | None:
        """Prüft ob der Text ein direkter Command ist.

        Erkennung in 3 Stufen:
        1. Exakter Match (z.B. "status", "screenshot", "pause")
        2. Volume-Pattern (z.B. "volume 50", "lautstärke 30")
        3. Keyword-Suche in natürlicher Sprache (z.B. "schick mir ein screenshot")

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

        # Stufe 3: Keyword-Suche in natürlicher Sprache
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
        if command in ("status", "systemstatus"):
            return self._cmd_status()

        if command in ("screenshot", "screen"):
            return self._cmd_screenshot()

        if command in MEDIA_KEYS:
            return self._cmd_media(command)

        if command == "volume":
            return self._cmd_volume(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

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

    def _cmd_screenshot(self) -> CommandResult:
        """Screenshot aufnehmen und als PNG speichern."""
        try:
            import mss
        except ImportError:
            return CommandResult(
                command="screenshot",
                success=False,
                text="mss nicht installiert (pip install mss).",
            )

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
