# Phase 87.B – Computed-Background-Heuristik

**Status:** Konzept (2026-05-13)
**Branch:** `feature/phase-87-b-konzept` (Konzept-Commit) →
`feature/phase-87-b-computed-background` (Implementation, geplant)
**Aufwand:** 1 Konzept-Session + ~2-3 Implementations-Sessions (3 Etappen)
**Vorgaenger:** Phase 85 (HtmlEmailSanitizer, V3-Limitation),
Phase 86 (tinycss2-Refactor, `css_decl_resolver`),
Phase 87.1 (Iteration-Crash-Hotfix + Realwelt-Befund Fewo-Direkt)

## Trigger

Phase 85 hat `color:white`/`color:#fff` als Hidden-Marker eingefuehrt.
Konzept-Doc V3 (`phase-85-html-email-sanitizer.md` Revisions-Block) hat
das ausdruecklich als Known Limitation dokumentiert: eine Mail mit
dunklem Body-Background und `color:white`-Text ist optisch lesbar, wird
aber vom Sanitizer gestrippt. Der Test
`test_dark_theme_white_text_is_stripped_known_limitation` schreibt das
seitdem als bewusste False-Positive fest. Damals theoretisches Risiko,
akzeptiert.

**Realwelt-Befund (Phase 87.1, 2026-05-13):** Lera-Smoketest mit einer
echten Fewo-Direkt-Reservierungs-Bestaetigung produzierte zuerst einen
Iteration-Crash (in 87.1 gefixt); nach dem Crash-Fix blieb ein
Inhalts-Verlust uebrig: der CTA-Button "Freunde einladen" mit
`color:#FFFFFF` auf `background-color:#0F51EC` an einem Container-
Eltern-Tag wurde komplett aus der Zusammenfassung gestrippt. Hauptinhalt
der Mail kommt korrekt durch -- nur die als Button gestaltete sichtbare
Aktions-Empfehlung fehlt.

**Eigenkritik beim Konzept-Schreiben:** Section 11 V10 von
`phase-85-html-email-sanitizer.md` (Update nach Phase 86, Stand
2026-05-13) listet die V3-Limitation NICHT mehr. Stattdessen dokumentiert
sie nur die verwandte Inheritance-Limitation
(`<div style="font-size:1px"><span>EVIL</span>` -- Eltern-Style
greift, Filter haengt am leeren Span-Style). Bei der V10-Migration ist
die V3-Limitation versehentlich weggekuerzt worden. Der Fewo-Direkt-
Button kombiniert in der Praxis beide Limitations: die Hidden-Color-
Pruefung kennt weder den Background-Kontext (V3) noch sieht sie den
am Eltern-Container definierten Background (V10-Inheritance).

Phase 87.B addressiert genau diese Kombination: ein Style-Walker
traversiert die Tag-Hierarchie, sammelt die `background-color`
Vorfahren-Decls (Inheritance), und entscheidet ueber eine Helligkeits-
Heuristik, ob `color:white` in dem konkreten Kontext als hidden oder
visible einzustufen ist.

## Abgrenzung

* **Phase 86 (`css_decl_resolver`):** parst einzelne Style-Decls
  spec-konform via tinycss2, fuehrt Cascade fuer `!important` und
  last-wins durch. Phase 87.B baut darauf auf -- der Walker nutzt
  `css_decl_resolver` fuer das Parsen jedes Vorfahren-Style-Strings,
  Cascade wird NICHT erweitert.
* **Phase 86.1 (Section 11 V10 Limitations):** dokumentiert die
  Inheritance-Limitation als generelles "Out-of-Scope, weil kein
  Style-Walker existiert". Phase 87.B implementiert genau den Walker --
  aber bewusst nur fuer `background-color`, nicht fuer `font-size` oder
  andere inheritbare Properties (die bleiben Limitation; Erweiterung
  waere weitere Folge-Phase).
* **Phase 87.1 (Iteration-Crash):** hat das Symptom des Realwelt-
  Befundes ueberhaupt erst sichtbar gemacht. Der Crash-Fix ist
  unabhaengig; Phase 87.B fixt den Inhalts-Verlust, der nach 87.1 als
  einziges Symptom uebrig blieb.

