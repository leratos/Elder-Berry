# Phase 86 – tinycss2-basierter CSS-Resolver fuer HtmlEmailSanitizer

**Status:** Konzept (2026-05-12) – Pre-Commitment nach Phase 85.7
**Branch:** `feature/phase-86-tinycss2-refactor`
**Aufwand:** ~2-3 Sessions, 3 Etappen
**Vorgaenger:** Phase 85 (HtmlEmailSanitizer) – Konzept-Doc V1-V9

## Trigger

Phase 85 hat in 7 Sub-Etappen (85.1 bis 85.7) einen Regex-basierten
HTML/CSS-Sanitizer aufgebaut. Davon waren 4 reaktive Sub-Etappen
(85.4-85.7) Code-Review-Reaktionen auf konkrete Bypass-Vektoren, die
der chatgpt-codex-connector in der PR-Review identifiziert hat:

| Sub-Etappe | Bug-Klasse                                       | Codex/Eigen |
| ---------- | ------------------------------------------------ | ----------- |
| 85.4-P2    | `opacity:0(?!\.)`-Lookahead schluckt 0.0/0.00    | Codex       |
| 85.5       | `re.search()` liest first-match, CSS = last      | Codex (opacity), Eigen (font-size) |
| 85.6       | `!important`-Cascade ignoriert                   | Codex (opacity), Eigen (font-size) |
| 85.7       | CSS-Kommentare `/* ... */` nicht als Whitespace  | Codex       |
| 85.7-Lueke | Unterminierte `/*` bis EOF nicht abgedeckt       | Codex       |

Jede Iteration hat eine andere CSS-Mechanik aufgedeckt, die im
Regex-Modell nicht spec-konform abbildbar war. V8 des 85-Konzept-
Docs hatte tinycss2-Refactor schon als "optional, wenn Iterations-
Frequenz weiter steigt" markiert. Die Frequenz IST gestiegen
(4 Codex-Findings in 4 PR-Iterations innerhalb einer Session),
darum jetzt der strukturelle Schritt.

## Ziel

Ersatz der Regex-basierten Filter-Pipeline in
`HtmlEmailSanitizer._style_is_hidden()` durch einen echten
CSS-Token/Declaration-Parser mit Cascade-Resolver. Damit:

1. Alle bisherigen 5 Bypass-Klassen sind strukturell ausgeschlossen
   (Decimal-Zero, Multi-Decl, !important, Kommentare incl.
   unterminiert).
2. Neue, kuenftig identifizierte CSS-Mechaniken (Custom-Properties
   `var()`, `calc()`, Property-Shorthand `font:`) werden vom Parser
   token-korrekt verworfen statt als Inject-Vektor durchgelassen.
3. Sanitizer wird wartungsaermer: keine spec-Lookups mehr pro
   Regex-Edit, der Parser ist die Spec.

## Out of Scope

- HTML-Parsing: BeautifulSoup bleibt fuer DOM-Tree-Walk und
  Subtree-Removal (`<script>`, `<style>` etc.). tinycss2 ersetzt
  nur den **Style-Attribut-Inhalt-Parser**.
- Computed-Cascade ueber mehrere Tags (inherited styles): nicht
  abgedeckt, bleibt Known Limitation aus Konzept 85 Abschnitt 11.
  Saubere Loesung waere Render-Tree-Walker, das ist eigenes Thema.
- `<style>`-Inline-Stylesheets parsen (z.B. um Selektoren auf
  body anzuwenden): tinycss2 kann das technisch, aber wir
  decompose `<style>`-Subtrees komplett. Aenderung dieser
  Pipeline-Architektur waere eigenes Konzept.
- `@media`/`@supports`-Conditional-Rules: nicht in inline-style
  erlaubt, daher kein Vektor.
- HTML-Entity-Decoding in Style-Attribut-Werten: BS4 macht das
  schon beim Parsen, der Style-String ist beim Sanitizer schon
  decoded.

## Architektur

### Pipeline (alte vs. neue)

**Alt (Phase 85.1-85.7):**

```
style-Attribut-String
  -> _CSS_COMMENT_RE.sub() entfernt /* ... */ (mit Closer)
  -> _HIDDEN_STYLE_PATTERNS.search() -- Literal-String-Matching
  -> _FONT_SIZE_RE.findall() -- Regex-Tupel-Liste
  -> _OPACITY_RE.findall() -- Regex-Tupel-Liste
  -> _resolve_decl() -- last-important-wins-Resolver
```

