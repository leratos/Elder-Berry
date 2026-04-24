"""WebFetcher -- Webseiten abrufen und Klartext extrahieren.

Phase 64 (H-3): URL-Validierung via ``ensure_public_url`` blockiert SSRF-
Versuche auf private/loopback/metadata-IPs. Aufrufer erhalten ``ValueError``
(UnsafeUrlError-Subklasse), wenn eine URL nicht oeffentlich aufloesbar ist --
insbesondere relevant fuer URLs aus Matrix-Nachrichten (advanced_commands
"fasse <url> zusammen").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from elder_berry.core.url_validator import ensure_public_url

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; Elder-Berry/1.0)"
_TIMEOUT = 10.0


@dataclass(frozen=True)
class WebContent:
    """Extrahierter Inhalt einer Webseite."""

    url: str
    title: str
    text: str
    truncated: bool
    source: str = "web"


class WebFetcher:
    """Ruft eine URL ab und extrahiert den Klartext.

    Primär via *trafilatura*, Fallback auf BeautifulSoup (h1 + p-Tags).
    """

    def __init__(self, max_chars: int = 8000) -> None:
        self._max_chars = max_chars

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def fetch(self, url: str) -> WebContent:
        """Webseite abrufen und Klartext extrahieren.

        Raises:
            ValueError: URL leer oder ungueltig.
            httpx.TimeoutException: Timeout beim Abruf.
            httpx.RequestError: Netzwerk-/Verbindungsfehler.
            RuntimeError: Kein Text extrahierbar.
        """
        if not url or not url.strip():
            raise ValueError("Keine URL angegeben.")

        # SSRF-Schutz: blockiert http/https-only, private, loopback,
        # link-local (169.254/16 -- AWS/Azure-Metadata), multicast.
        # UnsafeUrlError ist ValueError-Subklasse, damit der Aufrufer
        # (advanced_commands._cmd_web_summary) weiterhin mit einem
        # einzigen `except ValueError` reagieren kann.
        url = ensure_public_url(url)

        html = self._download(url)
        title, text = self._extract(html, url)

        if not text or not text.strip():
            raise RuntimeError(
                f"Kein Text aus {url} extrahierbar (Seite leer oder JS-only)."
            )

        truncated = False
        if len(text) > self._max_chars:
            text = text[: self._max_chars]
            truncated = True

        return WebContent(
            url=url,
            title=title or url,
            text=text,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # private
    # ------------------------------------------------------------------

    def _download(self, url: str) -> str:
        """HTML per httpx herunterladen."""
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.text
        except httpx.TimeoutException:
            raise
        except httpx.RequestError:
            raise

    def _extract(self, html: str, url: str) -> tuple[str, str]:
        """Text und Titel aus HTML extrahieren.

        Versucht zuerst trafilatura, dann BeautifulSoup als Fallback.
        """
        title, text = self._extract_trafilatura(html, url)
        if text:
            return title, text

        logger.debug("trafilatura lieferte keinen Text, Fallback auf BeautifulSoup")
        return self._extract_beautifulsoup(html)

    @staticmethod
    def _extract_trafilatura(html: str, url: str) -> tuple[str, str]:
        """Extraktion via trafilatura."""
        try:
            import trafilatura

            result = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
            )
            # Titel separat extrahieren
            metadata = trafilatura.metadata.extract_metadata(html, default_url=url)
            title = metadata.title if metadata and metadata.title else ""
            return title, result or ""
        except Exception as exc:
            logger.warning("trafilatura-Extraktion fehlgeschlagen: %s", exc)
            return "", ""

    @staticmethod
    def _extract_beautifulsoup(html: str) -> tuple[str, str]:
        """Fallback-Extraktion: h1 + alle p-Tags."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Titel aus <title> oder <h1>
            title_tag = soup.find("title")
            h1_tag = soup.find("h1")
            title = ""
            if title_tag and title_tag.string:
                title = title_tag.string.strip()
            elif h1_tag:
                title = h1_tag.get_text(strip=True)

            # Text aus p-Tags
            paragraphs = soup.find_all("p")
            text = "\n\n".join(
                p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
            )
            return title, text
        except Exception as exc:
            logger.warning("BeautifulSoup-Extraktion fehlgeschlagen: %s", exc)
            return "", ""
