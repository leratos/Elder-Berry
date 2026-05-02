"""DocumentClassifier – Dokumente analysieren und Dateinamen vorschlagen.

Extrahiert Text aus Dokumenten (PDF, Bilder) und nutzt ein LLM
(AnthropicClient) um Kategorie, Datum und Beschreibung zu bestimmen.
Bilder werden via Claude Vision analysiert (describe_image).

OCR-Fallback: Stirling-PDF auf dem eigenen Server.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.llm.anthropic_client import AnthropicClient
    from elder_berry.tools.document_reader import DocumentReader
    from elder_berry.tools.stirling_pdf import StirlingPDFClient

logger = logging.getLogger(__name__)

# Max Zeichen die an Ollama geschickt werden (Text-Extrakt)
MAX_CLASSIFY_CHARS = 3000

# Bild-Formate die Claude Vision verarbeiten kann
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# Kategorie → Zielordner Mapping
CATEGORY_FOLDER_MAP: dict[str, str] = {
    "Vertrag": "Dokumente/Vertraege",
    "Rechnung": "Dokumente/Rechnungen",
    "Behoerden": "Dokumente/Behoerden",
    "Steuer": "Dokumente/Behoerden",
    "Haus": "Dokumente/Haus",
    "Manual": "Manuale",
    "Projekt": "Projekte",
    "Notiz": "Notizen",
    "Sonstiges": "Sonstiges",
}

# Erlaubte Kategorien (für Prompt + Validierung)
VALID_CATEGORIES = frozenset(CATEGORY_FOLDER_MAP.keys())

# Manual-Unterordner (für Prompt + Validierung)
MANUAL_SUBFOLDERS = frozenset({"3D-Druck", "Elektronik", "Netzwerk", "Smart-Home"})

# Umlaut-Mapping für Dateinamen-Bereinigung
_UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "Ä": "Ae",
    "Ö": "Oe",
    "Ü": "Ue",
}


@dataclass(frozen=True)
class FilingSuggestion:
    """Vorschlag für Dateiname und Zielordner."""

    date: str
    """Datum im Format YYYY-MM-DD."""

    category: str
    """Kategorie (z.B. 'Haus', 'Rechnung')."""

    description: str
    """Beschreibung (z.B. 'RK-Bedachung-Angebot')."""

    target_folder: str
    """Ziel-Ordner auf Nextcloud (z.B. 'Dokumente/Haus')."""

    filename: str
    """Vorgeschlagener Dateiname (z.B. '2026-04-02_Haus_RK-Bedachung-Angebot.pdf')."""

    confidence: str
    """Vertrauen: 'high', 'medium' oder 'low'."""

    manual_subfolder: str = ""
    """Unterordner bei Manual (z.B. 'Elektronik'), sonst leer."""


def _clean_description(text: str) -> str:
    """Bereinigt Beschreibung für Dateinamen: Umlaute, Leerzeichen, Unterstriche."""
    for umlaut, replacement in _UMLAUT_MAP.items():
        text = text.replace(umlaut, replacement)
    # Leerzeichen → Bindestriche
    text = text.replace(" ", "-")
    # Unterstriche → Bindestriche (Unterstriche sind Block-Trenner)
    text = text.replace("_", "-")
    # Mehrfach-Bindestriche → einzelner
    text = re.sub(r"-{2,}", "-", text)
    # Nur erlaubte Zeichen: Buchstaben, Zahlen, Bindestriche
    text = re.sub(r"[^a-zA-Z0-9\-]", "", text)
    return text.strip("-")


_SYSTEM_PROMPT = """\
Du bist ein Dokumenten-Klassifizierer. Analysiere den Text und bestimme:
1. datum — Datum aus dem Dokument (YYYY-MM-DD). Falls nicht erkennbar: heute.
2. kategorie — EXAKT eine aus: Vertrag, Rechnung, Behoerden, Steuer, Haus, \
Manual, Projekt, Notiz, Sonstiges
3. beschreibung — Firma und/oder Dokumenttyp. Regeln:
   - Bindestriche statt Leerzeichen
   - Keine Umlaute (ae/oe/ue statt ä/ö/ü)
   - Keine Unterstriche (die sind Block-Trenner)
   - Beispiele: RK-Bedachung-Angebot, Zahnarzt-Dr-Weber, Mietvertrag-Wohnung
