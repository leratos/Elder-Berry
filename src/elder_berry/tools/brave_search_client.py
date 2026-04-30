"""BraveSearchClient – Web-Suche via Brave Search API.

Sucht im Internet über die Brave Search API und gibt strukturierte
Ergebnisse zurück. API-Key wird aus SecretStore geladen.

Free Tier: 2000 Queries/Monat, keine Kreditkarte nötig.

Verwendung:
    client = BraveSearchClient(secret_store=store)
    results = client.search("Dachdecker Plattenburg")
    text = client.format_results(results)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.core.secret_store import SecretStore

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.search.brave.com/res/v1/web/search"
REQUEST_TIMEOUT = 10
DEFAULT_COUNT = 5
MAX_COUNT = 20


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """Ein einzelnes Suchergebnis."""

    title: str
    url: str
    description: str


# ---------------------------------------------------------------------------
# BraveSearchClient
# ---------------------------------------------------------------------------


class BraveSearchClient:
    """Brave Search API Client.

    Lazy-Init: httpx.Client wird erst beim ersten Request erstellt.
    API-Key aus SecretStore: brave_api_key.
    """

    def __init__(self, secret_store: SecretStore) -> None:
        self._store = secret_store
        self._client = None

    def _get_client(self):
        """Lazy-Init: httpx.Client mit Timeout."""
        if self._client is not None:
            return self._client

        import httpx

        self._client = httpx.Client(timeout=REQUEST_TIMEOUT)
        return self._client

    def _get_api_key(self) -> str:
        """Lädt API-Key aus SecretStore.

        Raises:
            ValueError: Wenn API-Key nicht konfiguriert ist.
        """
        key = self._store.get_or_none("brave_api_key")
        if not key:
            raise ValueError(
                "Brave Search API-Key nicht konfiguriert. "
                "Bitte via SecretStore setzen:\n"
                "  store.set('brave_api_key', '<dein-key>')\n"
                "Kostenlos registrieren: https://brave.com/search/api/"
            )
        return key

    def search(self, query: str, count: int = DEFAULT_COUNT) -> list[SearchResult]:
        """Führt eine Web-Suche durch.

        Args:
            query: Suchbegriff.
            count: Anzahl Ergebnisse (1-20, Default 5).

        Returns:
            Liste von SearchResult.

        Raises:
            ValueError: Wenn API-Key fehlt.
            httpx.HTTPStatusError: Bei API-Fehlern.
        """
        if not query or not query.strip():
            return []

        count = max(1, min(count, MAX_COUNT))
        api_key = self._get_api_key()
        client = self._get_client()

        resp = client.get(
            API_BASE_URL,
            params={
                "q": query.strip(),
                "count": str(count),
            },
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    description=item.get("description", ""),
                )
            )

        return results

    def format_results(self, results: list[SearchResult]) -> str:
        """Formatierter Text für Matrix-Ausgabe.

        Args:
            results: Liste von SearchResult.

        Returns:
            Lesbarer Text mit Titel, URL und Beschreibung.
        """
        if not results:
            return "Keine Ergebnisse gefunden."

        lines = [f"🔍 {len(results)} Ergebnis{'se' if len(results) != 1 else ''}:\n"]

        for i, r in enumerate(results, 1):
            desc = _clean_description(r.description)
            lines.append(f"{i}. **{r.title}**")
            lines.append(f"   {r.url}")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def format_results_detailed(self, results: list[SearchResult]) -> str:
        """Detaillierter Text für Chat-History (LLM-Kontext).

        Enthält alle Informationen, damit das LLM bei Rückfragen
        auf die Ergebnisse zugreifen kann.

        Args:
            results: Liste von SearchResult.

        Returns:
            Detaillierter Text mit allen Feldern.
        """
        if not results:
            return "Keine Ergebnisse gefunden."

        lines = [f"Web-Suchergebnisse ({len(results)} Treffer):\n"]

        for i, r in enumerate(results, 1):
            lines.append(f"--- Ergebnis {i} ---")
            lines.append(f"Titel: {r.title}")
            lines.append(f"URL: {r.url}")
            lines.append(f"Beschreibung: {r.description}")
            lines.append("")

        return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _clean_description(desc: str) -> str:
    """Entfernt HTML-Tags aus der Beschreibung."""
    if not desc:
        return ""

    import re

    clean = re.sub(r"<[^>]+>", "", desc)
    return clean.strip()
