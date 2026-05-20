"""Tests fuer contact_address_resolver -- Kontakt-Adress-Aufloesung mit
Mehrdeutigkeits-Check.

Phase 92 (E0): ausgegliedert aus tests/test_route_commands.py
(TestResolveContact). Pruefen die ausgegliederte Funktion und das
``AddressResolution``-DTO direkt -- ohne Handler-Instanz.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.tools.contact_address_resolver import (
    AddressResolution,
    HOME_SYNONYMS,
    is_home_synonym,
    looks_like_address,
    resolve_contact_address,
)

USER_ID = "@test:matrix.org"


def _make_contact(
    name: str = "Lisa Müller",
    address: str = "Hauptstr. 12, 10115 Berlin",
) -> MagicMock:
    c = MagicMock()
    c.name = name
    c.address = address
    return c


@pytest.fixture
def contact_store() -> MagicMock:
    store = MagicMock()
    store.find_by_group.return_value = [
        _make_contact("Zuhause", "Musterstr. 5, 12345 Berlin"),
    ]
    store.search.return_value = [
        _make_contact("Lisa Müller", "Hauptstr. 12, 10115 Berlin"),
    ]
    return store


# ---------------------------------------------------------------------------
# is_home_synonym / looks_like_address
# ---------------------------------------------------------------------------


class TestIsHomeSynonym:
    def test_none_is_home(self) -> None:
        assert is_home_synonym(None) is True

    @pytest.mark.parametrize(
        "name",
        ["mir", "zuhause", "daheim", "home", "zu hause", "meiner"],
    )
    def test_home_synonyms(self, name: str) -> None:
        assert is_home_synonym(name) is True

    @pytest.mark.parametrize("name", ["ZUHAUSE", "Home", "Mir"])
    def test_home_synonyms_case_insensitive(self, name: str) -> None:
        assert is_home_synonym(name) is True

    @pytest.mark.parametrize("name", ["Lisa", "Andrea", ""])
    def test_non_home_names(self, name: str) -> None:
        assert is_home_synonym(name) is False


class TestLooksLikeAddress:
    @pytest.mark.parametrize(
        "text",
        [
            "Am Brendegraben 21, 13127 Berlin",
            "Musterstr. 1, 12345 Berlin",
            "Hauptstraße 42",
            "10115 Berlin",
        ],
    )
    def test_addresses(self, text: str) -> None:
        assert looks_like_address(text) is True

    @pytest.mark.parametrize("text", ["Lisa", "Andrea", "Kaufland"])
    def test_names(self, text: str) -> None:
        assert looks_like_address(text) is False


# ---------------------------------------------------------------------------
# resolve_contact_address
# ---------------------------------------------------------------------------


class TestResolveContactAddress:
    def test_home(self, contact_store: MagicMock) -> None:
        res = resolve_contact_address(contact_store, USER_ID, None)
        assert res.address == "Musterstr. 5, 12345 Berlin"
        assert res.ambiguous_matches == ()
        contact_store.find_by_group.assert_called_with(USER_ID, "home")

    @pytest.mark.parametrize("synonym", sorted(HOME_SYNONYMS))
    def test_home_synonyms(
        self,
        contact_store: MagicMock,
        synonym: str,
    ) -> None:
        res = resolve_contact_address(contact_store, USER_ID, synonym)
        assert res.address == "Musterstr. 5, 12345 Berlin"
        contact_store.find_by_group.assert_called_with(USER_ID, "home")

    def test_home_missing(self, contact_store: MagicMock) -> None:
        contact_store.find_by_group.return_value = []
        res = resolve_contact_address(contact_store, USER_ID, None)
        assert res.address is None
        assert res.ambiguous_matches == ()

    def test_by_name(self, contact_store: MagicMock) -> None:
        res = resolve_contact_address(contact_store, USER_ID, "Lisa")
        assert res.address == "Hauptstr. 12, 10115 Berlin"
        assert res.ambiguous_matches == ()
        contact_store.search.assert_called_with(USER_ID, "Lisa")

    def test_not_found(self, contact_store: MagicMock) -> None:
        contact_store.search.return_value = []
        res = resolve_contact_address(contact_store, USER_ID, "Unbekannt")
        assert res.address is None
        assert res.ambiguous_matches == ()

    @pytest.mark.parametrize(
        "raw_address",
        [
            "Am Brendegraben 21, 13127 Berlin",
            "Musterstr. 1, 12345 Berlin",
            "Hauptstraße 42",
            "10115 Berlin",
            '"Am Brendegraben 21 in 13127 Berlin"',
        ],
    )
    def test_direct_address(
        self,
        contact_store: MagicMock,
        raw_address: str,
    ) -> None:
        res = resolve_contact_address(contact_store, USER_ID, raw_address)
        assert res.address is not None
        contact_store.search.assert_not_called()

    def test_direct_address_strips_quotes(
        self,
        contact_store: MagicMock,
    ) -> None:
        res = resolve_contact_address(
            contact_store,
            USER_ID,
            '"Am Brendegraben 21, 13127 Berlin"',
        )
        assert res.address == "Am Brendegraben 21, 13127 Berlin"

    def test_contact_without_address(
        self,
        contact_store: MagicMock,
    ) -> None:
        contact_store.search.return_value = [_make_contact("Lisa", "")]
        res = resolve_contact_address(contact_store, USER_ID, "Lisa")
        assert res.address is None
        assert res.ambiguous_matches == ()

    # ------------------------------------------------------------------
    # Mehrdeutigkeit (Phase 43 Bugfix, jetzt in der Util)
    # ------------------------------------------------------------------

    def test_ambiguous_multiple_matches(
        self,
        contact_store: MagicMock,
    ) -> None:
        contact_store.search.return_value = [
            _make_contact("Lisa Müller", "Hauptstr. 12, 10115 Berlin"),
            _make_contact("Lisa Schmidt", "Mozartweg 4, 04416 Markranstädt"),
        ]
        res = resolve_contact_address(contact_store, USER_ID, "Lisa")
        assert res.address is None
        assert res.ambiguous_matches == ("Lisa Müller", "Lisa Schmidt")
        assert res.candidate_addresses == (
            "Hauptstr. 12, 10115 Berlin",
            "Mozartweg 4, 04416 Markranstädt",
        )

    def test_ambiguous_resolves_with_exact_name_match(
        self,
        contact_store: MagicMock,
    ) -> None:
        contact_store.search.return_value = [
            _make_contact("Lisa Müller", "Hauptstr. 12, 10115 Berlin"),
            _make_contact("Lisa Schmidt", "Mozartweg 4, 04416 Markranstädt"),
        ]
        res = resolve_contact_address(contact_store, USER_ID, "Lisa Müller")
        assert res.address == "Hauptstr. 12, 10115 Berlin"
        assert res.ambiguous_matches == ()
        assert res.candidate_addresses == ()

    def test_ambiguous_exact_match_is_case_insensitive(
        self,
        contact_store: MagicMock,
    ) -> None:
        contact_store.search.return_value = [
            _make_contact("Lisa Müller", "Hauptstr. 12, 10115 Berlin"),
            _make_contact("Lisa Schmidt", "Mozartweg 4, 04416 Markranstädt"),
        ]
        res = resolve_contact_address(contact_store, USER_ID, "lisa müller")
        assert res.address == "Hauptstr. 12, 10115 Berlin"
        assert res.ambiguous_matches == ()

    def test_ambiguous_multiple_exact_matches_still_ambiguous(
        self,
        contact_store: MagicMock,
    ) -> None:
        contact_store.search.return_value = [
            _make_contact("Lisa", "Hauptstr. 12, 10115 Berlin"),
            _make_contact("Lisa", "Mozartweg 4, 04416 Markranstädt"),
        ]
        res = resolve_contact_address(contact_store, USER_ID, "Lisa")
        assert res.address is None
        assert res.ambiguous_matches == ("Lisa", "Lisa")
        # Beide Adressen sollten weitergegeben werden, damit der
        # Listen-Picker den Index korrekt aufloest.
        assert res.candidate_addresses == (
            "Hauptstr. 12, 10115 Berlin",
            "Mozartweg 4, 04416 Markranstädt",
        )

    def test_ambiguous_caps_candidate_list_at_five(
        self,
        contact_store: MagicMock,
    ) -> None:
        contact_store.search.return_value = [
            _make_contact(f"Lisa {i}", f"Str. {i}") for i in range(7)
        ]
        res = resolve_contact_address(contact_store, USER_ID, "Lisa")
        assert len(res.ambiguous_matches) == 5
        assert len(res.candidate_addresses) == 5


# ---------------------------------------------------------------------------
# AddressResolution dataclass
# ---------------------------------------------------------------------------


class TestAddressResolution:
    def test_default_is_empty(self) -> None:
        res = AddressResolution()
        assert res.address is None
        assert res.ambiguous_matches == ()
        assert res.candidate_addresses == ()

    def test_frozen(self) -> None:
        res = AddressResolution(address="x")
        with pytest.raises(AttributeError):
            res.address = "y"  # type: ignore[misc]
