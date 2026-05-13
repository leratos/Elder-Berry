"""css_decl_resolver -- tinycss2-basierter Inline-Style-Parser mit Cascade.

Phase 86.1 -- siehe docs/concepts/phase-86-tinycss2-refactor.md.

Liefert reine Funktionen ueber dem tinycss2-Token-Modell:

- ``parse_inline_style(style)`` parst einen ``style``-Attribut-Inhalt mit
  ``tinycss2.parse_declaration_list``, filtert Parse-Errors raus und
  loest die CSS-Cascade fuer mehrfach genannte Properties auf
  (``!important`` schlaegt non-important, sonst ``last-declaration-wins``).
- Pro Property kommt genau eine ``ResolvedDecl``-Instanz zurueck.
- Die Wert-Pruefer (``opacity_is_zero``, ``font_size_below_threshold``,
  ``display_is_none``, ``visibility_is_hidden``, ``color_is_white``)
  arbeiten direkt auf den Token-Listen aus ``ResolvedDecl.value_tokens``.

Phase 86.2 ersetzt den Regex-basierten ``HtmlEmailSanitizer._style_is_hidden``
durch genau diese Bausteine. 86.1 ist eigenstaendig: keine I/O, kein
Sanitizer-Bezug, keine State, alle Funktionen rein -- damit thread-safe
und vollstaendig durch Pure-Tests abdeckbar.

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


_VALIDATORS: Final[dict[str, Callable[[list[Node]], bool]]] = {
    "opacity": _is_recognized_opacity,
    "font-size": _is_recognized_font_size,
    "display": _is_recognized_display,
    "visibility": _is_recognized_visibility,
    "color": _is_recognized_color,
}
