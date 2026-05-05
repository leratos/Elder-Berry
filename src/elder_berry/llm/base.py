"""Abstrakte Basisklasse für alle LLM-Clients."""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Einheitliche Schnittstelle für Ollama und OpenRouter."""

    @abstractmethod
    def is_available(self) -> bool:
        """Prüft ob der Client erreichbar ist."""
        pass

    @abstractmethod
    def generate(self, prompt: str, system: str = "") -> str:
        """
        Sendet einen Prompt und gibt die Antwort zurück.

        Args:
            prompt: Der Benutzer-Prompt.
            system: Optionaler System-Prompt.

        Returns:
            Antwort-Text des Modells.

        Raises:
            RuntimeError: Wenn der Client nicht verfügbar oder die Anfrage fehlschlägt.
        """
        pass
