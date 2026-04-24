"""Abstrakte Basisklassen und DTOs für das Memory-System."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class MemoryEntry:
    """
    Eine einzelne Erinnerung – eine Nachricht im Gespräch.

    Attributes:
        id:         Eindeutige ID (UUID4-String).
        role:       "user" | "assistant" | "system"
        content:    Der Nachrichtentext.
        timestamp:  UTC-Zeitstempel.
        session_id: Zugehörige Session (ein Gespräch = eine Session).
        metadata:   Optionale Zusatzinfos (z.B. emotion, action_taken).
    """

    id: str
    role: str
    content: str
    timestamp: datetime
    session_id: str
    metadata: dict = field(default_factory=dict, compare=False, hash=False)

    @staticmethod
    def create(
        role: str,
        content: str,
        session_id: str,
        metadata: dict | None = None,
    ) -> "MemoryEntry":
        """Factory: erstellt Entry mit auto-generierter ID und aktuellem Timestamp."""
        return MemoryEntry(
            id=str(uuid.uuid4()),
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
            metadata=metadata or {},
        )


@dataclass
class MemoryContext:
    """
    Zusammengestellter Kontext aus dem Gedächtnis für den System-Prompt.

    Attributes:
        recent:   Letzte N Nachrichten (zeitlich sortiert, älteste zuerst).
        relevant: K semantisch ähnliche Nachrichten zur aktuellen Anfrage.
    """

    recent: list[MemoryEntry]
    relevant: list[MemoryEntry]

    def to_prompt_text(self, max_chars: int = 3000) -> str:
        """
        Formatiert den Memory-Kontext als Text für den System-Prompt.

        Gibt einen leeren String zurück wenn beide Listen leer sind.
        """
        sections: list[str] = []

        if self.recent:
            lines = ["[Letzte Nachrichten]"]
            for entry in self.recent:
                ts = entry.timestamp.strftime("%d.%m. %H:%M")
                lines.append(f"  [{ts}] {entry.role}: {entry.content[:200]}")
            sections.append("\n".join(lines))

        # Relevante Erinnerungen die NICHT bereits in recent sind
        recent_ids = {e.id for e in self.recent}
        unique_relevant = [e for e in self.relevant if e.id not in recent_ids]
        if unique_relevant:
            lines = ["[Relevante Erinnerungen]"]
            for entry in unique_relevant:
                ts = entry.timestamp.strftime("%d.%m.%Y %H:%M")
                lines.append(f"  [{ts}] {entry.role}: {entry.content[:200]}")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        result = "\n\n".join(sections)
        return result[:max_chars] if len(result) > max_chars else result

    def is_empty(self) -> bool:
        return not self.recent and not self.relevant


class MemoryStore(ABC):
    """
    Abstrakte Schnittstelle für das Konversations-Gedächtnis.

    Implementierungen:
        ChromaMemoryStore – ChromaDB + semantische Vektorsuche (Produktion)
    """

    @abstractmethod
    def add(self, entry: MemoryEntry) -> None:
        """Speichert einen neuen Memory-Eintrag."""
        ...

    @abstractmethod
    def get_recent(
        self,
        n: int = 10,
        session_id: str | None = None,
    ) -> list[MemoryEntry]:
        """
        Gibt die letzten N Einträge zurück (zeitlich sortiert, älteste zuerst).

        Args:
            n:          Maximale Anzahl Einträge.
            session_id: Wenn gesetzt, nur Einträge dieser Session.
        """
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        k: int = 5,
        exclude_session: str | None = None,
    ) -> list[MemoryEntry]:
        """
        Semantische Suche nach ähnlichen Einträgen.

        Args:
            query:           Suchanfrage (wird in Embedding umgewandelt).
            k:               Maximale Anzahl Treffer.
            exclude_session: Session-ID die ausgeschlossen werden soll (z.B. aktuelle).
        """
        ...

    def get_context(
        self,
        query: str,
        recent_n: int = 8,
        relevant_k: int = 4,
        current_session_id: str | None = None,
    ) -> MemoryContext:
        """
        Standard-Implementierung: kombiniert recency + semantic search.

        Args:
            query:              Aktuelle Nutzereingabe (für semantische Suche).
            recent_n:           Letzte N Nachrichten der aktuellen Session.
            relevant_k:         K semantisch ähnliche aus früheren Sessions.
            current_session_id: Aktuelle Session (für recency + exclude bei search).
        """
        recent = self.get_recent(n=recent_n, session_id=current_session_id)
        relevant = self.search(
            query=query,
            k=relevant_k,
            exclude_session=current_session_id,
        )
        return MemoryContext(recent=recent, relevant=relevant)

    @abstractmethod
    def new_session(self) -> str:
        """Erstellt eine neue Session-ID und gibt sie zurück."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Löscht alle gespeicherten Einträge (für Tests / Reset)."""
        ...