## Ziel

`color:#FFFFFF`/`color:white`/`color:rgb(255,255,255)` und das Legacy-
Attribut `<font color="white">` werden NICHT mehr als hidden gestrippt,
wenn der computed Background des betroffenen Tags im Walker-Pfad als
dunkel erkannt wird (WCAG-Relative-Luminanz unter Schwelle).

Adversarial weiss-auf-weiss bleibt als hidden erkannt:
* Background im Walker-Pfad ist hell → color:white = hidden.
* Kein Background im Walker-Pfad gesetzt → Default "weisser Mail-Body"
  → color:white = hidden (Status-Quo erhalten, siehe Frage B).

## Out of Scope

* **Vollstaendige CSS-Render-Engine.** Wir parsen nur
  `background-color`/`bgcolor` der Vorfahren, kein `background` shorthand,
  keine `background-image`, keine Theme-Variablen.
* **Computed-Cascade fuer andere Properties.** `font-size`-Inheritance
  (V10-Limitation) bleibt unangetastet -- fuer den Fewo-Direkt-Vektor
  brauchen wir nur `background-color`-Cascade.
* **Computed `color`-Inheritance.** Wenn `color:white` am Eltern-Tag
  steht und am Child gar kein `color` gesetzt ist, ist der Child fuer
  uns nicht direkt verdaechtig -- der Hidden-Check wird heute schon
  nur ausgeloest, wenn `style=` am Tag `color:white` enthaelt. Das
  bleibt so.
* **CSS-Variablen / `var(--bg)` im Background.** Analog zu Section 11
  V10 Custom-Properties -- konservativ "kein dunkler bg gefunden",
  faellt damit unter die Default-weiss-Annahme.
* **`background-image`-only Container.** Wenn ein Container nur ein
  Background-Bild und keine `background-color` hat, sehen wir keinen
  bg im Walker-Pfad. Konservativ → Default weiss. Bilder als
  Hintergrund-Definition kann der Sanitizer nicht aufloesen.
* **Section 11 V10 Doku-Migration.** Die fehlende V3-Limitation in
  Section 11 wird in Phase 87.B nur ALS BEFUND dokumentiert. Die
  Section-11-Migration (V11-Update mit Verweis auf 87.B-Fix und
  Klaerung welche Limitations bleiben) ist explizit Folge-Phase, um
  87.B-Konzept-Scope eng zu halten.

## Ausgangslage

### Aktueller Hidden-Check-Pfad

Stand Phase 86 + 87.1, in `src/elder_berry/tools/html_email_sanitizer.py`:

```python
def _style_is_hidden(self, style: str) -> bool:
    decls = parse_style_decls(style)            # tinycss2 via resolver
    if opacity_is_zero(decls): return True
    if font_size_below_threshold(decls, ...): return True
    if display_is_none(decls): return True
    if visibility_is_hidden(decls): return True
    if color_is_white(decls): return True       # <-- hier liegt die V3-Limitation
    return False
```

Und der separate Legacy-Attribut-Pass:

```python
_COLOR_ATTR_HIDDEN = re.compile(r"^(?:#?fff(?:fff)?|white)$", re.IGNORECASE)
for tag in soup.find_all(attrs={"color": _COLOR_ATTR_HIDDEN}):
    tag.decompose()
```

Beide Pfade kennen den Tag-Kontext nicht. Sie sehen nur den Style-String
bzw. nur den Color-Attribut-Wert.

### Was der Walker zu lesen hat

Background-Color kann in HTML-Mails an drei Stellen stehen:

1. **`style="background-color: #0F51EC"`** -- moderne Inline-CSS.
2. **`bgcolor="#0F51EC"`** -- Legacy-HTML-Attribut, in Marketing-Mails
   noch sehr verbreitet (Outlook-Kompatibilitaet).
