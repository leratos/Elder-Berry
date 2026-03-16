"""EmbeddingClient – Abstraktion für Vektor-Embeddings."""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx


class EmbeddingClient(ABC):
    """Einheitliche Schnittstelle für Embedding-Modelle."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Gibt einen Embedding-Vektor für den Text zurück."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Prüft ob der Embedding-Dienst erreichbar ist."""
        ...


class OllamaEmbeddingClient(EmbeddingClient):
    """
    Embedding-Client für Ollama (nomic-embed-text).

    Voraussetzung Tower/Laptop:
        ollama pull nomic-embed-text

    nomic-embed-text produziert 768-dimensionale Vektoren, läuft vollständig
    lokal auf GPU – keine API-Kosten, keine Internetverbindung nötig.
    """

    DEFAULT_MODEL = "nomic-embed-text"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        """Prüft ob Ollama erreichbar ist (gleicher Endpunkt wie OllamaClient)."""
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def embed(self, text: str) -> list[float]:
        """
        Generiert ein Embedding für den Text via Ollama.

        Args:
            text: Zu embeddender Text (wird auf 2048 Tokens gekürzt wenn nötig).

        Returns:
            Embedding-Vektor als Liste von Floats.

        Raises:
            RuntimeError: Wenn Ollama nicht erreichbar oder Fehler auftritt.
        """
        # Grober Schutz gegen zu langen Input (Ollama hat ein Token-Limit)
        if len(text) > 8000:
            text = text[:8000]

        try:
            resp = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama Embedding HTTP-Fehler: {e.response.status_code}"
            ) from e
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(f"Ollama nicht erreichbar für Embeddings: {e}") from e
