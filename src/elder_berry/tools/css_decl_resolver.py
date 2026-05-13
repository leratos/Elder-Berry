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

from collections.abc import Iterable
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

    1. ``!important``-Decls schlagen non-important Decls derselben
       Property.
    2. Innerhalb derselben Importance gilt ``last-declaration-wins``.
    """
    resolved: dict[str, ResolvedDecl] = {}
    insertion_order: list[str] = []
    for decl in decls:
        name = str(decl.lower_name)
        new = ResolvedDecl(
            name=name,
            value_tokens=_strip_value_whitespace(decl.value),
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
    """
    start = 0
    end = len(tokens)
    while start < end and isinstance(tokens[start], WhitespaceToken):
        start += 1
    while end > start and isinstance(tokens[end - 1], WhitespaceToken):
        end -= 1
    return list(tokens[start:end])


def _first_non_whitespace(tokens: list[Node]) -> Node | None:
    for token in tokens:
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
