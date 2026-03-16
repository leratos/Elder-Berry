"""Anthropic-Client – Claude Sonnet 4.6 als primäres LLM-Backend."""
import os

from dotenv import load_dotenv

from .base import LLMClient

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-6"

# Lazy-Import: anthropic wird erst bei erster Nutzung benötigt
try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False


class AnthropicClient(LLMClient):
    """
    LLM-Client für die Anthropic API (Claude Sonnet 4.6).

    Primäres Backend des LLMRouter – höchste Antwortqualität für
    Charakter-Konsistenz, JSON-Aktionsparsen und RAG-Kontext-Verarbeitung.

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