3. **`<style>`-Block im Head** -- nicht relevant, weil der bereits in
   der Hart-Remove-Phase per `decompose()` aus dem Tree verschwindet
   (Phase 85 4.2). Inline-Style bleibt also die einzige Quelle.

Beide Quellen (1 + 2) muss der Walker beruecksichtigen.

## Architektur

### Walker

Neue private Methode in `HtmlEmailSanitizer`:

```python
def _compute_effective_background(self, tag: Tag) -> str | None:
    """Traversiere Vorfahren des Tags, sammele die naechste explizite
    background-Definition (style oder bgcolor). Return: Color-Token
    als String, oder None wenn nichts gefunden (Default-Pfad).
    """
    for ancestor in itertools.chain([tag], tag.parents):
        bgcolor_attr = ancestor.get("bgcolor")
        if bgcolor_attr:
            return bgcolor_attr
        style_attr = ancestor.get("style", "")
        bg = _background_color_from_style(style_attr)  # via css_decl_resolver
        if bg is not None:
            return bg
    return None
```

Traversal-Reihenfolge: aktueller Tag zuerst (damit `style="background:..."`
am Element selbst gewinnt), dann Eltern bis Wurzel. Erstes Hit gewinnt --
das matched die CSS-Spezifitaets-Regel "naechster explizit gesetzter
Background-Vorfahr".

### Helper im Resolver

Erweiterung von `src/elder_berry/tools/css_decl_resolver.py`:

```python
def background_color_token(decls: list[Decl]) -> Token | None:
    """Cascade-Aufloesung der background-color-Decls (last-important
    > last-non-important). Returnt Token oder None.
    """

def background_is_dark(token: Token, threshold: float = 0.179) -> bool:
    """WCAG-Relative-Luminanz < threshold => dunkel."""
```

Recognition-Validator fuer `background-color` in `_VALIDATORS` analog
zu `color`. Trennung: tokenizer + cascade in `css_decl_resolver`,
sRGB-Linearisierung + Luminanz in einer eigenen kleinen Hilfsfunktion
(pure math, einfach testbar).

### Helligkeits-Heuristik (WCAG-Relative-Luminanz)

```python
def _srgb_to_linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

def _relative_luminance(r: int, g: int, b: int) -> float:
    return (
        0.2126 * _srgb_to_linear(r)
        + 0.7152 * _srgb_to_linear(g)
        + 0.0722 * _srgb_to_linear(b)
    )
```

**Schwelle:** `0.179` -- WCAG-Standard-Schwelle "background ist eher
dunkel oder eher hell" (Punkt, an dem gegen schwarz und gegen weiss
derselbe Kontrast erreicht wird).

Konkrete Werte zur Validierung:

| Background | Luminanz | dunkel? |
| ---------- | -------- | ------- |
| `#000000`  | 0.000    | ja      |
| `#0F51EC` (Fewo-Direkt-Button) | ≈ 0.12 | ja |
| `#888888`  | ≈ 0.226  | nein    |
| `#FFFFFF`  | 1.000    | nein    |

Die naive Variante `max(r,g,b) < 128` wuerde `#0F51EC` nicht als dunkel
erkennen (max=236). Das ist genau der Realwelt-Vektor, den die Phase
loesen soll -- WCAG-Luminanz ist hier strukturell richtig, nicht
optional.

### Integration

Sanitizer-Hook-Signatur wird minimal erweitert:

```python
# vorher
def _style_is_hidden(self, style: str) -> bool: ...

# nachher
def _color_is_hidden_in_context(self, tag: Tag, color_token: Token) -> bool:
    bg = self._compute_effective_background(tag)
    if bg is None:                       # Default = weiss (Frage B)
        return color_is_white_token(color_token)
    bg_token = parse_color(bg)
    if bg_token is None:                 # bg unparsbar => konservativ
        return color_is_white_token(color_token)
    if background_is_dark(bg_token):
        return False                     # weiss auf dunkel = visible
    return color_is_white_token(color_token)
```

Aufgerufen aus:

