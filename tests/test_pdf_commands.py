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
                "pdf_merge",
                "pdf zusammenfügen A.pdf B.pdf",
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
                "pdf_compress",
                "pdf komprimieren Geheim.pdf",
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
                "pdf_compress",
                "pdf komprimieren Vertrag",
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
                "pdf_compress",
                f"pdf komprimieren {local_pdf}",
            )

        assert result.success is True
        assert "Komprimiert" in result.text

    def test_commands_in_help(
        self,
        handler: PDFCommandHandler,
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
                "pdf_ocr",
                f"pdf ocr {local_pdf}",
            )

        assert result.success is True


# ── Additional coverage: helper functions, error paths, all commands ───


class TestHelperFunctions:
    def test_is_local_path_unix(self) -> None:
        from elder_berry.comms.commands.pdf_commands import _is_local_path

        assert _is_local_path("/home/user/test.pdf") is True

    def test_is_local_path_windows(self) -> None:
        from elder_berry.comms.commands.pdf_commands import _is_local_path

        assert _is_local_path("C:/Users/test.pdf") is True

    def test_is_local_path_nc_name(self) -> None:
        from elder_berry.comms.commands.pdf_commands import _is_local_path

        assert _is_local_path("report.pdf") is False

    def test_split_filenames_simple(self) -> None:
        from elder_berry.comms.commands.pdf_commands import _split_filenames

        assert _split_filenames("a.pdf b.pdf") == ["a.pdf", "b.pdf"]

    def test_split_filenames_quoted(self) -> None:
        from elder_berry.comms.commands.pdf_commands import _split_filenames

        assert _split_filenames('"my file.pdf" other.pdf') == [
            "my file.pdf",
            "other.pdf",
        ]

    def test_split_filenames_single(self) -> None:
        from elder_berry.comms.commands.pdf_commands import _split_filenames

        assert _split_filenames("only.pdf") == ["only.pdf"]


