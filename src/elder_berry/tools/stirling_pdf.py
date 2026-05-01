"""StirlingPDFClient – REST-Client for Stirling-PDF API.

Supports merge, split, compress, OCR, convert (PDF↔Word), and image extraction.
Credentials are read from SecretStore:
    stirling_pdf_url, stirling_pdf_api_key
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

# ── Exceptions ─────────────────────────────────────────────────────────


class StirlingPDFError(Exception):
    """General Stirling-PDF operation error."""


class StirlingPDFConnectionError(StirlingPDFError):
    """Server unreachable or network error."""


# ── DTOs ───────────────────────────────────────────────────────────────


@dataclass
class PDFResult:
    """Ergebnis einer PDF-Operation."""

    success: bool
    output_path: Path | None = None
    output_paths: list[Path] = field(default_factory=list)
    message: str = ""
    original_name: str = ""


# ── Client ─────────────────────────────────────────────────────────────

_TIMEOUT = 120.0  # OCR und Konvertierung können dauern


class StirlingPDFClient:
    """REST-Client für die Stirling-PDF API."""

    def __init__(self, secret_store: SecretStore) -> None:
        self._base_url = (secret_store.get_or_none("stirling_pdf_url") or "").rstrip(
            "/"
        )
        self._api_key = secret_store.get_or_none("stirling_pdf_api_key") or ""

    @property
    def _has_credentials(self) -> bool:
        return bool(self._base_url and self._api_key)

    def is_available(self) -> bool:
        """Check if credentials are present and the server is reachable."""
        if not self._has_credentials:
            return False
        try:
            resp = httpx.get(
                f"{self._base_url}/api/v1/info/status",
                headers={"X-API-Key": self._api_key},
                timeout=10.0,
            )
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception as exc:
            logger.warning("Stirling-PDF availability check failed: %s", exc)
            return False

    # ── Internal helpers ───────────────────────────────────────────────

    def _call_api(
        self,
        endpoint: str,
        files: list[tuple],
        data: dict | None = None,
        output_path: Path | None = None,
    ) -> bytes:
        """Sendet Request an Stirling-PDF API, gibt Response-Bytes zurück.

        Raises:
            StirlingPDFConnectionError: Server nicht erreichbar.
            StirlingPDFError: API-Fehler (4xx/5xx).
        """
        url = f"{self._base_url}/api/v1/{endpoint}"
        headers = {"X-API-Key": self._api_key}

        try:
            response = httpx.post(
                url,
                headers=headers,
                files=files,
                data=data or {},
                timeout=_TIMEOUT,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise StirlingPDFConnectionError(
                f"Stirling-PDF nicht erreichbar: {exc}"
            ) from exc

        if response.status_code == 401:
            raise StirlingPDFError("Authentifizierung fehlgeschlagen (401)")
        if response.status_code >= 400:
            raise StirlingPDFError(
                f"API-Fehler: HTTP {response.status_code} – {response.text[:200]}"
            )

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)

        return response.content

    def _unzip_response(self, content: bytes, output_dir: Path) -> list[Path]:
        """Entpackt eine ZIP-Response in output_dir.

        Returns:
            Liste der entpackten Dateipfade.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".zip",
                delete=False,
            )
            tmp.write(content)
            tmp.close()

            paths: list[Path] = []
            with zipfile.ZipFile(tmp.name, "r") as zf:
                for name in zf.namelist():
                    # Skip directories and hidden files
                    if name.endswith("/") or name.startswith("__"):
                        continue
                    extracted = Path(zf.extract(name, output_dir))
                    paths.append(extracted)
            return paths
        finally:
            if tmp is not None:
                Path(tmp.name).unlink(missing_ok=True)

    @staticmethod
    def _read_file(path: Path) -> tuple[str, bytes, str]:
        """Liest eine Datei und gibt (filename, bytes, mime) zurück."""
        data = path.read_bytes()
        suffix = path.suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
            ".doc": "application/msword",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }
        mime = mime_map.get(suffix, "application/octet-stream")
        return path.name, data, mime

    # ── Public API ─────────────────────────────────────────────────────

    def merge(self, pdf_paths: list[Path], output_path: Path) -> PDFResult:
        """Fügt mehrere PDFs zusammen.

        Args:
            pdf_paths: Liste der PDF-Dateien (mind. 2).
            output_path: Pfad für die zusammengefügte PDF.
        """
        if len(pdf_paths) < 2:
            return PDFResult(
                success=False,
                message="Mindestens 2 PDFs zum Zusammenfügen nötig.",
            )

        files = []
        for p in pdf_paths:
            name, data, mime = self._read_file(p)
            files.append(("fileInput", (name, data, mime)))

        try:
            self._call_api(
                "general/merge-pdfs",
                files=files,
                output_path=output_path,
            )
            return PDFResult(
                success=True,
                output_path=output_path,
                message=f"{len(pdf_paths)} PDFs zusammengefügt.",
                original_name=output_path.name,
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

    def split(
        self,
        pdf_path: Path,
        pages: str,
        output_dir: Path,
    ) -> PDFResult:
        """Teilt eine PDF nach Seitenangabe.

        Args:
            pdf_path: Quell-PDF.
            pages: Seitenangabe, z.B. "1-3" oder "1,3,5".
            output_dir: Verzeichnis für die Ergebnis-PDFs.
        """
        name, data, mime = self._read_file(pdf_path)
        files = [("fileInput", (name, data, mime))]

        try:
            content = self._call_api(
                "general/split-pdf-by-pages",
                files=files,
                data={"pages": pages},
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

        # Response kann ZIP oder einzelne PDF sein
        if content[:2] == b"PK":  # ZIP magic bytes
            paths = self._unzip_response(content, output_dir)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            stem = pdf_path.stem
            single = output_dir / f"{stem}_seite_{pages}.pdf"
            single.write_bytes(content)
            paths = [single]

        return PDFResult(
            success=True,
            output_paths=paths,
            message=f"PDF aufgeteilt: {len(paths)} Datei(en).",
            original_name=pdf_path.name,
        )

    def compress(
        self,
        pdf_path: Path,
        output_path: Path,
        level: int = 5,
    ) -> PDFResult:
        """Komprimiert eine PDF.

        Args:
            pdf_path: Quell-PDF.
            output_path: Pfad für die komprimierte PDF.
            level: Komprimierungsstufe 1-9 (Standard: 5).
        """
        name, data, mime = self._read_file(pdf_path)
        files = [("fileInput", (name, data, mime))]

        try:
            self._call_api(
                "misc/compress-pdf",
                files=files,
                data={"optimizeLevel": str(level)},
                output_path=output_path,
            )
            original_size = pdf_path.stat().st_size
            compressed_size = output_path.stat().st_size
            ratio = (1 - compressed_size / original_size) * 100 if original_size else 0
            return PDFResult(
                success=True,
                output_path=output_path,
                message=(
                    f"Komprimiert: {original_size / 1024:.0f} KB → "
                    f"{compressed_size / 1024:.0f} KB ({ratio:.0f}% kleiner)."
                ),
                original_name=pdf_path.name,
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

    def ocr(
        self,
        pdf_path: Path,
        output_path: Path,
        languages: str = "deu+eng",
    ) -> PDFResult:
        """Führt OCR auf einer PDF aus.

        Args:
            pdf_path: Quell-PDF.
            output_path: Pfad für die OCR-PDF.
            languages: Sprachen, z.B. "deu+eng".
        """
        name, data, mime = self._read_file(pdf_path)
        files = [("fileInput", (name, data, mime))]

        try:
            self._call_api(
                "misc/ocr-pdf",
                files=files,
                data={"ocrType": "force-ocr", "languages": languages},
                output_path=output_path,
            )
            return PDFResult(
                success=True,
                output_path=output_path,
                message=f"OCR abgeschlossen (Sprachen: {languages}).",
                original_name=pdf_path.name,
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

    def to_word(self, pdf_path: Path, output_path: Path) -> PDFResult:
        """Konvertiert PDF → DOCX.

        Args:
            pdf_path: Quell-PDF.
            output_path: Pfad für die DOCX-Datei.
        """
        name, data, mime = self._read_file(pdf_path)
        files = [("fileInput", (name, data, mime))]

        try:
            self._call_api(
                "convert/pdf-to-word",
                files=files,
                data={"outputFormat": "docx"},
                output_path=output_path,
            )
            return PDFResult(
                success=True,
                output_path=output_path,
                message="PDF → Word konvertiert.",
                original_name=pdf_path.name,
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

    def to_pdf(self, file_path: Path, output_path: Path) -> PDFResult:
        """Konvertiert DOCX/Bild → PDF.

        Args:
            file_path: Quelldatei (DOCX, PNG, JPG etc.).
            output_path: Pfad für die PDF.
        """
        name, data, mime = self._read_file(file_path)
        files = [("fileInput", (name, data, mime))]

        try:
            self._call_api(
                "convert/file-to-pdf",
                files=files,
                output_path=output_path,
            )
            return PDFResult(
                success=True,
                output_path=output_path,
                message=f"{file_path.suffix.upper()} → PDF konvertiert.",
                original_name=file_path.name,
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

    def extract_images(
        self,
        pdf_path: Path,
        output_dir: Path,
    ) -> PDFResult:
        """Extrahiert Bilder aus einer PDF.

        Args:
            pdf_path: Quell-PDF.
            output_dir: Verzeichnis für die extrahierten Bilder.
        """
        name, data, mime = self._read_file(pdf_path)
        files = [("fileInput", (name, data, mime))]

        try:
            content = self._call_api(
                "misc/extract-images",
                files=files,
            )
        except StirlingPDFError as exc:
            return PDFResult(success=False, message=str(exc))

        if content[:2] == b"PK":  # ZIP
            paths = self._unzip_response(content, output_dir)
        else:
            # Einzelnes Bild
            output_dir.mkdir(parents=True, exist_ok=True)
            single = output_dir / f"{pdf_path.stem}_image.png"
            single.write_bytes(content)
            paths = [single]

        if not paths:
            return PDFResult(
                success=True,
                message="Keine Bilder in der PDF gefunden.",
                original_name=pdf_path.name,
            )

        return PDFResult(
            success=True,
            output_paths=paths,
            message=f"{len(paths)} Bild(er) extrahiert.",
            original_name=pdf_path.name,
        )
