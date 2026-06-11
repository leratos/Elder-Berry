"""Tests fuer place_types -- Typ-/Reisemodus-Validierung (Phase 97, R2-C1/C2).

Diese Funktionen sind die Code-GARANTIE (nicht der LLM): erfundene Typen
und Reisemodus-Synonyme duerfen nicht in den API-Call bzw. den Radius-
Lookup durchschlagen.
"""

from __future__ import annotations

import pytest

from elder_berry.tools.maps_link_builder import VALID_TRAVEL_MODES
from elder_berry.tools.nearby_place_search import RADIUS_BY_MODE
from elder_berry.tools.place_types import (
    SUPPORTED_INCLUDED_TYPES,
    expand_exclude_types,
    normalize_included_type,
    normalize_travel_mode,
)


class TestNormalizeIncludedType:
    def test_table_a_type_passes(self) -> None:
        assert normalize_included_type("bar") == "bar"
        assert normalize_included_type("supermarket") == "supermarket"

    def test_case_insensitive_and_trimmed(self) -> None:
        assert normalize_included_type("  BAR ") == "bar"

    def test_invented_type_rejected(self) -> None:
        # Kernfall R2-C1: shisha_shop existiert nicht -> None (Freitext-Pfad).
        assert normalize_included_type("shisha_shop") is None

    def test_unknown_type_rejected(self) -> None:
        assert normalize_included_type("rockerbar") is None

    def test_none_and_empty(self) -> None:
        assert normalize_included_type(None) is None
        assert normalize_included_type("") is None
        assert normalize_included_type("   ") is None


class TestNormalizeTravelMode:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("driving", "driving"),
            ("car", "driving"),
            ("auto", "driving"),
            ("mit dem auto", "driving"),
            ("walking", "walking"),
            ("foot", "walking"),
            ("zu fuss", "walking"),
            ("zu-fuss", "walking"),
            ("laufen", "walking"),
            ("bicycling", "bicycling"),
            ("fahrrad", "bicycling"),
            ("rad", "bicycling"),
            ("transit", "transit"),
            ("oepnv", "transit"),
            ("öpnv", "transit"),
            ("bahn", "transit"),
        ],
    )
    def test_synonyms_map_to_vocabulary(self, raw: str, expected: str) -> None:
        result = normalize_travel_mode(raw)
        assert result == expected
        assert result in VALID_TRAVEL_MODES

    def test_case_insensitive(self) -> None:
        assert normalize_travel_mode("Auto") == "driving"

    def test_eszett_spelling_maps_to_walking(self) -> None:
        # Codex-Review PR #302: normale deutsche Schreibung "zu Fuß".
        assert normalize_travel_mode("zu Fuß") == "walking"
        assert normalize_travel_mode("zu FUSS") == "walking"
        assert normalize_travel_mode("Fuß") == "walking"

    def test_unknown_returns_none(self) -> None:
        # Unbekanntes -> None (Rueckfrage), KEIN KeyError im Radius-Lookup.
        assert normalize_travel_mode("teleport") is None
        assert normalize_travel_mode("flying") is None

    def test_none_and_empty(self) -> None:
        assert normalize_travel_mode(None) is None
        assert normalize_travel_mode("") is None


class TestSingleSourceOfTruth:
    """B3: RADIUS_BY_MODE und das Synonym-Ziel duerfen NICHT driften."""

    def test_radius_keys_match_vocabulary(self) -> None:
        # Die einzige Stelle, die das Vokabular definiert, ist
        # MapsLinkBuilder.VALID_TRAVEL_MODES. RADIUS_BY_MODE muss exakt
        # dieselben Modi abdecken -- sonst KeyError oder toter Modus.
        assert set(RADIUS_BY_MODE) == set(VALID_TRAVEL_MODES)

    def test_every_synonym_target_is_a_valid_mode(self) -> None:
        # Jeder Modus, den normalize_travel_mode liefern kann, muss im
        # Vokabular liegen.
        for mode in VALID_TRAVEL_MODES:
            assert normalize_travel_mode(mode) == mode

    def test_included_types_nonempty(self) -> None:
        assert len(SUPPORTED_INCLUDED_TYPES) > 0


class TestExpandExcludeTypes:
    def test_bar_expands_to_hookah_and_siblings(self) -> None:
        # Codex-Review PR #302: bar muss hookah_bar mitfangen.
        expanded = expand_exclude_types(("bar",))
        assert "bar" in expanded
        assert "hookah_bar" in expanded

    def test_unknown_type_passes_through(self) -> None:
        assert expand_exclude_types(("supermarket",)) == frozenset({"supermarket"})

    def test_skips_blank_entries(self) -> None:
        assert expand_exclude_types(("", "  ", "bar")) == expand_exclude_types(("bar",))

    def test_empty_is_empty(self) -> None:
        assert expand_exclude_types(()) == frozenset()

    def test_lowercases_and_dedups(self) -> None:
        assert expand_exclude_types(("BAR", "bar")) == expand_exclude_types(("bar",))
