"""Tests für StirlingPDFClient – HTTP komplett gemockt."""
from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from elder_berry.tools.stirling_pdf import (
    StirlingPDFClient,
)


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def secret_store() -> MagicMock:
    store = MagicMock()
    store.get_or_none.side_effect = lambda key: {
        "stirling_pdf_url": "https://pdf.example.com",
        "stirling_pdf_api_key": "test-key-123",
    }.get(key)
    return store


@pytest.fixture()
def client(secret_store: MagicMock) -> StirlingPDFClient:
    return StirlingPDFClient(secret_store=secret_store)


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    """Erstellt eine Fake-PDF-Datei."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    return pdf


@pytest.fixture()
def sample_docx(tmp_path: Path) -> Path:
    """Erstellt eine Fake-DOCX-Datei."""
    docx = tmp_path / "test.docx"
    docx.write_bytes(b"PK\x03\x04 fake docx content")
    return docx


@pytest.fixture()
def sample_png(tmp_path: Path) -> Path:
    """Erstellt eine Fake-PNG-Datei."""
    png = tmp_path / "test.png"
    png.write_bytes(b"\x89PNG fake image content")
    return png


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Erstellt ein ZIP im Speicher mit den angegebenen Dateien."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ── Credentials & Verfügbarkeit ───────────────────────────────────────


class TestAvailability:
    def test_is_available_success(self, client: StirlingPDFClient) -> None:
        resp = MagicMock(status_code=200)
        with patch("httpx.get", return_value=resp):
            assert client.is_available() is True

    def test_is_available_no_credentials(self) -> None:
        store = MagicMock()
        store.get_or_none.return_value = None
        c = StirlingPDFClient(secret_store=store)
        assert c.is_available() is False

    def test_is_available_server_unreachable(
        self, client: StirlingPDFClient,
    ) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            assert client.is_available() is False


# ── Merge ──────────────────────────────────────────────────────────────


class TestMerge:
    def test_merge_two_pdfs(
        self, client: StirlingPDFClient, tmp_path: Path,
    ) -> None:
        pdf1 = tmp_path / "a.pdf"
        pdf2 = tmp_path / "b.pdf"
        pdf1.write_bytes(b"%PDF a")
        pdf2.write_bytes(b"%PDF b")
        output = tmp_path / "merged.pdf"

        merged_content = b"%PDF merged"
        resp = MagicMock(status_code=200, content=merged_content)
        with patch("httpx.post", return_value=resp):
            result = client.merge([pdf1, pdf2], output)

        assert result.success is True
        assert output.exists()
        assert output.read_bytes() == merged_content
        assert "2 PDFs" in result.message

    def test_merge_too_few_files(
        self, client: StirlingPDFClient, tmp_path: Path,
    ) -> None:
        pdf = tmp_path / "only.pdf"
        pdf.write_bytes(b"%PDF")
        result = client.merge([pdf], tmp_path / "out.pdf")
        assert result.success is False
        assert "Mindestens 2" in result.message

    def test_merge_server_error(
        self, client: StirlingPDFClient, tmp_path: Path,
    ) -> None:
        pdf1 = tmp_path / "a.pdf"
        pdf2 = tmp_path / "b.pdf"
        pdf1.write_bytes(b"%PDF a")
        pdf2.write_bytes(b"%PDF b")

        resp = MagicMock(status_code=500, text="Internal Server Error")
        with patch("httpx.post", return_value=resp):
            result = client.merge([pdf1, pdf2], tmp_path / "out.pdf")

        assert result.success is False
        assert "500" in result.message


# ── Split ──────────────────────────────────────────────────────────────


class TestSplit:
    def test_split_pages_zip(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output_dir = tmp_path / "split_out"
        zip_content = _make_zip({
            "page_1.pdf": b"%PDF page 1",
            "page_2.pdf": b"%PDF page 2",
            "page_3.pdf": b"%PDF page 3",
        })
        resp = MagicMock(status_code=200, content=zip_content)
        with patch("httpx.post", return_value=resp):
            result = client.split(sample_pdf, "1-3", output_dir)

        assert result.success is True
        assert len(result.output_paths) == 3
        assert "3 Datei" in result.message

    def test_split_single_page(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output_dir = tmp_path / "split_single"
        single_content = b"%PDF single page"
        resp = MagicMock(status_code=200, content=single_content)
        with patch("httpx.post", return_value=resp):
            result = client.split(sample_pdf, "2", output_dir)

        assert result.success is True
        assert len(result.output_paths) == 1
        assert result.output_paths[0].read_bytes() == single_content


# ── Compress ───────────────────────────────────────────────────────────


class TestCompress:
    def test_compress_default_level(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "compressed.pdf"
        # Smaller than original
        compressed = b"%PDF compressed"
        resp = MagicMock(status_code=200, content=compressed)
        with patch("httpx.post", return_value=resp) as mock_post:
            result = client.compress(sample_pdf, output)

        assert result.success is True
        assert output.exists()
        # Check default level=5 was sent
        call_data = mock_post.call_args
        assert call_data.kwargs["data"]["optimizeLevel"] == "5"

    def test_compress_custom_level(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "compressed9.pdf"
        resp = MagicMock(status_code=200, content=b"%PDF tiny")
        with patch("httpx.post", return_value=resp) as mock_post:
            result = client.compress(sample_pdf, output, level=9)

        assert result.success is True
        call_data = mock_post.call_args
        assert call_data.kwargs["data"]["optimizeLevel"] == "9"

    def test_compress_file_smaller(
        self, client: StirlingPDFClient, tmp_path: Path,
    ) -> None:
        pdf = tmp_path / "big.pdf"
        pdf.write_bytes(b"x" * 10000)
        output = tmp_path / "small.pdf"

        resp = MagicMock(status_code=200, content=b"x" * 1000)
        with patch("httpx.post", return_value=resp):
            result = client.compress(pdf, output)

        assert result.success is True
        assert "kleiner" in result.message


# ── OCR ────────────────────────────────────────────────────────────────


class TestOCR:
    def test_ocr_default_languages(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "ocr.pdf"
        resp = MagicMock(status_code=200, content=b"%PDF with text")
        with patch("httpx.post", return_value=resp) as mock_post:
            result = client.ocr(sample_pdf, output)

        assert result.success is True
        call_data = mock_post.call_args
        assert call_data.kwargs["data"]["languages"] == "deu+eng"
        assert call_data.kwargs["data"]["ocrType"] == "force-ocr"

    def test_ocr_success(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "ocr_result.pdf"
        resp = MagicMock(status_code=200, content=b"%PDF ocr result")
        with patch("httpx.post", return_value=resp):
            result = client.ocr(sample_pdf, output)

        assert result.success is True
        assert output.exists()
        assert "OCR abgeschlossen" in result.message


# ── Convert ────────────────────────────────────────────────────────────


class TestConvert:
    def test_to_word_success(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "result.docx"
        resp = MagicMock(status_code=200, content=b"PK\x03\x04 docx content")
        with patch("httpx.post", return_value=resp):
            result = client.to_word(sample_pdf, output)

        assert result.success is True
        assert output.exists()
        assert "Word" in result.message

    def test_to_pdf_from_docx(
        self, client: StirlingPDFClient, sample_docx: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "converted.pdf"
        resp = MagicMock(status_code=200, content=b"%PDF from docx")
        with patch("httpx.post", return_value=resp):
            result = client.to_pdf(sample_docx, output)

        assert result.success is True
        assert output.exists()
        assert "PDF konvertiert" in result.message

    def test_to_pdf_from_image(
        self, client: StirlingPDFClient, sample_png: Path, tmp_path: Path,
    ) -> None:
        output = tmp_path / "from_image.pdf"
        resp = MagicMock(status_code=200, content=b"%PDF from png")
        with patch("httpx.post", return_value=resp):
            result = client.to_pdf(sample_png, output)

        assert result.success is True
        assert output.exists()


# ── Extract Images ─────────────────────────────────────────────────────


class TestExtractImages:
    def test_extract_images_success(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output_dir = tmp_path / "images"
        zip_content = _make_zip({
            "img_1.png": b"\x89PNG image 1",
            "img_2.jpg": b"\xff\xd8\xff image 2",
        })
        resp = MagicMock(status_code=200, content=zip_content)
        with patch("httpx.post", return_value=resp):
            result = client.extract_images(sample_pdf, output_dir)

        assert result.success is True
        assert len(result.output_paths) == 2
        assert "2 Bild" in result.message

    def test_extract_images_no_images(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        output_dir = tmp_path / "empty_images"
        zip_content = _make_zip({})  # Leere ZIP
        resp = MagicMock(status_code=200, content=zip_content)
        with patch("httpx.post", return_value=resp):
            result = client.extract_images(sample_pdf, output_dir)

        assert result.success is True
        assert "Keine Bilder" in result.message


# ── Error Handling ─────────────────────────────────────────────────────


class TestErrors:
    def test_api_timeout(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        with patch(
            "httpx.post", side_effect=httpx.TimeoutException("timeout"),
        ):
            result = client.compress(sample_pdf, tmp_path / "out.pdf")

        assert result.success is False
        assert "nicht erreichbar" in result.message

    def test_api_auth_error(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        resp = MagicMock(status_code=401, text="Unauthorized")
        with patch("httpx.post", return_value=resp):
            result = client.compress(sample_pdf, tmp_path / "out.pdf")

        assert result.success is False
        assert "401" in result.message

    def test_invalid_pdf(
        self, client: StirlingPDFClient, sample_pdf: Path, tmp_path: Path,
    ) -> None:
        resp = MagicMock(status_code=400, text="Invalid PDF file")
        with patch("httpx.post", return_value=resp):
            result = client.ocr(sample_pdf, tmp_path / "out.pdf")

        assert result.success is False
        assert "400" in result.message
