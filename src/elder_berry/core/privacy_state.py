"""PrivacyState – geräteweiter Laufzeitschalter für den lokalen Modus.

Phase 98: Im Privacy-Modus laufen STT, TTS und LLM **ausschließlich** über die
lokale Pipeline (Tower-FasterWhisper, Tower-XTTS bzw. lokale Engine, Ollama).
Die Semantik ist **hart**: ein Cloud-Call ist ein Fehler, kein stiller
Fallback – lieber sichtbar scheitern als heimlich Audio/Text in die Cloud
schicken.

Scope (bewusst): geräteweit (ein physisches Mikrofon/Lautsprecher), nicht pro
Matrix-Raum. Default ist **aus** – Privacy wird explizit eingeschaltet und gilt
nur zur Laufzeit (kein persistenter Zustand über Neustart).

Wird per DI in ``LLMRouter``, ``STTRouter`` und ``TTSRouter`` injiziert.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PrivacyState:
    """Teilbarer Ein/Aus-Schalter für den lokalen Modus."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        if not self._enabled:
            logger.info("Privacy-Modus AKTIVIERT – STT/TTS/LLM nur noch lokal")
        self._enabled = True

    def disable(self) -> None:
        if self._enabled:
            logger.info("Privacy-Modus DEAKTIVIERT – Cloud-Backends wieder erlaubt")
        self._enabled = False

    def toggle(self) -> bool:
        """Schaltet um und gibt den neuen Zustand zurück."""
        if self._enabled:
            self.disable()
        else:
            self.enable()
        return self._enabled
