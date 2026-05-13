"""Pure-Tests fuer ``elder_berry.tools.css_decl_resolver`` (Phase 86.1).

Keine ``HtmlEmailSanitizer``-Bezuege -- die Migration der vorhandenen
``test_html_email_sanitizer.py``-Suite zum Resolver passiert in Phase 86.2.

Strukturiert nach Konzept-Doc ``docs/concepts/phase-86-tinycss2-refactor.md``
Abschnitt "Test-Strategie":

- ``TestParseInlineStyle``        -- Tokenizer + Decl-Extraktion
- ``TestCascadeResolver``         -- ``!important`` vs. ``last-wins``
- ``TestOpacityIsZero``           -- alle bisherigen Decimal-/Format-Edges
- ``TestFontSizeBelowThreshold``  -- ``px``-Schwellwert + Known Limitation
- ``TestDisplayIsNone``           -- Case- + Whitespace-Varianten
- ``TestVisibilityIsHidden``      -- Case-Varianten
- ``TestColorIsWhite``            -- Hex/Ident/``rgb()``-Spaces-Syntax
- ``TestHistoricalBypassVectors`` -- die 5 dokumentierten Bypass-Vektoren
                                     aus Phase 85.4/.5/.6/.7/.7-Lueke
- ``TestPerformanceSmoke``        -- Median < 100 ms pro Mail-Style
"""

from __future__ import annotations

import statistics
import time
from dataclasses import FrozenInstanceError

import pytest
from tinycss2.ast import NumberToken, WhitespaceToken

from elder_berry.tools.css_decl_resolver import (
    ResolvedDecl,
    color_is_white,
    display_is_none,
    font_size_below_threshold,
    opacity_is_zero,
    parse_inline_style,
    visibility_is_hidden,
)


def _value_tokens_for(style: str, name: str) -> list:
    """Hilfs-Helper: parst ``style`` und gibt die Value-Tokens der
    angegebenen Property aus der Cascade-aufgeloesten Liste zurueck.
    """
    decls = parse_inline_style(style)
    for decl in decls:
        if decl.name == name:
            return decl.value_tokens
    raise AssertionError(f"property {name!r} nicht in parse-Ergebnis: {decls!r}")


