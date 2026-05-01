"""Elder-Berry Memory – RAG-basiertes Konversations-Gedächtnis."""

from .base import MemoryEntry, MemoryContext, MemoryStore
from .embedding import EmbeddingClient, OllamaEmbeddingClient

__all__ = [
    "MemoryEntry",
    "MemoryContext",
    "MemoryStore",
    "EmbeddingClient",
    "OllamaEmbeddingClient",
]
