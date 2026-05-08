"""Tests: MarkdownRenderer -- server-side Sanitization (Phase 78 Etappe 3)."""

from __future__ import annotations

from elder_berry.web.markdown_renderer import MarkdownRenderer


class TestBasicRendering:
    def test_empty_input(self) -> None:
        assert MarkdownRenderer().render("") == ""

    def test_paragraph(self) -> None:
        out = MarkdownRenderer().render("Hallo Welt")
        assert "<p>" in out
        assert "Hallo Welt" in out

    def test_heading(self) -> None:
        out = MarkdownRenderer().render("# Titel\n\n## Unter")
        assert "<h1>Titel</h1>" in out
        assert "<h2>Unter</h2>" in out

    def test_list(self) -> None:
        out = MarkdownRenderer().render("- a\n- b\n- c")
        assert "<ul>" in out
        assert "<li>a</li>" in out

    def test_code_block(self) -> None:
        out = MarkdownRenderer().render("```python\nprint('hi')\n```")
        assert "<pre>" in out
        assert "<code" in out
        assert "print" in out

    def test_link(self) -> None:
        out = MarkdownRenderer().render("[Link](https://example.com)")
        assert '<a href="https://example.com"' in out


class TestSanitization:
    """Sicherheitsfokus: kein aktives Markup mit Script-Effekt im Output.

    `html: False` im Parser escaped Roh-HTML zu Text ('&lt;script&gt;...'
    statt '<script>...'). Das ist sicher -- Browser rendert das als
    Plain-Text. Wir pruefen daher *aktive* Tag-Formen, nicht den
    String-Inhalt.
    """

    def test_strips_active_script_tag(self) -> None:
        out = MarkdownRenderer().render("Anfang <script>alert(1)</script> Ende")
        # Kein aktiver <script>-Tag (mit echtem '<')
        assert "<script>" not in out
        assert "</script>" not in out

    def test_strips_iframe(self) -> None:
        out = MarkdownRenderer().render('<iframe src="evil"></iframe>')
        assert "<iframe" not in out

    def test_strips_style_tag(self) -> None:
        out = MarkdownRenderer().render("<style>body{display:none}</style>")
        assert "<style" not in out

    def test_strips_active_event_handler(self) -> None:
        out = MarkdownRenderer().render('<a href="x" onclick="alert(1)">x</a>')
        # Kein aktives onclick-Attribut im echten <a>-Element
        assert '<a href="x" onclick=' not in out

    def test_strips_active_javascript_href(self) -> None:
        out = MarkdownRenderer().render("[click](javascript:alert(1))")
        # Wichtig: kein <a href="javascript:..."> aktiv im Output.
        assert 'href="javascript:' not in out

    def test_allows_https_link(self) -> None:
        out = MarkdownRenderer().render("[ok](https://example.com)")
        assert "https://example.com" in out

    def test_allows_mailto_link(self) -> None:
        out = MarkdownRenderer().render("[mail](mailto:a@b.de)")
        assert "mailto:a@b.de" in out

    def test_bleach_layer_strips_html_passthrough(self) -> None:
        """Defense-in-Depth: wenn jemand den Parser mit html=True
        konfiguriert, muss bleach den XSS-Schmutz weiterhin abfangen."""
        from markdown_it import MarkdownIt

        permissive = MarkdownIt("commonmark", {"html": True})
        renderer = MarkdownRenderer(renderer=permissive)
        out = renderer.render("ok <script>alert(1)</script> done")
        # Bleach strippt das aktive Script-Tag, auch wenn der Parser
        # es durchgelassen hat.
        assert "<script>" not in out
        assert "<script" not in out


class TestRobustness:
    def test_does_not_crash_on_garbled_input(self) -> None:
        """Parser-Fehler -> Fallback auf escapeden Plain-Text."""
        renderer = MarkdownRenderer()
        # Edge: nicht-druckbare Zeichen
        out = renderer.render("\x00\x01\x02 normal text")
        # Kein Crash, irgendein String zurueck.
        assert isinstance(out, str)

    def test_roundtrip_block_with_codeblock(self) -> None:
        """Ein realistischer Saleria-Output (Konzept §4-Template)."""
        md = (
            "Spielt Tracks ueber die Spotify Web API direkt aus Matrix.\n\n"
            "## Erste Beispielanfrage\n\n"
            '- "spiel was von Hans Zimmer"\n'
        )
        out = MarkdownRenderer().render(md)
        assert "<h2>" in out
        assert "Spotify Web API" in out
        assert "Hans Zimmer" in out
