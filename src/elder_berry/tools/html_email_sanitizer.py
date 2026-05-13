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
        #
        # Phase 87.B-3: zwei Listen statt einer. Color-hidden Tags
        # nehmen den Unwrap-Pfad (visible Dark-bg-Islands aus dem
        # Subtree retten); Hard-hidden Tags (opacity/display/font-size/
        # visibility) bleiben direkter decompose().
        to_decompose: list[Tag] = []
        to_strip_color: list[Tag] = []
        for tag in soup.find_all(style=True):
            if getattr(tag, "attrs", None) is None:
                continue
            style = tag.get("style", "")
            if not isinstance(style, str):
                continue
            reason = self._hidden_reason(tag, style)
            if reason == "hard":
                to_decompose.append(tag)
            elif reason == "color":
                to_strip_color.append(tag)
        for tag in to_decompose:
            if getattr(tag, "attrs", None) is None:
                continue
            tag.decompose()
        for tag in to_strip_color:
            if getattr(tag, "attrs", None) is None:
                # Kann durch einen frueheren strip/decompose tot gemacht
                # worden sein (verschachtelte hidden-Container).
                continue
            self._strip_hidden_color_tag(tag)

    def _hidden_reason(self, tag: Tag, style: str) -> str | None:
        """Klassifiziert, WARUM ein Tag als hidden gilt.

        Phase 87.B-3: Strip-Verhalten ist Reason-abhaengig:

        * ``"hard"`` -- opacity:0, display:none, visibility:hidden,
          font-size unter Schwelle. Diese Hidden-Pfade implizieren,
          dass der Mail-Client den gesamten Subtree nicht rendert;
          Hidden-Strip-Unwrap (87.B-3) ist hier OUT-OF-SCOPE (siehe
          Konzept Restrisiken).
        * ``"color"`` -- ``color:white`` UND
          ``_color_is_hidden_in_context`` liefert True. Hier rettet
          ``_strip_hidden_color_tag`` visible Dark-bg-Islands.
        * ``None`` -- Tag ist nicht hidden.

        Reihenfolge: hard-Hidden vor color-Hidden. Wenn beides
        zutrifft (z.B. ``opacity:0; color:white``), gewinnt hard --
        Konzept Restrisiken "Unwrap nur fuer Color-Hidden".
        """
        by_name = {decl.name: decl for decl in parse_inline_style(style)}

        opacity = by_name.get("opacity")
        if opacity is not None and opacity_is_zero(opacity.value_tokens):
            return "hard"

        font_size = by_name.get("font-size")
        if font_size is not None and font_size_below_threshold(
            font_size.value_tokens, self._min_font_size_px
        ):
            return "hard"

        display = by_name.get("display")
        if display is not None and display_is_none(display.value_tokens):
            return "hard"

        visibility = by_name.get("visibility")
        if visibility is not None and visibility_is_hidden(visibility.value_tokens):
            return "hard"

        color = by_name.get("color")
        if (
            color is not None
            and color_is_white(color.value_tokens)
            and self._color_is_hidden_in_context(tag)
        ):
            return "color"

        return None

    def _style_is_hidden(self, tag: Tag, style: str) -> bool:
        """Convenience-Wrapper: True wenn der Tag aus irgendeinem Grund
        hidden ist (siehe ``_hidden_reason``).
        """
        return self._hidden_reason(tag, style) is not None

    @staticmethod
    def _tag_own_background_rgb(tag: Tag) -> RGB | None:
        """Liefert das Background-RGB DES TAGS SELBST (kein Walker).

        Zwei Quellen, Reihenfolge nach CSS-Spec (Phase 87.B-5):

        1. CSS ``background-color`` aus dem ``style``-Attribut --
           Inline-Style ueberschreibt Presentational-Attribute.
        2. Legacy ``bgcolor``-HTML-Attribut -- Fallback wenn style
           kein ``background-color`` setzt ODER die Decl vom Validator
           als invalid gefiltert wurde.

        Phase 87.B-5 PR-Review-Fix (Codex P1 "Honor inline CSS before
        legacy bgcolor"): Die urspruengliche Reihenfolge "bgcolor zuerst"
        verletzt CSS-Spec und oeffnet einen Hidden-Text-Bypass --
        ``<td bgcolor="#000" style="background-color:#fff">`` rendert
        im Mail-Client mit weissem bg, der alte Walker sah aber den
        dunklen ``bgcolor`` und liess ``color:white`` als visible
        durch.

        Wenn ``style`` eine syntaktisch gueltige aber fuer unseren
        Parser unparsbare Decl traegt (``rgba()``, ``var()``,
        ``hsl()``), liefert dieser Helper ``None`` -- bgcolor wird in
        dem Fall ABSICHTLICH NICHT konsultiert, weil der Browser auch
        die unparsbare Style-Decl ueber bgcolor priorisieren wuerde.
        Konservativ Default-weiss-Annahme.
        """
        style = tag.get("style", "")
        if isinstance(style, str) and "background-color" in style.lower():
            decls = parse_inline_style(style)
            for decl in decls:
                if decl.name == "background-color":
                    # style hat eine gueltige background-color-Decl.
                    # Sie gewinnt ueber bgcolor, auch wenn ihr Wert
                    # fuer uns nicht in RGB aufloesbar ist.
                    return parse_color_to_rgb(decl.value_tokens)
            # 'background-color' stand zwar im style-String, aber
            # alle Decls dazu wurden vom Validator als invalid
            # gefiltert (z.B. 'background-color:notacolor'). CSS-
            # Spec: invalid declarations werden ignoriert, bgcolor
            # bleibt aktiv. Falle durch.
        bgcolor = tag.get("bgcolor")
        if isinstance(bgcolor, str) and bgcolor:
            rgb = parse_color_to_rgb(tinycss2.parse_component_value_list(bgcolor))
            if rgb is not None:
                return rgb
        return None

    def _compute_effective_background_rgb(self, tag: Tag) -> RGB | None:
        """Walker: traversiert Tag + Vorfahren, sucht den naechsten
        explizit gesetzten Background. Erstes Hit gewinnt.

        Beruecksichtigt zwei Quellen pro Ancestor (siehe
        ``_tag_own_background_rgb``). ``transparent``/``currentcolor``
        zaehlen NICHT als gesetzter Background -- der Walker geht in
        dem Fall zur naechsten Ebene hoch.
        """
        for ancestor in itertools.chain([tag], tag.parents):
            rgb = self._tag_own_background_rgb(ancestor)
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
        # Phase 87.B-3: strip via _strip_hidden_color_tag (Unwrap
        # visible Dark-bg-Islands), nicht via direktem decompose.
        to_remove: list[Tag] = []
        for tag in soup.find_all(attrs={"color": _COLOR_ATTR_HIDDEN}):
            if getattr(tag, "attrs", None) is None:
                continue
            if self._color_is_hidden_in_context(tag):
                to_remove.append(tag)
        for tag in to_remove:
            if getattr(tag, "attrs", None) is None:
                continue
            self._strip_hidden_color_tag(tag)

    def _collect_dark_bg_islands(self, root: Tag) -> list[Tag]:
        """Sammelt visible Dark-bg-Islands im Subtree von ``root``.

        Island = Tag, der einen eigenen dunklen Background traegt
        (``style="background-color:..."`` oder ``bgcolor="..."``,
        WCAG-Luminanz < Schwelle).

        Konzept 87.B-3: Die ursprueliche Definition "Tag mit
        color:white am Tag selbst" hat eine Luecke -- ein
        zwischenliegender bg-Ancestor wird mit dem Strip-Target
        dekomponiert, so dass nach Extract der bg verloren waere.
        Saubere Definition: Tag mit EIGENEM dunklen bg. Children mit
        color:white bleiben automatisch im Subtree des Islands und
        sind im neuen Kontext (Eltern-Ebene) weiterhin sichtbar.

        Rekursive Walk in document order; Children eines bereits
        gesammelten Islands werden uebersprungen, damit nested
        Islands nicht doppelt extrahiert werden (sonst zerlegt
        ``extract()`` die DOM-Struktur).
        """
        islands: list[Tag] = []
        for descendant in root.find_all(True):
            if any(island in descendant.parents for island in islands):
                continue
            bg = self._tag_own_background_rgb(descendant)
            if bg is not None and background_is_dark(bg):
                islands.append(descendant)
        return islands

    def _strip_hidden_color_tag(self, tag: Tag) -> None:
        """Strip ``tag`` (color-hidden), aber rette visible Dark-bg-
        Islands aus dem Subtree per ``extract()`` an die Eltern-Ebene.

        Reine Text-Nodes und Tags ohne eigenen dunklen bg im Subtree
        bleiben im gestrippten Tag und gehen mit ihm verloren --
        damit ist der 85.x-Anti-Spam-Hidden-Text-Strip wirksam
        (Spam-Text-Bypass-Schutz).
        """
        if getattr(tag, "attrs", None) is None:
            return
        parent = tag.parent
        if parent is None:
            tag.decompose()
            return
        islands = self._collect_dark_bg_islands(tag)
        if not islands:
            tag.decompose()
            return
        insert_at = parent.index(tag)
        for island in islands:
            extracted = island.extract()
            parent.insert(insert_at, extracted)
            insert_at += 1
        tag.decompose()

    def _normalize_and_cap(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        text = text.strip()
        if len(text) > self._max_chars:
            text = text[: self._max_chars] + _CAP_MARKER
        return text