1. **`_style_is_hidden(tag, style)`** (Signatur aufgeruestet von
   `style: str` zu `tag: Tag, style: str`): wenn der Cascade-Resolver
   eine Color-Decl `color:white` liefert, fragt der Sanitizer ueber
   `_color_is_hidden_in_context(tag, color_token)` -- Walker entscheidet.
   Andere Hidden-Checks (opacity, display, font-size) bleiben tag-frei.
2. **Legacy-Attribut-Pass** (heute regex-basiert in einer Schleife):
   die `_COLOR_ATTR_HIDDEN`-Pruefung ruft denselben Helper. Beide
   Pfade benutzen dieselbe Walker-Logik, das wird zentralisiert -- das
   war die Lehre aus 85.x "zwei Code-Pfade pro Hidden-Check sind teuer".

### Performance

Pro hidden-style-Tag ein Walker-Lauf bis zur ersten background-Definition
oder bis `<body>`. Realwelt-Marketing-HTML: ~30 Tag-Tiefe, ~20-50
hidden-Color-Kandidaten pro Mail. Worst-Case 1500 dict-lookups + ~30
tinycss2-Parses (jeder Vorfahren-Style einmal). Das passt unter die
85.1-V4-Perf-Smoke-Schwelle (100ms Median ueber 5 Fixtures).

**Kein Caching in der ersten Iteration.** Wenn die V4-Smoke nach
87.B-2 unter Druck kommt, wird Memoization (`id(tag) -> bg-token`)
nachgeruestet -- 5 Zeilen, isolierter Pull. Premature optimization
ist hier die teurere Variante.

## Etappenplan

### Etappe 87.B-1 -- Resolver-Erweiterung + Helligkeits-Heuristik

* `css_decl_resolver.py`: `background_color_token`, neuer
  `_VALIDATORS`-Eintrag fuer `background-color`, Token-Parser fuer
  Hex/Named/rgb() (analog zur bestehenden Color-Erkennung).
* Neue Hilfsfunktion `_relative_luminance` + `background_is_dark`
  (in derselben Datei, weil "pure color math" thematisch passt).
