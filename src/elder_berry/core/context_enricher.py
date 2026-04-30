"""ContextEnricher – Reichert Kalender-Events mit Kontext aus anderen Quellen an.

Sucht in NoteStore, IMAPEmailClient, WeatherClient und MemoryStore nach
relevanten Informationen zu einem Termin-Titel und lässt das LLM eine
natürliche Zusammenfassung formulieren.

Wird vom CalendarWatcher beim ersten Reminder (z.B. 15 Min vor Termin)
aufgerufen. Graceful Degradation: fehlende oder fehlerhafte Quellen werden
übersprungen, der Alert geht trotzdem raus.

Verwendung:
    enricher = ContextEnricher(
        note_store=note_store,
        email_client=email_client,
        weather_client=weather_client,
        llm=llm_client,
        default_user_id="@user:matrix.example.com",
    )
    extra = enricher.enrich_event("Meeting Max", datetime(...), "Büro")
    # → "Notiz: Max wollte über das Dachprojekt sprechen\n..."
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.llm.base import LLMClient
    from elder_berry.memory.base import MemoryStore
    from elder_berry.tools.email_client import IMAPEmailClient
    from elder_berry.tools.note_store import NoteStore
    from elder_berry.tools.weather_client import WeatherClient

logger = logging.getLogger(__name__)

# Timeout pro Datenquelle (Sekunden)
SOURCE_TIMEOUT_SECONDS = 3

# LLM-System-Prompt für die Kontext-Formatierung
ENRICHMENT_SYSTEM_PROMPT = (
    "Du bist Saleria Berry, eine charmante Assistentin. "
    "Dir werden Kontext-Informationen zu einem anstehenden Termin gegeben. "
    "Fasse die relevanten Informationen in 2-3 kurzen Sätzen zusammen. "
    "Sei natürlich und hilfreich, nicht steif. "
    "Wenn Informationen nicht zum Termin passen, lass sie weg. "
    "Antworte NUR mit der Zusammenfassung, kein Smalltalk."
)


@dataclass(frozen=True)
class EnrichmentResult:
    """Ergebnis der Kontext-Anreicherung für ein Event."""

    raw_notes: list[str] = field(default_factory=list)
    raw_mails: list[str] = field(default_factory=list)
    raw_weather: str | None = None
    raw_memories: list[str] = field(default_factory=list)
    formatted: str = ""

    @property
    def has_context(self) -> bool:
        """True wenn mindestens eine Quelle Kontext geliefert hat."""
        return bool(
            self.raw_notes or self.raw_mails or self.raw_weather or self.raw_memories
        )


class ContextEnricher:
    """Reichert Events mit relevantem Kontext aus verschiedenen Quellen an.

    Alle Datenquellen sind optional (Graceful Degradation).
    Pro Quelle gilt ein Timeout von SOURCE_TIMEOUT_SECONDS.
    """

    def __init__(
        self,
        note_store: NoteStore | None = None,
        email_client: IMAPEmailClient | None = None,
        weather_client: WeatherClient | None = None,
        memory_store: MemoryStore | None = None,
        llm: LLMClient | None = None,
        default_user_id: str = "",
    ) -> None:
        """
        Args:
            note_store: NoteStore für Fakten/Notizen-Suche.
            email_client: IMAPEmailClient für Mail-Suche.
            weather_client: WeatherClient für aktuelle Wetterdaten.
            memory_store: MemoryStore (ChromaDB) für semantische Suche.
            llm: LLMClient für natürliche Formatierung der Ergebnisse.
            default_user_id: User-ID für NoteStore-Suche.
        """
        self._note_store = note_store
        self._email_client = email_client
        self._weather_client = weather_client
        self._memory_store = memory_store
        self._llm = llm
        self._default_user_id = default_user_id

    def enrich_event(
        self,
        title: str,
        event_time: datetime,
        location: str | None = None,
    ) -> EnrichmentResult:
        """Sammelt Kontext aus allen Quellen und formatiert ihn via LLM.

        Args:
            title: Termin-Titel (z.B. "Meeting Max").
            event_time: Start-Zeitpunkt des Termins.
            location: Optionaler Ort des Termins.

        Returns:
            EnrichmentResult mit Roh-Daten und formatierter Zusammenfassung.
            Bei Fehler oder leerem Kontext: EnrichmentResult mit has_context=False.
        """
        raw_notes = self._search_notes(title)
        raw_mails = self._search_mails(title)
        raw_weather = self._get_weather(location)
        raw_memories = self._search_memories(title)

        if not any([raw_notes, raw_mails, raw_weather, raw_memories]):
            return EnrichmentResult()

        formatted = self._format_with_llm(
            title,
            event_time,
            location,
            raw_notes,
            raw_mails,
            raw_weather,
            raw_memories,
        )

        return EnrichmentResult(
            raw_notes=raw_notes,
            raw_mails=raw_mails,
            raw_weather=raw_weather,
            raw_memories=raw_memories,
            formatted=formatted,
        )

    def _run_with_timeout(self, func, *args, source_name: str):
        """Führt eine Funktion mit Timeout aus. Bei Fehler → None."""
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(func, *args)
                return future.result(timeout=SOURCE_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            logger.warning(
                "ContextEnricher: %s Timeout (%ss)", source_name, SOURCE_TIMEOUT_SECONDS
            )
            return None
        except Exception as e:
            logger.warning("ContextEnricher: %s Fehler: %s", source_name, e)
            return None

    def _search_notes(self, query: str) -> list[str]:
        """Durchsucht NoteStore nach dem Termin-Titel."""
        if not self._note_store or not self._default_user_id:
            return []

        result = self._run_with_timeout(
            self._note_store.search,
            self._default_user_id,
            query,
            3,
            source_name="NoteStore",
        )
        if not result:
            return []

        return [
            f"{'🔑 ' + n.key + ': ' if n.key else '📝 '}{n.content}" for n in result
        ]

    def _search_mails(self, query: str) -> list[str]:
        """Durchsucht IMAP nach dem Termin-Titel (letzte 7 Tage)."""
        if not self._email_client:
            return []

        result = self._run_with_timeout(
            self._email_client.search,
            query,
            3,
            7,
            source_name="IMAP",
        )
        if not result:
            return []

        return [
            f"{m.sender}: {m.subject} ({m.date.strftime('%d.%m. %H:%M') if m.date else 'unbekannt'})"
            for m in result
        ]

    def _get_weather(self, location: str | None) -> str | None:
        """Holt aktuelle Wetterdaten (nur wenn Ort vorhanden)."""
        if not self._weather_client or not location:
            return None

        result = self._run_with_timeout(
            self._weather_client.get_current,
            source_name="Weather",
        )
        if not result:
            return None

        return (
            f"{result.description}, {result.temperature}°C"
            f" (gefühlt {result.apparent_temperature}°C)"
        )

    def _search_memories(self, query: str) -> list[str]:
        """Durchsucht ChromaDB MemoryStore semantisch."""
        if not self._memory_store:
            return []

        result = self._run_with_timeout(
            self._memory_store.search,
            query,
            3,
            source_name="MemoryStore",
        )
        if not result:
            return []

        return [m.content for m in result]

    def _format_with_llm(
        self,
        title: str,
        event_time: datetime,
        location: str | None,
        notes: list[str],
        mails: list[str],
        weather: str | None,
        memories: list[str],
    ) -> str:
        """Lässt das LLM die gesammelten Infos natürlich zusammenfassen."""
        if not self._llm:
            return self._format_fallback(notes, mails, weather, memories)

        parts = [f'Termin: "{title}" um {event_time.strftime("%H:%M")}']
        if location:
            parts.append(f"Ort: {location}")

        if notes:
            parts.append("Notizen:\n" + "\n".join(f"- {n}" for n in notes))
        if mails:
            parts.append("Relevante Mails:\n" + "\n".join(f"- {m}" for m in mails))
        if weather:
            parts.append(f"Wetter: {weather}")
        if memories:
            parts.append("Erinnerungen:\n" + "\n".join(f"- {m}" for m in memories))

        prompt = "\n\n".join(parts)

        try:
            result = self._llm.generate(prompt, system=ENRICHMENT_SYSTEM_PROMPT)
            return result.strip()
        except Exception as e:
            logger.warning("ContextEnricher: LLM-Formatierung fehlgeschlagen: %s", e)
            return self._format_fallback(notes, mails, weather, memories)

    @staticmethod
    def _format_fallback(
        notes: list[str],
        mails: list[str],
        weather: str | None,
        memories: list[str],
    ) -> str:
        """Template-basierter Fallback wenn LLM nicht verfügbar."""
        lines = []
        if notes:
            lines.append("📝 " + "; ".join(notes))
        if mails:
            lines.append("📧 " + "; ".join(mails))
        if weather:
            lines.append(f"🌤️ {weather}")
        if memories:
            lines.append("💭 " + "; ".join(memories))
        return "\n".join(lines)
