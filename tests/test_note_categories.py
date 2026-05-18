"""Tests: note_categories -- Whitelist + canonical_category()-Resolver."""

from __future__ import annotations

import pytest

from elder_berry.tools.note_categories import (
    DEFAULT_CATEGORY,
    KNOWN_CATEGORIES,
    canonical_category,
)


class TestWhitelist:
    def test_default_category_is_known(self):
        assert DEFAULT_CATEGORY in KNOWN_CATEGORIES

    def test_default_category_value(self):
        assert DEFAULT_CATEGORY == "Allgemein"

    def test_known_categories_are_single_word(self):
        """Pattern-Trenner erlaubt nur Single-Word-Categories."""
        for category in KNOWN_CATEGORIES:
            assert " " not in category


class TestCanonicalCategory:
    def test_exact_match_is_known(self):
        assert canonical_category("Einkauf") == ("Einkauf", True)

    def test_lowercase_resolves_to_canonical(self):
        assert canonical_category("einkauf") == ("Einkauf", True)

    def test_uppercase_resolves_to_canonical(self):
        assert canonical_category("EINKAUF") == ("Einkauf", True)

    def test_unknown_category_is_override(self):
        category, is_known = canonical_category("MoscowMule")
        assert category == "MoscowMule"
        assert is_known is False

    def test_strips_whitespace_on_known(self):
        assert canonical_category("  Arbeit  ") == ("Arbeit", True)

    def test_strips_whitespace_on_unknown(self):
        assert canonical_category("  Quatsch  ") == ("Quatsch", False)

    def test_unknown_keeps_original_casing(self):
        """Override-Fall: Eingabe-Schreibweise bleibt unveraendert."""
        category, is_known = canonical_category("eInKaUfSlIsTe")
        assert category == "eInKaUfSlIsTe"
        assert is_known is False

    @pytest.mark.parametrize("known", sorted(KNOWN_CATEGORIES))
    def test_all_known_categories_roundtrip(self, known):
        assert canonical_category(known) == (known, True)

    @pytest.mark.parametrize("known", sorted(KNOWN_CATEGORIES))
    def test_all_known_categories_case_insensitive(self, known):
        category, is_known = canonical_category(known.lower())
        assert category == known
        assert is_known is True
