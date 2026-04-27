"""PDFCommandHandler – PDF-Verarbeitung via Stirling-PDF über Matrix-Commands.

Commands:
    pdf zusammenfügen <a.pdf> <b.pdf>       – PDFs zusammenfügen
    pdf aufteilen <datei> seiten 1-3         – Seiten extrahieren
    pdf komprimieren <datei> [stufe 1-9]     – Dateigröße reduzieren
    pdf ocr <datei>                          – Text erkennen (Deutsch+Englisch)
    pdf zu word <datei>                      – PDF → Word konvertieren
    zu pdf <datei>                           – Word/Bild → PDF konvertieren
    pdf bilder <datei>                       – Bilder aus PDF extrahieren
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult, user_friendly_error
from elder_berry.core.path_guard import PathGuard

if TYPE_CHECKING:
    from elder_berry.tools.nextcloud_files import NextcloudFilesClient
    from elder_berry.tools.stirling_pdf import StirlingPDFClient

logger = logging.getLogger(__name__)

# ── Patterns ───────────────────────────────────────────────────────────

PDF_MERGE_PATTERN = re.compile(
    r"^pdf\s+(?:zusammenfügen|merge|verbinden)\s+(.+)$",
    re.IGNORECASE,
)

PDF_SPLIT_PATTERN = re.compile(
    r"^pdf\s+(?:aufteilen|split|teilen)\s+(.+?)\s+(?:seiten?|pages?)\s+(.+)$",
    re.IGNORECASE,
)

PDF_COMPRESS_PATTERN = re.compile(
    r"^pdf\s+(?:komprimieren|compress|verkleinern)\s+(.+?)"
    r"(?:\s+(?:stufe|level)\s+(\d))?$",
    re.IGNORECASE,
)

PDF_OCR_PATTERN = re.compile(
    r"^pdf\s+ocr\s+(.+)$",
    re.IGNORECASE,
)

PDF_TO_WORD_PATTERN = re.compile(
    r"^pdf\s+(?:zu|to|nach)\s+word\s+(.+)$",
    re.IGNORECASE,
)

PDF_FROM_FILE_PATTERN = re.compile(
    r"^(?:zu\s+pdf|to\s+pdf|pdf\s+(?:konvertiere?|convert))\s+(.+)$",
    re.IGNORECASE,
)

PDF_EXTRACT_IMAGES_PATTERN = re.compile(
    r"^pdf\s+(?:bilder|images?|bilder\s+extrahieren)\s+(.+)$",
    re.IGNORECASE,
)

# ── Helpers ────────────────────────────────────────────────────────────

# Erkennung lokaler Pfade (Windows oder Unix absolute Pfade)
_LOCAL_PATH_PATTERN = re.compile(r"^[a-zA-Z]:[/\\]|^/")


def _is_local_path(text: str) -> bool:
    """Prüft ob der Text ein lokaler Dateipfad ist."""
    return bool(_LOCAL_PATH_PATTERN.match(text.strip()))


def _split_filenames(text: str) -> list[str]:
    """Splittet eine Dateiliste (Leerzeichen-getrennt, respektiert Anführungszeichen)."""
    # Einfaches Splitting: Dateien durch Leerzeichen getrennt
    # Dateinamen mit Leerzeichen müssen in Anführungszeichen stehen
    parts: list[str] = []
    current = ""
    in_quotes = False
    for char in text.strip():
        if char == '"':
            in_quotes = not in_quotes
        elif char == " " and not in_quotes:
            if current:
                parts.append(current)
                current = ""
        else:
            current += char
    if current:
        parts.append(current)
    return parts


class PDFCommandHandler(CommandHandler):
    """Handler für PDF-Verarbeitungs-Commands via Stirling-PDF."""

    def __init__(
        self,
        stirling_pdf: StirlingPDFClient | None = None,
        nextcloud_files: NextcloudFilesClient | None = None,
        path_guard: PathGuard | None = None,
    ) -> None:
        self._spdf = stirling_pdf
        self._nc = nextcloud_files
        self._path_guard = path_guard or PathGuard.default()

    # ── CommandHandler interface ────────────────────────────────────────

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (PDF_MERGE_PATTERN, "pdf_merge", True, False),
            (PDF_SPLIT_PATTERN, "pdf_split", True, False),
            (PDF_COMPRESS_PATTERN, "pdf_compress", True, False),
            (PDF_OCR_PATTERN, "pdf_ocr", True, False),
            (PDF_TO_WORD_PATTERN, "pdf_to_word", True, False),
            (PDF_FROM_FILE_PATTERN, "pdf_from_file", True, False),
            (PDF_EXTRACT_IMAGES_PATTERN, "pdf_extract_images", True, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "pdf zusammenfügen <a.pdf> <b.pdf>: PDFs zusammenfügen",
            "pdf aufteilen <datei> seiten 1-3: Seiten extrahieren",
            "pdf komprimieren <datei> [stufe 1-9]: Dateigröße reduzieren",
            "pdf ocr <datei>: Text erkennen (Deutsch+Englisch)",
            "pdf zu word <datei>: PDF → Word konvertieren",
            "zu pdf <datei>: Word/Bild → PDF konvertieren",
            "pdf bilder <datei>: Bilder aus PDF extrahieren",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "pdf_compress": ["pdf komprimieren", "pdf verkleinern"],
            "pdf_merge": ["pdf zusammenfügen", "pdf verbinden", "pdf merge"],
            "pdf_split": ["pdf aufteilen", "pdf teilen", "pdf split"],
            "pdf_ocr": ["pdf ocr", "text erkennen"],
            "pdf_to_word": ["pdf zu word", "pdf to word", "pdf nach word"],
            "pdf_from_file": ["zu pdf", "to pdf", "pdf konvertieren"],
            "pdf_extract_images": ["pdf bilder", "bilder extrahieren"],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if self._spdf is None:
            return self.not_configured(
                command, "PDF-Verarbeitung (Stirling-PDF)", setup_step=7,
            )

        if command == "pdf_merge":
            return self._cmd_merge(raw_text)
        if command == "pdf_split":
            return self._cmd_split(raw_text)
        if command == "pdf_compress":
            return self._cmd_compress(raw_text)
        if command == "pdf_ocr":
            return self._cmd_ocr(raw_text)
        if command == "pdf_to_word":
            return self._cmd_to_word(raw_text)
        if command == "pdf_from_file":
            return self._cmd_from_file(raw_text)
        if command == "pdf_extract_images":
            return self._cmd_extract_images(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter PDF-Command: {command}",
        )

    # ── NC-Helfer ──────────────────────────────────────────────────────

    def _resolve_nc_file(
        self, name: str, temp_dir: Path,
    ) -> tuple[Path | None, str, str]:
        """Sucht Datei in Nextcloud, lädt sie herunter.

        Returns:
            (local_path, remote_path, error_message)
            Bei Fehler: (None, "", error_message)
        """
        if self._nc is None:
            return None, "", "⚠ Nextcloud nicht konfiguriert. Einrichten unter http://localhost:8090/setup (Schritt 4)"

        try:
            results = self._nc.search(name)
        except Exception as exc:
            logger.error("NC search failed: %s", exc)
            return None, "", user_friendly_error(exc, "Nextcloud-Suche")

        # Alle Dateien (nicht nur PDFs) — für to_pdf brauchen wir auch DOCX etc.
        matches = [f for f in results if not f.is_dir]
        if len(matches) == 0:
            return None, "", f"Keine Datei '{name}' in Nextcloud gefunden."
        if len(matches) > 1:
            listing = "\n".join(
                f"  \U0001f4c4 {f.path}" for f in matches[:5]
            )
            return (
                None, "",
                f"Mehrere Treffer:\n{listing}\nBitte genauer angeben.",
            )

        remote_path = matches[0].path
        try:
            local_path = self._nc.download(remote_path, local_dir=temp_dir)
        except Exception as exc:
            logger.error("NC download failed: %s", exc)
            return None, "", f"Download fehlgeschlagen: {exc}"

        return local_path, remote_path, ""

    def _upload_nc_result(
        self, local_path: Path, remote_dir: str,
    ) -> str:
        """Lädt Ergebnis-Datei nach Nextcloud hoch.

        Returns:
            Remote-Pfad oder Fehlermeldung.
        """
        if self._nc is None:
            return f"(lokal: {local_path})"

        target = f"{remote_dir.rstrip('/')}/{local_path.name}"
        try:
            result_path = self._nc.upload(local_path, target)
            return result_path
        except Exception as exc:
            logger.error("NC upload failed: %s", exc)
            return f"Upload fehlgeschlagen: {exc}"

    def _get_remote_dir(self, remote_path: str) -> str:
        """Extrahiert das Verzeichnis aus einem Remote-Pfad."""
        parts = remote_path.rsplit("/", 1)
        return parts[0] if len(parts) > 1 else ""

    def _resolve_file(
        self, name: str, temp_dir: Path,
    ) -> tuple[Path | None, str, str]:
        """Löst Dateiname auf: lokaler Pfad oder Nextcloud-Suche.

        Returns:
            (local_path, remote_path, error_message)
        """
        name = name.strip()
        if _is_local_path(name):
            # Path-Traversal-Schutz (Phase 69): Pfad muss in einem
            # erlaubten Basis-Verzeichnis liegen. PermissionError -> Abbruch
            # ohne Pfad-Echo. FileNotFoundError -> "Datei nicht gefunden".
            try:
                local = self._path_guard.validate(name)
            except PermissionError:
                return None, "", (
                    "Zugriff verweigert. Datei liegt ausserhalb "
                    "erlaubter Verzeichnisse (z.B. Documents, Downloads)."
                )
            except FileNotFoundError:
                return None, "", "Datei nicht gefunden."
            return local, "", ""

        # Nextcloud-Suche
        return self._resolve_nc_file(name, temp_dir)

    # ── Commands ───────────────────────────────────────────────────────

    def _cmd_merge(self, raw_text: str) -> CommandResult:
        match = PDF_MERGE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_merge",
                success=False,
                text="Format: pdf zusammenfügen <datei1> <datei2> [datei3...]",
            )

        filenames = _split_filenames(match.group(1))
        if len(filenames) < 2:
            return CommandResult(
                command="pdf_merge",
                success=False,
                text="Mindestens 2 Dateien zum Zusammenfügen nötig.",
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local_paths: list[Path] = []
            remote_dir = ""
            for fname in filenames:
                local, rpath, err = self._resolve_file(fname, temp_dir)
                if local is None:
                    return CommandResult(
                        command="pdf_merge", success=False, text=err,
                    )
                local_paths.append(local)
                if rpath and not remote_dir:
                    remote_dir = self._get_remote_dir(rpath)

            import time
            ts = time.strftime("%Y%m%d_%H%M%S")
            output = temp_dir / f"merged_{ts}.pdf"
            result = self._spdf.merge(local_paths, output)
            if not result.success:
                return CommandResult(
                    command="pdf_merge", success=False, text=result.message,
                )

            # Upload
            if self._nc and remote_dir:
                nc_path = self._upload_nc_result(output, remote_dir)
                return CommandResult(
                    command="pdf_merge",
                    success=True,
                    text=f"{result.message}\nHochgeladen: {nc_path}",
                )

            return CommandResult(
                command="pdf_merge",
                success=True,
                text=f"{result.message}\nErgebnis: {output}",
                file_path=output,
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _cmd_split(self, raw_text: str) -> CommandResult:
        match = PDF_SPLIT_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_split",
                success=False,
                text="Format: pdf aufteilen <datei> seiten 1-3,5",
            )

        filename = match.group(1).strip()
        pages = match.group(2).strip()

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local, remote_path, err = self._resolve_file(filename, temp_dir)
            if local is None:
                return CommandResult(
                    command="pdf_split", success=False, text=err,
                )

            output_dir = temp_dir / "split"
            result = self._spdf.split(local, pages, output_dir)
            if not result.success:
                return CommandResult(
                    command="pdf_split", success=False, text=result.message,
                )

            # Upload
            remote_dir = self._get_remote_dir(remote_path) if remote_path else ""
            if self._nc and remote_dir:
                uploaded: list[str] = []
                for p in result.output_paths:
                    nc_path = self._upload_nc_result(p, remote_dir)
                    uploaded.append(nc_path)
                return CommandResult(
                    command="pdf_split",
                    success=True,
                    text=f"{result.message}\nHochgeladen:\n"
                         + "\n".join(f"  \U0001f4c4 {u}" for u in uploaded),
                )

            return CommandResult(
                command="pdf_split",
                success=True,
                text=result.message,
                file_paths=list(result.output_paths),
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _cmd_compress(self, raw_text: str) -> CommandResult:
        match = PDF_COMPRESS_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_compress",
                success=False,
                text="Format: pdf komprimieren <datei> [stufe 1-9]",
            )

        filename = match.group(1).strip()
        level = int(match.group(2)) if match.group(2) else 5

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local, remote_path, err = self._resolve_file(filename, temp_dir)
            if local is None:
                return CommandResult(
                    command="pdf_compress", success=False, text=err,
                )

            stem = local.stem
            output = temp_dir / f"{stem}_compressed.pdf"
            result = self._spdf.compress(local, output, level=level)
            if not result.success:
                return CommandResult(
                    command="pdf_compress", success=False, text=result.message,
                )

            # Upload
            remote_dir = self._get_remote_dir(remote_path) if remote_path else ""
            if self._nc and remote_dir:
                nc_path = self._upload_nc_result(output, remote_dir)
                return CommandResult(
                    command="pdf_compress",
                    success=True,
                    text=f"{result.message}\nHochgeladen: {nc_path}",
                )

            return CommandResult(
                command="pdf_compress",
                success=True,
                text=result.message,
                file_path=output,
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _cmd_ocr(self, raw_text: str) -> CommandResult:
        match = PDF_OCR_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_ocr",
                success=False,
                text="Format: pdf ocr <datei>",
            )

        filename = match.group(1).strip()

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local, remote_path, err = self._resolve_file(filename, temp_dir)
            if local is None:
                return CommandResult(
                    command="pdf_ocr", success=False, text=err,
                )

            stem = local.stem
            output = temp_dir / f"{stem}_ocr.pdf"
            result = self._spdf.ocr(local, output)
            if not result.success:
                return CommandResult(
                    command="pdf_ocr", success=False, text=result.message,
                )

            remote_dir = self._get_remote_dir(remote_path) if remote_path else ""
            if self._nc and remote_dir:
                nc_path = self._upload_nc_result(output, remote_dir)
                return CommandResult(
                    command="pdf_ocr",
                    success=True,
                    text=f"{result.message}\nHochgeladen: {nc_path}",
                )

            return CommandResult(
                command="pdf_ocr",
                success=True,
                text=result.message,
                file_path=output,
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _cmd_to_word(self, raw_text: str) -> CommandResult:
        match = PDF_TO_WORD_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_to_word",
                success=False,
                text="Format: pdf zu word <datei>",
            )

        filename = match.group(1).strip()

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local, remote_path, err = self._resolve_file(filename, temp_dir)
            if local is None:
                return CommandResult(
                    command="pdf_to_word", success=False, text=err,
                )

            stem = local.stem
            output = temp_dir / f"{stem}.docx"
            result = self._spdf.to_word(local, output)
            if not result.success:
                return CommandResult(
                    command="pdf_to_word", success=False, text=result.message,
                )

            remote_dir = self._get_remote_dir(remote_path) if remote_path else ""
            if self._nc and remote_dir:
                nc_path = self._upload_nc_result(output, remote_dir)
                return CommandResult(
                    command="pdf_to_word",
                    success=True,
                    text=f"{result.message}\nHochgeladen: {nc_path}",
                )

            return CommandResult(
                command="pdf_to_word",
                success=True,
                text=result.message,
                file_path=output,
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _cmd_from_file(self, raw_text: str) -> CommandResult:
        match = PDF_FROM_FILE_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_from_file",
                success=False,
                text="Format: zu pdf <datei>",
            )

        filename = match.group(1).strip()

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local, remote_path, err = self._resolve_file(filename, temp_dir)
            if local is None:
                return CommandResult(
                    command="pdf_from_file", success=False, text=err,
                )

            stem = local.stem
            output = temp_dir / f"{stem}.pdf"
            result = self._spdf.to_pdf(local, output)
            if not result.success:
                return CommandResult(
                    command="pdf_from_file", success=False, text=result.message,
                )

            remote_dir = self._get_remote_dir(remote_path) if remote_path else ""
            if self._nc and remote_dir:
                nc_path = self._upload_nc_result(output, remote_dir)
                return CommandResult(
                    command="pdf_from_file",
                    success=True,
                    text=f"{result.message}\nHochgeladen: {nc_path}",
                )

            return CommandResult(
                command="pdf_from_file",
                success=True,
                text=result.message,
                file_path=output,
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _cmd_extract_images(self, raw_text: str) -> CommandResult:
        match = PDF_EXTRACT_IMAGES_PATTERN.match(raw_text.strip())
        if not match:
            return CommandResult(
                command="pdf_extract_images",
                success=False,
                text="Format: pdf bilder <datei>",
            )

        filename = match.group(1).strip()

        temp_dir = Path(tempfile.mkdtemp(prefix="eb_pdf_"))
        try:
            local, remote_path, err = self._resolve_file(filename, temp_dir)
            if local is None:
                return CommandResult(
                    command="pdf_extract_images", success=False, text=err,
                )

            output_dir = temp_dir / "images"
            result = self._spdf.extract_images(local, output_dir)
            if not result.success:
                return CommandResult(
                    command="pdf_extract_images",
                    success=False,
                    text=result.message,
                )

            remote_dir = self._get_remote_dir(remote_path) if remote_path else ""
            if self._nc and remote_dir and result.output_paths:
                uploaded: list[str] = []
                for p in result.output_paths:
                    nc_path = self._upload_nc_result(p, remote_dir)
                    uploaded.append(nc_path)
                return CommandResult(
                    command="pdf_extract_images",
                    success=True,
                    text=f"{result.message}\nHochgeladen:\n"
                         + "\n".join(f"  \U0001f5bc {u}" for u in uploaded),
                )

            return CommandResult(
                command="pdf_extract_images",
                success=True,
                text=result.message,
                file_paths=list(result.output_paths),
            )
        finally:
            if self._nc:
                shutil.rmtree(temp_dir, ignore_errors=True)
