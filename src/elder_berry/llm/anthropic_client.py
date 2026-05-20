"""Anthropic-Client – Claude Sonnet 4.6 als primäres LLM-Backend."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .base import LLMClient

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-6"

# Beta-Header und Tool-Version für Sonnet 4.6 / Opus 4.6 / Opus 4.5
COMPUTER_USE_BETA = "computer-use-2025-11-24"
COMPUTER_USE_TOOL_VERSION = "computer_20251124"

# Lazy-Import: anthropic wird erst bei erster Nutzung benötigt
try:
    import anthropic as _anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False


@dataclass(frozen=True)
class ComputerUseAction:
    """Strukturierte Aktion aus der Computer-Use-API-Antwort."""

    action: str
    coordinate: tuple[int, int] | None = None
    text: str | None = None
    scroll_direction: str | None = None
    scroll_amount: int | None = None
    tool_use_id: str = ""


class AnthropicClient(LLMClient):
    """
    LLM-Client für die Anthropic API (Claude Sonnet 4.6).

    Primäres Backend des LLMRouter – höchste Antwortqualität für
    Charakter-Konsistenz, JSON-Aktionsparsen und RAG-Kontext-Verarbeitung.

    Unterstützt auch Computer Use (Vision + Tool) über die Beta-API.

    Benötigt: ANTHROPIC_API_KEY (Umgebungsvariable oder .env)
              anthropic-Paket: pip install anthropic (oder pip install -e .[remote])
    """

    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _get_client(self):
        """Gibt den Anthropic-SDK-Client zurück (Lazy-Init)."""
        if not _ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic-Paket nicht installiert. "
                "Installiere es mit: pip install anthropic"
            )
        if self._client is None:
            self._client = _anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def _check_available(self) -> None:
        """Prüft ob API-Key und Paket verfügbar sind."""
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY nicht gesetzt. "
                "Setze ihn in .env oder als Umgebungsvariable."
            )
        if not _ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic-Paket nicht installiert. "
                "Installiere es mit: pip install anthropic"
            )

    def is_available(self) -> bool:
        """Verfügbar wenn ANTHROPIC_API_KEY gesetzt ist."""
        return bool(self._api_key)

    def generate(self, prompt: str, system: str = "") -> str:
        """
        Sendet einen Prompt an Claude Sonnet 4.6 und gibt die Antwort zurück.

        Args:
            prompt: Der Benutzer-Prompt.
            system: Optionaler System-Prompt.

        Returns:
            Antwort-Text von Claude.

        Raises:
            RuntimeError: Wenn API-Key fehlt, Paket fehlt oder API-Fehler auftritt.
        """
        self._check_available()

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        try:
            msg = self._get_client().messages.create(**kwargs)
            return msg.content[0].text
        except _anthropic.APIStatusError as e:
            raise RuntimeError(
                f"Anthropic API-Fehler: {e.status_code} – {e.message}"
            ) from e
        except _anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic nicht erreichbar: {e}") from e
        except _anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic Rate-Limit erreicht: {e}") from e

    def tool_call(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 1024,
    ) -> dict:
        """Erzwingt einen Tool-Use-Call und gibt das ``tool_input`` zurueck.

        Phase 92: vom RouteIntentParser genutzt, um Multi-Stop-Anfragen
        in ein strukturiertes Schema zu zwingen (kein Freitext-Roundtrip,
        kein Hallucinations-Risiko). Bewusst generisch -- jeder Caller,
        der eine schema-getreue Antwort braucht, kann das Tool als Dict
        uebergeben und kriegt das geparste Input-Dict zurueck.

        Args:
            prompt: User-Prompt.
            tool: Tool-Definition (Dict mit ``name``, ``description``,
                ``input_schema``).
            system: Optionaler System-Prompt.
            max_tokens: Cap fuer die Antwort. Tool-Calls brauchen normaler-
                weise wenig, Default 1024.

        Returns:
            Das ``input``-Dict des Tool-Use-Blocks. Anthropic erzwingt
            das Schema serverseitig via ``tool_choice``, der Caller
            darf dem trauen.

        Raises:
            RuntimeError: Bei API-Fehlern oder wenn die Antwort keinen
                Tool-Use-Block enthielt (sollte mit ``tool_choice`` nie
                passieren, aber defensiv geprueft).
        """
        self._check_available()

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
        }
        if system:
            kwargs["system"] = system

        try:
            msg = self._get_client().messages.create(**kwargs)
        except _anthropic.APIStatusError as e:
            raise RuntimeError(
                f"Anthropic API-Fehler: {e.status_code} – {e.message}"
            ) from e
        except _anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic nicht erreichbar: {e}") from e
        except _anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic Rate-Limit erreicht: {e}") from e

        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                # SDK liefert input als Dict zurueck.
                return dict(block.input)
        raise RuntimeError(
            f"Anthropic-Antwort enthielt keinen tool_use-Block fuer '{tool['name']}'",
        )

    def describe_image(
        self,
        image_base64: str,
        prompt: str = "Beschreibe was du auf diesem Bild siehst.",
        system: str = "",
        media_type: str = "image/jpeg",
    ) -> str:
        """Analysiert ein Bild per Claude Vision API.

        Nutzt die Standard Messages API (kein Beta nötig).

        Args:
            image_base64: Base64-kodiertes Bild.
            prompt: Frage/Anweisung zum Bild.
            system: Optionaler System-Prompt.
            media_type: MIME-Type (default: image/jpeg).

        Returns:
            Textuelle Beschreibung des Bildes.

        Raises:
            RuntimeError: Bei API-Fehlern.
        """
        self._check_available()

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ]

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        try:
            msg = self._get_client().messages.create(**kwargs)
            return msg.content[0].text
        except _anthropic.APIStatusError as e:
            raise RuntimeError(
                f"Anthropic API-Fehler: {e.status_code} – {e.message}"
            ) from e
        except _anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic nicht erreichbar: {e}") from e
        except _anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic Rate-Limit erreicht: {e}") from e

    def computer_use(
        self,
        screenshot_base64: str,
        instruction: str,
        display_width: int,
        display_height: int,
        system: str = "",
    ) -> ComputerUseAction:
        """
        Sendet einen Screenshot + Anweisung an Claude und erhält eine
        strukturierte Computer-Use-Aktion zurück.

        Nutzt die Beta-API mit computer_20251124 Tool-Definition.

        Args:
            screenshot_base64: Base64-kodierter Screenshot (PNG).
            instruction: Was der User auf dem Bildschirm tun möchte.
            display_width: Breite des Screenshots in Pixeln.
            display_height: Höhe des Screenshots in Pixeln.
            system: Optionaler System-Prompt.

        Returns:
            ComputerUseAction mit action, coordinate, text etc.

        Raises:
            RuntimeError: Bei API-Fehlern oder unerwartetem Antwortformat.
        """
        self._check_available()

        tools = [
            {
                "type": COMPUTER_USE_TOOL_VERSION,
                "name": "computer",
                "display_width_px": display_width,
                "display_height_px": display_height,
            }
        ]

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": instruction,
                    },
                ],
            }
        ]

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "tools": tools,
            "messages": messages,
            "betas": [COMPUTER_USE_BETA],
        }
        if system:
            kwargs["system"] = system

        try:
            response = self._get_client().beta.messages.create(**kwargs)
        except _anthropic.APIStatusError as e:
            raise RuntimeError(
                f"Anthropic API-Fehler: {e.status_code} – {e.message}"
            ) from e
        except _anthropic.APIConnectionError as e:
            raise RuntimeError(f"Anthropic nicht erreichbar: {e}") from e
        except _anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic Rate-Limit erreicht: {e}") from e

        return self._parse_computer_use_response(response)

    @staticmethod
    def _parse_computer_use_response(response) -> ComputerUseAction:
        """Extrahiert die Computer-Use-Aktion aus der API-Antwort."""
        for block in response.content:
            if block.type == "tool_use" and block.name == "computer":
                inp = block.input
                coord = inp.get("coordinate")
                return ComputerUseAction(
                    action=inp["action"],
                    coordinate=tuple(coord) if coord else None,
                    text=inp.get("text"),
                    scroll_direction=inp.get("scroll_direction"),
                    scroll_amount=inp.get("scroll_amount"),
                    tool_use_id=block.id,
                )

        # Kein Tool-Use-Block → Claude hat nur Text geantwortet
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        text_response = " ".join(text_parts) if text_parts else "Keine Aktion erkannt."
        raise RuntimeError(
            f"Computer Use: Keine Aktion in der Antwort. Claude sagt: {text_response}"
        )
