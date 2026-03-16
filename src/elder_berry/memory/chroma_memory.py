"""ChromaMemoryStore – RAG-Gedächtnis mit ChromaDB + Ollama-Embeddings."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .base import MemoryEntry, MemoryStore
from .embedding import EmbeddingClient

# ChromaDB: Lazy-Import (optional dependency)
try:
    import chromadb
    from chromadb import Collection
    _CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore[assignment]
    Collection = None  # type: ignore[assignment]
    _CHROMA_AVAILABLE = False

DEFAULT_COLLECTION = "elder_berry_memories"
DEFAULT_DB_PATH = Path.home() / ".elder-berry" / "memory"


class _OllamaEmbeddingFunction:
    """Wrapper: OllamaEmbeddingClient → ChromaDB EmbeddingFunction-Interface."""

    def __init__(self, client: EmbeddingClient) -> None:
        self._client = client

    def name(self) -> str:
        """ChromaDB ruft name() als Methode auf."""
        return "ollama_embedding"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._client.embed(text) for text in input]


class ChromaMemoryStore(MemoryStore):
    """
    RAG-Gedächtnis basierend auf ChromaDB.

    Speichert alle Konversations-Nachrichten als Vektoren und ermöglicht
    semantische Suche nach ähnlichen Erinnerungen.

    Embedding-Strategie:
        - Mit OllamaEmbeddingClient: nomic-embed-text (lokal, empfohlen)
        - Ohne EmbeddingClient:       ChromaDB Default (lädt Modell beim ersten Start)

    Args:
        db_path:          Pfad zur ChromaDB-Datenbank (persistent).
        embedding_client: Optionaler EmbeddingClient (OllamaEmbeddingClient).
        collection_name:  Name der ChromaDB-Collection.

    Raises:
        RuntimeError: Wenn chromadb-Paket nicht installiert ist.
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        embedding_client: EmbeddingClient | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        if not _CHROMA_AVAILABLE:
            raise RuntimeError(
                "chromadb-Paket nicht installiert. "
                "Installiere es mit: pip install chromadb"
            )
        self._db_path = Path(db_path)
        self._embedding_client = embedding_client
        self._collection_name = collection_name
        self._client: chromadb.PersistentClient | None = None
        self._collection: Collection | None = None

    def _get_collection(self) -> Collection:
        """Lazy-Init: erstellt ChromaDB-Client + Collection bei erster Nutzung."""
        if self._collection is None:
            self._db_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._db_path))

            kwargs: dict = {"name": self._collection_name}
            if self._embedding_client is not None:
                kwargs["embedding_function"] = _OllamaEmbeddingFunction(
                    self._embedding_client
                )
            self._collection = self._client.get_or_create_collection(**kwargs)
        return self._collection

    # ------------------------------------------------------------------
    # MemoryStore Interface
    # ------------------------------------------------------------------

    def add(self, entry: MemoryEntry) -> None:
        """Speichert einen MemoryEntry in ChromaDB."""
        col = self._get_collection()
        col.add(
            ids=[entry.id],
            documents=[entry.content],
            metadatas=[{
                "role": entry.role,
                "session_id": entry.session_id,
                "timestamp_iso": entry.timestamp.isoformat(),
                "timestamp_unix": entry.timestamp.timestamp(),
                **{k: str(v) for k, v in entry.metadata.items()},
            }],
        )

    def get_recent(
        self,
        n: int = 10,
        session_id: str | None = None,
    ) -> list[MemoryEntry]:
        """
        Gibt die letzten N Einträge zurück, optional gefiltert nach Session.

        Sortiert nach Timestamp (älteste zuerst).
        """
        col = self._get_collection()

        where = {"session_id": session_id} if session_id else None
        kwargs: dict = {"include": ["documents", "metadatas"]}
        if where:
            kwargs["where"] = where

        result = col.get(**kwargs)
        entries = self._result_to_entries(result)

        # Sortieren nach Timestamp (älteste zuerst), letzte n zurückgeben
        entries.sort(key=lambda e: e.timestamp)
        return entries[-n:] if len(entries) > n else entries

    def search(
        self,
        query: str,
        k: int = 5,
        exclude_session: str | None = None,
    ) -> list[MemoryEntry]:
        """
        Semantische Ähnlichkeitssuche mit dem Embedding des Query-Texts.

        Args:
            query:           Suchanfrage.
            k:               Maximale Anzahl Treffer.
            exclude_session: Session-ID die ausgeschlossen wird.

        Returns:
            Liste von MemoryEntries sortiert nach Relevanz (ähnlichste zuerst).
        """
        col = self._get_collection()

        total = col.count()
        if total == 0:
            return []

        # Wir brauchen mehr als k wenn wir nachher filtern
        n_results = min(total, k * 3 if exclude_session else k)

        kwargs: dict = {
            "query_texts": [query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if exclude_session:
            kwargs["where"] = {"session_id": {"$ne": exclude_session}}
            # Nach Filterung evtl. weniger Treffer → erneut count
            filtered_count = col.count()  # Annäherung, ChromaDB filtert intern
            if filtered_count == 0:
                return []

        try:
            result = col.query(**kwargs)
        except Exception:
            return []

        entries = self._query_result_to_entries(result)
        return entries[:k]

    def new_session(self) -> str:
        """Erstellt eine neue eindeutige Session-ID."""
        return str(uuid.uuid4())

    def clear(self) -> None:
        """Löscht alle Einträge aus der Collection."""
        col = self._get_collection()
        ids_result = col.get(include=[])
        if ids_result["ids"]:
            col.delete(ids=ids_result["ids"])

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _result_to_entries(self, result: dict) -> list[MemoryEntry]:
        """Wandelt ChromaDB get()-Ergebnis in MemoryEntry-Liste um."""
        entries = []
        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])

        for i, entry_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""
            entries.append(self._meta_to_entry(entry_id, doc, meta))
        return entries

    def _query_result_to_entries(self, result: dict) -> list[MemoryEntry]:
        """Wandelt ChromaDB query()-Ergebnis in MemoryEntry-Liste um."""
        entries = []
        ids_list = result.get("ids", [[]])[0]
        docs_list = result.get("documents", [[]])[0]
        metas_list = result.get("metadatas", [[]])[0]

        for i, entry_id in enumerate(ids_list):
            meta = metas_list[i] if i < len(metas_list) else {}
            doc = docs_list[i] if i < len(docs_list) else ""
            entries.append(self._meta_to_entry(entry_id, doc, meta))
        return entries

    @staticmethod
    def _meta_to_entry(entry_id: str, doc: str, meta: dict) -> MemoryEntry:
        """Erstellt ein MemoryEntry aus ChromaDB-Metadaten."""
        ts_iso = meta.get("timestamp_iso", "")
        try:
            timestamp = datetime.fromisoformat(ts_iso)
        except (ValueError, TypeError):
            timestamp = datetime.now(timezone.utc)

        # Core-Felder aus metadata extrahieren, Rest als metadata behalten
        core_keys = {"role", "session_id", "timestamp_iso", "timestamp_unix"}
        extra_meta = {k: v for k, v in meta.items() if k not in core_keys}

        return MemoryEntry(
            id=entry_id,
            role=meta.get("role", "unknown"),
            content=doc,
            timestamp=timestamp,
            session_id=meta.get("session_id", ""),
            metadata=extra_meta,
        )