* Tests in `tests/test_css_decl_resolver.py`:
  parametrisierte Luminanz-Tests (Hex, Named-Colors, rgb()),
  Schwellen-Edge-Cases (#888 ist NICHT dunkel,
  #0F51EC IST dunkel), Cascade-Tests fuer multiple
  `background-color`-Decls (last-important wins).
* Acceptance: mypy strict + ruff clean, alle Resolver-Tests gruen,
  keine Sanitizer-Aenderung.
* Aufwand: ~halbe Session.

### Etappe 87.B-2 -- Sanitizer-Walker-Integration

* `html_email_sanitizer.py`: `_compute_effective_background`,
  `_color_is_hidden_in_context`, Signatur-Aenderung an
  `_style_is_hidden(tag, style)`.
* Legacy-Attribut-Pass von Regex-Schleife auf Walker-Helper umgestellt
  (kein zweiter Pfad).
* V3-Test `test_dark_theme_white_text_is_stripped_known_limitation`
  wird **umgedreht** und umbenannt zu
  `test_dark_theme_white_text_survives` -- dokumentiert den 87.B-Fix.
* Neue Tests:
  * Fewo-Direkt-Replikat: Container mit `background-color:#0F51EC`,
    Child mit `color:#FFFFFF` → visible.
  * Adversarial-Fall: kein bg gesetzt + `color:white` → hidden
    (Default-weiss-Annahme).
  * Heller bg im Walker-Pfad + `color:white` → hidden.
  * Walker-Tiefe 1 / 5 / 20 Ebenen.
  * `bgcolor`-Attribut (Legacy) am Eltern-Tag + `color:white`-style
    am Child → visible.
  * `<font color="white">` mit dunklem Container → visible.
* Perf-Smoke: bestehende V4-Suite mit dem neuen Walker laufen lassen,
  Median weiterhin < 100ms.
* Acceptance: voller pytest gruen, mypy strict + ruff clean,
  Realwelt-Smoke mit echter Fewo-Direkt-Mail (von Lera).
* Aufwand: ~1 Session.

### Etappe 87.B-3 -- Doku + Befund Section 11 V10

* `CLAUDE.md`-Abschnitt "E-MAIL-HANDLING": kurzer Verweis, dass
  `color:white`-Hidden-Check kontextabhaengig ist (background-Walker
  in Sanitizer).
* `phase-87-b-computed-background-heuristik.md`-Konzept-Doc selbst
  bekommt einen Abschnitt "Abgeschlossen" mit Befunden -- analog wie
  bei Phase 85/86.
* `phase-85-html-email-sanitizer.md` Section 11 V10:
  **bewusst NICHT in 87.B angefasst.** Statt dessen: in dieser Konzept-
  Datei (Abschnitt "Restrisiken") und im Journal als Befund vermerken,
  damit eine spaetere Doku-Migrations-Phase die Section-11-Limitation-
  Liste konsistent zur 87.B-Realitaet zieht. Anti-Scope-Schutz.
* Aufwand: ~Viertel-Session.

## Test-Strategie

### TestBackgroundLuminance (im Resolver-Test)

Pure-Math-Tests fuer `_relative_luminance` und `background_is_dark`.
Parametrisiert ueber:

* Hex 3-stellig (`#000`, `#fff`, `#888`, `#03f`).
* Hex 6-stellig inkl. Fewo-Direkt-Replikat (`#0F51EC`).
* Named-Colors (`black`, `white`, `navy`, `red`, `yellow`).
* `rgb(...)` mit Whitespace-Varianten.

Edge-Cases: `rgba(...)`-Alpha bleibt ignoriert (Sanitizer nimmt
konservativ den RGB-Anteil, Alpha-Compositing waere Render-Engine-
Scope).

### TestBackgroundCascade (im Resolver-Test)

Multi-Decl-Cascade fuer `background-color` analog zu den 86er
Cascade-Tests:

* last-wins ohne `!important`.
* `!important` priorisiert.
* Ungueltige spaetere Decls fallen zurueck auf vorherige gueltige
  (Lehre aus Phase 87.1.1).

### TestComputedBackgroundWalker (im Sanitizer-Test)

* Walker-Tiefe 1: bg am Tag selbst.
* Walker-Tiefe 5: bg an einem mittleren Vorfahr.
* Walker-Tiefe 20: bg am Body.
* Kein bg im Pfad: liefert None → Default weiss greift.
* `bgcolor`-Attribut wird gefunden.
* `style="background-color:..."`-Decl wird gefunden.
* `bgcolor` UND `style` am selben Tag: wer gewinnt? Definierte
  Reihenfolge: `bgcolor` zuerst gepruefft (Legacy-Marketing-Mails
  setzen oft beides redundant; wenn beide da sind, ist es egal).

### TestColorIsHiddenInContext (im Sanitizer-Test)

* `color:white` + dunkler Walker-bg → not hidden.
* `color:white` + heller Walker-bg → hidden.
* `color:white` + kein Walker-bg → hidden (Default).
* `<font color="white">` + dunkler Container → not hidden.
* Fewo-Direkt-Replikat exact: vollstaendige Tag-Hierarchie wie in der
  Realwelt-Mail.

### Regressionsschutz

* Alle bestehenden 85.x/86er-Hidden-Tests bleiben gruen
  (`opacity:0`, `display:none`, `visibility:hidden`, `font-size:1px`).
* `TestHistoricalBypassVectors` aus 87.1 bleibt gruen.
* V4-Perf-Smoke unter 100ms Median.

## Definition of Done

Phase 87.B gilt als abgeschlossen, wenn:

1. `css_decl_resolver.background_color_token` + `background_is_dark`
   existieren, getestet, mypy/ruff clean.
2. `HtmlEmailSanitizer._compute_effective_background` +
   `_color_is_hidden_in_context` existieren; `_style_is_hidden`-
   Signatur aufgeruestet; Legacy-Color-Attribut-Pass auf Walker
   umgestellt.
3. Umgedrehter V3-Test
   (`test_dark_theme_white_text_survives`) ist gruen.
4. Fewo-Direkt-Replikat-Test ist gruen.
5. Voller pytest-Lauf gruen, keine Regressionen, V4-Perf-Smoke ok.
6. Lera-Realwelt-Smoketest mit der konkreten Fewo-Direkt-Mail: CTA
   "Freunde einladen" steht in der Zusammenfassung.
7. CLAUDE.md kurzer Hinweis ergaenzt.
8. Journal: `## Abgeschlossen: Phase 87.B` mit Befunden + expliziter
   Verweis "Section 11 V10 in 85-Konzept-Doc braucht Folge-Migration".

## Restrisiken

### V3-Limitation-Migration in Section 11 V10

Section 11 V10 listet die V3-Limitation nicht. Phase 87.B fixt sie
strukturell, dokumentiert das im 87.B-Konzept und im Journal, aendert
aber Section 11 in `phase-85-html-email-sanitizer.md` ABSICHTLICH
NICHT. Folge-Phase muss:

* Section 11 V10 → V11 erweitern: V3-Limitation als gefixt vermerken,
  Inheritance-Limitation auf andere Properties (font-size, color)
  einschraenken, Verweis auf 87.B-Konzept aufnehmen.
* Restliche Inheritance-Faelle (font-size, opacity-Inheritance) ggf.
  als eigene Folge-Limitation klarstellen.

### Walker-Tiefe vs. Perf

Annahme "30 Tag-Tiefe" ist empirisch, nicht hart belegt. Falls eine
adversarial konstruierte Mail extrem tief verschachtelt ist (z.B.
1000 Ebenen, wie 85-`test_deeply_nested_html` schon testet), wird
der Walker langsam. Schutz: bestehender Perf-Smoke + Iteration-Crash-
Guard aus 87.1 (max-recursion). Falls knapp wird Caching nachgeruestet
(siehe Architektur-Abschnitt).

### Color-Inheritance bleibt offen

Wenn ein Eltern-Tag `color:white` am Style hat und der Child gar kein
`color` setzt, sehen wir den Child nicht als verdaechtig -- der
Hidden-Check feuert nur bei explizitem `color:white` am Tag selbst.
Das war auch vor 87.B so; 87.B macht es nicht schlimmer, aber auch
nicht besser. Realer Vektor selten, weil Marketing-Mails Color
typischerweise pro Text-Element setzen.

### `background:` Shorthand

Phase 87.B parst nur `background-color`. Wenn eine Mail `background:
#0F51EC` (Shorthand) statt `background-color: #0F51EC` nutzt, sieht
der Walker keinen bg an dem Tag -- konservativ Default-weiss. In der
Realwelt nutzen Marketing-Mails fast immer `background-color` (Outlook-
Kompatibilitaet), aber das ist eine Restwahrscheinlichkeit. Trivial
nachruestbar, wenn ein realer Vektor auftaucht.

### CSS-Variablen / `var(--bg)`

Analog zu Section 11 V10. Walker sieht `background-color:var(--theme-
bg)`, kann den Wert nicht aufloesen, liefert None → Default weiss.
Bei Dark-Theme-Templates mit CSS-Variablen wuerde der Fix nicht
greifen -- color:white wuerde weiterhin als hidden gestrippt. In
Realwelt-Mail-Clients ist Custom-Property-Support unzuverlaessig
(Apple Mail ja, Gmail meist nein), sodass solche Templates ohnehin
unsicher rendern.

### Background-Bild ohne Background-Farbe

Container, der nur `background-image: url(...)` hat und keine
`background-color`, liefert dem Walker nichts → Default-weiss. Wenn
das Bild faktisch dunkel ist und der Text weiss, wuerde der Sanitizer
strippen. Bilder als Background-Definition kann der Sanitizer ohne
OCR und Image-Loading nicht aufloesen -- bleibt Limitation, wenn ein
realer Vektor auftaucht, ist die Antwort "Marketing-Mail-Erkennung
per Subject" (Section 7.3 in 85-Konzept), nicht Sanitizer-Aufruestung.