class TestResolveNcFile:
    """Tests für _resolve_nc_file Hilfsmethode."""

    def test_nc_none_returns_error(self, tmp_path: Path) -> None:
        h = PDFCommandHandler(stirling_pdf=MagicMock(), nextcloud_files=None)
        local, remote, err = h._resolve_nc_file("test.pdf", tmp_path)
        assert local is None
        assert "nicht konfiguriert" in err

    def test_nc_search_exception(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.side_effect = RuntimeError("Verbindung fehlgeschlagen")
        local, remote, err = handler._resolve_nc_file("test.pdf", tmp_path)
        assert local is None
        assert "fehlgeschlagen" in err

    def test_nc_download_exception(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.return_value = [_NCFile("test.pdf", "Docs/test.pdf")]
        mock_nc.download.side_effect = RuntimeError("Download-Fehler")
        local, remote, err = handler._resolve_nc_file("test.pdf", tmp_path)
        assert local is None
        assert "Download fehlgeschlagen" in err


class TestUploadNcResult:
    """Tests für _upload_nc_result."""

    def test_nc_none_returns_local_path(
        self, handler_no_nc: PDFCommandHandler, tmp_path: Path
    ) -> None:
        f = tmp_path / "result.pdf"
        f.write_bytes(b"content")
        result = handler_no_nc._upload_nc_result(f, "Docs")
        assert str(f) in result

    def test_upload_exception(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.upload.side_effect = RuntimeError("Upload-Fehler")
        f = tmp_path / "result.pdf"
        f.write_bytes(b"content")
        msg = handler._upload_nc_result(f, "Docs")
        assert "fehlgeschlagen" in msg


class TestUnknownCommand:
    def test_unknown_command_returns_failure(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_nonexistent", "pdf nonexistent test")
        assert result.success is False
        assert "Unbekannter" in result.text


class TestLocalPathNotFound:
    def test_local_path_missing(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute(
                "pdf_compress", "pdf komprimieren /nonexistent/path/file.pdf"
            )
        assert result.success is False
        assert "nicht gefunden" in result.text


# ── Merge error paths ──────────────────────────────────────────────────


class TestMergeErrors:
    def test_merge_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_merge", "pdf zusammenfügen")
        assert result.success is False
        assert "Format" in result.text

    def test_merge_only_one_file(
        self, handler: PDFCommandHandler, tmp_path: Path
    ) -> None:
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_merge", "pdf zusammenfügen single.pdf")
        assert result.success is False
        assert "Mindestens" in result.text

    def test_merge_first_file_not_found(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.return_value = []
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute(
                "pdf_merge", "pdf zusammenfügen missing_a.pdf missing_b.pdf"
            )
        assert result.success is False

    def test_merge_spdf_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        dl_a = tmp_path / "A.pdf"
        dl_b = tmp_path / "B.pdf"
        dl_a.write_bytes(b"%PDF")
        dl_b.write_bytes(b"%PDF")

        def search_side(name):
            if "A.pdf" in name:
                return [_NCFile("A.pdf", "Docs/A.pdf")]
            return [_NCFile("B.pdf", "Docs/B.pdf")]

        def dl_side(path, local_dir=None):
            if "A.pdf" in path:
                return dl_a
            return dl_b

        mock_nc.search.side_effect = search_side
        mock_nc.download.side_effect = dl_side
        mock_spdf.merge.return_value = PDFResult(
            success=False, message="Stirling fehlgeschlagen."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_merge", "pdf zusammenfügen A.pdf B.pdf")
        assert result.success is False
        assert "Stirling" in result.text

    def test_merge_local_files_no_nc_upload(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        local_a = tmp_path / "A.pdf"
        local_b = tmp_path / "B.pdf"
        local_a.write_bytes(b"%PDF A")
        local_b.write_bytes(b"%PDF B")

        mock_spdf.merge.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "merged.pdf",
            message="Zusammengefügt.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute(
                "pdf_merge", f"pdf zusammenfügen {local_a} {local_b}"
            )
        assert result.success is True
        assert "Ergebnis" in result.text


# ── Split command ───────────────────────────────────────────────────────


class TestSplitCommand:
    def test_split_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_split", "pdf aufteilen")
        assert result.success is False
        assert "Format" in result.text

    def test_split_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Doc.pdf", "Docs/Doc.pdf")]
        dl_file = tmp_path / "Doc.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_nc.upload.return_value = "Docs/Doc_p1.pdf"

        split_out = tmp_path / "split" / "Doc_p1.pdf"
        split_out.parent.mkdir(exist_ok=True)
        split_out.write_bytes(b"%PDF")

        mock_spdf.split.return_value = PDFResult(
            success=True,
            output_paths=[split_out],
            message="Aufgeteilt.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_split", "pdf aufteilen Doc.pdf seiten 1")
        assert result.success is True
        assert "Hochgeladen" in result.text

    def test_split_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Doc.pdf", "Docs/Doc.pdf")]
        dl_file = tmp_path / "Doc.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_spdf.split.return_value = PDFResult(
            success=False, message="Seiten ungültig."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_split", "pdf aufteilen Doc.pdf seiten 99")
        assert result.success is False
        assert "Seiten" in result.text

    def test_split_local_no_nc_upload(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        local_pdf = tmp_path / "local.pdf"
        local_pdf.write_bytes(b"%PDF")
        split_out = tmp_path / "local_p1.pdf"
        split_out.write_bytes(b"%PDF")

        mock_spdf.split.return_value = PDFResult(
            success=True,
            output_paths=[split_out],
            message="Aufgeteilt.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute(
                "pdf_split", f"pdf aufteilen {local_pdf} seiten 1"
            )
        assert result.success is True
        assert result.file_paths is not None

    def test_split_file_not_found(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.return_value = []
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_split", "pdf aufteilen missing.pdf seiten 1")
        assert result.success is False


# ── Compress error paths ────────────────────────────────────────────────


class TestCompressErrors:
    def test_compress_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_compress", "pdf komprimieren")
        assert result.success is False
        assert "Format" in result.text

    def test_compress_spdf_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Big.pdf", "Docs/Big.pdf")]
        dl_file = tmp_path / "Big.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_spdf.compress.return_value = PDFResult(
            success=False, message="Komprimierung fehlgeschlagen."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_compress", "pdf komprimieren Big.pdf")
        assert result.success is False


# ── OCR error paths ─────────────────────────────────────────────────────


class TestOcrErrors:
    def test_ocr_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_ocr", "pdf ocr")
        assert result.success is False
        assert "Format" in result.text

    def test_ocr_spdf_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Scan.pdf", "Scans/Scan.pdf")]
        dl_file = tmp_path / "Scan.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_spdf.ocr.return_value = PDFResult(
            success=False, message="OCR fehlgeschlagen."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_ocr", "pdf ocr Scan.pdf")
        assert result.success is False

    def test_ocr_local_no_nc(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        local_pdf = tmp_path / "scan.pdf"
        local_pdf.write_bytes(b"%PDF")
        output = tmp_path / "scan_ocr.pdf"
        output.write_bytes(b"%PDF")

        mock_spdf.ocr.return_value = PDFResult(
            success=True,
            output_path=output,
            message="OCR abgeschlossen.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute("pdf_ocr", f"pdf ocr {local_pdf}")
        assert result.success is True
        assert result.file_path is not None


# ── ToWord command ──────────────────────────────────────────────────────


class TestToWordCommand:
    def test_to_word_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_to_word", "pdf zu word")
        assert result.success is False
        assert "Format" in result.text

    def test_to_word_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Bericht.pdf", "Docs/Bericht.pdf")]
        dl_file = tmp_path / "Bericht.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_nc.upload.return_value = "Docs/Bericht.docx"

        mock_spdf.to_word.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "Bericht.docx",
            message="Konvertiert: Bericht.docx",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_to_word", "pdf zu word Bericht.pdf")
        assert result.success is True
        assert "Hochgeladen" in result.text

    def test_to_word_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Doc.pdf", "Docs/Doc.pdf")]
        dl_file = tmp_path / "Doc.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_spdf.to_word.return_value = PDFResult(
            success=False, message="Konvertierung fehlgeschlagen."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_to_word", "pdf zu word Doc.pdf")
        assert result.success is False

    def test_to_word_local_no_nc(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        local_pdf = tmp_path / "report.pdf"
        local_pdf.write_bytes(b"%PDF")

        mock_spdf.to_word.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "report.docx",
            message="Konvertiert.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute("pdf_to_word", f"pdf zu word {local_pdf}")
        assert result.success is True
        assert result.file_path is not None

    def test_to_word_file_not_found(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.return_value = []
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_to_word", "pdf zu word missing.pdf")
        assert result.success is False


# ── FromFile command ────────────────────────────────────────────────────


class TestFromFileCommand:
    def test_from_file_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_from_file", "zu pdf")
        assert result.success is False
        assert "Format" in result.text

    def test_from_file_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Brief.docx", "Docs/Brief.docx")]
        dl_file = tmp_path / "Brief.docx"
        dl_file.write_bytes(b"PK word content")
        mock_nc.download.return_value = dl_file
        mock_nc.upload.return_value = "Docs/Brief.pdf"

        mock_spdf.to_pdf.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "Brief.pdf",
            message="Konvertiert: Brief.pdf",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_from_file", "zu pdf Brief.docx")
        assert result.success is True
        assert "Hochgeladen" in result.text

    def test_from_file_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Brief.docx", "Docs/Brief.docx")]
        dl_file = tmp_path / "Brief.docx"
        dl_file.write_bytes(b"content")
        mock_nc.download.return_value = dl_file
        mock_spdf.to_pdf.return_value = PDFResult(
            success=False, message="Konvertierung fehlgeschlagen."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_from_file", "zu pdf Brief.docx")
        assert result.success is False

    def test_from_file_local_no_nc(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        local_docx = tmp_path / "letter.docx"
        local_docx.write_bytes(b"content")

        mock_spdf.to_pdf.return_value = PDFResult(
            success=True,
            output_path=tmp_path / "letter.pdf",
            message="Konvertiert.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute("pdf_from_file", f"zu pdf {local_docx}")
        assert result.success is True
        assert result.file_path is not None

    def test_from_file_not_found(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.return_value = []
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_from_file", "zu pdf missing.docx")
        assert result.success is False


# ── ExtractImages command ───────────────────────────────────────────────


class TestExtractImagesCommand:
    def test_extract_images_bad_pattern(self, handler: PDFCommandHandler) -> None:
        result = handler.execute("pdf_extract_images", "pdf bilder")
        assert result.success is False
        assert "Format" in result.text

    def test_extract_images_nc_workflow(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Katalog.pdf", "Docs/Katalog.pdf")]
        dl_file = tmp_path / "Katalog.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_nc.upload.return_value = "Docs/img1.png"

        img1 = tmp_path / "images" / "img1.png"
        img1.parent.mkdir(exist_ok=True)
        img1.write_bytes(b"PNG data")

        mock_spdf.extract_images.return_value = PDFResult(
            success=True,
            output_paths=[img1],
            message="3 Bilder extrahiert.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_extract_images", "pdf bilder Katalog.pdf")
        assert result.success is True
        assert "Hochgeladen" in result.text

    def test_extract_images_failure(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_nc.search.return_value = [_NCFile("Doc.pdf", "Docs/Doc.pdf")]
        dl_file = tmp_path / "Doc.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file
        mock_spdf.extract_images.return_value = PDFResult(
            success=False, message="Keine Bilder gefunden."
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_extract_images", "pdf bilder Doc.pdf")
        assert result.success is False

    def test_extract_images_local_no_nc(
        self, handler_no_nc: PDFCommandHandler, mock_spdf: MagicMock, tmp_path: Path
    ) -> None:
        local_pdf = tmp_path / "catalog.pdf"
        local_pdf.write_bytes(b"%PDF")

        img1 = tmp_path / "img1.png"
        img1.write_bytes(b"PNG")

        mock_spdf.extract_images.return_value = PDFResult(
            success=True,
            output_paths=[img1],
            message="1 Bild extrahiert.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler_no_nc.execute(
                "pdf_extract_images", f"pdf bilder {local_pdf}"
            )
        assert result.success is True
        assert result.file_paths is not None

    def test_extract_images_file_not_found(
        self, handler: PDFCommandHandler, mock_nc: MagicMock, tmp_path: Path
    ) -> None:
        mock_nc.search.return_value = []
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_extract_images", "pdf bilder missing.pdf")
        assert result.success is False

    def test_extract_images_nc_no_output_paths(
        self,
        handler: PDFCommandHandler,
        mock_spdf: MagicMock,
        mock_nc: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Wenn keine output_paths → kein Upload, aber success=True."""
        mock_nc.search.return_value = [_NCFile("Doc.pdf", "Docs/Doc.pdf")]
        dl_file = tmp_path / "Doc.pdf"
        dl_file.write_bytes(b"%PDF")
        mock_nc.download.return_value = dl_file

        mock_spdf.extract_images.return_value = PDFResult(
            success=True,
            output_paths=[],
            message="0 Bilder.",
        )

        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            result = handler.execute("pdf_extract_images", "pdf bilder Doc.pdf")
        assert result.success is True


# ── Path-Traversal-Schutz (Phase 69 Security-Fix) ──────────────────────


class TestPathTraversalGuard:
    """PathGuard verhindert beliebige Dateizugriffe via lokaler Pfade."""

    def _make_handler(
        self,
        mock_spdf: MagicMock,
        allowed_base: Path,
    ) -> PDFCommandHandler:
        from elder_berry.core.path_guard import PathGuard

        return PDFCommandHandler(
            stirling_pdf=mock_spdf,
            nextcloud_files=None,
            path_guard=PathGuard([allowed_base]),
        )

    def test_local_path_outside_base_blocked(
        self,
        mock_spdf: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Existierende Datei ausserhalb der Base -> Zugriff verweigert."""
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        outside_pdf = tmp_path / "outside.pdf"
        outside_pdf.write_bytes(b"%PDF outside")

        handler = self._make_handler(mock_spdf, safe_base)

        with patch("tempfile.mkdtemp", return_value=str(safe_base)):
            result = handler.execute(
                "pdf_compress",
                f"pdf komprimieren {outside_pdf}",
            )

        assert result.success is False
        assert "Zugriff verweigert" in result.text
        # Pfad darf nicht echoed werden
        assert str(outside_pdf) not in result.text
        # StirlingPDF darf nicht angefasst worden sein
        mock_spdf.compress.assert_not_called()

    def test_local_path_dotdot_blocked(
        self,
        mock_spdf: MagicMock,
        tmp_path: Path,
    ) -> None:
        """`../`-Traversal wird via resolve() aufgeloest und abgewiesen."""
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        secret = tmp_path / "secret.pdf"
        secret.write_bytes(b"%PDF secret")

        handler = self._make_handler(mock_spdf, safe_base)
        traversal = safe_base / ".." / "secret.pdf"

        with patch("tempfile.mkdtemp", return_value=str(safe_base)):
            result = handler.execute(
                "pdf_ocr",
                f"pdf ocr {traversal}",
            )

        assert result.success is False
        assert "Zugriff verweigert" in result.text
        mock_spdf.ocr.assert_not_called()

    def test_local_path_inside_base_allowed(
        self,
        mock_spdf: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Datei innerhalb der Base wird normal verarbeitet."""
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        ok_pdf = safe_base / "ok.pdf"
        ok_pdf.write_bytes(b"%PDF ok")

        mock_spdf.compress.return_value = PDFResult(
            success=True,
            output_path=safe_base / "ok_compressed.pdf",
            message="Komprimiert.",
        )

        handler = self._make_handler(mock_spdf, safe_base)
        with patch("tempfile.mkdtemp", return_value=str(safe_base)):
            result = handler.execute(
                "pdf_compress",
                f"pdf komprimieren {ok_pdf}",
            )

        assert result.success is True
        mock_spdf.compress.assert_called_once()

    def test_merge_blocks_traversal_in_first_file(
        self,
        mock_spdf: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Bei merge wird auch der erste Datei-Argument validiert."""
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"%PDF outside")
        ok_b = safe_base / "b.pdf"
        ok_b.write_bytes(b"%PDF b")

        handler = self._make_handler(mock_spdf, safe_base)
        with patch("tempfile.mkdtemp", return_value=str(safe_base)):
            result = handler.execute(
                "pdf_merge",
                f"pdf zusammenfügen {outside} {ok_b}",
            )

        assert result.success is False
        assert "Zugriff verweigert" in result.text
        mock_spdf.merge.assert_not_called()
