"""Tests: safe_log -- CR/LF-Schutz fuer Log-Forgery-Pravention."""
from __future__ import annotations

import pytest

from elder_berry.core.log_sanitize import safe_log


class TestSafeLog:
    @pytest.mark.parametrize("value,expected", [
        ("hallo", "hallo"),
        ("", ""),
        ("   ", "   "),
        ("with spaces and 123", "with spaces and 123"),
        ("Umlaute äöü ß", "Umlaute äöü ß"),
        ("emoji ✨🤖", "emoji ✨🤖"),
    ])
    def test_passthrough_for_clean_strings(self, value, expected):
        assert safe_log(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("a\nb", "ab"),
        ("a\rb", "ab"),
        ("a\r\nb", "ab"),
        ("\nstart", "start"),
        ("end\n", "end"),
        ("multi\nline\nlog", "multilinelog"),
    ])
    def test_strips_cr_and_lf(self, value, expected):
        assert safe_log(value) == expected

    def test_log_forgery_attempt(self):
        """Klassischer Log-Forgery-Vektor: gefakete Audit-Zeile injizieren."""
        attack = "alice\nINFO: AUDIT: secret 'admin_token' geloescht von 127.0.0.1"
        result = safe_log(attack)
        # Newline entfernt -> keine zweite Log-Zeile entsteht
        assert "\n" not in result
        # Inhalt laeuft auf einer Zeile zusammen, bleibt aber sichtbar
        assert "alice" in result
        assert "AUDIT" in result

    def test_accepts_non_string_objects(self):
        assert safe_log(42) == "42"
        assert safe_log(True) == "True"
        assert safe_log(None) == "None"
        assert safe_log(["a", "b"]) == "['a', 'b']"

    def test_object_with_dunder_str(self):
        class Custom:
            def __str__(self) -> str:
                return "custom\nrepr"

        assert safe_log(Custom()) == "customrepr"

    def test_no_other_chars_changed(self):
        """Tabs, Backslashes, Quotes etc. bleiben unangetastet."""
        s = "tab\there\\backslash\"quote'apostrophe"
        assert safe_log(s) == s