class TestParseInlineStyle:
    def test_empty_string_returns_empty_list(self) -> None:
        assert parse_inline_style("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert parse_inline_style("   \t\n  ") == []

    def test_single_decl(self) -> None:
        decls = parse_inline_style("color: red")
        assert len(decls) == 1
        assert decls[0].name == "color"
        assert decls[0].important is False

    def test_multiple_distinct_decls(self) -> None:
        decls = parse_inline_style("color:red; font-size:14px; display:block")
        assert [d.name for d in decls] == ["color", "font-size", "display"]

    def test_decl_name_is_lowercased(self) -> None:
        decls = parse_inline_style("OPACITY:0")
        assert decls[0].name == "opacity"

    def test_decl_with_important_flag(self) -> None:
        decls = parse_inline_style("opacity:0 !important")
        assert decls[0].important is True

    def test_decl_without_important_flag(self) -> None:
        decls = parse_inline_style("opacity:0")
        assert decls[0].important is False

    def test_comment_between_decls_is_stripped(self) -> None:
        decls = parse_inline_style("color:red /* note */; opacity:0")
        assert [d.name for d in decls] == ["color", "opacity"]

    def test_comment_inside_value_is_stripped(self) -> None:
        decls = parse_inline_style("opacity:0/* foo */")
        assert decls[0].name == "opacity"

    def test_unterminated_comment_to_eof_swallows_rest(self) -> None:
        # tinycss2 behandelt /*...EOF als einen offenen Kommentar bis
        # Eingabe-Ende -- Browser-Verhalten unterscheidet sich aber
        # die safe-side fuer uns ist: was hinter dem unterminierten
        # Kommentar steht, gilt als nicht da. Damit kann die zweite
        # "opacity:1" niemals als sichtbare Decl gewinnen
        # (Phase-85.7-Luecke geschlossen).
        decls = parse_inline_style("opacity:0/*; opacity:1")
        assert len(decls) == 1
        assert decls[0].name == "opacity"
        assert opacity_is_zero(decls[0].value_tokens) is True

    def test_leading_and_trailing_whitespace_in_value_is_stripped(self) -> None:
        decls = parse_inline_style("opacity:   0   ")
        assert len(decls[0].value_tokens) == 1
        assert not isinstance(decls[0].value_tokens[0], WhitespaceToken)

    def test_inner_whitespace_in_value_is_preserved(self) -> None:
        # rgb(255 255 255) -> Function-Argumente enthalten Whitespace,
        # die Token-Liste der Declaration selbst hat aber nur eine
        # FunctionBlock -> Inner-Whitespace ist innerhalb der Function-
        # Args. Test dass die Function ueberlebt.
        decls = parse_inline_style("color: rgb(255 255 255)")
        assert decls[0].name == "color"
        assert color_is_white(decls[0].value_tokens) is True

    def test_invalid_decl_is_ignored(self) -> None:
        # "garbage" ist kein gueltiges Property:Value -- tinycss2 markiert
        # das als ParseError; wir ignorieren es kommentarlos.
        decls = parse_inline_style("garbage; opacity:0")
        assert [d.name for d in decls] == ["opacity"]

    def test_returns_resolveddecl_dataclass(self) -> None:
        decls = parse_inline_style("opacity:0")
        assert isinstance(decls[0], ResolvedDecl)


class TestCascadeResolver:
    def test_last_decl_wins_without_important(self) -> None:
        decls = parse_inline_style("opacity:0; opacity:1")
        assert len(decls) == 1
        # last-wins -> 1.0 -> nicht zero
        assert opacity_is_zero(decls[0].value_tokens) is False

    def test_last_decl_wins_reverse(self) -> None:
        decls = parse_inline_style("opacity:1; opacity:0")
        assert opacity_is_zero(decls[0].value_tokens) is True

    def test_important_beats_later_non_important(self) -> None:
        decls = parse_inline_style("opacity:0!important; opacity:1")
        assert opacity_is_zero(decls[0].value_tokens) is True

    def test_later_important_beats_earlier_non_important(self) -> None:
        decls = parse_inline_style("opacity:1; opacity:0!important")
        assert opacity_is_zero(decls[0].value_tokens) is True

    def test_last_important_wins_among_importants(self) -> None:
        decls = parse_inline_style("opacity:0!important; opacity:1!important")
        # beide important -> last-wins
        assert opacity_is_zero(decls[0].value_tokens) is False

    def test_cascade_preserves_insertion_order_across_properties(self) -> None:
        decls = parse_inline_style("opacity:0; color:red; opacity:1; color:black")
        # opacity ist zuerst gesehen worden, color danach
        assert [d.name for d in decls] == ["opacity", "color"]


class TestOpacityIsZero:
    @pytest.mark.parametrize(
        "style",
        [
            "opacity:0",
            "opacity:0.0",
            "opacity:0.00",
            "opacity:.0",
            "opacity:0%",
            "opacity:calc(0)",
        ],
    )
    def test_recognizes_zero(self, style: str) -> None:
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is True

    @pytest.mark.parametrize(
        "style",
        [
            "opacity:0.01",
            "opacity:0.5",
            "opacity:1",
            "opacity:1.0",
            "opacity:100%",
            "opacity:50%",
        ],
    )
    def test_non_zero_numbers_are_not_zero(self, style: str) -> None:
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is False

    @pytest.mark.parametrize(
        "style",
        [
            "opacity:inherit",
            "opacity:initial",
            "opacity:var(--invisible)",
            "opacity:calc(0 + 0)",
            "opacity:calc(0.5)",
        ],
    )
    def test_unresolvable_or_complex_is_not_zero(self, style: str) -> None:
        # Konservative False-Negative: ohne Custom-Property-Resolver
        # oder Arithmetik-Evaluator wird nicht als hidden klassifiziert.
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is False

    def test_empty_token_list_is_not_zero(self) -> None:
        assert opacity_is_zero([]) is False

    def test_only_whitespace_is_not_zero(self) -> None:
        assert opacity_is_zero([WhitespaceToken(1, 1, " ")]) is False


class TestFontSizeBelowThreshold:
    @pytest.mark.parametrize("style", ["font-size:1px", "font-size:5px"])
    def test_below_threshold_is_true(self, style: str) -> None:
        tokens = _value_tokens_for(style, "font-size")
        assert font_size_below_threshold(tokens, 6) is True

    def test_exactly_threshold_is_false(self) -> None:
        tokens = _value_tokens_for("font-size:6px", "font-size")
        assert font_size_below_threshold(tokens, 6) is False

    @pytest.mark.parametrize("style", ["font-size:7px", "font-size:14px"])
    def test_above_threshold_is_false(self, style: str) -> None:
        tokens = _value_tokens_for(style, "font-size")
        assert font_size_below_threshold(tokens, 6) is False

    def test_uppercase_unit_is_recognized(self) -> None:
        # lower_unit normalisiert die Unit -- "1PX" zaehlt als px.
        tokens = _value_tokens_for("font-size:1PX", "font-size")
        assert font_size_below_threshold(tokens, 6) is True

    @pytest.mark.parametrize(
        "style",
        [
            "font-size:0.5em",
            "font-size:0.5rem",
            "font-size:50%",
            "font-size:small",
        ],
    )
    def test_non_px_units_are_not_evaluated(self, style: str) -> None:
        # Known Limitation Phase 86.1 -- em/rem/% nicht ohne Render-
        # Kontext umrechenbar, daher kein hidden-Flag. Test
        # dokumentiert das Verhalten als bewusste Entscheidung.
        tokens = _value_tokens_for(style, "font-size")
        assert font_size_below_threshold(tokens, 6) is False

    def test_empty_token_list_is_false(self) -> None:
        assert font_size_below_threshold([], 6) is False


class TestDisplayIsNone:
    @pytest.mark.parametrize(
        "style",
        ["display:none", "display:NONE", "display: none", "display:  None"],
    )
    def test_recognizes_none(self, style: str) -> None:
        tokens = _value_tokens_for(style, "display")
        assert display_is_none(tokens) is True

    @pytest.mark.parametrize(
        "style", ["display:block", "display:inline", "display:flex"]
    )
    def test_other_values_are_false(self, style: str) -> None:
        tokens = _value_tokens_for(style, "display")
        assert display_is_none(tokens) is False

    def test_empty_token_list_is_false(self) -> None:
        assert display_is_none([]) is False


class TestVisibilityIsHidden:
    @pytest.mark.parametrize(
        "style",
        ["visibility:hidden", "visibility:HIDDEN", "visibility: Hidden"],
    )
    def test_recognizes_hidden(self, style: str) -> None:
        tokens = _value_tokens_for(style, "visibility")
        assert visibility_is_hidden(tokens) is True

    @pytest.mark.parametrize("style", ["visibility:visible", "visibility:collapse"])
    def test_other_values_are_false(self, style: str) -> None:
        tokens = _value_tokens_for(style, "visibility")
        assert visibility_is_hidden(tokens) is False

    def test_empty_token_list_is_false(self) -> None:
        assert visibility_is_hidden([]) is False


class TestColorIsWhite:
    @pytest.mark.parametrize(
        "style",
        [
            "color:#fff",
            "color:#FFF",
            "color:#ffffff",
            "color:#FFFFFF",
            "color:white",
            "color:WHITE",
            "color:White",
            "color:rgb(255,255,255)",
            "color:rgb(255, 255, 255)",
            "color:rgb(255 255 255)",
        ],
    )
    def test_recognizes_white(self, style: str) -> None:
        tokens = _value_tokens_for(style, "color")
        assert color_is_white(tokens) is True

    @pytest.mark.parametrize(
        "style",
        [
            "color:#ccc",
            "color:#000",
            "color:#fffffe",
            "color:black",
            "color:red",
            "color:rgb(254,255,255)",
            "color:rgb(255,255,254)",
            "color:rgb(255,255,255,0.5)",  # rgba-Syntax -- 4 Args, nicht white
        ],
    )
    def test_other_colors_are_false(self, style: str) -> None:
        tokens = _value_tokens_for(style, "color")
        assert color_is_white(tokens) is False

    def test_empty_token_list_is_false(self) -> None:
        assert color_is_white([]) is False


class TestHistoricalBypassVectors:
    """Die 5 dokumentierten Bypass-Klassen aus Phase 85.4-85.7 muessen
    mit dem neuen Resolver korrekt als hidden klassifiziert werden.

    Diese Tests sind der wichtigste 86.1-Akzeptanztest: sie zeigen,
    dass der strukturelle Refactor in 86.2 die historischen Vektoren
    nicht regressieren laesst -- noch bevor der Sanitizer-Code
    angefasst wird.
    """

    @pytest.mark.parametrize("style", ["opacity:0.0", "opacity:0.00"])
    def test_phase_85_4_p2_decimal_zero(self, style: str) -> None:
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is True

    @pytest.mark.parametrize(
        "style",
        [
            "opacity:1; opacity:0.0",
            "opacity:1.0; opacity:0",
        ],
    )
    def test_phase_85_5_multi_decl_opacity_last_zero(self, style: str) -> None:
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is True

    @pytest.mark.parametrize(
        "style",
        [
            "font-size:20px; font-size:1px",
            "font-size:14px; font-size:5px",
        ],
    )
    def test_phase_85_5_multi_decl_font_size_last_small(self, style: str) -> None:
        tokens = _value_tokens_for(style, "font-size")
        assert font_size_below_threshold(tokens, 6) is True

    @pytest.mark.parametrize(
        "style",
        [
            "opacity:0!important; opacity:1",
            "opacity:0 !important; opacity:1",
            "opacity:0!IMPORTANT; opacity:1",
        ],
    )
    def test_phase_85_6_important_opacity(self, style: str) -> None:
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is True

    @pytest.mark.parametrize(
        "style",
        [
            "font-size:1px!important; font-size:14px",
            "font-size:1px !important; font-size:20px",
        ],
    )
    def test_phase_85_6_important_font_size(self, style: str) -> None:
        tokens = _value_tokens_for(style, "font-size")
        assert font_size_below_threshold(tokens, 6) is True

    @pytest.mark.parametrize(
        "style",
        [
            "opacity:0!/**/important; opacity:1",
            "opacity:0!/* foo */important; opacity:1",
            "opacity:0/**/!important; opacity:1",
        ],
    )
    def test_phase_85_7_important_with_comment(self, style: str) -> None:
        # tinycss2 normalisiert /* ... */ als Whitespace-Aequivalent
        # bereits beim Tokenisieren -- der !important-Marker wird
        # spec-konform erkannt.
        tokens = _value_tokens_for(style, "opacity")
        assert opacity_is_zero(tokens) is True

    @pytest.mark.parametrize(
        ("style", "prop", "checker"),
        [
            ("display/**/:none", "display", display_is_none),
            ("visibility/**/:hidden", "visibility", visibility_is_hidden),
            ("color/**/:white", "color", color_is_white),
        ],
    )
    def test_phase_85_7_comment_around_property_separator(
        self, style: str, prop: str, checker: object
    ) -> None:
        # Browser-/Spec-konformes Verhalten: /* ... */ zaehlt als
        # Whitespace -- "display/**/:none" wird als "display:none"
        # gelesen. tinycss2 macht das beim Tokenisieren mit
        # skip_comments=True automatisch. Der 85.7-Regex-Filter
        # brauchte dafuer den expliziten _CSS_COMMENT_RE-Sub.
        tokens = _value_tokens_for(style, prop)
        assert checker(tokens) is True  # type: ignore[operator]

    @pytest.mark.parametrize(
        "style",
        [
            "opacity:0/*; opacity:1",
            "opacity:0/* opacity:1",
            "font-size:1px/*; font-size:14px",
        ],
    )
    def test_phase_85_7_lueke_unterminated_comment_to_eof(self, style: str) -> None:
        # Die Luecke aus dem 85.7-PR: unterminierte /*-Kommentare bis
        # EOF. tinycss2 sieht den /*-Start, ignoriert den Rest bis
        # Input-Ende -- nur die erste Decl bleibt sichtbar.
        # Auswertung der ersten Decl liefert hidden=True.
        decls = parse_inline_style(style)
        assert len(decls) == 1
        decl = decls[0]
        if decl.name == "opacity":
            assert opacity_is_zero(decl.value_tokens) is True
        elif decl.name == "font-size":
            assert font_size_below_threshold(decl.value_tokens, 6) is True
        else:
            raise AssertionError(f"Unerwartete Property: {decl.name}")


class TestPerformanceSmoke:
    """Median-Laufzeit < 100 ms ueber 5 synthetische Marketing-Mail-
    Stylesheets, jeweils ~10 Wiederholungen. Analog Phase 85.1 V4.
    """

    _MAIL_STYLES: tuple[str, ...] = (
        "font-family:Arial,sans-serif; font-size:14px; color:#333333; "
        "line-height:1.5; padding:20px; background-color:#ffffff; "
        "border-radius:8px; box-shadow:0 2px 4px rgba(0,0,0,0.1)",
        "display:flex; justify-content:center; align-items:center; "
        "min-height:200px; background:linear-gradient(90deg,#f0f0f0,#e0e0e0); "
        "margin:0 auto; max-width:600px; color:rgb(50,50,50); font-weight:bold",
        "opacity:1; visibility:visible; display:block; position:relative; "
        "top:0; left:0; width:100%; height:auto; border:1px solid #cccccc; "
        "padding:10px 20px; font-size:16px; color:black",
        "background-image:url('https://example.com/img.png'); "
        "background-repeat:no-repeat; background-position:center; "
        "background-size:cover; min-height:300px; margin-bottom:24px; "
        "border-top:2px solid #1976d2; color:#222222; font-size:13px",
        "/* tracking pixel hidden */ opacity:0; width:1px; height:1px; "
        "display:none; visibility:hidden; font-size:1px; color:#ffffff; "
        "position:absolute; left:-9999px",
    )

    def test_median_below_100ms(self) -> None:
        timings_ms: list[float] = []
        for style in self._MAIL_STYLES:
            for _ in range(10):
                start = time.perf_counter()
                decls = parse_inline_style(style)
                # echte Verarbeitung simulieren, damit Compiler nicht
                # wegoptimiert
                for decl in decls:
                    if decl.name == "opacity":
                        opacity_is_zero(decl.value_tokens)
                    elif decl.name == "font-size":
                        font_size_below_threshold(decl.value_tokens, 6)
                    elif decl.name == "display":
                        display_is_none(decl.value_tokens)
                    elif decl.name == "visibility":
                        visibility_is_hidden(decl.value_tokens)
                    elif decl.name == "color":
                        color_is_white(decl.value_tokens)
                end = time.perf_counter()
                timings_ms.append((end - start) * 1000.0)

        median = statistics.median(timings_ms)
        assert median < 100.0, (
            f"Median {median:.2f} ms ueber Schwelle 100 ms (samples: {len(timings_ms)})"
        )


def test_resolveddecl_is_frozen() -> None:
    """ResolvedDecl ist immutable -- Cascade-Resolver gibt freezed
    Snapshots zurueck, die kein Aufrufer veraendert.
    """
    decl = ResolvedDecl(
        name="opacity", value_tokens=[NumberToken(1, 1, 0, 0, "0")], important=False
    )
    with pytest.raises(FrozenInstanceError):
        decl.name = "color"  # type: ignore[misc]