Problem: Regex matched nicht spec-konform fuer:
- unterminierte Kommentare bis EOF
- CSS-Custom-Properties / `var()` / `calc()`
- HTML-Entity-encoded Special-Chars im Attribut-Wert
  (eigentlich BS4-decoded, aber Regex sieht trotzdem die finalen
  Zeichen; gut wenn alle Chars Standard sind, kritisch wenn nicht)

**Neu (Phase 86):**

```
style-Attribut-String
  -> tinycss2.parse_declaration_list() -- echte CSS-Tokenisierung
     (Kommentare jeder Art weg, Whitespace normalisiert,
     unterminierte Token korrekt abgehandelt)
  -> Liste von Declaration-Objekten:
     [Declaration(name="opacity", value=[Token...], important=bool), ...]
  -> Cascade-Resolver:
     - Pro property_name: alle Declarations sammeln
     - importants[-1] vor non-importants[-1]
  -> Wert-Auswertung pro relevant property:
     - opacity: float == 0.0 ?
     - font-size: int < threshold ? (bisher nur px, jetzt
       Token-aware auch z.B. em/rem mit Schwellwert-Heuristik)
     - display: none ?
     - visibility: hidden ?
     - color: #fff / white / rgb(255,255,255) ?
```

### Dep-Aenderung in pyproject.toml

`tinycss2>=1.3.0` ergaenzen in **denselben Gruppen** wie heute
`beautifulsoup4`: `web`, `server`, `tower`, `matrix`, `remote`.
Begruendung: tinycss2 ist transitive Pflicht-Dep ueber den
gleichen Import-Chain wie BS4. Inline-Kommentar verweist auf
Phase 86.

Lizenz: BSD-3-Clause, Pure-Python, keine C-Build-Dependencies.
Package-Groesse ~50 KB. mypy hat eigene Stubs nicht; ggf.
`tinycss2.*` in der `ignore_missing_imports`-Liste analog `bs4.*`.

### Klassen-Skizze

```python
class HtmlEmailSanitizer:
    """Unveraendert aus Phase 85. Nur die _style_is_hidden-
    Implementation wechselt; alle anderen Methoden, __init__-Param,
    sanitize()-API bleiben kompatibel.
    """

    # Statische Wert-Pruefer als @staticmethod oder Modul-Funktionen:
    @staticmethod
    def _opacity_is_zero(tokens: list[Token]) -> bool: ...

    @staticmethod
    def _font_size_below_threshold(
        tokens: list[Token], threshold_px: int
    ) -> bool: ...

    @staticmethod
    def _display_is_none(tokens: list[Token]) -> bool: ...

    @staticmethod
    def _visibility_is_hidden(tokens: list[Token]) -> bool: ...

    @staticmethod
    def _color_is_white(tokens: list[Token]) -> bool: ...

    def _style_is_hidden(self, style: str) -> bool:
        decls = tinycss2.parse_declaration_list(
            style, skip_comments=True, skip_whitespace=True
        )
        # Filter auf Error-Tokens (parse errors) -- die ignorieren
        valid = [d for d in decls if d.type == "declaration"]

        # Cascade-Resolver pro property
        resolved: dict[str, Declaration] = {}
        for decl in valid:
            existing = resolved.get(decl.lower_name)
            if existing is None:
                resolved[decl.lower_name] = decl
            else:
                # !important > non-important; bei gleicher
                # Importance gilt last-wins.
                if decl.important and not existing.important:
                    resolved[decl.lower_name] = decl
                elif decl.important == existing.important:
                    resolved[decl.lower_name] = decl
                # else: existing.important and not decl.important
                # -> existing bleibt.

        # Property-Checks:
        for name, decl in resolved.items():
            if name == "opacity" and self._opacity_is_zero(decl.value):
                return True
            if name == "font-size" and self._font_size_below_threshold(
                decl.value, self._min_font_size_px
            ):
                return True
            if name == "display" and self._display_is_none(decl.value):
                return True
            if name == "visibility" and self._visibility_is_hidden(decl.value):
                return True
            if name == "color" and self._color_is_white(decl.value):
                return True
        return False
```

`tinycss2.Declaration.value` ist eine Liste von Token-Objekten
(z.B. `NumberToken`, `DimensionToken`, `IdentToken`, `HashToken`,
`FunctionBlock` etc.). Die Wert-Pruefer iterieren ueber diese
Token-Liste und beantworten die jeweilige Hidden-Frage spec-korrekt.


## Etappenplan

