"""AdvancedCommandHandler -- Computer Use, Web Search, Document Summary, Audio.

Extrahiert aus remote_commands.py (Refactoring).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from elder_berry.comms.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from elder_berry.actions.computer_use import ComputerUseController
    from elder_berry.core.audio_router import AudioRouter
    from elder_berry.tools.brave_search_client import BraveSearchClient
    from elder_berry.tools.document_reader import DocumentReader
    from elder_berry.tools.web_fetcher import WebFetcher

logger = logging.getLogger(__name__)

# Regex fuer Web-Zusammenfassung: "fasse https://... zusammen",
# "zusammenfassung von https://...", "fasse die seite https://... zusammen"
WEB_SUMMARY_PATTERN = re.compile(
    r"^(?:fasse(?:\s+mal)?\s+)?(https?://\S+)(?:\s+zusammen)?$"
    r"|^zusammenfassung\s+von\s+(https?://\S+)$"
    r"|^(?:fasse(?:\s+mal)?\s+)?(?:die\s+)?seite\s+(https?://\S+)(?:\s+zusammen)?$",
    re.IGNORECASE,
)

# Regex fuer Audio-Modus: "audio lokal an", "audio lokal aus"
AUDIO_LOCAL_PATTERN = re.compile(
    r"^audio\s+lokal\s+(an|aus|ein|off|on)$",
    re.IGNORECASE,
)

# Regex: "zusammenfassung C:\...\datei.pdf", "fasse zusammen /path/to/file.txt"
# Auch: "fasse C:\...\datei.pdf zusammen"
DOCUMENT_SUMMARY_PATTERN = re.compile(
    r"(?:zusammenfassung|fasse\s+zusammen)\s+"
    r"([a-zA-Z]:\\[^\s]+|/[^\s]+)"
    r"|fasse\s+([a-zA-Z]:\\[^\s]+|/[^\s]+)\s+zusammen",
    re.IGNORECASE,
)

# Regex fuer Computer Use: "klick auf den OK-Button", "tippe Hello World",
# "scroll runter", "drueck Strg+S"
# Toleriert natuerliche Sprache: "klick mal auf", "bitte klick auf", "auf X klicken"
COMPUTER_USE_PATTERN = re.compile(
    r"^(?:klick(?:e)?\s+(?:mal\s+)?auf\s+(.+)"   # klick [mal] auf <Element>
    r"|(?:auf\s+(.+?)\s+klicken)"                  # auf <Element> klicken
    r"|tippe\s+(.+)"                                # tippe <Text>
    r"|scroll(?:e?)\s+(runter|hoch|nach\s+\w+)"    # scroll runter/hoch/nach unten
    r"|dr\u00fcck(?:e)?\s+(.+))$",                  # drueck <Taste>
    re.IGNORECASE,
)

# Regex fuer Web-Suche: "suche Dachdecker", "such mal Python Tutorial",
# "google Rezept Lasagne", "finde Dachdecker in der Naehe"
WEB_SEARCH_PATTERN = re.compile(
    r"^(?:such\s+mal|suche?|google|finde)\s+(.+)$",
    re.IGNORECASE,
)


class AdvancedCommandHandler(CommandHandler):
    """Handler fuer Computer Use, Web Search, Document Summary, Audio."""

    def __init__(
        self,
        computer_use: ComputerUseController | None = None,
        search_client: BraveSearchClient | None = None,
        document_reader: DocumentReader | None = None,
        audio_router: AudioRouter | None = None,
        web_fetcher: WebFetcher | None = None,
    ) -> None:
        self._computer_use = computer_use
        self._search_client = search_client
        self._document_reader = document_reader
        self._audio_router = audio_router
        self._web_fetcher = web_fetcher

    @property
    def simple_commands(self) -> set[str]:
        return {"audio"}

    @property
    def patterns(self) -> list[tuple[re.Pattern, str, bool, bool]]:
        return [
            (AUDIO_LOCAL_PATTERN, "audio_toggle", False, False),
            (WEB_SUMMARY_PATTERN, "web_summary", True, True),
            (DOCUMENT_SUMMARY_PATTERN, "document_summary", True, True),
            (COMPUTER_USE_PATTERN, "computer_use", False, False),
            (WEB_SEARCH_PATTERN, "web_search", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "zusammenfassung <pfad>: PDF/TXT zusammenfassen",
            "fasse <url> zusammen: Webseite zusammenfassen",
            "suche <begriff>: Im Internet suchen (Brave Search)",
            "klick auf <element> / tippe <text> / scroll runter|hoch / drück <taste>: PC-Steuerung per Vision",
            "audio / audio lokal an / audio lokal aus: Audio-Modus steuern",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "web_summary": [
                "fasse die seite zusammen", "webseite zusammenfassen",
                "url zusammenfassen", "fasse den artikel zusammen",
                "artikel zusammenfassen", "link zusammenfassen",
            ],
            "document_summary": [
                "fasse die pdf zusammen", "pdf zusammenfassen",
                "dokument zusammenfassen", "zusammenfassung der datei",
                "datei zusammenfassen", "fass das zusammen",
            ],
            "audio_toggle": [
                "audio lokal", "lokale wiedergabe", "ton am pc",
                "sound am pc", "lautsprecher am pc",
            ],
            "computer_use": [
                "klick auf", "klicke auf", "klick mal auf", "dr\u00fcck auf",
                "tippe in", "scroll runter", "scroll hoch", "scroll nach",
                "auf accept klicken", "auf ok klicken",
                "auf den button klicken", "kannst du das anklicken",
            ],
            "web_search": [
                "such mir", "suche mir", "suche mal", "such mal",
                "google mal", "google mir", "recherchiere",
                "finde heraus", "im internet suchen",
                "nachschauen im internet", "schau mal im netz",
                "im netz suchen", "kannst du nachschauen",
            ],
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "web_summary":
            return self._cmd_web_summary(raw_text)

        if command == "document_summary":
            return self._cmd_document_summary(raw_text)

        if command in ("audio", "audio_toggle"):
            return self._cmd_audio(raw_text)

        if command == "computer_use":
            return self._cmd_computer_use(raw_text)

        if command == "web_search":
            return self._cmd_search(raw_text)

        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Command: {command}",
        )

    # ------------------------------------------------------------------
    # Dokument-Zusammenfassung
    # ------------------------------------------------------------------

    def _cmd_document_summary(self, raw_text: str) -> CommandResult:
        """Liest ein PDF/TXT-Dokument und liefert den extrahierten Text."""
        if not self._document_reader:
            return CommandResult(
                command="document_summary", success=False,
                text="DocumentReader nicht verf\u00fcgbar.",
            )

        # Pfad aus dem Regex extrahieren
        match = DOCUMENT_SUMMARY_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="document_summary", success=False,
                text="Pfad nicht erkannt. Beispiel: zusammenfassung C:\\Docs\\report.pdf",
            )

        file_path_str = match.group(1) or match.group(2)
        file_path = Path(file_path_str)

        # Pr\u00fcfe ob Datei unterst\u00fctzt wird
        if not self._document_reader.is_supported(file_path):
            return CommandResult(
                command="document_summary", success=False,
                text=f"Dateiformat '{file_path.suffix}' nicht unterst\u00fctzt. "
                     f"Erlaubt: PDF, TXT.",
            )

        try:
            result = self._document_reader.read_file(file_path)

            # Header f\u00fcr User-Antwort (Bridge schickt das ans LLM)
            header = f"\U0001f4c4 {result.source} ({result.pages} Seite(n))"
            if result.truncated:
                header += " [gek\u00fcrzt]"

            # text: kurzer Header (Bridge ersetzt das durch LLM-Zusammenfassung)
            # history_text: Rohtext f\u00fcr LLM-Kontext (R\u00fcckfragen m\u00f6glich)
            return CommandResult(
                command="document_summary",
                success=True,
                text=header,
                history_text=f"Dokument '{result.source}' ({result.pages} Seiten):\n\n{result.text}",
            )

        except FileNotFoundError:
            return CommandResult(
                command="document_summary", success=False,
                text=f"Datei nicht gefunden: {file_path}",
            )
        except Exception as e:
            logger.error("Dokument-Zusammenfassung fehlgeschlagen: %s", e)
            return CommandResult(
                command="document_summary", success=False,
                text=f"Fehler beim Lesen: {e}",
            )

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _cmd_audio(self, raw_text: str) -> CommandResult:
        """Audio-Modus anzeigen oder umschalten."""
        if not self._audio_router:
            return CommandResult(
                command="audio", success=False,
                text="AudioRouter nicht verf\u00fcgbar.",
            )

        from elder_berry.core.audio_router import AudioOutputMode

        normalized = raw_text.strip().lower()
        match = AUDIO_LOCAL_PATTERN.match(normalized)

        if match:
            flag = match.group(1)
            if flag in ("an", "ein", "on"):
                new_mode = self._audio_router.set_mode(AudioOutputMode.MATRIX_AND_LOCAL)
            else:
                new_mode = self._audio_router.set_mode(AudioOutputMode.MATRIX_ONLY)
        else:
            # Nur Status anzeigen (bei "audio" ohne Parameter)
            mode = self._audio_router.mode
            local = "verf\u00fcgbar" if self._audio_router.local_available else "nicht verf\u00fcgbar"
            return CommandResult(
                command="audio", success=True,
                text=f"Audio-Modus: {mode.value}\nLokale Wiedergabe: {local}",
            )

        mode_text = {
            AudioOutputMode.MATRIX_ONLY: "Nur Matrix",
            AudioOutputMode.MATRIX_AND_LOCAL: "Matrix + Lokal",
        }
        return CommandResult(
            command="audio", success=True,
            text=f"Audio-Modus: {mode_text.get(new_mode, new_mode.value)}",
        )

    # ------------------------------------------------------------------
    # Computer Use (Vision-gesteuerte PC-Bedienung)
    # ------------------------------------------------------------------

    def _cmd_computer_use(self, raw_text: str) -> CommandResult:
        """F\u00fchrt eine Computer-Use-Aktion aus (Vision + PC-Steuerung).

        Erkennt nat\u00fcrliche Anweisungen wie:
        - "klick auf den OK-Button"
        - "tippe Hello World"
        - "scroll runter"
        - "dr\u00fcck Strg+S"
        """
        if not self._computer_use:
            return CommandResult(
                command="computer_use", success=False,
                text="Computer Use nicht verf\u00fcgbar (AnthropicClient oder ActionController fehlt).",
            )

        # Originaltext als Anweisung an den Controller weiterleiten
        instruction = raw_text.strip()

        try:
            result = self._computer_use.execute_instruction(instruction)
        except Exception as e:
            logger.error("Computer Use fehlgeschlagen: %s", e)
            return CommandResult(
                command="computer_use", success=False,
                text=f"Computer Use fehlgeschlagen: {e}",
            )

        return CommandResult(
            command="computer_use",
            success=result.success,
            text=result.message,
            image_path=result.verification_image_path,
        )

    # ------------------------------------------------------------------
    # Web-Zusammenfassung
    # ------------------------------------------------------------------

    def _cmd_web_summary(self, raw_text: str) -> CommandResult:
        """Webseite abrufen und Klartext fuer LLM-Zusammenfassung liefern."""
        if not self._web_fetcher:
            return CommandResult(
                command="web_summary", success=False,
                text="WebFetcher nicht verfuegbar.",
            )

        # URL aus dem Regex extrahieren (3 Gruppen moeglich)
        match = WEB_SUMMARY_PATTERN.search(raw_text.strip())
        if not match:
            return CommandResult(
                command="web_summary", success=False,
                text="URL nicht erkannt. Beispiel: fasse https://example.com zusammen",
            )

        url = match.group(1) or match.group(2) or match.group(3)

        try:
            content = self._web_fetcher.fetch(url)
        except ValueError as exc:
            return CommandResult(
                command="web_summary", success=False,
                text=f"Ungueltige URL: {exc}",
            )
        except Exception as exc:
            logger.error("Web-Zusammenfassung fehlgeschlagen fuer %s: %s", url, exc)

            # Fallback: Brave Search Snippet
            if self._search_client:
                try:
                    results = self._search_client.search(url)
                    snippet = self._search_client.format_results(results)
                    if snippet:
                        return CommandResult(
                            command="web_summary",
                            success=True,
                            text=f"\U0001f310 {url} [Volltext nicht verfuegbar, Snippet:]",
                            history_text=f"Webseite '{url}' (Snippet via Suche):\n\n{snippet}",
                        )
                except Exception as search_exc:
                    logger.warning("Brave-Search-Fallback fehlgeschlagen: %s", search_exc)

            return CommandResult(
                command="web_summary", success=False,
                text=f"Seite konnte nicht gelesen werden: {exc}",
            )

        header = f"\U0001f310 {content.title} ({content.url})"
        if content.truncated:
            header += " [gekuerzt]"

        return CommandResult(
            command="web_summary",
            success=True,
            text=header,
            history_text=f"Webseite '{content.title}' ({content.url}):\n\n{content.text}",
        )

    # ------------------------------------------------------------------
    # Web-Suche
    # ------------------------------------------------------------------

    def _cmd_search(self, raw_text: str) -> CommandResult:
        """Web-Suche via Brave Search API.

        Extrahiert den Suchbegriff aus dem Text und gibt formatierte
        Ergebnisse zur\u00fcck. Rohe Ergebnisse werden in history_text
        gespeichert, damit das LLM bei R\u00fcckfragen darauf zugreifen kann.
        """
        if not self._search_client:
            return CommandResult(
                command="web_search", success=False,
                text="Web-Suche nicht verf\u00fcgbar (Brave API-Key fehlt).",
            )

        # Suchbegriff extrahieren
        match = WEB_SEARCH_PATTERN.match(raw_text.strip())
        if match:
            query = match.group(1).strip()
        else:
            # Keyword-Match: versuche "suche" / "google" etc. zu entfernen
            query = raw_text.strip()
            for prefix in ("such mir", "suche mir", "suche mal", "such mal",
                           "google mal", "google mir", "recherchiere",
                           "finde heraus", "im internet suchen"):
                lower = query.lower()
                if lower.startswith(prefix):
                    query = query[len(prefix):].strip()
                    break

        if not query:
            return CommandResult(
                command="web_search", success=False,
                text="Bitte gib einen Suchbegriff an (z.B. 'suche Dachdecker Plattenburg').",
            )

        try:
            results = self._search_client.search(query)
        except Exception as e:
            logger.error("Web-Suche fehlgeschlagen: %s", e)
            return CommandResult(
                command="web_search", success=False,
                text=f"Web-Suche fehlgeschlagen: {e}",
            )

        text = self._search_client.format_results(results)
        history = self._search_client.format_results_detailed(results)

        return CommandResult(
            command="web_search",
            success=True,
            text=text,
            history_text=history,
        )
