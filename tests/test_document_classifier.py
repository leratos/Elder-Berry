"""Tests für DocumentClassifier – Klassifizierung, Textextraktion, JSON-Parsing."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.document_classifier import (
    DocumentClassifier,
    _clean_description,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def llm():
    return MagicMock()


@pytest.fixture()
def reader():
    return MagicMock()


@pytest.fixture()
def stirling():
    return MagicMock()


@pytest.fixture()
def classifier(llm, reader, stirling):
    return DocumentClassifier(
        llm=llm,
        document_reader=reader,
        stirling_pdf=stirling,
    )


@pytest.fixture()
def classifier_no_stirling(llm, reader):
    return DocumentClassifier(
        llm=llm,
        document_reader=reader,
        stirling_pdf=None,
    )


def _llm_json(**kwargs) -> str:
    """Baut eine JSON-Antwort wie das LLM sie liefern würde."""
    defaults = {
        "datum": "2026-04-02",
        "kategorie": "Sonstiges",
        "beschreibung": "Dokument",
        "manual_unterordner": "",
        "confidence": "high",
    }
    defaults.update(kwargs)
    return json.dumps(defaults)


# ── Klassifizierung ──────────────────────────────────────────────────────


def test_classify_rechnung(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Rechnung Nr. 12345 von Zahnarzt Dr. Weber")
    llm.generate.return_value = _llm_json(
        kategorie="Rechnung", beschreibung="Zahnarzt-Dr-Weber",
    )

    result = classifier.classify(Path("C:/tmp/scan.pdf"))

    assert result.category == "Rechnung"
    assert result.target_folder == "Dokumente/Rechnungen"
    assert "Zahnarzt-Dr-Weber" in result.filename


def test_classify_vertrag(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Mietvertrag für Wohnung")
    llm.generate.return_value = _llm_json(
        kategorie="Vertrag", beschreibung="Mietvertrag-Wohnung",
    )

    result = classifier.classify(Path("C:/tmp/vertrag.pdf"))

    assert result.category == "Vertrag"
    assert result.target_folder == "Dokumente/Vertraege"


def test_classify_haus_angebot(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Angebot RK Bedachung")
    llm.generate.return_value = _llm_json(
        kategorie="Haus", beschreibung="RK-Bedachung-Angebot",
    )

    result = classifier.classify(Path("C:/tmp/angebot.pdf"))

    assert result.category == "Haus"
    assert result.target_folder == "Dokumente/Haus"


def test_classify_manual_elektronik(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Arduino Uno Handbuch")
    llm.generate.return_value = _llm_json(
        kategorie="Manual", beschreibung="Arduino-Uno-Handbuch",
        manual_unterordner="Elektronik",
    )

    result = classifier.classify(Path("C:/tmp/manual.pdf"))

    assert result.category == "Manual"
    assert result.target_folder == "Manuale/Elektronik"
    assert result.manual_subfolder == "Elektronik"


def test_classify_manual_unknown_sub(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Irgendein Manual")
    llm.generate.return_value = _llm_json(
        kategorie="Manual", beschreibung="Handbuch",
        manual_unterordner="Kochen",  # ungültig
    )

    result = classifier.classify(Path("C:/tmp/manual.pdf"))

    assert result.category == "Manual"
    assert result.target_folder == "Manuale"  # kein Unterordner
    assert result.manual_subfolder == ""


def test_classify_projekt(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Elder-Berry Projektdokumentation")
    llm.generate.return_value = _llm_json(
        kategorie="Projekt", beschreibung="Elder-Berry-Doku",
    )

    result = classifier.classify(Path("C:/tmp/projekt.pdf"))

    assert result.category == "Projekt"
    assert result.target_folder == "Projekte"


def test_classify_low_confidence(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Irgendein Dokument")
    llm.generate.return_value = _llm_json(confidence="low")

    result = classifier.classify(Path("C:/tmp/doc.pdf"))

    assert result.confidence == "low"


def test_classify_no_text_scanned_ocr_fallback(classifier, llm, reader, stirling):
    """Kein Text → OCR über Stirling → Text vorhanden."""
    reader.read_pdf.side_effect = [
        MagicMock(text="[Kein Text erkannt – möglicherweise ein gescanntes Dokument."),
        MagicMock(text="OCR-Text: Rechnung von Firma XY"),
    ]
    stirling.ocr.return_value = MagicMock(success=True, output_path=Path("C:/tmp/ocr.pdf"))
    llm.generate.return_value = _llm_json(
        kategorie="Rechnung", beschreibung="Firma-XY",
    )

    result = classifier.classify(Path("C:/tmp/scan.pdf"))

    assert result.category == "Rechnung"
    stirling.ocr.assert_called_once()


def test_classify_no_text_no_stirling(classifier_no_stirling, llm, reader):
    """Kein Text, kein Stirling → nur Dateiname als Kontext."""
    reader.read_pdf.return_value = MagicMock(
        text="[Kein Text erkannt – möglicherweise ein gescanntes Dokument.",
    )
    llm.generate.return_value = _llm_json(beschreibung="scan-001")

    result = classifier_no_stirling.classify(Path("C:/tmp/scan_001.pdf"))

    assert result is not None  # kein Crash


def test_classify_with_hint_category(classifier, llm, reader):
    """User-Korrektur 'Kategorie ist Haus' → neuer Vorschlag via LLM."""
    reader.read_pdf.return_value = MagicMock(text="Angebot für Dachdeckerarbeiten")
    llm.generate.return_value = _llm_json(
        kategorie="Haus", beschreibung="Dachdecker-Angebot",
    )

    result = classifier.classify_with_hint(
        Path("C:/tmp/scan.pdf"), "Kategorie ist Haus",
    )

    assert result.category == "Haus"
    # LLM wurde aufgerufen (kein direkter Build)
    llm.generate.assert_called_once()
    assert "korrigiert" in llm.generate.call_args.kwargs["prompt"]


def test_classify_with_hint_full_name(classifier, llm):
    """'Haus Angebot-Dach' → direkt gebaut ohne LLM."""
    result = classifier.classify_with_hint(
        Path("C:/tmp/scan.pdf"), "Haus Angebot-Dach",
    )

    assert result.category == "Haus"
    assert result.description == "Angebot-Dach"
    assert result.target_folder == "Dokumente/Haus"
    assert result.confidence == "high"
    llm.generate.assert_not_called()


def test_classify_date_from_doc(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Datum: 2025-12-15")
    llm.generate.return_value = _llm_json(datum="2025-12-15")

    result = classifier.classify(Path("C:/tmp/doc.pdf"))

    assert result.date == "2025-12-15"


def test_classify_date_fallback_today(classifier, llm, reader):
    reader.read_pdf.return_value = MagicMock(text="Kein Datum im Text")
    llm.generate.return_value = _llm_json(datum="ungültig")

    result = classifier.classify(Path("C:/tmp/doc.pdf"))

    assert result.date == date.today().isoformat()


# ── Textextraktion ───────────────────────────────────────────────────────


def test_extract_pdf_with_text(classifier, reader):
    reader.read_pdf.return_value = MagicMock(text="PDF-Text hier")

    text = classifier._extract_text(Path("C:/tmp/doc.pdf"))

    assert text == "PDF-Text hier"


def test_extract_pdf_ocr_fallback(classifier, reader, stirling):
    reader.read_pdf.side_effect = [
        MagicMock(text="[Kein Text erkannt – gescanntes Dokument."),
        MagicMock(text="OCR-Ergebnis"),
    ]
    stirling.ocr.return_value = MagicMock(success=True, output_path=Path("C:/tmp/ocr.pdf"))

    text = classifier._extract_text(Path("C:/tmp/scan.pdf"))

    assert text == "OCR-Ergebnis"


def test_extract_image_vision(classifier, llm):
    img_path = Path("C:/tmp/foto.jpg")
    with patch.object(Path, "read_bytes", return_value=b"fake-image"):
        llm.describe_image.return_value = "Ein Angebot von Firma XY"
        text = classifier._extract_text(img_path)

    assert text == "Ein Angebot von Firma XY"
    llm.describe_image.assert_called_once()
    # Prüfe dass media_type korrekt gesetzt wird
    call_kwargs = llm.describe_image.call_args.kwargs
    assert call_kwargs["media_type"] == "image/jpeg"


def test_extract_image_png_media_type(classifier, llm):
    """PNG-Bilder bekommen den richtigen media_type."""
    img_path = Path("C:/tmp/scan.png")
    with patch.object(Path, "read_bytes", return_value=b"fake-png"):
        llm.describe_image.return_value = "Scan-Ergebnis"
        classifier._extract_text(img_path)

    call_kwargs = llm.describe_image.call_args.kwargs
    assert call_kwargs["media_type"] == "image/png"


def test_extract_image_vision_fails(classifier, llm):
    img_path = Path("C:/tmp/foto.png")
    with patch.object(Path, "read_bytes", return_value=b"fake-image"):
        llm.describe_image.side_effect = RuntimeError("Vision nicht verfügbar")
        text = classifier._extract_text(img_path)

    assert text == ""


def test_extract_unknown_format(classifier):
    text = classifier._extract_text(Path("C:/tmp/doc.docx"))

    assert text == ""


def test_classify_llm_unavailable(classifier, llm, reader):
    """LLM nicht erreichbar → Fallback-Suggestion."""
    reader.read_pdf.return_value = MagicMock(text="Irgendein Text")
    llm.generate.side_effect = RuntimeError("API nicht erreichbar")

    result = classifier.classify(Path("C:/tmp/doc.pdf"))

    assert result.confidence == "low"
    assert result.category == "Sonstiges"


# ── JSON-Parsing ─────────────────────────────────────────────────────────


def test_parse_valid_json(classifier):
    response = _llm_json(
        kategorie="Haus", beschreibung="RK-Bedachung-Angebot",
        datum="2026-04-02",
    )

    result = classifier._parse_response(response, Path("C:/tmp/scan.pdf"))

    assert result.category == "Haus"
    assert result.description == "RK-Bedachung-Angebot"
    assert result.date == "2026-04-02"


def test_parse_json_in_markdown(classifier):
    response = '```json\n' + _llm_json(kategorie="Rechnung") + '\n```'

    result = classifier._parse_response(response, Path("C:/tmp/scan.pdf"))

    assert result.category == "Rechnung"


def test_parse_invalid_json(classifier):
    result = classifier._parse_response(
        "Das ist kein JSON", Path("C:/tmp/scan.pdf"),
    )

    assert result.confidence == "low"
    assert result.category == "Sonstiges"


def test_parse_invalid_category(classifier):
    response = _llm_json(kategorie="Fantasie")

    result = classifier._parse_response(response, Path("C:/tmp/scan.pdf"))

    assert result.category == "Sonstiges"


def test_description_umlaut_cleanup():
    assert _clean_description("Ärztliche Überweisung") == "Aerztliche-Ueberweisung"
    assert _clean_description("Straßen_Amt") == "Strassen-Amt"
    assert _clean_description("Mein  Dokument") == "Mein-Dokument"
