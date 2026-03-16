"""LLMRouter – primäres Backend (Anthropic) mit Offline-Fallback (Ollama)."""
import logging

from .base import LLMClient
from .anthropic_client import AnthropicClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class LLMRouter(LLMClient):
    """
    Wählt automatisch das beste verfügbare LLM-Backend.

    Standard-Kette:  AnthropicClient (Sonnet 4.6) → OllamaClient (offline)

    Abhängigkeiten werden explizit per Konstruktor übergeben (Dependency Injection).
    Für den Standard-Anwendungsfall: LLMRouter.create_default()
    """

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self._primary = primary
        self._fallback = fallback

    @classmethod
    def create_default(
        cls,
        primary_model: str | None = None,
        fallback_model: str | None = None,
    ) -> "LLMRouter":
        """
        Erstellt Router mit Standard-Kette: Anthropic (Sonnet 4.6) → Ollama (phi4:14b).

        Args:
            primary_model:  Anthropic-Modell (default: claude-sonnet-4-6)
            fallback_model: Ollama-Modell    (default: phi4:14b)
        """
        kwargs_primary = {"model": primary_model} if primary_model else {}
        kwargs_fallback = {"model": fallback_model} if fallback_model else {}
        return cls(
            primary=AnthropicClient(**kwargs_primary),
            fallback=OllamaClient(**kwargs_fallback),
        )

    def _select_client(self) -> LLMClient:
        if self._primary.is_available():
            name = getattr(self._primary, "name", type(self._primary).__name__)
            logger.info("LLM-Backend: %s (primär)", name)
            return self._primary
        if self._fallback.is_available():
            name = getattr(self._fallback, "name", type(self._fallback).__name__)
            logger.info("LLM-Backend: %s (Fallback)", name)
            return self._fallback
        raise RuntimeError(
            "Kein LLM-Backend verfügbar. "
            "ANTHROPIC_API_KEY nicht gesetzt und Ollama nicht erreichbar."
        )

    def is_available(self) -> bool:
        return self._primary.is_available() or self._fallback.is_available()

    def generate(self, prompt: str, system: str = "") -> str:
        client = self._select_client()
        return client.generate(prompt, system)

    @property
    def active_backend(self) -> str:
        """Gibt den Namen des aktiven Backends zurück (z.B. 'anthropic', 'ollama')."""
        for client in (self._primary, self._fallback):
            if client.is_available():
                return getattr(client, "name", type(client).__name__.lower())
        return "none"
