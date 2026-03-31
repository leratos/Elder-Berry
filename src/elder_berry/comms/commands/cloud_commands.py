"""CloudCommandHandler – Nextcloud file operations via Matrix commands.

Commands:
    cloud upload <pfad> [ziel]  – Upload local file to Nextcloud
    cloud download <pfad>       – Download file from Nextcloud
    cloud dateien [ordner]      – List directory contents
    cloud suche <query>         – Search files by name
    cloud inhalt <query>        – Search inside file contents (Full text search)
    cloud link <pfad>           – Create public share link
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient

logger = logging.getLogger(__name__)

# ── Patterns ────────────────────────────────────────────────────────────

CLOUD_UPLOAD_PATTERN = re.compile(
    r"^cloud\s+upload\s+([a-zA-Z]:\\[^\s]+|/[^\s]+)(?:\s+(.+))?$",
    re.IGNORECASE,
)

CLOUD_DOWNLOAD_PATTERN = re.compile(
    r"^cloud\s+download\s+(.+)$",
    re.IGNORECASE,
)

CLOUD_LIST_PATTERN = re.compile(
    r"^cloud\s+(?:dateien|ls|list)(?:\s+(.+))?$",
    re.IGNORECASE,
)

CLOUD_SEARCH_PATTERN = re.compile(
    r"^cloud\s+(?:suche|search|find)\s+(.+)$",
    re.IGNORECASE,
)

CLOUD_CONTENT_SEARCH_PATTERN = re.compile(
    r"^cloud\s+(?:inhalt|content|volltext|durchsuche)\s+(.+)$",
    re.IGNORECASE,
)

CLOUD_LINK_PATTERN = re.compile(
    r"^cloud\s+(?:link|share|teile)\s+(.+)$",
    re.IGNORECASE,
)


def _format_size(size_bytes: int) -> str:
    """Format file size as human-readable string."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


