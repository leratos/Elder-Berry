"""css_decl_resolver -- tinycss2-basierter Inline-Style-Parser mit Cascade.

Phase 86.1 -- siehe docs/concepts/phase-86-tinycss2-refactor.md.
Phase 87.B-1 erweitert um background-color-RGB-Parsing + WCAG-
Helligkeits-Heuristik (siehe phase-87-b-computed-background-heuristik.md).

Liefert reine Funktionen ueber dem tinycss2-Token-Modell:

- ``parse_inline_style(style)`` parst einen ``style``-Attribut-Inhalt mit
  ``tinycss2.parse_declaration_list``, filtert Parse-Errors raus und
  loest die CSS-Cascade fuer mehrfach genannte Properties auf
  (``!important`` schlaegt non-important, sonst ``last-declaration-wins``).
- Pro Property kommt genau eine ``ResolvedDecl``-Instanz zurueck.
- Die Wert-Pruefer (``opacity_is_zero``, ``font_size_below_threshold``,
  ``display_is_none``, ``visibility_is_hidden``, ``color_is_white``)
  arbeiten direkt auf den Token-Listen aus ``ResolvedDecl.value_tokens``.
- ``parse_color_to_rgb`` + ``background_color_rgb`` extrahieren konkrete
  RGB-Werte; ``background_is_dark`` entscheidet via WCAG-Relative-
  Luminanz, ob ein RGB-Tripel als dunkel gilt.

Phase 86.2 ersetzt den Regex-basierten ``HtmlEmailSanitizer._style_is_hidden``
durch genau diese Bausteine. 86.1/87.B-1 sind eigenstaendig: keine I/O,
kein Sanitizer-Bezug, kein State, alle Funktionen rein -- damit thread-
safe und vollstaendig durch Pure-Tests abdeckbar.

Known Limitations (bewusst, nicht-zero False-Negatives sind in Mail-
Sanitizer-Kontext akzeptabler als False-Positives):

- ``opacity: var(--x)`` -- ohne Custom-Property-Resolver unbestimmt,
  zaehlt als nicht-zero.
- ``opacity: calc(0 + 0)`` und andere zusammengesetzte ``calc``-
  Expressions -- ohne Arithmetik-Evaluator unbestimmt. Nur der
  triviale Fall ``calc(0)`` wird erkannt.
- ``font-size`` in ``em``/``rem``/``%`` -- ohne Render-Kontext nicht
  in absolute Pixel umrechenbar, daher nicht ausgewertet.
- ``color`` in ``rgba()``/``hsl()``/``hsla()`` -- 86.1 erkennt nur die
  drei explizit gelisteten Formen (Hex/Ident/``rgb()``).
- ``background-color`` in ``rgba()``/``hsl()``/``hsla()`` -- analog
  zu color. 87.B-1 erkennt Hex/Named/``rgb()``; Alpha-Compositing
  ist Render-Engine-Scope und out-of-scope (siehe Konzept-Doc 87.B).
- ``transparent``/``currentcolor`` -- liefern ``None`` aus
  ``parse_color_to_rgb``, weil sie keinen konkreten Background
  definieren (Walker geht zur naechsten Hierarchie hoch).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

import tinycss2
from tinycss2.ast import (
    Declaration,
    DimensionToken,
    FunctionBlock,
    HashToken,
    IdentToken,
    LiteralToken,
    Node,
    NumberToken,
    PercentageToken,
    WhitespaceToken,
)

_HEX_WHITE: Final[frozenset[str]] = frozenset({"fff", "ffffff"})
_RGB_WHITE_COMPONENT: Final[float] = 255.0

# CSS-Wide-Keywords aus CSS-Cascade-Spec, gelten fuer JEDE Property.
_CSS_WIDE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"inherit", "initial", "unset", "revert", "revert-layer"}
)

# Math- und Reference-Functions: opaque-Werte, die wir nicht aufloesen,
# aber als "syntaktisch valid fuer fast jede Property" anerkennen.
_MATH_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"calc", "min", "max", "clamp", "var", "env", "attr"}
)

# display-Werte aus CSS-Display-3-Spec. Liste ist gross, aber stabil.
# CSS-wide-keywords werden separat geprueft.
_DISPLAY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "none",
        "block",
        "inline",
        "inline-block",
        "flex",
        "inline-flex",
        "grid",
        "inline-grid",
        "flow-root",
        "inline-flow-root",
        "table",
        "inline-table",
        "table-row-group",
        "table-header-group",
        "table-footer-group",
        "table-row",
        "table-cell",
        "table-column-group",
        "table-column",
        "table-caption",
        "list-item",
        "inline-list-item",
        "contents",
        "run-in",
        "ruby",
        "ruby-base",
        "ruby-text",
        "ruby-base-container",
        "ruby-text-container",
    }
)

# visibility-Werte aus CSS-Box-Model.
_VISIBILITY_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"visible", "hidden", "collapse"}
)

# Absolute + relative font-size-Keywords aus CSS-Fonts-Spec.
_FONT_SIZE_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "xx-small",
        "x-small",
        "small",
        "medium",
        "large",
        "x-large",
        "xx-large",
        "xxx-large",
        "smaller",
        "larger",
    }
)

# Color-Functions, die wir als syntaktisch valid anerkennen.
_COLOR_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {
        "rgb",
        "rgba",
        "hsl",
        "hsla",
        "hwb",
        "lab",
        "lch",
        "oklab",
        "oklch",
        "color",
        "color-mix",
    }
)

# WCAG-Relative-Luminanz-Schwelle (Phase 87.B-1).
# 0.179 ist der Punkt, an dem ein Background sowohl gegen schwarz als
# auch gegen weiss denselben Kontrast erzielt -- darunter gilt der bg
# als dunkel, darueber als hell. Schwelle aus WCAG-2.x-Recommended.
_LUMINANCE_DARK_THRESHOLD: Final[float] = 0.179

# CSS Named Colors (CSS-Color-3) + transparent/currentcolor.
# Quelle: https://www.w3.org/TR/css-color-3/#svg-color
_COLOR_NAMED: Final[frozenset[str]] = frozenset(
    {
        "transparent",
        "currentcolor",
        "aliceblue",
        "antiquewhite",
        "aqua",
        "aquamarine",
        "azure",
        "beige",
        "bisque",
        "black",
        "blanchedalmond",
        "blue",
        "blueviolet",
        "brown",
        "burlywood",
        "cadetblue",
        "chartreuse",
        "chocolate",
        "coral",
        "cornflowerblue",
        "cornsilk",
        "crimson",
        "cyan",
        "darkblue",
        "darkcyan",
        "darkgoldenrod",
        "darkgray",
        "darkgreen",
        "darkgrey",
        "darkkhaki",
        "darkmagenta",
        "darkolivegreen",
        "darkorange",
        "darkorchid",
        "darkred",
        "darksalmon",
        "darkseagreen",
        "darkslateblue",
        "darkslategray",
        "darkslategrey",
        "darkturquoise",
        "darkviolet",
        "deeppink",
        "deepskyblue",
        "dimgray",
        "dimgrey",
        "dodgerblue",
        "firebrick",
        "floralwhite",
        "forestgreen",
        "fuchsia",
        "gainsboro",
        "ghostwhite",
        "gold",
        "goldenrod",
        "gray",
        "green",
        "greenyellow",
        "grey",
        "honeydew",
        "hotpink",
        "indianred",
        "indigo",
        "ivory",
        "khaki",
        "lavender",
        "lavenderblush",
        "lawngreen",
        "lemonchiffon",
        "lightblue",
        "lightcoral",
        "lightcyan",
        "lightgoldenrodyellow",
        "lightgray",
        "lightgreen",
        "lightgrey",
        "lightpink",
        "lightsalmon",
        "lightseagreen",
        "lightskyblue",
        "lightslategray",
        "lightslategrey",
        "lightsteelblue",
        "lightyellow",
        "lime",
        "limegreen",
        "linen",
        "magenta",
        "maroon",
        "mediumaquamarine",
        "mediumblue",
        "mediumorchid",
        "mediumpurple",
        "mediumseagreen",
        "mediumslateblue",
        "mediumspringgreen",
        "mediumturquoise",
        "mediumvioletred",
        "midnightblue",
        "mintcream",
        "mistyrose",
        "moccasin",
        "navajowhite",
        "navy",
        "oldlace",
        "olive",
        "olivedrab",
        "orange",
        "orangered",
        "orchid",
        "palegoldenrod",
        "palegreen",
        "paleturquoise",
        "palevioletred",
        "papayawhip",
        "peachpuff",
        "peru",
        "pink",
        "plum",
        "powderblue",
        "purple",
        "rebeccapurple",
        "red",
        "rosybrown",
        "royalblue",
        "saddlebrown",
        "salmon",
        "sandybrown",
        "seagreen",
        "seashell",
        "sienna",
        "silver",
        "skyblue",
        "slateblue",
        "slategray",
        "slategrey",
        "snow",
        "springgreen",
        "steelblue",
        "tan",
        "teal",
        "thistle",
        "tomato",
        "turquoise",
        "violet",
        "wheat",
        "white",
        "whitesmoke",
        "yellow",
        "yellowgreen",
    }
)


@dataclass(frozen=True)
class ResolvedDecl:
    """Effektive Declaration nach Cascade-Resolver.

    Attribute:
        name: klein-geschrieben (``tinycss2.Declaration.lower_name``).
        value_tokens: Token-Liste der Declaration ohne fuehrende oder
            abschliessende ``WhitespaceToken``. Inner-Whitespace bleibt
            erhalten (relevant fuer z.B. ``rgb(255 255 255)``).
        important: ``True`` wenn die effektive Decl mit ``!important``
            markiert war.
    """

    name: str
    value_tokens: list[Node]
    important: bool


@dataclass(frozen=True)
class RGB:
    """RGB-Tripel mit Komponenten in ``0..255`` (Phase 87.B-1).

    Wird von ``parse_color_to_rgb`` zurueckgegeben und von
    ``_relative_luminance`` + ``background_is_dark`` konsumiert.
    Alpha-Kanal ist out-of-scope (siehe Modul-Docstring).
    """

    r: int
    g: int
    b: int


# Vollstaendige CSS-Color-3 Named-Color-RGB-Map (147 Eintraege ohne
# transparent/currentcolor, die separat zu None aufloesen).
# Quelle: https://www.w3.org/TR/css-color-3/#svg-color
_NAMED_COLOR_RGB: Final[dict[str, RGB]] = {
    "aliceblue": RGB(240, 248, 255),
    "antiquewhite": RGB(250, 235, 215),
    "aqua": RGB(0, 255, 255),
    "aquamarine": RGB(127, 255, 212),
    "azure": RGB(240, 255, 255),
    "beige": RGB(245, 245, 220),
    "bisque": RGB(255, 228, 196),
    "black": RGB(0, 0, 0),
    "blanchedalmond": RGB(255, 235, 205),
    "blue": RGB(0, 0, 255),
    "blueviolet": RGB(138, 43, 226),
    "brown": RGB(165, 42, 42),
    "burlywood": RGB(222, 184, 135),
    "cadetblue": RGB(95, 158, 160),
    "chartreuse": RGB(127, 255, 0),
    "chocolate": RGB(210, 105, 30),
    "coral": RGB(255, 127, 80),
    "cornflowerblue": RGB(100, 149, 237),
    "cornsilk": RGB(255, 248, 220),
    "crimson": RGB(220, 20, 60),
    "cyan": RGB(0, 255, 255),
    "darkblue": RGB(0, 0, 139),
    "darkcyan": RGB(0, 139, 139),
    "darkgoldenrod": RGB(184, 134, 11),
    "darkgray": RGB(169, 169, 169),
    "darkgreen": RGB(0, 100, 0),
    "darkgrey": RGB(169, 169, 169),
    "darkkhaki": RGB(189, 183, 107),
    "darkmagenta": RGB(139, 0, 139),
    "darkolivegreen": RGB(85, 107, 47),
    "darkorange": RGB(255, 140, 0),
    "darkorchid": RGB(153, 50, 204),
    "darkred": RGB(139, 0, 0),
    "darksalmon": RGB(233, 150, 122),
    "darkseagreen": RGB(143, 188, 143),
    "darkslateblue": RGB(72, 61, 139),
    "darkslategray": RGB(47, 79, 79),
    "darkslategrey": RGB(47, 79, 79),
    "darkturquoise": RGB(0, 206, 209),
    "darkviolet": RGB(148, 0, 211),
    "deeppink": RGB(255, 20, 147),
    "deepskyblue": RGB(0, 191, 255),
    "dimgray": RGB(105, 105, 105),
    "dimgrey": RGB(105, 105, 105),
    "dodgerblue": RGB(30, 144, 255),
    "firebrick": RGB(178, 34, 34),
    "floralwhite": RGB(255, 250, 240),
    "forestgreen": RGB(34, 139, 34),
    "fuchsia": RGB(255, 0, 255),
    "gainsboro": RGB(220, 220, 220),
    "ghostwhite": RGB(248, 248, 255),
    "gold": RGB(255, 215, 0),
    "goldenrod": RGB(218, 165, 32),
    "gray": RGB(128, 128, 128),
    "green": RGB(0, 128, 0),
    "greenyellow": RGB(173, 255, 47),
    "grey": RGB(128, 128, 128),
    "honeydew": RGB(240, 255, 240),
    "hotpink": RGB(255, 105, 180),
    "indianred": RGB(205, 92, 92),
    "indigo": RGB(75, 0, 130),
    "ivory": RGB(255, 255, 240),
    "khaki": RGB(240, 230, 140),
    "lavender": RGB(230, 230, 250),
    "lavenderblush": RGB(255, 240, 245),
    "lawngreen": RGB(124, 252, 0),
    "lemonchiffon": RGB(255, 250, 205),
    "lightblue": RGB(173, 216, 230),
    "lightcoral": RGB(240, 128, 128),
    "lightcyan": RGB(224, 255, 255),
    "lightgoldenrodyellow": RGB(250, 250, 210),
    "lightgray": RGB(211, 211, 211),
    "lightgreen": RGB(144, 238, 144),
    "lightgrey": RGB(211, 211, 211),
    "lightpink": RGB(255, 182, 193),
    "lightsalmon": RGB(255, 160, 122),
    "lightseagreen": RGB(32, 178, 170),
    "lightskyblue": RGB(135, 206, 250),
    "lightslategray": RGB(119, 136, 153),
    "lightslategrey": RGB(119, 136, 153),
    "lightsteelblue": RGB(176, 196, 222),
    "lightyellow": RGB(255, 255, 224),
    "lime": RGB(0, 255, 0),
    "limegreen": RGB(50, 205, 50),
    "linen": RGB(250, 240, 230),
    "magenta": RGB(255, 0, 255),
    "maroon": RGB(128, 0, 0),
    "mediumaquamarine": RGB(102, 205, 170),
    "mediumblue": RGB(0, 0, 205),
    "mediumorchid": RGB(186, 85, 211),
    "mediumpurple": RGB(147, 112, 219),
    "mediumseagreen": RGB(60, 179, 113),
    "mediumslateblue": RGB(123, 104, 238),
    "mediumspringgreen": RGB(0, 250, 154),
    "mediumturquoise": RGB(72, 209, 204),
    "mediumvioletred": RGB(199, 21, 133),
    "midnightblue": RGB(25, 25, 112),
    "mintcream": RGB(245, 255, 250),
    "mistyrose": RGB(255, 228, 225),
    "moccasin": RGB(255, 228, 181),
    "navajowhite": RGB(255, 222, 173),
    "navy": RGB(0, 0, 128),
    "oldlace": RGB(253, 245, 230),
    "olive": RGB(128, 128, 0),
    "olivedrab": RGB(107, 142, 35),
    "orange": RGB(255, 165, 0),
    "orangered": RGB(255, 69, 0),
    "orchid": RGB(218, 112, 214),
    "palegoldenrod": RGB(238, 232, 170),
    "palegreen": RGB(152, 251, 152),
    "paleturquoise": RGB(175, 238, 238),
    "palevioletred": RGB(219, 112, 147),
    "papayawhip": RGB(255, 239, 213),
    "peachpuff": RGB(255, 218, 185),
    "peru": RGB(205, 133, 63),
    "pink": RGB(255, 192, 203),
    "plum": RGB(221, 160, 221),
    "powderblue": RGB(176, 224, 230),
    "purple": RGB(128, 0, 128),
    "rebeccapurple": RGB(102, 51, 153),
    "red": RGB(255, 0, 0),
    "rosybrown": RGB(188, 143, 143),
    "royalblue": RGB(65, 105, 225),
    "saddlebrown": RGB(139, 69, 19),
    "salmon": RGB(250, 128, 114),
    "sandybrown": RGB(244, 164, 96),
    "seagreen": RGB(46, 139, 87),
    "seashell": RGB(255, 245, 238),
    "sienna": RGB(160, 82, 45),
    "silver": RGB(192, 192, 192),
    "skyblue": RGB(135, 206, 235),
    "slateblue": RGB(106, 90, 205),
    "slategray": RGB(112, 128, 144),
    "slategrey": RGB(112, 128, 144),
    "snow": RGB(255, 250, 250),
    "springgreen": RGB(0, 255, 127),
    "steelblue": RGB(70, 130, 180),
    "tan": RGB(210, 180, 140),
    "teal": RGB(0, 128, 128),
    "thistle": RGB(216, 191, 216),
    "tomato": RGB(255, 99, 71),
    "turquoise": RGB(64, 224, 208),
    "violet": RGB(238, 130, 238),
    "wheat": RGB(245, 222, 179),
    "white": RGB(255, 255, 255),
    "whitesmoke": RGB(245, 245, 245),
    "yellow": RGB(255, 255, 0),
    "yellowgreen": RGB(154, 205, 50),
}


def parse_inline_style(style: str) -> list[ResolvedDecl]:
    """Parst einen Inline-Style und gibt die effektiven Declarations zurueck.

    Reihenfolge der Liste = Reihenfolge der jeweils ersten Sichtung der
    Property im Input. Pro Property genau eine ``ResolvedDecl``.

    ``ParseError`` und alles, was tinycss2 nicht als ``Declaration``
    erkennt, wird ignoriert -- kaputtes CSS waere ein false-positive-
    Risiko, wenn wir es als "hidden" werten wuerden.
    """
    if not style:
        return []

    raw = tinycss2.parse_declaration_list(
        style, skip_comments=True, skip_whitespace=True
    )
    return _cascade_resolve(node for node in raw if isinstance(node, Declaration))


def opacity_is_zero(tokens: list[Node]) -> bool:
    """``True``, wenn die Token-Liste semantisch fuer ``opacity == 0`` steht.

    Erkennt:

    - ``NumberToken`` mit Wert ``0`` (deckt ``0``, ``0.0``, ``0.00``, ``.0``)
    - ``PercentageToken`` mit Wert ``0`` (``0%``). Spec sagt opacity sollte
      reines Number sein, aber manche Browser akzeptieren Prozent --
      konservativ-aggressiv als hidden behandelt.
    - ``calc(0)`` mit genau einem ``NumberToken``-Argument gleich 0.

    Alles andere (``inherit``, ``initial``, ``var(--x)``, ``calc(0+0)``,
    ``0.01``, ``1``, leere Tokenliste) liefert ``False``.
    """
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, NumberToken):
        return float(first.value) == 0.0
    if isinstance(first, PercentageToken):
        return float(first.value) == 0.0
    if isinstance(first, FunctionBlock) and first.lower_name == "calc":
        inner = [arg for arg in first.arguments if not isinstance(arg, WhitespaceToken)]
        if len(inner) == 1 and isinstance(inner[0], NumberToken):
            return float(inner[0].value) == 0.0
        return False
    return False


def font_size_below_threshold(tokens: list[Node], threshold_px: int) -> bool:
    """``True``, wenn die Token-Liste eine font-size in ``px`` unterhalb
    der Schwelle ausdrueckt.

    Nicht-``px``-Einheiten (``em``, ``rem``, ``%``, ``pt``, ``vh``,
    Schlüsselwoerter wie ``small``) liefern ``False``. Begruendung
    siehe Modul-Docstring "Known Limitations".
    """
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, DimensionToken) and first.lower_unit == "px":
        return float(first.value) < threshold_px
    return False


def display_is_none(tokens: list[Node]) -> bool:
    """``True``, wenn der erste relevante Token ``IdentToken("none")`` ist
    (case-insensitive).
    """
    first = _first_non_whitespace(tokens)
    if isinstance(first, IdentToken):
        return bool(first.lower_value == "none")
    return False


def visibility_is_hidden(tokens: list[Node]) -> bool:
    """``True``, wenn der erste relevante Token ``IdentToken("hidden")``
    ist (case-insensitive).
    """
    first = _first_non_whitespace(tokens)
    if isinstance(first, IdentToken):
        return bool(first.lower_value == "hidden")
    return False


def color_is_white(tokens: list[Node]) -> bool:
    """``True``, wenn die Token-Liste einen weissen Farbwert ausdrueckt.

    Erkennt drei Formen:

    - ``HashToken`` mit Hex ``fff`` oder ``ffffff`` (case-insensitive)
    - ``IdentToken`` mit lower_value ``white``
    - ``FunctionBlock`` ``rgb(255, 255, 255)`` oder ``rgb(255 255 255)``
      -- Whitespace und Kommata als Separator werden ignoriert.

    ``rgba()``/``hsl()``/``hsla()``/Named-Colors ausser ``white`` sind
    nicht abgedeckt (siehe Modul-Docstring).
    """
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, HashToken):
        return first.value.lower() in _HEX_WHITE
    if isinstance(first, IdentToken):
        return bool(first.lower_value == "white")
    if isinstance(first, FunctionBlock) and first.lower_name == "rgb":
        return _rgb_args_are_white(first.arguments)
    return False


def parse_color_to_rgb(tokens: list[Node]) -> RGB | None:
    """Extrahiert ein RGB-Tripel aus einer Color-Token-Liste (Phase 87.B-1).

    Erkennt drei Formen:

    - ``HashToken`` mit 3-stelligem (``#abc``) oder 6-stelligem
      (``#aabbcc``) Hex. 4-/8-stellige Hex-Variante (Alpha) wird auf
      die ersten 6 Stellen reduziert -- Alpha-Compositing ist out-of-
      scope (siehe Modul-Docstring).
    - ``IdentToken`` mit Named Color aus ``_NAMED_COLOR_RGB``.
      ``transparent`` und ``currentcolor`` liefern ``None``, weil sie
      keinen konkreten Background definieren.
    - ``FunctionBlock`` ``rgb(r, g, b)`` oder ``rgb(r g b)`` mit
      drei NumberTokens (0..255). Werte ausserhalb des Bereichs werden
      auf 0/255 geclamped (CSS-Spec-konform).

    ``rgba()``/``hsl()``/``hsla()``/``var()``/``calc()`` und alle
    anderen Formen liefern ``None`` -- der Walker behandelt das
    konservativ als "kein parsbarer bg im Walker-Pfad".
    """
    first = _first_non_whitespace(tokens)
    if first is None:
        return None
    if isinstance(first, HashToken):
        return _hex_token_to_rgb(first.value)
    if isinstance(first, IdentToken):
        ident = first.lower_value
        if ident in {"transparent", "currentcolor"}:
            return None
        return _NAMED_COLOR_RGB.get(ident)
    if isinstance(first, FunctionBlock) and first.lower_name == "rgb":
        return _rgb_args_to_rgb(first.arguments)
    return None


def background_color_rgb(decls: list[ResolvedDecl]) -> RGB | None:
    """Holt die ``background-color``-Decl aus der Cascade-Liste und
    parst sie zu RGB. ``None`` wenn Property fehlt oder nicht parsbar
    (transparent/var()/rgba()/etc.).

    Die Cascade-Aufloesung selbst macht ``parse_inline_style``;
    diese Funktion erwartet die bereits aufgeloeste Liste und liest
    nur den einzigen verbleibenden ``background-color``-Eintrag.
    """
    for decl in decls:
        if decl.name == "background-color":
            return parse_color_to_rgb(decl.value_tokens)
    return None


def _srgb_to_linear(channel: int) -> float:
    """sRGB-Gamma-Korrektur fuer einen Kanal (0..255 → 0..1 linear).

    Formel aus WCAG-2.x-Spec.
    """
    c = channel / 255.0
    if c <= 0.03928:
        return c / 12.92
    return float(((c + 0.055) / 1.055) ** 2.4)


def _relative_luminance(rgb: RGB) -> float:
    """WCAG-Relative-Luminanz eines RGB-Tripels.

    Liefert einen Wert in ``0.0`` (reines Schwarz) bis ``1.0`` (reines
    Weiss). Konkrete Anker:

    - ``RGB(0, 0, 0)`` → 0.000
    - ``RGB(255, 255, 255)`` → 1.000
    - ``RGB(15, 81, 236)`` (typischer dunkler Marketing-Button-bg) → ca. 0.12
    - ``RGB(136, 136, 136)`` (#888) → ca. 0.246
    """
    return (
        0.2126 * _srgb_to_linear(rgb.r)
        + 0.7152 * _srgb_to_linear(rgb.g)
        + 0.0722 * _srgb_to_linear(rgb.b)
    )


def background_is_dark(rgb: RGB, threshold: float = _LUMINANCE_DARK_THRESHOLD) -> bool:
    """``True``, wenn die Relative-Luminanz unterhalb der Schwelle liegt.

    Default-Schwelle ``0.179`` ist der WCAG-Mittelpunkt, an dem ein
    Background sowohl gegen schwarz als auch gegen weiss denselben
    Kontrast erzielt.
    """
    return _relative_luminance(rgb) < threshold


def _hex_token_to_rgb(hex_value: str) -> RGB | None:
    """Konvertiert ein ``HashToken.value`` (ohne ``#``) zu RGB.

    Akzeptiert 3-/4-/6-/8-stellige Hex. 4 und 8 ignorieren den Alpha-
    Anteil (letzte 1 bzw. 2 Stellen). Alles andere liefert ``None``.
    """
    h = hex_value.lower()
    if len(h) == 3 and all(c in "0123456789abcdef" for c in h):
        return RGB(int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    if len(h) == 4 and all(c in "0123456789abcdef" for c in h):
        # 4-stelliges Hex = RGBA-Kurzform; Alpha (letzte Stelle) ignorieren.
        return RGB(int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    if len(h) == 6 and all(c in "0123456789abcdef" for c in h):
        return RGB(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    if len(h) == 8 and all(c in "0123456789abcdef" for c in h):
        # 8-stelliges Hex = RGBA-Langform; Alpha (letzte 2 Stellen) ignorieren.
        return RGB(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return None


def _rgb_args_to_rgb(arguments: list[Node]) -> RGB | None:
    """Extrahiert drei Number-Komponenten aus einem ``rgb()``-Block.

    Separatoren (Whitespace, Komma) werden ignoriert. Werte ausserhalb
    0..255 werden geclamped (CSS-Spec: out-of-range clamping).
    Prozent-Werte (``rgb(100% 50% 0%)``) oder zusaetzliche Argumente
    (``rgb(r g b / a)``) liefern ``None`` -- bewusst konservativ.
    """
    components = [
        arg for arg in arguments if not isinstance(arg, (WhitespaceToken, LiteralToken))
    ]
    if len(components) != 3:
        return None
    rgb_values: list[int] = []
    for arg in components:
        if not isinstance(arg, NumberToken):
            return None
        clamped = max(0, min(255, int(float(arg.value))))
        rgb_values.append(clamped)
    return RGB(rgb_values[0], rgb_values[1], rgb_values[2])


def _cascade_resolve(decls: Iterable[Declaration]) -> list[ResolvedDecl]:
    """Setzt die CSS-Cascade fuer mehrfach genannte Properties um.

    Regel (verkuerzt aus CSS-Cascade-Spec):

    1. Syntaktisch parsebare aber semantisch invalide Decls werden
       fuer Properties, die wir ueberhaupt validieren (siehe
       ``_VALIDATORS``), uebersprungen -- die vorherige gueltige
       Decl bleibt aktiv. Phase 87.1.1 schliesst damit den
       invalid-later-value-Bypass aus Codex-PR-Review (z.B.
       ``opacity:0; opacity:bogus`` wuerde sonst die Hidden-Decl
       ueberschreiben).
    2. ``!important``-Decls schlagen non-important Decls derselben
       Property.
    3. Innerhalb derselben Importance gilt ``last-declaration-wins``.
    """
    resolved: dict[str, ResolvedDecl] = {}
    insertion_order: list[str] = []
    for decl in decls:
        name = str(decl.lower_name)
        value_tokens = _strip_value_whitespace(decl.value)
        validator = _VALIDATORS.get(name)
        if validator is not None and not validator(value_tokens):
            # Browser-Spec: invalid declaration wird ignoriert,
            # vorherige gueltige Decl bleibt aktiv. Ohne diesen
            # Skip wuerde "opacity:0; opacity:bogus" die hidden-
            # Decl ueberschreiben und EVIL durchlassen.
            continue
        new = ResolvedDecl(
            name=name,
            value_tokens=value_tokens,
            important=bool(decl.important),
        )
        existing = resolved.get(name)
        if existing is None:
            insertion_order.append(name)
            resolved[name] = new
            continue
        if existing.important and not new.important:
            # Existing !important schlaegt nicht-!important Nachfolger.
            continue
        resolved[name] = new
    return [resolved[name] for name in insertion_order]


def _strip_value_whitespace(tokens: list[Node]) -> list[Node]:
    """Entfernt fuehrende/abschliessende ``WhitespaceToken``; Inner-
    Whitespace bleibt fuer Funktions-Argument-Separatoren erhalten.

    Phase 87.1.3: ``tokens or ()`` als Iteration-Quelle, damit CodeQL's
    Inter-Procedural-Analyse den Datenfluss als garantiert iterable
    erkennt (False-Positive ``py/non-iterable-in-for-loop`` aus dem
    Security-Scan).
    """
    safe_tokens = tokens or ()
    start = 0
    end = len(safe_tokens)
    while start < end and isinstance(safe_tokens[start], WhitespaceToken):
        start += 1
    while end > start and isinstance(safe_tokens[end - 1], WhitespaceToken):
        end -= 1
    return list(safe_tokens[start:end])


def _first_non_whitespace(tokens: list[Node]) -> Node | None:
    # Phase 87.1.3: ``tokens or ()`` -- siehe _strip_value_whitespace.
    for token in tokens or ():
        if not isinstance(token, WhitespaceToken):
            return token
    return None


def _rgb_args_are_white(arguments: list[Node]) -> bool:
    """Prueft, ob die Argumente eines ``rgb()``-FunctionBlocks drei
    NumberTokens mit Wert 255 sind. Separatoren (Whitespace, Komma)
    werden ignoriert.
    """
    components = [
        arg for arg in arguments if not isinstance(arg, (WhitespaceToken, LiteralToken))
    ]
    if len(components) != 3:
        return False
    for arg in components:
        if not isinstance(arg, NumberToken):
            return False
        if float(arg.value) != _RGB_WHITE_COMPONENT:
            return False
    return True


# --- Recognition-Validatoren (Phase 87.1.1) ------------------------------
#
# Pro Hidden-Detection-Property eine Funktion, die ``True`` liefert, wenn
# die Token-Liste einen syntaktisch erwarteten Wert fuer diese Property
# enthaelt. Wird vom Cascade-Resolver genutzt, um Browser-konform
# "invalid declarations werden ignoriert" umzusetzen.
#
# Diese Funktionen sind absichtlich tolerant: alles, was wir nicht
# eindeutig als invalid erkennen, wird recognized. False-Negative bei
# der Recognition (= Decl als invalid markiert, obwohl Browser sie als
# valid sieht) ist unproblematisch, weil die vorherige gueltige Decl
# dann aktiv bleibt -- konservativ in Richtung Hidden-Detection.


def _is_function_recognized_as_value(name: str) -> bool:
    """Math- und Reference-Functions sind opaque, aber syntaktisch
    valid fuer fast jede Property -- z.B. ``calc(...)``, ``var(--x)``.
    """
    return name in _MATH_FUNCTIONS


def _is_recognized_opacity(tokens: list[Node]) -> bool:
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, (NumberToken, PercentageToken)):
        return True
    if isinstance(first, IdentToken):
        return first.lower_value in _CSS_WIDE_KEYWORDS
    if isinstance(first, FunctionBlock):
        return _is_function_recognized_as_value(first.lower_name)
    return False


def _is_recognized_font_size(tokens: list[Node]) -> bool:
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, (DimensionToken, PercentageToken)):
        return True
    if isinstance(first, IdentToken):
        return (
            first.lower_value in _FONT_SIZE_KEYWORDS
            or first.lower_value in _CSS_WIDE_KEYWORDS
        )
    if isinstance(first, FunctionBlock):
        return _is_function_recognized_as_value(first.lower_name)
    return False


def _is_recognized_display(tokens: list[Node]) -> bool:
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, IdentToken):
        return (
            first.lower_value in _DISPLAY_KEYWORDS
            or first.lower_value in _CSS_WIDE_KEYWORDS
        )
    if isinstance(first, FunctionBlock):
        return _is_function_recognized_as_value(first.lower_name)
    return False


def _is_recognized_visibility(tokens: list[Node]) -> bool:
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, IdentToken):
        return (
            first.lower_value in _VISIBILITY_KEYWORDS
            or first.lower_value in _CSS_WIDE_KEYWORDS
        )
    if isinstance(first, FunctionBlock):
        return _is_function_recognized_as_value(first.lower_name)
    return False


def _is_recognized_color(tokens: list[Node]) -> bool:
    first = _first_non_whitespace(tokens)
    if first is None:
        return False
    if isinstance(first, HashToken):
        # Akzeptiert jeden HashToken; semantische Korrektheit (3/6/8-stelliges
        # Hex, gueltige Hex-Zeichen) ist Browser-Aufgabe. Hidden-Detection
        # entscheidet sich an color_is_white und filtert nur 'fff'/'ffffff'.
        return True
    if isinstance(first, IdentToken):
        return (
            first.lower_value in _COLOR_NAMED or first.lower_value in _CSS_WIDE_KEYWORDS
        )
    if isinstance(first, FunctionBlock):
        return first.lower_name in _COLOR_FUNCTIONS or _is_function_recognized_as_value(
            first.lower_name
        )
    return False


def _is_recognized_background_color(tokens: list[Node]) -> bool:
    """Recognition-Validator fuer ``background-color`` (Phase 87.B-1).

    Verhalten identisch zu ``_is_recognized_color`` -- ``background-
    color`` akzeptiert dieselbe Wert-Grammatik (`<color>`).
    """
    return _is_recognized_color(tokens)


_VALIDATORS: Final[dict[str, Callable[[list[Node]], bool]]] = {
    "opacity": _is_recognized_opacity,
    "font-size": _is_recognized_font_size,
    "display": _is_recognized_display,
    "visibility": _is_recognized_visibility,
    "color": _is_recognized_color,
    "background-color": _is_recognized_background_color,
}
