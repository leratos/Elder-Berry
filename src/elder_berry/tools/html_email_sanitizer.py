"""HtmlEmailSanitizer -- HTML-Mail-Bodies in sicherheits-bereinigten Plain-Text.

Konvertiert HTML-Mail-Bodies (z.B. aus IMAP-Multipart-Mails) in lesbaren,
Inject-armen Plain-Text. Wird vom IMAPEmailClient an den LLM-Prompt der
zusammenfassen-Funktion durchgereicht.

Phase 85 -- siehe docs/concepts/phase-85-html-email-sanitizer.md fuer
Architektur und Bug-Diagnose. Filtert:

- Inhalte gefaehrlicher Subtrees (script, style, head, meta, link,
  noscript, title, iframe, object, embed) -- decompose, nicht unwrap,
  damit auch der Inhalt verschwindet
- HTML-Kommentare (alte Regex brach an inneren > Zeichen)
- Hidden-Text per style-Attribut (display:none, visibility:hidden,
  opacity:0, font-size < min_font_size_px, weisse Schrift)
- Hidden-Text per legacy color-Attribut (<font color="#fff">)
- Default: blockquotes (Fake-Quote-Inject-Vektor; opt-in via
  keep_blockquotes=True)

Restrisiko (Konzept Abschnitt 7.1): sichtbarer normaler Text mit
Inject-Versuchen wird NICHT gefiltert -- dagegen schuetzt nur der
bestehende LLM-Prompt-Untrusted-Wrapper und die Pending-Confirmation-
Pipeline.

Pure Klasse: kein I/O, keine externen Calls, immutable nach __init__,
damit thread-safe.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)


# Subtrees, deren Inhalt komplett aus dem Output entfernt wird.
_DECOMPOSE_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "head",
    "meta",
    "link",
    "noscript",
    "title",
    "iframe",
    "object",
    "embed",
)

# style-Attribut-Muster fuer Hidden-Text. font-size wird separat per
# Wert-Vergleich gegen min_font_size_px geprueft -- ein Character-Class-
# Regex wie [0-{min}]px (frueherer Konzept-Entwurf) scheitert an
# Schwellen >= 10, weil [0-9] nur Einzelziffern matcht.
_HIDDEN_STYLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"display\s*:\s*none", re.IGNORECASE),
    re.compile(r"visibility\s*:\s*hidden", re.IGNORECASE),
    re.compile(r"color\s*:\s*#?fff(?:fff)?\b", re.IGNORECASE),
    re.compile(r"color\s*:\s*white\b", re.IGNORECASE),
    re.compile(
        r"color\s*:\s*rgb\(\s*255\s*,\s*255\s*,\s*255\s*\)",
        re.IGNORECASE,
    ),
)

_FONT_SIZE_RE: re.Pattern[str] = re.compile(
    r"font-size\s*:\s*(\d+)\s*px", re.IGNORECASE
)

# opacity: 0.0 / 0.00 / .0 zaehlen alle als komplett transparent
# (CSS-Semantik). Numeric-Parse statt Regex-Literal, weil der frueher
# verwendete Negative-Lookahead (?!\.) Decimal-Zero-Bypass durchliess
# (Phase 85.4 PR-Review P2). Konsistent zu _FONT_SIZE_RE.
_OPACITY_RE: re.Pattern[str] = re.compile(r"opacity\s*:\s*([\d.]+)", re.IGNORECASE)

# Legacy <font color="...">: weiss in beiden Schreibweisen.
_COLOR_ATTR_HIDDEN: re.Pattern[str] = re.compile(
    r"^(?:#?fff(?:fff)?|white)$", re.IGNORECASE
)

_CAP_MARKER: str = "\n[...gekuerzt...]"


class HtmlEmailSanitizer:
    """Konvertiert HTML-Mail-Bodies in sicherheits-bereinigten Plain-Text.

    Pure Klasse (Instanz-State nur fuer Konfiguration). Keine I/O,
    keine externen Calls. Thread-safe, weil immutable nach __init__.
    """

    def __init__(
        self,
        max_chars: int = 8000,
        keep_blockquotes: bool = False,
        min_font_size_px: int = 6,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars muss > 0 sein")
        if min_font_size_px < 0:
            raise ValueError("min_font_size_px muss >= 0 sein")
        self._max_chars = max_chars
        self._keep_blockquotes = keep_blockquotes
        self._min_font_size_px = min_font_size_px

    @property
    def max_chars(self) -> int:
        return self._max_chars

    def sanitize(self, html: str) -> str:
        """HTML rein, sicherer Plain-Text raus.

        Niemals Exceptions -- kaputtes HTML faellt durch zu leerem
        Output oder bestmoeglichem Parse-Ergebnis.
        """
        if not html:
            return ""

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            # Defensive Net: html.parser ist Pure-Python und fast nie
            # crashy, aber ein leerer Briefing-Pipeline-String ist
            # immer noch besser als ein gefressenes Exception oben.
            logger.warning("BeautifulSoup-Parse fehlgeschlagen: %s", exc)
            return ""

        self._remove_dangerous_subtrees(soup)
        self._remove_comments(soup)
        if not self._keep_blockquotes:
            self._remove_blockquotes(soup)
        self._remove_hidden_styled(soup)
        self._remove_hidden_color_attr(soup)

        text = soup.get_text(separator="\n", strip=True)
        return self._normalize_and_cap(text)

    @staticmethod
    def _remove_dangerous_subtrees(soup: BeautifulSoup) -> None:
        for tag_name in _DECOMPOSE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

    @staticmethod
    def _remove_comments(soup: BeautifulSoup) -> None:
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()

    @staticmethod
    def _remove_blockquotes(soup: BeautifulSoup) -> None:
        for bq in soup.find_all("blockquote"):
            bq.decompose()

    def _remove_hidden_styled(self, soup: BeautifulSoup) -> None:
        for tag in soup.find_all(style=True):
            style = tag.get("style", "")
            if not isinstance(style, str):
                continue
            if self._style_is_hidden(style):
                tag.decompose()

    def _style_is_hidden(self, style: str) -> bool:
        if any(p.search(style) for p in _HIDDEN_STYLE_PATTERNS):
            return True
        font_match = _FONT_SIZE_RE.search(style)
        if font_match and int(font_match.group(1)) < self._min_font_size_px:
            return True
        opacity_match = _OPACITY_RE.search(style)
        if opacity_match:
            try:
                if float(opacity_match.group(1)) == 0.0:
                    return True
            except ValueError:
                pass
        return False

    @staticmethod
    def _remove_hidden_color_attr(soup: BeautifulSoup) -> None:
        for tag in soup.find_all(attrs={"color": _COLOR_ATTR_HIDDEN}):
            tag.decompose()

    def _normalize_and_cap(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        text = text.strip()
        if len(text) > self._max_chars:
            text = text[: self._max_chars] + _CAP_MARKER
        return text