4. manual_unterordner — NUR wenn kategorie=Manual: einer aus \
3D-Druck, Elektronik, Netzwerk, Smart-Home. Sonst leer.
5. confidence — high (eindeutig), medium (unsicher bei Kategorie), low (geraten)

Antworte NUR mit JSON, kein anderer Text:
{"datum": "2026-04-02", "kategorie": "Haus", "beschreibung": \
"RK-Bedachung-Angebot", "manual_unterordner": "", "confidence": "high"}"""


class DocumentClassifier:
    """Analysiert Dokumente und schlägt Dateinamen vor."""

    def __init__(
        self,
        llm: AnthropicClient,
        document_reader: DocumentReader,
        stirling_pdf: StirlingPDFClient | None = None,
    ) -> None:
        self._llm = llm
        self._reader = document_reader
        self._stirling = stirling_pdf

    def classify(self, file_path: Path) -> FilingSuggestion:
        """Analysiert ein Dokument und gibt einen Ablage-Vorschlag zurück.

        Args:
            file_path: Lokaler Pfad zum Dokument.

        Returns:
            FilingSuggestion mit Dateiname und Zielordner.
        """
        text = self._extract_text(file_path)
        system_prompt, user_prompt = self._build_prompt(text, file_path.name)

        try:
            response = self._llm.generate(
                prompt=user_prompt,
                system=system_prompt,
            )
        except RuntimeError:
            logger.warning(
                "LLM nicht erreichbar für Klassifizierung von %s", file_path.name
            )
            return self._fallback_suggestion(file_path)

        return self._parse_response(response, file_path)

    def classify_with_hint(self, file_path: Path, hint: str) -> FilingSuggestion:
        """Klassifiziert mit User-Korrektur.

        Wenn hint mit einer gültigen Kategorie beginnt (z.B. 'Haus Angebot-Dach'),
        wird direkt ein FilingSuggestion gebaut ohne LLM.
        Sonst wird der Hint als zusätzlicher Kontext an Ollama gegeben.
        """
        parts = hint.strip().split(None, 1)
        if parts and parts[0] in VALID_CATEGORIES:
            category = parts[0]
            description = (
                _clean_description(parts[1]) if len(parts) > 1 else file_path.stem
            )
            target_folder = self._resolve_target_folder(category, "")
            today = date.today().isoformat()
            filename = f"{today}_{category}_{description}{file_path.suffix}"
            return FilingSuggestion(
                date=today,
                category=category,
                description=description,
                target_folder=target_folder,
                filename=filename,
                confidence="high",
            )

        # Hint als Korrektur an Ollama
        text = self._extract_text(file_path)
        system_prompt, user_prompt = self._build_prompt(text, file_path.name)
        user_prompt += (
            f"\n\nDer Nutzer hat korrigiert: {hint}. Passe deinen Vorschlag an."
        )

        try:
            response = self._llm.generate(
                prompt=user_prompt,
                system=system_prompt,
            )
        except RuntimeError:
            logger.warning("LLM nicht erreichbar für Korrektur von %s", file_path.name)
            return self._fallback_suggestion(file_path)

        return self._parse_response(response, file_path)

    def _extract_text(self, file_path: Path) -> str:
        """Extrahiert Text aus Dokument (PDF, Bild, sonstige)."""
        ext = file_path.suffix.lower()

        if ext == ".pdf":
            return self._extract_pdf(file_path)

        if ext in IMAGE_EXTENSIONS:
            return self._extract_image(file_path)

        # Sonstige: kein Text extrahierbar
        return ""

    def _extract_pdf(self, file_path: Path) -> str:
        """Extrahiert Text aus PDF, mit OCR-Fallback."""
        try:
            result = self._reader.read_pdf(file_path)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.warning("PDF lesen fehlgeschlagen: %s", exc)
            return ""

        # Prüfe ob Text vorhanden
        if result.text.startswith("[Kein Text erkannt"):
            # OCR-Fallback über Stirling-PDF
            if self._stirling is not None:
                return self._ocr_fallback(file_path)
            return ""

        return result.text[:MAX_CLASSIFY_CHARS]

    def _ocr_fallback(self, file_path: Path) -> str:
        """OCR über Stirling-PDF, dann erneut Text extrahieren."""
        import tempfile

        # Aufrufer (extract_text) filtert self._stirling is None bereits raus.
        assert self._stirling is not None
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ocr_path = Path(tmp_dir) / f"ocr_{file_path.name}"
                ocr_result = self._stirling.ocr(file_path, ocr_path)
                if not ocr_result.success or not ocr_result.output_path:
                    logger.warning("OCR fehlgeschlagen: %s", ocr_result.message)
                    return ""
                result = self._reader.read_pdf(ocr_result.output_path)
                if result.text.startswith("[Kein Text erkannt"):
                    return ""
                return result.text[:MAX_CLASSIFY_CHARS]
        except Exception as exc:
            logger.warning("OCR-Fallback fehlgeschlagen: %s", exc)
            return ""

    def _extract_image(self, file_path: Path) -> str:
        """Beschreibt ein Bild via Claude Vision (describe_image)."""
        try:
            image_bytes = file_path.read_bytes()
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            ext = file_path.suffix.lower()
            media_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }.get(ext, "image/jpeg")
            return self._llm.describe_image(
                image_base64=image_b64,
                prompt="Beschreibe dieses Dokument/Bild kurz auf Deutsch. "
                "Was ist der Inhalt? Welche Firma/Organisation? "
                "Gibt es ein Datum?",
                media_type=media_type,
            )
        except (RuntimeError, OSError) as exc:
            logger.warning("Bild-Analyse fehlgeschlagen: %s", exc)
            return ""

    def _build_prompt(self, text: str, filename: str) -> tuple[str, str]:
        """Baut System- und User-Prompt für die Klassifizierung."""
        if text:
            user_prompt = (
                f"Dateiname: {filename}\n\nDokumentinhalt:\n{text[:MAX_CLASSIFY_CHARS]}"
            )
        else:
            user_prompt = (
                f"Dateiname: {filename}\n\n"
                "Kein Textinhalt extrahierbar. "
                "Bitte anhand des Dateinamens klassifizieren."
            )
        return _SYSTEM_PROMPT, user_prompt

    def _parse_response(self, response: str, file_path: Path) -> FilingSuggestion:
        """Parst die LLM-Antwort und baut ein FilingSuggestion."""
        # ```json ... ``` Wrapper entfernen
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n", 1)
            if len(lines) > 1:
                cleaned = lines[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("LLM-Antwort kein gültiges JSON: %s", response[:200])
            return self._fallback_suggestion(file_path)

        # Validierung
        category = data.get("kategorie", "Sonstiges")
        if category not in VALID_CATEGORIES:
            category = "Sonstiges"

        datum = data.get("datum", "")
        if not re.match(r"\d{4}-\d{2}-\d{2}$", datum):
            datum = date.today().isoformat()

        raw_desc = data.get("beschreibung", "") or file_path.stem
        description = _clean_description(raw_desc)
        if not description:
            description = _clean_description(file_path.stem)

        manual_sub = data.get("manual_unterordner", "") or ""
        if manual_sub not in MANUAL_SUBFOLDERS:
            manual_sub = ""

        confidence = data.get("confidence", "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        target_folder = self._resolve_target_folder(category, manual_sub)
        filename = f"{datum}_{category}_{description}{file_path.suffix}"

        return FilingSuggestion(
            date=datum,
            category=category,
            description=description,
            target_folder=target_folder,
            filename=filename,
            confidence=confidence,
            manual_subfolder=manual_sub,
        )

    @staticmethod
    def _resolve_target_folder(category: str, manual_sub: str) -> str:
        """Bestimmt den Zielordner aus Kategorie + ggf. Unterordner."""
        base = CATEGORY_FOLDER_MAP.get(category, "Sonstiges")
        if category == "Manual" and manual_sub:
            return f"Manuale/{manual_sub}"
        return base

    @staticmethod
    def _fallback_suggestion(file_path: Path) -> FilingSuggestion:
        """Fallback wenn LLM nicht verfügbar oder Parsing fehlschlägt."""
        today = date.today().isoformat()
        stem = _clean_description(file_path.stem) or "Unbekannt"
        return FilingSuggestion(
            date=today,
            category="Sonstiges",
            description=stem,
            target_folder="Sonstiges",
            filename=f"{today}_Sonstiges_{stem}{file_path.suffix}",
            confidence="low",
        )
