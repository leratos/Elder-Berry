"""DocumentReader – Text aus PDF- und TXT-Dateien extrahieren.

Liest Dokumente und liefert den extrahierten Text für LLM-Zusammenfassungen.
Kein OCR – gescannte PDFs ohne eingebetteten Text werden erkannt und gemeldet.

Dependency: pymupdf (pip install pymupdf, import fitz)
Optional-Group: [documents] in pyproject.toml

Verwendung:
    reader = DocumentReader()
    text = reader.read_file(Path("C:/Users/docs/report.pdf"))
    if text:
        # An LLM zur Zusammenfassung übergeben
        pass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Unterstützte Dateiformate (lowercase Extensions)
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".txt"})

# Standard-Maximum: ~100k Zeichen (damit LLM-Kontext nicht überlaufen wird)
DEFAULT_MAX_CHARS = 100_000


@dataclass(frozen=True)
class DocumentResult:
    """Ergebnis einer Dokument-Extraktion."""

    text: str
    """Extrahierter Text (ggf. gekürzt)."""

    pages: int
    """Anzahl Seiten (bei TXT: 1)."""

    truncated: bool
    """True wenn Text gekürzt wurde (max_chars überschritten)."""

    source: str
    """Dateiname (ohne Pfad)."""


class DocumentReader:
    """Liest Text aus PDF- und TXT-Dateien.

    Konfigurierbar über max_chars (Standard: 100.000 Zeichen).
    Graceful Degradation wenn pymupdf nicht installiert ist.
    """

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self._max_chars = max_chars

    @staticmethod
    def is_supported(path: Path) -> bool:
        """Prüft ob das Dateiformat unterstützt wird."""
        return path.suffix.lower() in SUPPORTED_EXTENSIONS

    def read_file(self, path: Path) -> DocumentResult:
        """Dispatcher: liest PDF oder TXT basierend auf Extension.

        Args:
            path: Absoluter Pfad zur Datei.

        Returns:
            DocumentResult mit extrahiertem Text.

        Raises:
            FileNotFoundError: Datei existiert nicht.
            ValueError: Dateiformat nicht unterstützt.
            RuntimeError: Lesefehler (z.B. pymupdf fehlt, korrupte PDF).
        """
        if not path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {path}")

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Dateiformat '{ext}' nicht unterstützt. "
                f"Erlaubt: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        if ext == ".pdf":
            return self.read_pdf(path)
        return self.read_txt(path)

    def read_pdf(self, path: Path) -> DocumentResult:
        """Extrahiert Text aus einer PDF-Datei via pymupdf.

        Args:
            path: Absoluter Pfad zur PDF-Datei.

        Returns:
            DocumentResult mit extrahiertem Text.

        Raises:
            FileNotFoundError: Datei existiert nicht.
            RuntimeError: pymupdf nicht installiert oder PDF nicht lesbar.
        """
        if not path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {path}")

        try:
            import fitz  # pymupdf
        except ImportError:
            raise RuntimeError(
                "pymupdf ist nicht installiert. Installiere es mit: pip install pymupdf"
            ) from None

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise RuntimeError(f"PDF konnte nicht geöffnet werden: {e}") from e

        try:
            pages = len(doc)
            parts: list[str] = []
            total_chars = 0

            for page_num in range(pages):
                page = doc[page_num]
                page_text = page.get_text("text")
                parts.append(page_text)
                total_chars += len(page_text)

                if total_chars >= self._max_chars:
                    break

            text = "\n".join(parts)
            truncated = len(text) > self._max_chars

            if truncated:
                text = text[: self._max_chars]

            # Prüfe ob überhaupt Text extrahiert wurde
            stripped = text.strip()
            if not stripped:
                logger.warning(
                    "PDF enthält keinen extrahierbaren Text: %s (%d Seiten)",
                    path.name,
                    pages,
                )
                return DocumentResult(
                    text="[Kein Text erkannt – möglicherweise ein gescanntes Dokument. "
                    "OCR wird in dieser Version nicht unterstützt.]",
                    pages=pages,
                    truncated=False,
                    source=path.name,
                )

            if truncated:
                text += (
                    f"\n\n[... Text nach {self._max_chars:,} Zeichen gekürzt. "
                    f"Dokument hat {pages} Seiten.]"
                )

            return DocumentResult(
                text=text,
                pages=pages,
                truncated=truncated,
                source=path.name,
            )

        finally:
            doc.close()

    def read_txt(self, path: Path) -> DocumentResult:
        """Liest eine Textdatei (UTF-8, Fallback Latin-1).

        Args:
            path: Absoluter Pfad zur Textdatei.

        Returns:
            DocumentResult mit Text.

        Raises:
            FileNotFoundError: Datei existiert nicht.
            RuntimeError: Datei nicht lesbar.
        """
        if not path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {path}")

        # UTF-8 zuerst, Fallback auf Latin-1 (nie UnicodeDecodeError)
        text: str | None = None
        for encoding in ("utf-8", "latin-1"):
            try:
                text = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                raise RuntimeError(f"Textdatei konnte nicht gelesen werden: {e}") from e

        if text is None:
            raise RuntimeError(f"Textdatei nicht dekodierbar: {path}")

        truncated = len(text) > self._max_chars
        if truncated:
            text = text[: self._max_chars] + (
                f"\n\n[... Text nach {self._max_chars:,} Zeichen gekürzt.]"
            )

        return DocumentResult(
            text=text,
            pages=1,
            truncated=truncated,
            source=path.name,
        )