### Etappe 86.1 -- tinycss2-Helpers + Pure-Tests

Eigene Datei `src/elder_berry/tools/css_decl_resolver.py` mit:

* `parse_inline_style(style: str) -> list[ResolvedDecl]`
* `ResolvedDecl`-Dataclass: name, value-Tokens, is_important
* `opacity_is_zero(tokens) -> bool`
* `font_size_below_threshold(tokens, threshold_px) -> bool`
* `display_is_none(tokens) -> bool`
* `visibility_is_hidden(tokens) -> bool`
* `color_is_white(tokens) -> bool`

Eigene Testdatei `tests/test_css_decl_resolver.py`. Pure-Function-
Tests, kein HtmlEmailSanitizer-Bezug. Test-Klassen orientieren sich
an den 5 historischen Bypass-Vektoren plus neue Edge-Cases:

* `TestParseInlineStyle` -- happy path, multi-decl, !important,
  Kommentare, unterminierte Kommentare (sollten korrekt zu
  zwei Decls / null Decls fuehren), Whitespace-Varianten.
* `TestCascadeResolver` -- last-decl-wins, important-vor-non,
  identische Property-Mehrfach-Decls.
* `TestOpacityIsZero` -- 0, 0.0, 0.00, .0, 0%, calc(0), var(--x),
  inherit, initial -- alle bisherigen Decimal-Zero-Vektoren plus
  CSS-Spec-Edge-Cases. Negative: 0.01, 0.5, 1.
* `TestFontSizeBelowThreshold` -- 1px, 5px (default-threshold 6 ->
  unter), 6px (genau auf), 14px (drueber). em/rem heuristisch:
  unter 0.5em zaehlt als "unter" -- oder Known Limitation? In
  86.1 als Test dokumentieren, Loesung in 86.2 nachziehen.
* `TestDisplayIsNone` -- "none", "NONE", whitespace-Varianten.
* `TestVisibilityIsHidden` -- "hidden", "HIDDEN".
* `TestColorIsWhite` -- #fff, #ffffff, #FFF, white, WHITE,
  rgb(255,255,255), rgb(255 255 255) (CSS-Spaces-Syntax).
* `TestPerformanceSmoke` -- Median < 100ms pro Mail-Style fuer
  realistische Marketing-Mail-Stylesheets (analog Phase 85.1 V4).

mypy-strict, ruff clean. tinycss2 in pyproject ergaenzt.
Acceptance: alle Tests gruen, Coverage Resolver-Modul = 100%.

**Aufwand: ~1 Session.**

### Etappe 86.2 -- Integration in HtmlEmailSanitizer

* `_style_is_hidden()` ersetzt: nutzt jetzt
  `css_decl_resolver.parse_inline_style()` + die statischen
  Check-Funktionen.
* Alte Module-Konstanten `_HIDDEN_STYLE_PATTERNS`, `_FONT_SIZE_RE`,
  `_OPACITY_RE`, `_CSS_COMMENT_RE`, `_resolve_decl()` werden
  geloescht. **Keine Backward-Compat-Reste** (CLAUDE.md-Regel
  + Konzept-85-V1-Praezedenz).
* Bestehende `tests/test_html_email_sanitizer.py`-Suite bleibt
  unveraendert -- alle 98 Tests muessen weiter gruen sein (das
  ist der wichtigste Akzeptanztest: 5 historische Bypass-Klassen
  bleiben geschlossen).
* Neuer Integrations-Test: `test_unterminated_comment_does_not_leak`
  schliesst die Phase-85.7-Doku-Luecke
  (`opacity:0/*; opacity:1` -> hidden).
* Neuer Integrations-Test: `test_em_unit_below_threshold_is_hidden`
  falls Etappe 86.1 das mitgeloest hat.

mypy-strict, ruff clean.
Acceptance: voller pytest gruen, alle 98 bisherigen Sanitizer-Tests
weiterhin gruen, neue Tests gruen.

**Aufwand: ~halbe Session.**

### Etappe 86.3 -- Doku-Migration

* `docs/concepts/phase-85-html-email-sanitizer.md` Abschnitt 11
  "Known CSS-Limitations" entsprechend reduzieren -- alle
  Bypass-Klassen, die durch tinycss2 jetzt strukturell geschlossen
  sind, aus der Limitations-Liste streichen oder als
  "loesbar via Phase 86" markieren.
* `CLAUDE.md`-Abschnitt "E-MAIL-HANDLING" um einen Satz erweitern:
  "Phase 86: CSS-Style-Decls werden ueber `css_decl_resolver`
  (tinycss2) spec-konform geparst, kein eigenes Regex-Pattern
  in `_style_is_hidden`".
