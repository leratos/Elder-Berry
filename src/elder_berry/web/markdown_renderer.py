"""MarkdownRenderer -- server-side Markdown -> sanitisiertes HTML (Phase 78).

Pattern fuer Plugin-Vorschlaege im Dashboard (Konzept §3.8 + R3):
- markdown-it-py rendert Markdown -> HTML.
- bleach.clean() entfernt alles ausserhalb der Allowlist *bevor* das
  HTML den Browser erreicht. CSP aus Phase 70 + DOMPurify im Browser
  sind Defense-in-Depth, nicht primaerer Schutz.

Kapselung als Klasse, damit DI im Dashboard und Tests sauber bleiben.
"""

from __future__ import annotations

import logging
from typing import cast

import bleach  # type: ignore[import-untyped]
from markdown_it import MarkdownIt

logger = logging.getLogger(__name__)


# Allowlist laut Konzept §3.8 / R3. Kein <script>, <style>, <iframe>,
# kein on*-Attribut. Code-Bloecke bleiben fuer Spec-Lesbarkeit.
_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "ul",
        "ol",
        "li",
        "code",
        "pre",
        "h1",
        "h2",
        "h3",
        "h4",
        "strong",
        "em",
        "blockquote",
        "a",
        "hr",
    }
)

_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title"],
    "code": ["class"],  # markdown-it setzt language-* Klassen
    "pre": ["class"],
}

# bleach erlaubt nur diese Protokolle in href/src.
_ALLOWED_PROTOCOLS: frozenset[str] = frozenset({"http", "https", "mailto"})


class MarkdownRenderer:
    """Rendert Saleria-generierten Markdown sicher zu HTML.

    Args:
        renderer: Optionaler vorbereiteter MarkdownIt -- fuer Tests
            oder spezielle Konfigurationen. Default: ``MarkdownIt("commonmark")``
            mit aktivem ``html: False`` (Roh-HTML im Source wird ge-
            escaped, statt durchgelassen). Damit ist bleach die zweite
            Verteidigungslinie -- wenn der Parser doch HTML durchlaesst,
            faengt bleach es ab.
    """

    def __init__(self, renderer: MarkdownIt | None = None) -> None:
        self._md = renderer or MarkdownIt("commonmark", {"html": False})

    def render(self, markdown_text: str) -> str:
        """Markdown -> sanitisierter HTML-String."""
        if not markdown_text:
            return ""
        try:
            raw_html = self._md.render(markdown_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Markdown-Render fehlgeschlagen: %s", exc)
            # Fallback: nur Plain-Text, escaped.
            return cast(str, bleach.clean(markdown_text, tags=[], strip=True))
        return cast(
            str,
            bleach.clean(
                raw_html,
                tags=_ALLOWED_TAGS,
                attributes=_ALLOWED_ATTRIBUTES,
                protocols=_ALLOWED_PROTOCOLS,
                strip=True,
            ),
        )
