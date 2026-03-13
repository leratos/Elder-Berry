"""LLMRouter – wählt automatisch Ollama oder OpenRouter."""
import logging

from .base import LLMClient
from .ollama_client import OllamaClient
from .openrouter_client import OpenRouterClient

logger = logging.getLogger(__name__)


class LLMRouter(LLMClient):
    """
    Versucht zuerst Ollama (lokal). Wenn nicht erreichbar → OpenRouter.
    Der Rest des Systems spricht nur mit LLMRouter und merkt nichts vom Wechsel.

    Abhängigkeiten werden explizit per Konstruktor übergeben (Dependency Injection).
    Für den Standard-Anwendungsfall: LLMRouter.create_default()
    """

    def __init__(self, ollama: LLMClient, openrouter: LLMClient) -> None:
        self._ollama = ollama
        self._openrouter = openrouter

    @classmethod
    def create_default(
        cls,
        ollama_model: str | None = None,
        openrouter_model: str | None = None,
    ) -> "LLMRouter":
        """Erstellt Router mit Standard-Clients (Ollama lokal + OpenRouter Cloud)."""
        kwargs_ollama = {"model": ollama_model} if ollama_model else {}
        kwargs_or = {"model": openrouter_model} if openrouter_model else {}
        return cls(
            ollama=OllamaClient(**kwargs_ollama),
            openrouter=OpenRouterClient(**kwargs_or),
        )

    def _select_client(self) -> LLMClient:
        if self._ollama.is_available():
            logger.info("LLM-Backend: Ollama (lokal)")
            return self._ollama
        if self._openrouter.is_available():
            logger.info("LLM-Backend: OpenRouter (Cloud-Fallback)")
            return self._openrouter
        raise RuntimeError(
            "Kein LLM-Backend verfügbar. "
            "Ollama nicht erreichbar und OPENROUTER_API_KEY nicht gesetzt."
        )

    def is_available(self) -> bool:
        return self._ollama.is_available() or self._openrouter.is_available()

    def generate(self, prompt: str, system: str = "") -> str:
        client = self._select_client()
        return client.generate(prompt, system)

    @property
    def active_backend(self) -> str:
        """Gibt den Namen des aktuell aktiven Backends zurück."""
        if self._ollama.is_available():
            return "ollama"
        if self._openrouter.is_available():
            return "openrouter"
        return "none"
