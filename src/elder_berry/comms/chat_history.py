"""ChatHistory – Kurzzeit-Konversationsgedächtnis pro User (Sliding Window).

Speichert die letzten N Nachrichten pro User als Kontext für das LLM.
Getrennt von RAG-Memory (ChromaDB = Langzeit, ChatHistory = Kurzzeit Session).

Rolling Summary (Phase 23): Wenn Nachrichten aus dem Window rotieren, werden
sie zu einer kompakten Zusammenfassung komprimiert (max 3 Sätze). So behält
das LLM das Gesamtbild, auch wenn ältere Nachrichten nicht mehr im Window sind.

Verwendung:
    history = ChatHistory(max_messages=10, summarizer=my_summarizer)
    history.add("@user:matrix.org", "user", "Suche mail von RK Bedachung")
    history.add("@user:matrix.org", "assistant", "3 Mails gefunden: ...")
    context = history.format_for_prompt("@user:matrix.org")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

# Type alias für den Summarizer-Callback:
# (bisherige_zusammenfassung, evicted_nachrichten) → neue_zusammenfassung
Summarizer = Callable[[str, list["ChatMessage"]], str]

# Anzahl evicted Messages bevor ein Summary-Update getriggert wird
EVICTION_BATCH_SIZE = 3


@dataclass(frozen=True)
class ChatMessage:
    """Eine einzelne Nachricht im Chat-Verlauf."""

    role: str
    """'user' oder 'assistant'."""

    text: str
    """Nachrichtentext."""

    timestamp: float
    """Unix-Timestamp."""


class ChatHistory:
    """Sliding-Window Chat-Verlauf pro User mit Rolling Summary.

    Speichert maximal `max_messages` Nachrichten pro Sender.
    Ältere Nachrichten werden automatisch entfernt (FIFO).
    Wenn ein `summarizer` Callback gesetzt ist, werden evicted Messages
    gesammelt und bei Erreichen von EVICTION_BATCH_SIZE zu einer
    Rolling Summary komprimiert.
    """

    def __init__(
        self,
        max_messages: int = 10,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._max = max_messages
        self._summarizer = summarizer
        self._history: dict[str, list[ChatMessage]] = {}
        self._summaries: dict[str, str] = {}
        self._eviction_buffer: dict[str, list[ChatMessage]] = {}
        self._lock = threading.Lock()

    @property
    def max_messages(self) -> int:
        """Maximale Anzahl Nachrichten pro User."""
        return self._max

    def add(self, sender: str, role: str, text: str) -> None:
        """Fügt eine Nachricht zum Verlauf hinzu.

        Wenn Nachrichten aus dem Window fallen und ein Summarizer gesetzt ist,
        werden sie im Eviction-Buffer gesammelt. Bei EVICTION_BATCH_SIZE
        wird der Summarizer aufgerufen (im Background-Thread).

        Args:
            sender: User-ID (z.B. @user:matrix.org).
            role: 'user' oder 'assistant'.
            text: Nachrichtentext.
        """
        if not text or not text.strip():
            return

        msg = ChatMessage(role=role, text=text.strip(), timestamp=time.time())

        with self._lock:
            if sender not in self._history:
                self._history[sender] = []

            self._history[sender].append(msg)

            # Sliding Window: evicted Messages sammeln
            evicted: list[ChatMessage] = []
            while len(self._history[sender]) > self._max:
                evicted.append(self._history[sender].pop(0))

            if evicted and self._summarizer:
                if sender not in self._eviction_buffer:
                    self._eviction_buffer[sender] = []
                self._eviction_buffer[sender].extend(evicted)

                if len(self._eviction_buffer[sender]) >= EVICTION_BATCH_SIZE:
                    batch = self._eviction_buffer.pop(sender)
                    old_summary = self._summaries.get(sender, "")
                    self._trigger_summary(sender, old_summary, batch)

    def _trigger_summary(
        self, sender: str, old_summary: str, evicted: list[ChatMessage]
    ) -> None:
        """Startet den Summarizer im Background-Thread."""
        thread = threading.Thread(
            target=self._run_summary,
            args=(sender, old_summary, evicted),
            name=f"chat-summary-{sender[:20]}",
            daemon=True,
        )
        thread.start()

    def _run_summary(
        self, sender: str, old_summary: str, evicted: list[ChatMessage]
    ) -> None:
        """Führt den Summarizer aus und speichert das Ergebnis."""
        try:
            new_summary = self._summarizer(old_summary, evicted)
            if new_summary and new_summary.strip():
                with self._lock:
                    self._summaries[sender] = new_summary.strip()
                logger.debug(
                    "Summary aktualisiert für %s (%d Zeichen)", sender, len(new_summary)
                )
        except Exception:
            logger.exception("Fehler beim Erstellen der Zusammenfassung für %s", sender)

    def get_summary(self, sender: str) -> str:
        """Gibt die aktuelle Rolling Summary für einen User zurück."""
        with self._lock:
            return self._summaries.get(sender, "")

    def get(self, sender: str) -> list[ChatMessage]:
        """Gibt den Verlauf für einen User zurück.

        Args:
            sender: User-ID.

        Returns:
            Liste von ChatMessage (chronologisch, älteste zuerst).
        """
        with self._lock:
            return list(self._history.get(sender, []))

    def clear(self, sender: str | None = None) -> None:
        """Löscht den Verlauf.

        Args:
            sender: Wenn angegeben, nur für diesen User. Sonst alles.
        """
        with self._lock:
            if sender:
                self._history.pop(sender, None)
                self._summaries.pop(sender, None)
                self._eviction_buffer.pop(sender, None)
            else:
                self._history.clear()
                self._summaries.clear()
                self._eviction_buffer.clear()

    def format_for_prompt(self, sender: str) -> str:
        """Formatiert den Verlauf als Text für den LLM-Kontext.

        Wenn eine Rolling Summary vorhanden ist, wird sie vor den
        letzten Nachrichten angezeigt.

        Args:
            sender: User-ID.

        Returns:
            Formatierter Text oder leerer String wenn kein Verlauf.
        """
        with self._lock:
            messages = self._history.get(sender, [])
            summary = self._summaries.get(sender, "")

        if not messages and not summary:
            return ""

        parts: list[str] = []

        if summary:
            parts.append(f"Zusammenfassung bisheriges Gespräch:\n{summary}")

        if messages:
            parts.append("Letzte Nachrichten:")
            for msg in messages:
                prefix = "User" if msg.role == "user" else "Saleria"
                text = msg.text
                if len(text) > 500:
                    text = text[:500] + "... (gekürzt)"
                parts.append(f"{prefix}: {text}")

        return "\n".join(parts)
