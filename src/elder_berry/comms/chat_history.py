"""ChatHistory – Kurzzeit-Konversationsgedächtnis pro User (Sliding Window).

Speichert die letzten N Nachrichten pro User als Kontext für das LLM.
Getrennt von RAG-Memory (ChromaDB = Langzeit, ChatHistory = Kurzzeit Session).

Verwendung:
    history = ChatHistory(max_messages=10)
    history.add("@user:matrix.org", "user", "Suche mail von RK Bedachung")
    history.add("@user:matrix.org", "assistant", "3 Mails gefunden: ...")
    context = history.format_for_prompt("@user:matrix.org")
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


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
    """Sliding-Window Chat-Verlauf pro User.

    Speichert maximal `max_messages` Nachrichten pro Sender.
    Ältere Nachrichten werden automatisch entfernt (FIFO).
    """

    def __init__(self, max_messages: int = 10) -> None:
        self._max = max_messages
        self._history: dict[str, list[ChatMessage]] = {}

    @property
    def max_messages(self) -> int:
        """Maximale Anzahl Nachrichten pro User."""
        return self._max

    def add(self, sender: str, role: str, text: str) -> None:
        """Fügt eine Nachricht zum Verlauf hinzu.

        Args:
            sender: User-ID (z.B. @user:matrix.org).
            role: 'user' oder 'assistant'.
            text: Nachrichtentext.
        """
        if not text or not text.strip():
            return

        msg = ChatMessage(role=role, text=text.strip(), timestamp=time.time())

        if sender not in self._history:
            self._history[sender] = []

        self._history[sender].append(msg)

        # Sliding Window: älteste entfernen wenn über Limit
        if len(self._history[sender]) > self._max:
            self._history[sender] = self._history[sender][-self._max:]

    def get(self, sender: str) -> list[ChatMessage]:
        """Gibt den Verlauf für einen User zurück.

        Args:
            sender: User-ID.

        Returns:
            Liste von ChatMessage (chronologisch, älteste zuerst).
        """
        return list(self._history.get(sender, []))

    def clear(self, sender: str | None = None) -> None:
        """Löscht den Verlauf.

        Args:
            sender: Wenn angegeben, nur für diesen User. Sonst alles.
        """
        if sender:
            self._history.pop(sender, None)
        else:
            self._history.clear()

    def format_for_prompt(self, sender: str) -> str:
        """Formatiert den Verlauf als Text für den LLM-Kontext.

        Args:
            sender: User-ID.

        Returns:
            Formatierter Text oder leerer String wenn kein Verlauf.
        """
        messages = self._history.get(sender, [])
        if not messages:
            return ""

        lines = ["Bisheriger Gesprächsverlauf:"]
        for msg in messages:
            prefix = "User" if msg.role == "user" else "Saleria"
            # Text kürzen wenn sehr lang (z.B. lange Mail-Ergebnisse)
            text = msg.text
            if len(text) > 500:
                text = text[:500] + "... (gekürzt)"
            lines.append(f"{prefix}: {text}")

        return "\n".join(lines)
