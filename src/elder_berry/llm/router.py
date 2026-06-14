"""LLMRouter – health-aware Routing über mehrere LLM-Backends.

Phase 98: Der Router fällt nicht mehr nur dann auf das lokale Backend zurück,
wenn der API-Key fehlt, sondern auch bei einem **Laufzeitfehler** des
bevorzugten Backends (Störung/Rate-Limit). Ein schlanker Circuit-Breaker
verhindert Flapping (ein gestörtes Backend wird für eine Cooldown-Zeit
übersprungen), und jeder Backend-Wechsel wird geloggt und einmalig im Chat
markiert (``pop_backend_notice``). Vorbild ist das Runtime-Fallback-Muster aus
``core/tts_router.py`` / ``core/stt_router.py``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .anthropic_client import AnthropicClient
from .base import LLMClient
from .modes import DEFAULT_LLM_MODE, LLM_MODES
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

#: Default-Cooldown (Sekunden), für den ein gestörtes Backend übersprungen wird.
DEFAULT_COOLDOWN_SECONDS = 60.0


@runtime_checkable
class PrivacyLike(Protocol):
    """Strukturelles Subset von ``core.privacy_state.PrivacyState``.

    Der Router braucht nur den Lese-Zugriff ``is_enabled`` und vermeidet so
    einen Import von ``core`` (Import-Richtung bleibt ``core -> llm``).
    """

    @property
    def is_enabled(self) -> bool:
        """True, wenn der Privacy-Modus aktiv ist (lokal-only)."""


class LLMRouter(LLMClient):
    """Wählt zur Laufzeit das beste verfügbare LLM-Backend.

    Modi (kanonisch in :mod:`elder_berry.llm.modes`):

    * ``api_preferred``   – Anthropic → Ollama (Default)
    * ``local_preferred`` – Ollama → Anthropic
    * ``local_only``      – nur Ollama (hart, kein Cloud-Fallback)

    Im Privacy-Modus (injizierter :class:`PrivacyLike`) wird die Kette hart auf
    das lokale Backend reduziert – unabhängig vom gewählten Modus.

    Abhängigkeiten werden explizit per Konstruktor übergeben (DI).
    Standard-Anwendungsfall: :meth:`create_default`.
    """

    VALID_MODES = LLM_MODES

    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient,
        mode: str = DEFAULT_LLM_MODE,
        *,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        time_func: Callable[[], float] = time.monotonic,
        privacy_state: PrivacyLike | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        if mode not in self.VALID_MODES:
            raise ValueError(f"Ungültiger LLM-Modus: {mode}")
        self._mode = mode
        self._cooldown_seconds = cooldown_seconds
        self._time_func = time_func
        self._privacy_state = privacy_state

        # Circuit-Breaker: id(client) -> monotonic-Deadline, bis zu der das
        # Backend übersprungen wird.
        self._cooldown_until: dict[int, float] = {}

        # Degradations-Tracking für die Chat-Markierung.
        self._served_backend: str | None = None
        self._degraded = False
        self._degraded_announced = False

    @classmethod
    def create_default(
        cls,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        *,
        privacy_state: PrivacyLike | None = None,
    ) -> "LLMRouter":
        """Router mit Standard-Kette: Anthropic (Sonnet 4.6) → Ollama (phi4:14b).

        Args:
            primary_model:  Anthropic-Modell (default: claude-sonnet-4-6).
            fallback_model: Ollama-Modell    (default: phi4:14b).
            privacy_state:  Optionaler Privacy-Schalter (hart lokal).
        """
        kwargs_primary = {"model": primary_model} if primary_model else {}
        kwargs_fallback = {"model": fallback_model} if fallback_model else {}
        return cls(
            primary=AnthropicClient(**kwargs_primary),
            fallback=OllamaClient(**kwargs_fallback),
            privacy_state=privacy_state,
        )

    # -- Modus ----------------------------------------------------------------

    @property
    def mode(self) -> str:
        """Aktueller Routing-Modus (s. :data:`elder_berry.llm.modes.LLM_MODES`)."""
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in self.VALID_MODES:
            raise ValueError(f"Ungültiger LLM-Modus: {value}")
        self._mode = value

    # -- Backend-Auswahl ------------------------------------------------------

    def _ordered_backends(self) -> list[LLMClient]:
        """Kandidaten-Reihenfolge je Modus (bestes Backend zuerst).

        Im Privacy-Modus immer hart nur das lokale Backend.
        """
        if self._privacy_state is not None and self._privacy_state.is_enabled:
            return [self._fallback]
        if self._mode == "local_only":
            return [self._fallback]
        if self._mode == "local_preferred":
            return [self._fallback, self._primary]
        # api_preferred (Default)
        return [self._primary, self._fallback]

    def _in_cooldown(self, client: LLMClient) -> bool:
        return self._time_func() < self._cooldown_until.get(id(client), 0.0)

    def _trip_cooldown(self, client: LLMClient) -> None:
        self._cooldown_until[id(client)] = self._time_func() + self._cooldown_seconds

    @staticmethod
    def _name(client: LLMClient) -> str:
        return getattr(client, "name", type(client).__name__.lower())

    def _record_served(self, client: LLMClient, top: LLMClient) -> None:
        """Merkt das bedienende Backend und ob es eine Degradation ist."""
        self._served_backend = self._name(client)
        self._degraded = client is not top

    def is_available(self) -> bool:
        return self._primary.is_available() or self._fallback.is_available()

    def generate(self, prompt: str, system: str = "") -> str:
        """Erzeugt eine Antwort mit Runtime-Fallback über die Backend-Kette.

        Versucht die Backends in mode-abhängiger Reihenfolge. Ein Backend, das
        zur Laufzeit fehlschlägt, wird getrippt (Cooldown) und übersprungen;
        das letzte Backend der Kette wird nie wegen Cooldown ausgelassen
        (Last-Resort). Schlagen alle fehl, fliegt ``RuntimeError``.
        """
        order = self._ordered_backends()
        top = order[0]
        last_error: Exception | None = None

        for index, client in enumerate(order):
            is_last = index == len(order) - 1
            name = self._name(client)

            if not is_last and self._in_cooldown(client):
                logger.debug("LLM-Backend %s im Cooldown – übersprungen", name)
                continue
            if not client.is_available():
                logger.debug("LLM-Backend %s nicht verfügbar – übersprungen", name)
                continue

            try:
                result = client.generate(prompt, system)
            except Exception as exc:  # noqa: BLE001 – Runtime-Fallback auf nächstes Backend
                self._trip_cooldown(client)
                last_error = exc
                logger.warning("LLM-Backend %s fehlgeschlagen: %s", name, exc)
                continue

            if client is top:
                logger.info("LLM-Backend: %s", name)
            else:
                logger.warning(
                    "LLM-Backend: %s (Fallback – bevorzugtes Backend nicht verfügbar)",
                    name,
                )
            self._record_served(client, top)
            return result

        if self._privacy_state is not None and self._privacy_state.is_enabled:
            mode_hint = " (Privacy-Modus: nur lokal)"
        else:
            mode_hint = f" (Modus: {self._mode})"
        raise RuntimeError(
            "Kein LLM-Backend verfügbar" + mode_hint + ". "
            f"Alle Kandidaten erschöpft (letzter Fehler: {last_error})."
        )

    # -- Chat-Markierung ------------------------------------------------------

    def pop_backend_notice(self) -> str | None:
        """Liefert **einmalig** je Transition einen Hinweis auf den Wechsel.

        Bei Eintritt in den Degradations-Zustand (Antwort kommt nicht vom
        bevorzugten Backend) und beim Zurückkehren je genau eine Meldung,
        danach ``None`` – damit nicht jede Nachricht den Hinweis trägt.
        """
        if self._degraded and not self._degraded_announced:
            self._degraded_announced = True
            return (
                f"_(Hinweis: bevorzugtes LLM gerade nicht erreichbar – "
                f"ich antworte über {self._served_backend}.)_"
            )
        if not self._degraded and self._degraded_announced:
            self._degraded_announced = False
            return (
                f"_(Hinweis: bevorzugtes LLM wieder erreichbar – "
                f"zurück auf {self._served_backend}.)_"
            )
        return None

    # -- Status ---------------------------------------------------------------

    @property
    def degraded(self) -> bool:
        """True, wenn zuletzt nicht das bevorzugte Backend bedient hat."""
        return self._degraded

    @property
    def active_backend(self) -> str:
        """Name des aktiven Backends.

        Nach einem ``generate()`` das tatsächlich bedienende Backend, davor das
        erste verfügbare der mode-abhängigen Kette (``none`` wenn keins).
        """
        if self._served_backend is not None:
            return self._served_backend
        for client in self._ordered_backends():
            if client.is_available():
                return self._name(client)
        return "none"

    @property
    def primary_name(self) -> str:
        """Modellname des primären Backends."""
        return getattr(self._primary, "model", type(self._primary).__name__)

    @property
    def fallback_name(self) -> str:
        """Modellname des Fallback-Backends."""
        return getattr(self._fallback, "model", type(self._fallback).__name__)

    @property
    def primary_available(self) -> bool:
        """Ist das primäre Backend erreichbar?"""
        return self._primary.is_available()

    @property
    def fallback_available(self) -> bool:
        """Ist das Fallback-Backend erreichbar?"""
        return self._fallback.is_available()
