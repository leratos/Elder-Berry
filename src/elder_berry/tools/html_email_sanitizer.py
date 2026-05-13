"""HtmlEmailSanitizer -- HTML-Mail-Bodies in sicherheits-bereinigten Plain-Text.

Konvertiert HTML-Mail-Bodies (z.B. aus IMAP-Multipart-Mails) in lesbaren,
Inject-armen Plain-Text. Wird vom IMAPEmailClient an den LLM-Prompt der
zusammenfassen-Funktion durchgereicht.

Phase 85 -- siehe docs/concepts/phase-85-html-email-sanitizer.md fuer
Architektur und Bug-Diagnose. Phase 86 ersetzt die Regex-basierte
Hidden-Style-Pipeline durch ``css_decl_resolver`` (tinycss2), siehe
docs/concepts/phase-86-tinycss2-refactor.md. Filtert:

- Inhalte gefaehrlicher Subtrees (script, style, head, meta, link,
  noscript, title, iframe, object, embed) -- decompose, nicht unwrap,
  damit auch der Inhalt verschwindet
- HTML-Kommentare (alte Regex brach an inneren > Zeichen)
- Hidden-Text per style-Attribut (display:none, visibility:hidden,
  opacity:0, font-size < min_font_size_px, weisse Schrift) -- alle
  ueber tinycss2-Resolver mit voller CSS-Cascade incl. !important
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

import itertools
import logging
import re

import tinycss2
from bs4 import BeautifulSoup, Comment, Tag

from elder_berry.tools.css_decl_resolver import (
    RGB,
    background_color_rgb,
    background_is_dark,
    color_is_white,
    display_is_none,
    font_size_below_threshold,
    opacity_is_zero,
    parse_color_to_rgb,
    parse_inline_style,
    visibility_is_hidden,
)

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

# Legacy <font color="...">: weiss in beiden Schreibweisen. Phase 86.2
# behaelt diesen Regex, weil <font color> ein HTML-Attribut ist, kein
# CSS-Decl -- der tinycss2-Resolver greift hier nicht.
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
        # Phase 87.1: two-phase, weil decompose() in der Iteration die
        # Children des dekomponierten Tags "tot" macht (attrs wird None)
        # und ein spaeterer Schleifen-Schritt auf einem dieser tot-Tags
        # crashed. Real-Welt-Beispiel (Fewo-Direkt-Reservierungsmail):
        # <p style="color:#FFFFFF"><a style="color:#FFFFFF">Button</a></p>
        # -- find_all matched beide, dekomponiere <p>, naechste
        # Iteration trifft die tote <a> -> AttributeError. Fix: erst
        # alle hidden-Decisions sammeln, dann separat dekomponieren.
        # bs4-Stubs typen Tag.attrs als nicht-None, aber zur Laufzeit
        # IST es None nach decompose() -- daher getattr-defensiv.
        to_remove: list[Tag] = []
        for tag in soup.find_all(style=True):
            if getattr(tag, "attrs", None) is None:
                # Falls eine vorhergehende remove_*-Methode (oder ein
                # frueherer Schritt in dieser Schleife) schon
                # dekomponiert hat, ist das Tag tot -- skip statt
                # crashen.
                continue
            style = tag.get("style", "")
            if not isinstance(style, str):
                continue
            if self._style_is_hidden(tag, style):
                to_remove.append(tag)
        for tag in to_remove:
            if getattr(tag, "attrs", None) is None:
                # Kann durch einen frueheren decompose-Call in diesem
                # Loop tot gemacht worden sein (verschachtelte
                # hidden-Container).
                continue
            tag.decompose()

    def _style_is_hidden(self, tag: Tag, style: str) -> bool:
        # Phase 86.2: tinycss2-basierter Resolver ersetzt die Regex-
        # Pipeline der 85.x-Sub-Etappen. parse_inline_style fuehrt
        # Tokenisierung, Kommentar-Strip (auch unterminierte /*...EOF)
        # und Cascade-Resolver (!important vor non-, sonst last-wins)
        # in einem Schritt aus und liefert pro Property genau eine
        # ResolvedDecl. Die Wert-Pruefer arbeiten direkt auf den
        # tinycss2-Token-Listen.
        # Phase 87.B-2: Signatur um ``tag`` erweitert, damit der
        # color:white-Check den Walker-Pfad-Background des Tags
        # konsultieren kann (V3-Self + V10-Inheritance-Fix).
        by_name = {decl.name: decl for decl in parse_inline_style(style)}

        opacity = by_name.get("opacity")
        if opacity is not None and opacity_is_zero(opacity.value_tokens):
            return True

        font_size = by_name.get("font-size")
        if font_size is not None and font_size_below_threshold(
            font_size.value_tokens, self._min_font_size_px
        ):
            return True

        display = by_name.get("display")
        if display is not None and display_is_none(display.value_tokens):
            return True

        visibility = by_name.get("visibility")
        if visibility is not None and visibility_is_hidden(visibility.value_tokens):
            return True

        color = by_name.get("color")
        if (
            color is not None
            and color_is_white(color.value_tokens)
            and self._color_is_hidden_in_context(tag)
        ):
            return True

        return False

    def _compute_effective_background_rgb(self, tag: Tag) -> RGB | None:
        """Walker: traversiert Tag + Vorfahren, sucht den naechsten
        explizit gesetzten Background. Erstes Hit gewinnt.

        Beruecksichtigt zwei Quellen pro Ancestor (Reihenfolge):

        1. Legacy ``bgcolor``-HTML-Attribut (Marketing-Mails fuer
           Outlook-Kompatibilitaet).
        2. CSS ``background-color`` aus dem ``style``-Attribut.

        ``transparent``/``currentcolor`` zaehlen NICHT als gesetzter
        Background (``parse_color_to_rgb`` liefert ``None``) -- der
        Walker geht in dem Fall zur naechsten Ebene hoch. Phase 87.B-3
        nutzt diesen Helper auch fuer die visible-island-Pruefung im
        Hidden-Strip-Unwrap.
        """
        for ancestor in itertools.chain([tag], tag.parents):
            bgcolor = ancestor.get("bgcolor")
            if isinstance(bgcolor, str) and bgcolor:
                rgb = parse_color_to_rgb(tinycss2.parse_component_value_list(bgcolor))
                if rgb is not None:
                    return rgb
            style = ancestor.get("style", "")
            if isinstance(style, str) and "background-color" in style.lower():
                rgb = background_color_rgb(parse_inline_style(style))
                if rgb is not None:
                    return rgb
        return None

    def _color_is_hidden_in_context(self, tag: Tag) -> bool:
        """``True``, wenn ein als weiss erkannter Tag-Color im konkreten
        Walker-Kontext als hidden gilt.

        Regeln:

        * Walker findet dunklen Background → not hidden (weiss-auf-
          dunkel ist sichtbar).
        * Walker findet hellen Background → hidden (weiss-auf-hell).
        * Walker findet keinen Background (transparent/var/keine
          Vorfahren-Decl) → hidden (Default-weiss-Mail-Body-Annahme,
          Status-Quo erhalten; siehe Konzept 87.B Frage B).
        """
        bg = self._compute_effective_background_rgb(tag)
        if bg is None:
            return True
        return not background_is_dark(bg)

    def _remove_hidden_color_attr(self, soup: BeautifulSoup) -> None:
        # Phase 87.B-2: vor dem Strip den Walker-Pfad-Background
        # konsultieren, damit <font color="white"> in einem dunklen
        # Container nicht faelschlich gestrippt wird. Zwei-Phasen-
        # Schleife analog zu _remove_hidden_styled (verschachtelte
        # hidden-Container -> tote Tags).
        to_remove: list[Tag] = []
        for tag in soup.find_all(attrs={"color": _COLOR_ATTR_HIDDEN}):
            if getattr(tag, "attrs", None) is None:
                continue
            if self._color_is_hidden_in_context(tag):
                to_remove.append(tag)
        for tag in to_remove:
            if getattr(tag, "attrs", None) is None:
                continue
            tag.decompose()

    def _normalize_and_cap(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        text = text.strip()
        if len(text) > self._max_chars:
            text = text[: self._max_chars] + _CAP_MARKER
        return text
