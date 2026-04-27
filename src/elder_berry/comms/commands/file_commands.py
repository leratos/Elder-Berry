"""FileCommandHandler -- Clipboard, Send-File und Download-Commands.

Extrahiert aus remote_commands.py (Refactoring).
"""
from __future__ import annotations

import ipaddress
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from elder_berry.comms.commands.base import CommandHandler, CommandResult, user_friendly_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

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

# Regex für Download: "download https://..."
DOWNLOAD_PATTERN = re.compile(
    r"^download\s+(https?://\S+)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Standard-Erlaubte Wurzelverzeichnisse für send_file.
# None oder leeres Tuple = keine Einschränkung (nicht empfohlen).
# Konfigurierbar über FileCommandHandler.__init__.
_DEFAULT_SEND_FILE_ROOTS: tuple[Path, ...] = (
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Pictures",
)

# SSRF-Schutz: private / loopback / link-local Adressen ablehnen.
_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _is_safe_download_url(url: str) -> bool:
    """Lehnt private/loopback-Hosts ab (SSRF-Schutz fuer Downloads).

    DOWNLOAD_PATTERN erzwingt bereits https?://, daher wird hier nur
    der Hostname gegen interne Adressbereiche geprueft.
    """
    host = urlparse(url).hostname or ""
    if not host:
        return False
    # Pruefe zuerst, ob es ein IP-Literal ist; dann ablehnen wenn privat.
    # Falls kein IP-Literal (ValueError), ist es ein DNS-Name -- erlaubt.
    is_ip = False
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False

    if is_ip:
        addr = ipaddress.ip_address(host)
        return not any(addr in net for net in _PRIVATE_NETS)
    # DNS-Name: DNS-Aufloesung liegt ausserhalb unserer Kontrolle hier.
    return True


class FileCommandHandler(CommandHandler):
    """Handler für Clipboard-, Send-File- und Download-Commands."""

    def __init__(
        self,
        download_dir: Path | None = None,
        send_file_allowed_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self._download_dir = download_dir or Path.home() / "Downloads"
        self._send_file_allowed_roots: tuple[Path, ...] = tuple(
            r.resolve()
            for r in (
                send_file_allowed_roots
                if send_file_allowed_roots is not None
                else _DEFAULT_SEND_FILE_ROOTS
            )
        )

    # ------------------------------------------------------------------
    # CommandHandler interface
    # ------------------------------------------------------------------

    @property
    def simple_commands(self) -> set[str]:
        return {"clipboard"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (CLIP_WRITE_PATTERN, "clip_write", False, False),
            (SEND_FILE_PATTERN, "send_file", True, True),
            (DOWNLOAD_PATTERN, "download", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "clipboard: Zwischenablage lesen",
            "clip: <text>: Text in Zwischenablage schreiben",
            "schick mir <pfad>: Datei senden (max 50 MB)",
            "download <url>: Datei herunterladen",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "clipboard": [
                "zwischenablage", "clipboard lesen",
                "was ist im clipboard", "was hab ich kopiert",
                "zeig zwischenablage", "was ist kopiert",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        """Führt einen erkannten Command aus."""
        if command == "clipboard":
            return self._cmd_clipboard_read()
        if command == "clip_write":
            return self._cmd_clipboard_write(raw_text)
        if command == "send_file":
            return self._cmd_send_file(raw_text)
        if command == "download":
            return self._cmd_download(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter File-Command: {command}",
        )

    # ------------------------------------------------------------------
    # Clipboard
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
                text=user_friendly_error(e, "Clipboard lesen"),
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
                text=user_friendly_error(e, "Clipboard schreiben"),
            )

    # ------------------------------------------------------------------
    # Send File
    # ------------------------------------------------------------------

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
                text=user_friendly_error(e, "Datei"),
            )

        # Pfad gegen erlaubte Wurzelverzeichnisse prüfen (Roots bereits beim Init aufgelöst)
        if self._send_file_allowed_roots:
            allowed = any(
                file_path.is_relative_to(root)
                for root in self._send_file_allowed_roots
            )
            if not allowed:
                allowed_str = ", ".join(str(r) for r in self._send_file_allowed_roots)
                return CommandResult(
                    command="send_file",
                    success=False,
                    text=(
                        f"Zugriff verweigert: '{file_path}' liegt nicht in einem "
                        f"erlaubten Verzeichnis.\nErlaubt: {allowed_str}"
                    ),
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

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

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

        # SSRF-Schutz: private / loopback Hosts ablehnen.
        if not _is_safe_download_url(url):
            return CommandResult(
                command="download",
                success=False,
                text="Download abgelehnt: interne Adressen sind nicht erlaubt.",
            )

        try:
            import httpx
        except ImportError:
            return CommandResult(
                command="download",
                success=False,
                text="httpx nicht installiert.",
            )

        # Dateiname aus URL extrahieren und gegen Path-Traversal sanitisieren.
        # Path(...).name entfernt alle Verzeichnis-Trennzeichen (z.B. "../../.bashrc"
        # → ".bashrc"), sodass der Dateiname stets nur ein einfacher Name ist.
        from urllib.parse import unquote
        parsed = urlparse(url)
        raw_name = unquote(parsed.path.split("/")[-1])
        filename = Path(raw_name).name or "download"

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
                text=user_friendly_error(e, "Download"),
            )
        except Exception as e:
            logger.error("Download fehlgeschlagen: %s", e)
            target.unlink(missing_ok=True)
            return CommandResult(
                command="download",
                success=False,
                text=user_friendly_error(e, "Download"),
            )
