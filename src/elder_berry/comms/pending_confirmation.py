"""PendingConfirmation – Generischer Bestätigungs-Mechanismus.

Speichert eine ausstehende Aktion pro User mit TTL.
Wird von der Bridge zwischen Command-Erkennung und LLM-Fallback geprüft.

Verwendung:
    store = PendingConfirmationStore()
    store.set("@user:matrix.org", PendingAction(
        action_type="mail_reply",
        description="Draft für #4523",
        data={"to": "info@firma.de", "draft_text": "..."},
    ))
    response_type, action = store.check_response("@user:matrix.org", "ja")
    # response_type == "confirm", action == PendingAction(...)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Standard-TTL: 5 Minuten
DEFAULT_TTL_SECONDS = 300

# Bestätigungs-Antworten
CONFIRM_WORDS = frozenset(
    {"ja", "yes", "senden", "send", "ok", "passt", "abschicken"}
)
CANCEL_WORDS = frozenset(
    {"nein", "no", "abbrechen", "cancel", "verwerfen", "stopp"}
)
MODIFY_PREFIX = "ändern:"


@dataclass
class PendingAction:
    """Eine ausstehende Aktion die auf Bestätigung wartet."""

    action_type: str
    """Typ der Aktion (z.B. 'mail_reply', 'mail_delete')."""

    description: str
    """Menschenlesbare Beschreibung für den Nutzer."""

    data: dict[str, Any] = field(default_factory=dict)
    """Aktions-spezifische Daten (z.B. msg_id, draft_text, to, subject)."""

    created_at: float = field(default_factory=time.time)
    """Unix-Timestamp der Erstellung."""

    ttl: float = DEFAULT_TTL_SECONDS
    """Time-to-live in Sekunden."""

    @property
    def is_expired(self) -> bool:
        """True wenn die Aktion abgelaufen ist."""
        return (time.time() - self.created_at) > self.ttl


class PendingConfirmationStore:
    """Speichert ausstehende Aktionen pro User.

    Thread-safe: Python GIL + dict-Operationen sind atomar.
    Eine Aktion pro User (keine Queue).
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}

    def set(self, user_id: str, action: PendingAction) -> None:
        """Setzt eine ausstehende Aktion für einen User.

        Überschreibt eine eventuell bestehende Aktion (nur eine pro User).
        """
        self._pending[user_id] = action
        logger.info(
            "PendingAction gesetzt für %s: %s (TTL: %.0fs)",
            user_id, action.action_type, action.ttl,
        )

    def get(self, user_id: str) -> PendingAction | None:
        """Holt die ausstehende Aktion für einen User.

        Returns:
            PendingAction oder None (wenn keine oder abgelaufen).
        """
        action = self._pending.get(user_id)
        if action is None:
            return None
        if action.is_expired:
            logger.info(
                "PendingAction abgelaufen für %s: %s",
                user_id, action.action_type,
            )
            del self._pending[user_id]
            return None
        return action

    def clear(self, user_id: str) -> None:
        """Entfernt die ausstehende Aktion für einen User."""
        self._pending.pop(user_id, None)

    def check_response(
        self, user_id: str, text: str,
    ) -> tuple[str, PendingAction | None]:
        """Prüft ob ein Text eine Bestätigungs-Antwort ist.

        Args:
            user_id: Absender.
            text: Nachrichtentext.

        Returns:
            Tuple von (response_type, action):
            - ("confirm", action) → User hat bestätigt
            - ("cancel", action) → User hat abgebrochen
            - ("modify", action) → User will ändern
            - ("pending", action) → anderer Text, aber Aktion ist offen
            - ("none", None) → keine offene Aktion
        """
        action = self.get(user_id)
        if action is None:
            return ("none", None)

        normalized = text.strip().lower()

        if normalized in CONFIRM_WORDS:
            # NICHT clear() hier – Bridge löscht nach erfolgreicher Ausführung
            return ("confirm", action)

        if normalized in CANCEL_WORDS:
            self.clear(user_id)
            return ("cancel", action)

        if normalized.startswith(MODIFY_PREFIX):
            instruction = text[len(MODIFY_PREFIX):].strip()
            action.data["modify_instruction"] = instruction
            return ("modify", action)

        # Auch "ändern:" mit großem Ä prüfen
        if normalized.startswith("ändern:"):
            instruction = text[len("ändern:"):].strip()
            action.data["modify_instruction"] = instruction
            return ("modify", action)

        return ("pending", action)
