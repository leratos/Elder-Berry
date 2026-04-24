"""Tests: DocumentReader – Text aus PDF/TXT extrahieren."""
from pathlib import Path
from unittest.mock import patch

import pytest

from elder_berry.tools.document_reader import (
    DEFAULT_MAX_CHARS,
    SUPPORTED_EXTENSIONS,
    DocumentReader,
    DocumentResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def reader():
    """Standard-DocumentReader."""
    return DocumentReader()


@pytest.fixture
def small_reader():
    """DocumentReader mit niedrigem max_chars für Truncation-Tests."""
    return DocumentReader(max_chars=50)


# ---------------------------------------------------------------------------
# DocumentResult DTO
# ---------------------------------------------------------------------------

class TestDocumentResult:
    def test_frozen(self):
        result = DocumentResult(text="hello", pages=1, truncated=False, source="test.txt")
        with pytest.raises(AttributeError):
            result.text = "changed"

    def test_fields(self):
        result = DocumentResult(text="abc", pages=3, truncated=True, source="doc.pdf")
        assert result.text == "abc"
        assert result.pages == 3
        assert result.truncated is True
        assert result.source == "doc.pdf"


# ---------------------------------------------------------------------------
# is_supported
# ---------------------------------------------------------------------------

class TestIsSupported:
    def test_pdf_supported(self):
        assert DocumentReader.is_supported(Path("report.pdf")) is True

    def test_txt_supported(self):
        assert DocumentReader.is_supported(Path("notes.txt")) is True

    def test_pdf_uppercase(self):
        assert DocumentReader.is_supported(Path("REPORT.PDF")) is True

    def test_docx_not_supported(self):
        assert DocumentReader.is_supported(Path("doc.docx")) is False

    def test_xlsx_not_supported(self):
        assert DocumentReader.is_supported(Path("data.xlsx")) is False

    def test_no_extension(self):
        assert DocumentReader.is_supported(Path("README")) is False

    def test_supported_extensions_constant(self):
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".txt" in SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# read_txt
# ---------------------------------------------------------------------------

class TestReadTxt:
    def test_utf8_file(self, tmp_path, reader):
        f = tmp_path / "test.txt"
        f.write_text("Hallo Welt! Ähre wem Ähre gebührt.", encoding="utf-8")

        result = reader.read_txt(f)

        assert "Hallo Welt" in result.text
        assert "Ähre" in result.text
        assert result.pages == 1
        assert result.truncated is False
        assert result.source == "test.txt"

    def test_latin1_fallback(self, tmp_path, reader):
        f = tmp_path / "latin.txt"
        f.write_bytes("Stra\xdfe und Gr\xfc\xdfe".encode("latin-1"))

        result = reader.read_txt(f)

        assert "Straße" in result.text or "Stra" in result.text
        assert result.pages == 1

    def test_empty_file(self, tmp_path, reader):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        result = reader.read_txt(f)

        assert result.text == ""
        assert result.truncated is False

    def test_file_not_found(self, tmp_path, reader):
        with pytest.raises(FileNotFoundError):
            reader.read_txt(tmp_path / "nope.txt")

    def test_truncation(self, tmp_path, small_reader):
        f = tmp_path / "long.txt"
        f.write_text("A" * 200, encoding="utf-8")

        result = small_reader.read_txt(f)

        assert result.truncated is True
        assert "gekürzt" in result.text
        # Der eigentliche Text-Teil sollte max_chars lang sein (vor dem Suffix)
        assert result.text.startswith("A" * 50)


# ---------------------------------------------------------------------------
# read_pdf
# ---------------------------------------------------------------------------

class TestReadPdf:
    def test_simple_pdf(self, tmp_path, reader):
        """Test mit echtem pymupdf – erstellt ein Mini-PDF."""
        pytest.importorskip("fitz")
        import fitz

        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hallo PDF Welt!")
        doc.save(str(pdf_path))
        doc.close()

        result = reader.read_pdf(pdf_path)

        assert "Hallo PDF Welt" in result.text
        assert result.pages == 1
        assert result.truncated is False
        assert result.source == "test.pdf"

    def test_multipage_pdf(self, tmp_path, reader):
        pytest.importorskip("fitz")
        import fitz

        pdf_path = tmp_path / "multi.pdf"
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), f"Seite {i + 1}")
        doc.save(str(pdf_path))
        doc.close()

        result = reader.read_pdf(pdf_path)

        assert "Seite 1" in result.text
        assert "Seite 2" in result.text
        assert "Seite 3" in result.text
        assert result.pages == 3

    def test_empty_pdf_no_text(self, tmp_path, reader):
        """PDF ohne Text → Hinweis auf gescanntes Dokument."""
        pytest.importorskip("fitz")
        import fitz

        pdf_path = tmp_path / "empty.pdf"
        doc = fitz.open()
        doc.new_page()  # Leere Seite
        doc.save(str(pdf_path))
        doc.close()

        result = reader.read_pdf(pdf_path)

        assert "Kein Text erkannt" in result.text
        assert result.pages == 1

    def test_pdf_truncation(self, tmp_path, small_reader):
        pytest.importorskip("fitz")
        import fitz

        pdf_path = tmp_path / "long.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "X" * 200)
        doc.save(str(pdf_path))
        doc.close()

        result = small_reader.read_pdf(pdf_path)

        assert result.truncated is True
        assert "gekürzt" in result.text

    def test_pdf_not_found(self, tmp_path, reader):
        with pytest.raises(FileNotFoundError):
            reader.read_pdf(tmp_path / "nope.pdf")

    def test_pymupdf_not_installed(self, tmp_path, reader):
        """Graceful Error wenn pymupdf fehlt."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        with patch.dict("sys.modules", {"fitz": None}):
            with pytest.raises(RuntimeError, match="pymupdf"):
                reader.read_pdf(pdf_path)


# ---------------------------------------------------------------------------
# read_file (Dispatcher)
# ---------------------------------------------------------------------------

class TestReadFile:
    def test_dispatches_txt(self, tmp_path, reader):
        f = tmp_path / "notes.txt"
        f.write_text("Notizen hier.", encoding="utf-8")

        result = reader.read_file(f)

        assert "Notizen hier" in result.text
        assert result.source == "notes.txt"

    def test_dispatches_pdf(self, tmp_path, reader):
        pytest.importorskip("fitz")
        import fitz

        pdf_path = tmp_path / "doc.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "PDF Inhalt")
        doc.save(str(pdf_path))
        doc.close()

        result = reader.read_file(pdf_path)

        assert "PDF Inhalt" in result.text

    def test_unsupported_extension(self, tmp_path, reader):
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake xlsx")

        with pytest.raises(ValueError, match="nicht unterstützt"):
            reader.read_file(f)

    def test_file_not_found(self, tmp_path, reader):
        with pytest.raises(FileNotFoundError):
            reader.read_file(tmp_path / "gone.pdf")


# ---------------------------------------------------------------------------
# max_chars Konfiguration
# ---------------------------------------------------------------------------

class TestMaxChars:
    def test_default_max_chars(self):
        reader = DocumentReader()
        assert reader._max_chars == DEFAULT_MAX_CHARS

    def test_custom_max_chars(self):
        reader = DocumentReader(max_chars=500)
        assert reader._max_chars == 500
