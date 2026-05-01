"""WebFetcher -- Webseiten abrufen und Klartext extrahieren.

Phase 64 (H-3): URL-Validierung via ``ensure_public_url`` blockiert SSRF-
Versuche auf private/loopback/metadata-IPs. Aufrufer erhalten ``ValueError``
(UnsafeUrlError-Subklasse), wenn eine URL nicht oeffentlich aufloesbar ist --
insbesondere relevant fuer URLs aus Matrix-Nachrichten (advanced_commands
"fasse <url> zusammen").

Phase 70 (H-3): Stream-Download mit Hard-Cap (Default 5 MB). Vorher
liess ``httpx.get()`` die komplette Antwort durch und der ``max_chars``-
Trim griff erst NACH dem Read -- ein Server konnte uns mit beliebig
grossen Antworten den Speicher fluten (DoS).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from elder_berry.core.url_validator import ensure_public_url

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; Elder-Berry/1.0)"
_TIMEOUT = 10.0
_MAX_REDIRECTS = 10

# Phase 70 (H-3): Standard-Maximum fuer den Antwort-Body (HTML-Bytes,
# vor Text-Extraktion). 5 MB ist genug fuer realistische Artikel und
# klein genug, um einen DoS via riesiger Response zu verhindern.
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class ResponseTooLargeError(RuntimeError):
    """Antwort-Body ueberschreitet das konfigurierte Limit (Phase 70 H-3)."""


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

    def __init__(
        self,
        max_chars: int = 8000,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes muss >= 1024 sein")
        self._max_chars = max_chars
        self._max_response_bytes = max_response_bytes

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
        """HTML per httpx streamen und mit Hard-Cap herunterladen.

        Redirects werden manuell verfolgt; jede Location-URL wird erneut
        mit ``ensure_public_url()`` validiert, um SSRF via Open-Redirect
        (oeffentliche URL leitet auf 169.254.x.x / 10.x.x.x weiter) zu
        blockieren.

        Phase 70 (H-3): Stream + harter Byte-Cap. Wenn der Server einen
        ``Content-Length`` schickt, der das Limit ueberschreitet, brechen
        wir vor dem Body-Read ab. Sonst lesen wir chunk-weise und brechen
        beim Ueberschreiten mit :class:`ResponseTooLargeError` ab. Die
        Verbindung wird via ``with``-Block sauber geschlossen.
        """
        current_url = url
        redirects = 0
        while True:
            with httpx.stream(
                "GET",
                current_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    redirects += 1
                    if redirects > _MAX_REDIRECTS:
                        raise httpx.TooManyRedirects(
                            f"Zu viele Weiterleitungen (> {_MAX_REDIRECTS}) fuer {url}"
                        )
                    location = response.headers.get("location", "")
                    if not location:
                        raise httpx.RequestError(
                            f"Redirect ohne Location-Header von {current_url}"
                        )
                    current_url = ensure_public_url(
                        urljoin(current_url, location),
                    )
                    continue

                response.raise_for_status()
                return self._read_capped(response, current_url)

    def _read_capped(
        self,
        response: httpx.Response,
        current_url: str,
    ) -> str:
        """Liest den Stream chunk-weise, hart begrenzt auf ``max_response_bytes``.

        Wirft :class:`ResponseTooLargeError` sobald entweder
        ``Content-Length`` ueber dem Limit liegt oder die kumulierten
        Chunks das Limit reissen.
        """
        cl_header = response.headers.get("content-length")
        if cl_header is not None:
            try:
                claimed = int(cl_header)
            except ValueError:
                claimed = -1
            if claimed > self._max_response_bytes:
                raise ResponseTooLargeError(
                    f"Antwort von {current_url} signalisiert "
                    f"{claimed} Bytes > Limit {self._max_response_bytes}"
                )

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            if not chunk:
                continue
            total += len(chunk)
            if total > self._max_response_bytes:
                raise ResponseTooLargeError(
                    f"Antwort von {current_url} ueberschreitet das "
                    f"Limit von {self._max_response_bytes} Bytes "
                    f"(bisher gelesen: {total})"
                )
            chunks.append(chunk)

        body = b"".join(chunks)
        # httpx erkennt das Encoding bei ``stream`` nicht automatisch
        # (response.text waere ohne vorherigen Read leer); wir nehmen
        # das Encoding aus dem Header oder fallen auf utf-8 zurueck.
        encoding = response.encoding or "utf-8"
        try:
            return body.decode(encoding, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

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