* Journal "Abgeschlossen: Phase 86" mit:
  - Welche 5 historischen Bypass-Klassen sind strukturell zu.
  - Welche Known Limitations bleiben (computed-cascade,
    `<style>`-Block-Selektoren, Render-Tree-Walker).
  - Mini-Perf-Benchmark vorher/nachher.

**Aufwand: ~Viertel Session.**

### Reihenfolge

Strikt sequentiell. 86.2 startet erst, wenn alle 86.1-Tests gruen
und mypy/ruff clean. 86.3 erst nach 86.2.

## Test-Strategie

Die 98 Tests aus `tests/test_html_email_sanitizer.py` sind ab 86.2
**Migrationstests**: sie pruefen, dass der neue Resolver die
gleichen Hidden-Entscheidungen trifft wie der alte Regex-Code.
Brechen sie, ist das ein Architektur-Regression-Signal. Sie werden
nicht angepasst, ausser ein Test war selbst falsch (sehr unwahr-
scheinlich -- 98 Tests sind durch 7 Reviews iteriert).

Neue Test-Vektoren in 86.1, die der Regex-Pipeline schwer fielen:

* `opacity:0/*; opacity:1` -- unterminierter Kommentar bis EOF.
* `opacity:calc(0)` -- calc-Expression mit Zero-Result. (Erst
  parse-Tokens schauen, ob ein einfaches `calc(0)` durch
  Token-Iteration entdeckbar ist. Wenn nein -> Known Limitation.)
* `opacity:var(--invisible)` -- var() ohne Resolver bleibt
  unbestimmt. Spec-konformes Verhalten: NICHT als hidden
  klassifizieren, weil wir den Wert nicht kennen. Trade-off im
  Konzept ausdiskutiert: false-negative ist akzeptabler als
  false-positive bei legitimen Mails.
* `font:1px arial` -- shorthand-Property. tinycss2 parsed das als
  Declaration mit name="font". Wir koennen darin nach DimensionToken
  mit unit=px und value<threshold suchen, das ist ein eigener
  Property-Check. **86.1 entscheidet ob das im Scope ist.**
* Multiple opacity ueber !important-Boundary mit Kommentar-
  Mischformen.

## Definition of Done

Phase 86 gilt als abgeschlossen, wenn:

1. `css_decl_resolver.py` existiert, voll getestet, mypy-strict
   clean. 86.1 Aufwand-Schaetzung gehalten oder Abweichung
   begruendet.
2. `HtmlEmailSanitizer._style_is_hidden` nutzt den Resolver,
   alte Regex-Konstanten geloescht. 86.2 acceptance: alle 98
   bisherigen Tests + neue Integration-Tests gruen.
3. `pyproject.toml` listet `tinycss2>=1.3.0` in den 5 relevanten
   Gruppen (web/server/tower/matrix/remote).
4. `docs/concepts/phase-85-html-email-sanitizer.md` Abschnitt 11
   reduziert auf echte verbleibende Limitations.
5. `CLAUDE.md`-Abschnitt "E-MAIL-HANDLING" reflektiert den Resolver.
6. Journal-Eintrag `## Abgeschlossen: Phase 86`.
7. Optional: Lera-Smoketest mit echter HTML-Marketing-Mail
   bestaetigt: keine Regression in lesbarer Mail-Zusammenfassung.

## Restrisiken

* **tinycss2-API-Bruch:** Library ist 1.x, semver, BSD. Aktive
  Maintenance. Niedrig.
* **Performance:** Token-Parser ist langsamer als Regex. Phase 85.1
  V4-Smoketest (Median <100ms pro Mail) muss in 86.1 nachgewiesen
  werden, sonst Pipeline-Optimierung in 86.x. Realistisch okay,
  weil Mail-Bodies klein sind und Style-Attribute kurz.
* **False-Negatives bei var()/calc() ohne Resolver:** dokumentiert
  als Known Limitation, faengt LLM-Untrusted-Wrapper ab.
* **Iterations-Risiko erneut:** falls Codex weitere CSS-Edge-Cases
  findet, die tinycss2 nicht abdeckt (z.B. Property-Shorthand-
  Decomposition oder CSS-Functions), waere das Phase 87 -- aber
  Wahrscheinlichkeit deutlich geringer als bei Regex, weil
  tinycss2 die Spec implementiert, nicht wir.