class CloudCommandHandler(CommandHandler):
    """Handler for Nextcloud cloud file commands."""

    def __init__(
        self,
        nextcloud_files: NextcloudFilesClient | None = None,
    ) -> None:
        self._nc = nextcloud_files

    # ── CommandHandler interface ────────────────────────────────────────

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (CLOUD_UPLOAD_PATTERN, "cloud_upload", True, False),
            (CLOUD_DOWNLOAD_PATTERN, "cloud_download", False, False),
            (CLOUD_LIST_PATTERN, "cloud_list", False, False),
            (CLOUD_CONTENT_SEARCH_PATTERN, "cloud_content_search", False, False),
            (CLOUD_SEARCH_PATTERN, "cloud_search", False, False),
            (CLOUD_LINK_PATTERN, "cloud_link", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "cloud upload <pfad> [ziel]: Datei zu Nextcloud hochladen",
            "cloud download <pfad>: Datei aus Nextcloud herunterladen",
            "cloud dateien [ordner]: Nextcloud-Verzeichnis auflisten",
            "cloud suche <query>: Dateien in Nextcloud suchen (Dateiname)",
            "cloud inhalt <query>: Dateiinhalte durchsuchen (Volltextsuche)",
            "cloud link <pfad>: Öffentlichen Share-Link erstellen",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "cloud_list": ["nextcloud dateien", "cloud dateien", "nextcloud ordner"],
            "cloud_search": ["nextcloud suche", "cloud suche"],
            "cloud_content_search": [
                "cloud inhalt", "cloud durchsuche", "cloud volltext",
                "nextcloud inhalt", "nextcloud durchsuche",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if self._nc is None:
            return CommandResult(
                command=command,
                success=False,
                text="Nextcloud nicht konfiguriert.",
            )

        if command == "cloud_upload":
            return self._cmd_upload(raw_text)
        if command == "cloud_download":
            return self._cmd_download(raw_text)
        if command == "cloud_list":
            return self._cmd_list(raw_text)
        if command == "cloud_content_search":
            return self._cmd_content_search(raw_text)
        if command == "cloud_search":
            return self._cmd_search(raw_text)
        if command == "cloud_link":
            return self._cmd_link(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Cloud-Command: {command}",
        )

    # ── Upload ──────────────────────────────────────────────────────────

    def _cmd_upload(self, raw_text: str) -> CommandResult:
        match = CLOUD_UPLOAD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="cloud_upload",
                success=False,
                text="Ungültiges Format. Beispiel: cloud upload C:\\Dokumente\\datei.pdf",
            )

        local_path = Path(match.group(1))
        remote_dest = match.group(2)

        if not local_path.exists():
            return CommandResult(
                command="cloud_upload",
                success=False,
                text=f"Datei nicht gefunden: {local_path}",
            )
        if not local_path.is_file():
            return CommandResult(
                command="cloud_upload",
                success=False,
                text=f"Kein reguläres File: {local_path}",
            )

        from elder_berry.tools.nextcloud_files import MAX_UPLOAD_SIZE_BYTES
        size = local_path.stat().st_size
        if size > MAX_UPLOAD_SIZE_BYTES:
            return CommandResult(
                command="cloud_upload",
                success=False,
                text=f"Datei zu groß ({size / 1024 / 1024:.1f} MB, max 100 MB).",
            )

        # Default remote path: /Saleria/<filename>
        if remote_dest:
            remote_path = remote_dest.strip()
        else:
            remote_path = f"Saleria/{local_path.name}"

        try:
            result_path = self._nc.upload(local_path, remote_path)
            return CommandResult(
                command="cloud_upload",
                success=True,
                text=f"Hochgeladen: {local_path.name} → {result_path}",
            )
        except Exception as e:
            logger.error("Cloud upload failed: %s", e)
            return CommandResult(
                command="cloud_upload",
                success=False,
                text=f"Upload fehlgeschlagen: {e}",
            )

    # ── Download ────────────────────────────────────────────────────────

    def _cmd_download(self, raw_text: str) -> CommandResult:
        match = CLOUD_DOWNLOAD_PATTERN.match(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="cloud_download",
                success=False,
                text="Ungültiges Format. Beispiel: cloud download Dokumente/report.pdf",
            )

        remote_path = match.group(1).strip()
        try:
            local_path = self._nc.download(remote_path)
            return CommandResult(
                command="cloud_download",
                success=True,
                text=f"Heruntergeladen: {remote_path} → {local_path}",
                file_path=local_path,
            )
        except Exception as e:
            logger.error("Cloud download failed: %s", e)
            return CommandResult(
                command="cloud_download",
                success=False,
                text=f"Download fehlgeschlagen: {e}",
            )

    # ── List ────────────────────────────────────────────────────────────

    def _cmd_list(self, raw_text: str) -> CommandResult:
        match = CLOUD_LIST_PATTERN.match(raw_text.strip().lower())
        folder = match.group(1).strip() if match and match.group(1) else "/"

        try:
            entries = self._nc.list_dir(folder)
        except Exception as e:
            logger.error("Cloud list failed: %s", e)
            return CommandResult(
                command="cloud_list",
                success=False,
                text=f"Verzeichnis konnte nicht gelesen werden: {e}",
            )

        if not entries:
            return CommandResult(
                command="cloud_list",
                success=True,
                text=f"Ordner '{folder}' ist leer.",
            )

        max_show = 20
        lines: list[str] = []
        for entry in entries[:max_show]:
            if entry.is_dir:
                lines.append(f"\U0001f4c1 {entry.name}/")
            else:
                lines.append(f"\U0001f4c4 {entry.name}  ({_format_size(entry.size)})")

        if len(entries) > max_show:
            lines.append(f"(und {len(entries) - max_show} weitere)")

        return CommandResult(
            command="cloud_list",
            success=True,
            text="\n".join(lines),
        )

    # ── Search ──────────────────────────────────────────────────────────

    def _cmd_search(self, raw_text: str) -> CommandResult:
        match = CLOUD_SEARCH_PATTERN.match(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="cloud_search",
                success=False,
                text="Ungültiges Format. Beispiel: cloud suche report",
            )

        query = match.group(1).strip()
        try:
            results = self._nc.search(query)
        except Exception as e:
            logger.error("Cloud search failed: %s", e)
            return CommandResult(
                command="cloud_search",
                success=False,
                text=f"Suche fehlgeschlagen: {e}",
            )

        if not results:
            return CommandResult(
                command="cloud_search",
                success=True,
                text=f"Keine Ergebnisse für '{query}'.",
            )

        max_show = 20
        lines: list[str] = []
        for entry in results[:max_show]:
            if entry.is_dir:
                lines.append(f"\U0001f4c1 {entry.path}/")
            else:
                lines.append(f"\U0001f4c4 {entry.path}  ({_format_size(entry.size)})")

        if len(results) > max_show:
            lines.append(f"(und {len(results) - max_show} weitere)")

        return CommandResult(
            command="cloud_search",
            success=True,
            text="\n".join(lines),
        )

    # ── Content Search ─────────────────────────────────────────────────

    def _cmd_content_search(self, raw_text: str) -> CommandResult:
        match = CLOUD_CONTENT_SEARCH_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="cloud_content_search",
                success=False,
                text="Ungültiges Format. Beispiel: cloud inhalt Mietvertrag",
            )

        query = match.group(1).strip()
        try:
            results = self._nc.search_content(query)
        except Exception as e:
            logger.error("Cloud content search failed: %s", e)
            return CommandResult(
                command="cloud_content_search",
                success=False,
                text=f"Inhaltssuche fehlgeschlagen: {e}",
            )

        if not results:
            return CommandResult(
                command="cloud_content_search",
                success=True,
                text=f"Keine Dateien mit Inhalt '{query}' gefunden.",
            )

        max_show = 10
        lines = [f"🔍 {len(results)} Treffer für '{query}':"]
        for entry in results[:max_show]:
            name = entry.get("name", "?")
            path = entry.get("path", "")
            excerpt = entry.get("excerpt", "")
            lines.append(f"  📄 {name}")
            if path and path != name:
                lines.append(f"     📁 {path}")
            if excerpt:
                # Excerpt kürzen auf 150 Zeichen
                short = excerpt[:150] + ("…" if len(excerpt) > 150 else "")
                lines.append(f"     ➜ {short}")

        if len(results) > max_show:
            lines.append(f"(und {len(results) - max_show} weitere)")

        return CommandResult(
            command="cloud_content_search",
            success=True,
            text="\n".join(lines),
        )

    # ── Share Link ──────────────────────────────────────────────────────

    def _cmd_link(self, raw_text: str) -> CommandResult:
        match = CLOUD_LINK_PATTERN.match(raw_text.strip().lower())
        if not match:
            return CommandResult(
                command="cloud_link",
                success=False,
                text="Ungültiges Format. Beispiel: cloud link Dokumente/report.pdf",
            )

        remote_path = match.group(1).strip()
        try:
            url = self._nc.share_link(remote_path)
            return CommandResult(
                command="cloud_link",
                success=True,
                text=f"Share-Link: {url}",
            )
        except Exception as e:
            logger.error("Cloud share link failed: %s", e)
            return CommandResult(
                command="cloud_link",
                success=False,
                text=f"Share-Link fehlgeschlagen: {e}",
            )
