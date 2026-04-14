"""Tests für StartupSummary (Phase 52.2)."""

from __future__ import annotations

import pytest

from elder_berry.core.startup_summary import StartupSummary


class TestStartupSummaryAdd:
    """add() validiert Input und füllt Einträge."""

    def test_add_increments_length(self):
        s = StartupSummary()
        assert len(s) == 0
        s.add("LLM", "ok")
        assert len(s) == 1
        s.add("Matrix", "warn", "kein Token")
        assert len(s) == 2

    def test_add_strips_whitespace(self):
        s = StartupSummary()
        s.add("  LLM  ", "ok", "  Anthropic  ")
        e = s.entries[0]
        assert e.component == "LLM"
        assert e.detail == "Anthropic"

    def test_add_invalid_status_raises(self):
        s = StartupSummary()
        with pytest.raises(ValueError, match="Ungültiger Status"):
            s.add("LLM", "wrong")  # type: ignore[arg-type]

    def test_add_empty_component_raises(self):
        s = StartupSummary()
        with pytest.raises(ValueError):
            s.add("", "ok")
        with pytest.raises(ValueError):
            s.add("   ", "ok")


class TestStartupSummaryQueries:
    """counts(), has_failures(), entries."""

    def test_counts(self):
        s = StartupSummary()
        s.add("A", "ok")
        s.add("B", "ok")
        s.add("C", "warn")
        s.add("D", "fail")
        c = s.counts()
        assert c == {"ok": 2, "warn": 1, "fail": 1}

    def test_has_failures_true(self):
        s = StartupSummary()
        s.add("A", "ok")
        s.add("B", "fail")
        assert s.has_failures() is True

    def test_has_failures_false(self):
        s = StartupSummary()
        s.add("A", "ok")
        s.add("B", "warn")
        assert s.has_failures() is False

    def test_entries_is_immutable_tuple(self):
        s = StartupSummary()
        s.add("A", "ok")
        es = s.entries
        assert isinstance(es, tuple)
        # Mutation der Tuple-Kopie wirkt nicht zurück
        with pytest.raises((TypeError, AttributeError)):
            es[0].component = "X"  # type: ignore[misc]


class TestStartupSummaryRender:
    """ASCII-Box-Rendering."""

    def test_empty_summary_renders(self):
        s = StartupSummary()
        out = s.render()
        assert "Saleria – Startup Summary" in out
        assert "(keine Komponenten)" in out
        assert out.startswith("╔")
        assert out.endswith("╝")

    def test_render_contains_all_entries(self):
        s = StartupSummary()
        s.add("LLM", "ok", "Anthropic")
        s.add("Matrix", "warn", "kein Token")
        s.add("Tower", "fail", "nicht erreichbar")
        out = s.render()
        assert "LLM" in out
        assert "Anthropic" in out
        assert "Matrix" in out
        assert "kein Token" in out
        assert "Tower" in out
        assert "nicht erreichbar" in out

    def test_render_uses_status_glyphs(self):
        s = StartupSummary()
        s.add("A", "ok")
        s.add("B", "warn")
        s.add("C", "fail")
        out = s.render()
        assert "✓" in out
        assert "⚠" in out
        assert "✗" in out

    def test_render_lines_have_consistent_width(self):
        s = StartupSummary()
        s.add("A", "ok", "kurz")
        s.add("Eine ziemlich lange Komponente", "warn", "mit Detail-Text")
        out = s.render()
        lines = out.splitlines()
        widths = {len(line) for line in lines}
        assert len(widths) == 1, f"Zeilen unterschiedlich breit: {widths}"

    def test_render_uses_custom_title(self):
        s = StartupSummary(title="Testlauf")
        s.add("X", "ok")
        out = s.render()
        assert "Testlauf" in out


class TestStartupSummaryMatrix:
    """Matrix-Markdown-Format."""

    def test_empty_matrix_message(self):
        s = StartupSummary()
        msg = s.to_matrix_message()
        assert "Saleria" in msg
        assert "keine Komponenten" in msg

    def test_matrix_message_contains_entries(self):
        s = StartupSummary()
        s.add("LLM", "ok", "Anthropic")
        s.add("Email", "warn", "nicht konfiguriert")
        msg = s.to_matrix_message()
        assert "**LLM**" in msg
        assert "Anthropic" in msg
        assert "**Email**" in msg
        assert "nicht konfiguriert" in msg

    def test_matrix_message_summary_line(self):
        s = StartupSummary()
        s.add("A", "ok")
        s.add("B", "warn")
        s.add("C", "fail")
        msg = s.to_matrix_message()
        assert "1 ok" in msg
        assert "1 warn" in msg
        assert "1 fail" in msg

    def test_matrix_message_uses_glyphs(self):
        s = StartupSummary()
        s.add("X", "ok")
        msg = s.to_matrix_message()
        assert "✓" in msg
