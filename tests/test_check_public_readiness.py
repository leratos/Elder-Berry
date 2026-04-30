"""Tests fuer scripts/check_public_readiness.py.

Phase 71: Das Audit-Skript wurde generisch gemacht. Statt hardcoded
Maintainer-Werte laedt es Patterns aus einer optionalen Datei
``.public-readiness-blocklist.txt``. Diese Tests decken den Loader,
das Default-Fallback-Verhalten und das End-to-End-Scannen ab.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.check_public_readiness import (
    BLOCKLIST_FILENAME,
    DEFAULT_BLOCKLIST_PATTERNS,
    _build_custom_blocklist_category,
    _load_blocklist_patterns,
    _scan_file,
    build_categories,
    CategoryStats,
)


# ---------------------------------------------------------------------------
# _load_blocklist_patterns
# ---------------------------------------------------------------------------


class TestLoadBlocklistPatterns:
    """Loader-Logik fuer .public-readiness-blocklist.txt."""

    def test_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        # Frischer Repo-Root ohne Blocklist.
        assert _load_blocklist_patterns(tmp_path) == DEFAULT_BLOCKLIST_PATTERNS

    def test_returns_defaults_when_file_empty(self, tmp_path: Path) -> None:
        (tmp_path / BLOCKLIST_FILENAME).write_text("", encoding="utf-8")
        assert _load_blocklist_patterns(tmp_path) == DEFAULT_BLOCKLIST_PATTERNS

    def test_returns_defaults_when_only_comments(self, tmp_path: Path) -> None:
        # Datei nur mit Kommentar-Zeilen / Whitespace -> faellt auf
        # Defaults zurueck (kein Skeleton-Audit ohne Patterns).
        content = "# nur kommentare\n\n   \n# noch einer\n"
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        assert _load_blocklist_patterns(tmp_path) == DEFAULT_BLOCKLIST_PATTERNS

    def test_loads_simple_patterns(self, tmp_path: Path) -> None:
        content = "foo\\.com\nbar\\.tld\n"
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        patterns = _load_blocklist_patterns(tmp_path)
        assert patterns == ("foo\\.com", "bar\\.tld")

    def test_skips_comment_lines(self, tmp_path: Path) -> None:
        content = (
            "# header comment\nreal-pattern\\.com\n# another comment\nsecond-pattern\n"
        )
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        patterns = _load_blocklist_patterns(tmp_path)
        assert patterns == ("real-pattern\\.com", "second-pattern")

    def test_strips_inline_comments(self, tmp_path: Path) -> None:
        content = "domain\\.com   # production domain\n"
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        patterns = _load_blocklist_patterns(tmp_path)
        assert patterns == ("domain\\.com",)

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        content = "\n\nfoo\n\n\nbar\n\n"
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        patterns = _load_blocklist_patterns(tmp_path)
        assert patterns == ("foo", "bar")

    def test_preserves_pattern_order(self, tmp_path: Path) -> None:
        # Reihenfolge der Patterns ist relevant fuer reproducierbare
        # Audit-Reports -- Loader darf nicht sortieren.
        content = "z-pattern\na-pattern\nm-pattern\n"
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        patterns = _load_blocklist_patterns(tmp_path)
        assert patterns == ("z-pattern", "a-pattern", "m-pattern")

    def test_handles_utf8_content(self, tmp_path: Path) -> None:
        content = "muenchen\\.de\nkohtz\\.de  # mit Kommentar\n"
        (tmp_path / BLOCKLIST_FILENAME).write_text(content, encoding="utf-8")
        patterns = _load_blocklist_patterns(tmp_path)
        assert patterns == ("muenchen\\.de", "kohtz\\.de")


# ---------------------------------------------------------------------------
# _build_custom_blocklist_category
# ---------------------------------------------------------------------------


class TestBuildCustomBlocklistCategory:
    """Compile-Logik fuer Roh-Patterns -> Category."""

    def test_compiles_simple_patterns(self) -> None:
        cat = _build_custom_blocklist_category(("foo\\.com", "bar"))
        assert cat.key == "custom_blocklist"
        assert cat.severity == "high"
        assert len(cat.patterns) == 2
        assert all(isinstance(p, re.Pattern) for p in cat.patterns)

    def test_patterns_are_case_insensitive(self) -> None:
        cat = _build_custom_blocklist_category(("foo\\.com",))
        assert cat.patterns[0].search("FOO.COM") is not None
        assert cat.patterns[0].search("Foo.Com") is not None

    def test_skips_invalid_regex(self, capsys: pytest.CaptureFixture) -> None:
        # Ungueltige Regex (offene Klammer) darf das Audit nicht
        # crashen lassen -- die Zeile wird mit Warnung uebersprungen.
        cat = _build_custom_blocklist_category(
            ("valid-pattern", "[unclosed", "another-valid")
        )
        assert len(cat.patterns) == 2
        captured = capsys.readouterr()
        assert "[unclosed" in captured.err
        assert "ungueltig" in captured.err.lower()

    def test_empty_patterns_yields_empty_category(self) -> None:
        cat = _build_custom_blocklist_category(())
        assert cat.patterns == ()
        assert cat.key == "custom_blocklist"


# ---------------------------------------------------------------------------
# build_categories (Integration: Loader + Builder)
# ---------------------------------------------------------------------------


class TestBuildCategories:
    """Integration: build_categories liefert generic + custom mix."""

    def test_no_blocklist_uses_defaults(self, tmp_path: Path) -> None:
        cats = build_categories(tmp_path)
        keys = [c.key for c in cats]
        assert keys == ["custom_blocklist", "lan_ip", "matrix_id"]
        # Defaults muessen example.com finden.
        custom = cats[0]
        assert any(p.search("example.com") for p in custom.patterns)
        assert any(p.search("your-domain.tld") for p in custom.patterns)

    def test_with_blocklist_loads_custom(self, tmp_path: Path) -> None:
        (tmp_path / BLOCKLIST_FILENAME).write_text(
            "my-domain\\.com\n", encoding="utf-8"
        )
        cats = build_categories(tmp_path)
        custom = cats[0]
        assert any(p.search("my-domain.com") for p in custom.patterns)
        # Defaults sind WEG, sobald die Datei existiert und Patterns hat.
        assert not any(p.search("example.com") for p in custom.patterns)

    def test_generic_categories_always_present(self, tmp_path: Path) -> None:
        # lan_ip + matrix_id sind unabhaengig von der Blocklist.
        cats = build_categories(tmp_path)
        lan_ip = next(c for c in cats if c.key == "lan_ip")
        matrix = next(c for c in cats if c.key == "matrix_id")
        assert any(p.search("10.0.0.5") for p in lan_ip.patterns)
        assert any(p.search("@bot:matrix.example.com") for p in matrix.patterns)


# ---------------------------------------------------------------------------
# _scan_file (End-to-End-Treffer)
# ---------------------------------------------------------------------------


def _make_results(cats) -> dict[str, CategoryStats]:
    return {
        c.key: CategoryStats(
            label=c.label,
            severity=c.severity,
            description=c.description,
            recommendation=c.recommendation,
        )
        for c in cats
    }


class TestScanFile:
    """End-to-End: scan_file findet Treffer in echten Dateien."""

    def test_finds_custom_blocklist_match(self, tmp_path: Path) -> None:
        # Blocklist mit "secret-host" -- Treffer in einer .py-Datei.
        (tmp_path / BLOCKLIST_FILENAME).write_text(
            "\\bsecret-host\\b\n", encoding="utf-8"
        )
        target = tmp_path / "module.py"
        target.write_text("URL = 'https://secret-host/api'\n", encoding="utf-8")
        cats = build_categories(tmp_path)
        results = _make_results(cats)
        _scan_file(target, tmp_path, results, cats)

        custom = results["custom_blocklist"]
        assert len(custom.findings) == 1
        finding = custom.findings[0]
        assert finding.match == "secret-host"
        assert finding.line == 1
        assert finding.file == "module.py"

    def test_no_findings_with_default_blocklist_in_clean_repo(
        self, tmp_path: Path
    ) -> None:
        # Frisches Repo ohne example.com / your-domain.tld im Code:
        # Default-Blocklist soll NICHTS finden.
        target = tmp_path / "clean.py"
        target.write_text("x = 1\nprint('hello world')\n", encoding="utf-8")
        cats = build_categories(tmp_path)
        results = _make_results(cats)
        _scan_file(target, tmp_path, results, cats)
        for cat_key, stats in results.items():
            assert stats.findings == [], (
                f"Unerwarteter Treffer in {cat_key}: "
                f"{[f.match for f in stats.findings]}"
            )

    def test_default_blocklist_finds_skeleton_string(self, tmp_path: Path) -> None:
        # Wenn ein Fork example.com im Code hat, soll das Skeleton-Pattern
        # das anzeigen -- als Demo, dass das Tool grundsaetzlich laeuft.
        target = tmp_path / "config.py"
        target.write_text("DOMAIN = 'example.com'\n", encoding="utf-8")
        cats = build_categories(tmp_path)
        results = _make_results(cats)
        _scan_file(target, tmp_path, results, cats)
        custom = results["custom_blocklist"]
        assert len(custom.findings) == 1
        assert custom.findings[0].match.lower() == "example.com"

    def test_lan_ip_still_works_independent_of_blocklist(self, tmp_path: Path) -> None:
        # Kein Blocklist-File; LAN-IP-Erkennung muss trotzdem laufen.
        target = tmp_path / "config.py"
        target.write_text("HOST = '10.20.30.40'  # internes Geraet\n", encoding="utf-8")
        cats = build_categories(tmp_path)
        results = _make_results(cats)
        _scan_file(target, tmp_path, results, cats)
        lan = results["lan_ip"]
        assert len(lan.findings) == 1
        assert lan.findings[0].match == "10.20.30.40"

    def test_matrix_id_still_works_independent_of_blocklist(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "config.py"
        target.write_text("BOT = '@elder:matrix.example.com'\n", encoding="utf-8")
        cats = build_categories(tmp_path)
        results = _make_results(cats)
        _scan_file(target, tmp_path, results, cats)
        matrix = results["matrix_id"]
        assert len(matrix.findings) == 1
        assert "@elder:matrix.example.com" in matrix.findings[0].match
