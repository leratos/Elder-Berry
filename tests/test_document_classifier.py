"""Tests für DocumentClassifier – Klassifizierung, Textextraktion, JSON-Parsing."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.document_classifier import (
    CATEGORY_FOLDER_MAP,
    IMAGE_EXTENSIONS,
    MANUAL_SUBFOLDERS,
    MAX_CLASSIFY_CHARS,
    VALID_CATEGORIES,
    DocumentClassifier,
    FilingSuggestion,
    _clean_description,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def ollama():
    return MagicMock()


@pytest.fixture()
def reader():
    return MagicMock()


@pytest.fixture()
def stirling():
    return MagicMock()


@pytest.fixture()
def classifier(ollama, reader, stirling):
    return DocumentClassifier(
        ollama=ollama,
        document_reader=reader,
        stirling_pdf=stirling,
    )


@pytest.fixture()
def classifier_no_stirling(ollama, reader):
    return DocumentClassifier(
        ollama=ollama,
        document_reader=reader,
        stirling_pdf=None,
    )


def _llm_json(**kwargs) -> str:
    """Baut eine JSON-Antwort wie Ollama sie liefern würde."""
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


def test_classify_rechnung(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Rechnung Nr. 12345 von Zahnarzt Dr. Weber")
    ollama.generate.return_value = _llm_json(
        kategorie="Rechnung", beschreibung="Zahnarzt-Dr-Weber",
    )

    result = classifier.classify(Path("C:/tmp/scan.pdf"))

    assert result.category == "Rechnung"
    assert result.target_folder == "Dokumente/Rechnungen"
    assert "Zahnarzt-Dr-Weber" in result.filename


def test_classify_vertrag(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Mietvertrag für Wohnung")
    ollama.generate.return_value = _llm_json(
        kategorie="Vertrag", beschreibung="Mietvertrag-Wohnung",
    )

    result = classifier.classify(Path("C:/tmp/vertrag.pdf"))

    assert result.category == "Vertrag"
    assert result.target_folder == "Dokumente/Vertraege"


def test_classify_haus_angebot(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Angebot RK Bedachung")
    ollama.generate.return_value = _llm_json(
        kategorie="Haus", beschreibung="RK-Bedachung-Angebot",
    )

    result = classifier.classify(Path("C:/tmp/angebot.pdf"))

    assert result.category == "Haus"
    assert result.target_folder == "Dokumente/Haus"


def test_classify_manual_elektronik(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Arduino Uno Handbuch")
    ollama.generate.return_value = _llm_json(
        kategorie="Manual", beschreibung="Arduino-Uno-Handbuch",
        manual_unterordner="Elektronik",
    )

    result = classifier.classify(Path("C:/tmp/manual.pdf"))

    assert result.category == "Manual"
    assert result.target_folder == "Manuale/Elektronik"
    assert result.manual_subfolder == "Elektronik"


def test_classify_manual_unknown_sub(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Irgendein Manual")
    ollama.generate.return_value = _llm_json(
        kategorie="Manual", beschreibung="Handbuch",
        manual_unterordner="Kochen",  # ungültig
    )

    result = classifier.classify(Path("C:/tmp/manual.pdf"))

    assert result.category == "Manual"
    assert result.target_folder == "Manuale"  # kein Unterordner
    assert result.manual_subfolder == ""


def test_classify_projekt(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Elder-Berry Projektdokumentation")
    ollama.generate.return_value = _llm_json(
        kategorie="Projekt", beschreibung="Elder-Berry-Doku",
    )

    result = classifier.classify(Path("C:/tmp/projekt.pdf"))

    assert result.category == "Projekt"
    assert result.target_folder == "Projekte"


def test_classify_low_confidence(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Irgendein Dokument")
    ollama.generate.return_value = _llm_json(confidence="low")

    result = classifier.classify(Path("C:/tmp/doc.pdf"))

    assert result.confidence == "low"


def test_classify_no_text_scanned_ocr_fallback(classifier, ollama, reader, stirling):
    """Kein Text → OCR über Stirling → Text vorhanden."""
    reader.read_pdf.side_effect = [
        MagicMock(text="[Kein Text erkannt – möglicherweise ein gescanntes Dokument."),
        MagicMock(text="OCR-Text: Rechnung von Firma XY"),
    ]
    stirling.ocr.return_value = MagicMock(success=True, output_path=Path("C:/tmp/ocr.pdf"))
    ollama.generate.return_value = _llm_json(
        kategorie="Rechnung", beschreibung="Firma-XY",
    )

    result = classifier.classify(Path("C:/tmp/scan.pdf"))

    assert result.category == "Rechnung"
    stirling.ocr.assert_called_once()


def test_classify_no_text_no_stirling(classifier_no_stirling, ollama, reader):
    """Kein Text, kein Stirling → nur Dateiname als Kontext."""
    reader.read_pdf.return_value = MagicMock(
        text="[Kein Text erkannt – möglicherweise ein gescanntes Dokument.",
    )
    ollama.generate.return_value = _llm_json(beschreibung="scan-001")

    result = classifier_no_stirling.classify(Path("C:/tmp/scan_001.pdf"))

    assert result is not None  # kein Crash


def test_classify_with_hint_category(classifier, ollama, reader):
    """User-Korrektur 'Kategorie ist Haus' → neuer Vorschlag via LLM."""
    reader.read_pdf.return_value = MagicMock(text="Angebot für Dachdeckerarbeiten")
    ollama.generate.return_value = _llm_json(
        kategorie="Haus", beschreibung="Dachdecker-Angebot",
    )

    result = classifier.classify_with_hint(
        Path("C:/tmp/scan.pdf"), "Kategorie ist Haus",
    )

    assert result.category == "Haus"
    # LLM wurde aufgerufen (kein direkter Build)
    ollama.generate.assert_called_once()
    assert "korrigiert" in ollama.generate.call_args.kwargs["prompt"]


def test_classify_with_hint_full_name(classifier, ollama):
    """'Haus Angebot-Dach' → direkt gebaut ohne LLM."""
    result = classifier.classify_with_hint(
        Path("C:/tmp/scan.pdf"), "Haus Angebot-Dach",
    )

    assert result.category == "Haus"
    assert result.description == "Angebot-Dach"
    assert result.target_folder == "Dokumente/Haus"
    assert result.confidence == "high"
    ollama.generate.assert_not_called()


def test_classify_date_from_doc(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Datum: 2025-12-15")
    ollama.generate.return_value = _llm_json(datum="2025-12-15")

    result = classifier.classify(Path("C:/tmp/doc.pdf"))

    assert result.date == "2025-12-15"


def test_classify_date_fallback_today(classifier, ollama, reader):
    reader.read_pdf.return_value = MagicMock(text="Kein Datum im Text")
    ollama.generate.return_value = _llm_json(datum="ungültig")

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


def test_extract_image_vision(classifier, ollama):
    img_path = Path("C:/tmp/foto.jpg")
    with patch.object(Path, "read_bytes", return_value=b"fake-image"):
        ollama.generate_with_image.return_value = "Ein Angebot von Firma XY"
        text = classifier._extract_text(img_path)

    assert text == "Ein Angebot von Firma XY"
    ollama.generate_with_image.assert_called_once()


def test_extract_image_vision_fails(classifier, ollama):
    img_path = Path("C:/tmp/foto.png")
    with patch.object(Path, "read_bytes", return_value=b"fake-image"):
        ollama.generate_with_image.side_effect = RuntimeError("Vision nicht verfügbar")
        text = classifier._extract_text(img_path)

    assert text == ""


def test_extract_unknown_format(classifier):
    text = classifier._extract_text(Path("C:/tmp/doc.docx"))

    assert text == ""


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
