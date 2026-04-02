"""Tests für PDFCommandHandler – StirlingPDFClient + Nextcloud gemockt."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.comms.commands.pdf_commands import (
    PDF_COMPRESS_PATTERN,
    PDF_EXTRACT_IMAGES_PATTERN,
    PDF_FROM_FILE_PATTERN,
    PDF_MERGE_PATTERN,
    PDF_OCR_PATTERN,
    PDF_SPLIT_PATTERN,
    PDF_TO_WORD_PATTERN,
    PDFCommandHandler,
)
from elder_berry.tools.stirling_pdf import PDFResult


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def mock_spdf() -> MagicMock:
    """Mock StirlingPDFClient."""
    return MagicMock()


@pytest.fixture()
def mock_nc() -> MagicMock:
    """Mock NextcloudFilesClient."""
    nc = MagicMock()
    nc.search.return_value = []
    return nc


@pytest.fixture()
def handler(mock_spdf: MagicMock, mock_nc: MagicMock) -> PDFCommandHandler:
    return PDFCommandHandler(stirling_pdf=mock_spdf, nextcloud_files=mock_nc)


@pytest.fixture()
def handler_no_nc(mock_spdf: MagicMock) -> PDFCommandHandler:
    return PDFCommandHandler(stirling_pdf=mock_spdf, nextcloud_files=None)


# ── Pattern-Matching ───────────────────────────────────────────────────


class TestPatterns:
    def test_merge_pattern(self) -> None:
        m = PDF_MERGE_PATTERN.match("pdf zusammenfügen A.pdf B.pdf")
        assert m is not None
        assert m.group(1) == "A.pdf B.pdf"

    def test_merge_pattern_english(self) -> None:
        m = PDF_MERGE_PATTERN.match("pdf merge report1.pdf report2.pdf")
        assert m is not None

    def test_split_pattern(self) -> None:
        m = PDF_SPLIT_PATTERN.match("pdf aufteilen Vertrag.pdf seiten 1-3")
        assert m is not None
        assert m.group(1) == "Vertrag.pdf"
        assert m.group(2) == "1-3"

    def test_compress_pattern(self) -> None:
        m = PDF_COMPRESS_PATTERN.match("pdf komprimieren Vertrag.pdf")
        assert m is not None
        assert m.group(1) == "Vertrag.pdf"
        assert m.group(2) is None

    def test_compress_pattern_with_level(self) -> None:
        m = PDF_COMPRESS_PATTERN.match("pdf komprimieren Vertrag.pdf stufe 9")
        assert m is not None
        assert m.group(1) == "Vertrag.pdf"
        assert m.group(2) == "9"

    def test_ocr_pattern(self) -> None:
        m = PDF_OCR_PATTERN.match("pdf ocr Scan.pdf")
        assert m is not None
        assert m.group(1) == "Scan.pdf"

    def test_to_word_pattern(self) -> None:
        m = PDF_TO_WORD_PATTERN.match("pdf zu word Bericht.pdf")
        assert m is not None
        assert m.group(1) == "Bericht.pdf"

    def test_to_pdf_pattern(self) -> None:
        m = PDF_FROM_FILE_PATTERN.match("zu pdf Brief.docx")
        assert m is not None
        assert m.group(1) == "Brief.docx"

    def test_extract_images_pattern(self) -> None:
        m = PDF_EXTRACT_IMAGES_PATTERN.match("pdf bilder Katalog.pdf")
        assert m is not None
        assert m.group(1) == "Katalog.pdf"

    def test_no_collision_with_cloud(self) -> None:
        """PDF-Patterns starten alle mit 'pdf ' oder 'zu pdf' — kein Overlap."""
        cloud_texts = [
            "cloud upload test.pdf",
            "cloud suche bericht",
            "cloud dateien",
        ]
        for text in cloud_texts:
            assert PDF_MERGE_PATTERN.match(text) is None
            assert PDF_COMPRESS_PATTERN.match(text) is None
            assert PDF_OCR_PATTERN.match(text) is None


# ── NC-Workflow Execution ──────────────────────────────────────────────


class _NCFile:
    """Minimal NextcloudFile-Stub für Tests."""

    def __init__(self, name: str, path: str, is_dir: bool = False) -> None:
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = 1024
        self.modified = ""


class TestExecution:
    def test_compress_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Suche → Download → Compress → Upload."""
        # NC search returns one match
        mock_nc.search.return_value = [
            _NCFile("Vertrag.pdf", "Dokumente/Vertrag.pdf"),
        ]
        # NC download returns temp file
        dl_file = tmp_path / "Vertrag.pdf"
        dl_file.write_bytes(b"%PDF content")
        mock_nc.download.return_value = dl_file
        # NC upload returns path
        mock_nc.upload.return_value = "Dokumente/Vertrag_compressed.pdf"

        # Stirling-PDF compress succeeds
        mock_spdf.compress.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "Vertrag_compressed.pdf",
            message="Komprimiert: 100 KB → 50 KB (50% kleiner).",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_compress", "pdf komprimieren Vertrag.pdf")

        assert result.success is True
        assert "Komprimiert" in result.text
        assert "Hochgeladen" in result.text
        mock_nc.search.assert_called_once_with("Vertrag.pdf")
        mock_spdf.compress.assert_called_once()

    def test_merge_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Zwei Dateien aus NC → Merge → Upload."""
        file_a = _NCFile("A.pdf", "Docs/A.pdf")
        file_b = _NCFile("B.pdf", "Docs/B.pdf")

        def search_side_effect(name):
            if "A.pdf" in name:
                return [file_a]
            if "B.pdf" in name:
                return [file_b]
            return []

        mock_nc.search.side_effect = search_side_effect

        dl_a = tmp_path / "A.pdf"
        dl_b = tmp_path / "B.pdf"
        dl_a.write_bytes(b"%PDF A")
        dl_b.write_bytes(b"%PDF B")

        def download_side_effect(path, local_dir=None):
            if "A.pdf" in path:
                return dl_a
            return dl_b

        mock_nc.download.side_effect = download_side_effect
        mock_nc.upload.return_value = "Docs/merged_20260402.pdf"

        mock_spdf.merge.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "merged.pdf",
            message="2 PDFs zusammengefügt.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute(
                "pdf_merge", "pdf zusammenfügen A.pdf B.pdf",
            )

        assert result.success is True
        assert "zusammengefügt" in result.text
        assert mock_nc.search.call_count == 2

    def test_ocr_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        """NC Download → OCR → Upload."""
        mock_nc.search.return_value = [
            _NCFile("Scan.pdf", "Scans/Scan.pdf"),
        ]
        dl_file = tmp_path / "Scan.pdf"
        dl_file.write_bytes(b"%PDF scan")
        mock_nc.download.return_value = dl_file
        mock_nc.upload.return_value = "Scans/Scan_ocr.pdf"

        mock_spdf.ocr.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "Scan_ocr.pdf",
            message="OCR abgeschlossen (Sprachen: deu+eng).",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_ocr", "pdf ocr Scan.pdf")

        assert result.success is True
        assert "OCR" in result.text
        assert "Hochgeladen" in result.text

    def test_file_not_found_in_nc(
        self,
        handler: PDFCommandHandler,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Keine Treffer → Fehlermeldung."""
        mock_nc.search.return_value = []

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute(
                "pdf_compress", "pdf komprimieren Geheim.pdf",
            )

        assert result.success is False
        assert "nicht gefunden" in result.text.lower() or "keine" in result.text.lower()

    def test_multiple_matches_in_nc(
        self,
        handler: PDFCommandHandler,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Mehrere Treffer → Liste."""
        mock_nc.search.return_value = [
            _NCFile("Vertrag.pdf", "Docs/Vertrag.pdf"),
            _NCFile("Vertrag_alt.pdf", "Archiv/Vertrag_alt.pdf"),
        ]

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute(
                "pdf_compress", "pdf komprimieren Vertrag",
            )

        assert result.success is False
        assert "Mehrere" in result.text

    def test_no_stirling(self) -> None:
        """Client fehlt → Fehlermeldung."""
        h = PDFCommandHandler(stirling_pdf=None, nextcloud_files=None)
        result = h.execute("pdf_compress", "pdf komprimieren test.pdf")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    def test_no_nextcloud_local_path(
        self,
        handler_no_nc: PDFCommandHandler,
        mock_spdf: MagicMock,
        tmp_path: Path,
    ) -> None:
        """NC fehlt, lokaler Pfad funktioniert."""
        local_pdf = tmp_path / "local.pdf"
        local_pdf.write_bytes(b"%PDF local content")

        compressed = tmp_path / "local_compressed.pdf"
        compressed.write_bytes(b"%PDF compressed")

        mock_spdf.compress.return_value = PDFResult(
            success=True,
            output_path=compressed,
            message="Komprimiert.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute(
                "pdf_compress", f"pdf komprimieren {local_pdf}",
            )

        assert result.success is True
        assert "Komprimiert" in result.text

    def test_commands_in_help(
        self, handler: PDFCommandHandler,
    ) -> None:
        """command_descriptions vorhanden."""
        descs = handler.command_descriptions
        assert len(descs) == 7
        texts = " ".join(descs)
        assert "zusammenfügen" in texts
        assert "komprimieren" in texts
        assert "ocr" in texts
        assert "word" in texts.lower()

    def test_local_path_fallback_windows(
        self,
        handler_no_nc: PDFCommandHandler,
        mock_spdf: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Lokaler Windows-Pfad ohne Nextcloud."""
        local_pdf = tmp_path / "test.pdf"
        local_pdf.write_bytes(b"%PDF test")

        mock_spdf.ocr.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "test_ocr.pdf",
            message="OCR abgeschlossen.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute(
                "pdf_ocr", f"pdf ocr {local_pdf}",
            )

        assert result.success is True
