"""Tests für PendingInitiativeStore (Phase 89, Pfad C)."""

from __future__ import annotations

import time

import pytest

from elder_berry.comms.pending_initiative import (
    DEFAULT_TTL_SECONDS,
    INITIATIVE_CONFIRM_WORDS,
    PendingInitiative,
    PendingInitiativeStore,
)

USER = "@lera:matrix.org"


@pytest.fixture
def store() -> PendingInitiativeStore:
    return PendingInitiativeStore()


def _initiative(command: str = "kalender erstelle 15.08. Urlaub") -> PendingInitiative:
    return PendingInitiative(
        proposed_command=command,
        question="Soll ich den Termin eintragen?",
    )


# --- Grundlegende Store-Operationen ---------------------------------------


def test_set_and_get_roundtrip(store: PendingInitiativeStore) -> None:
    initiative = _initiative()
    store.set(USER, initiative)
    fetched = store.get(USER)
    assert fetched is not None
    assert fetched.proposed_command == "kalender erstelle 15.08. Urlaub"
    assert fetched.question == "Soll ich den Termin eintragen?"


def test_get_unknown_user_returns_none(store: PendingInitiativeStore) -> None:
    assert store.get("@unknown:matrix.org") is None


def test_clear_removes_initiative(store: PendingInitiativeStore) -> None:
    store.set(USER, _initiative())
    store.clear(USER)
    assert store.get(USER) is None


def test_clear_unknown_user_is_noop(store: PendingInitiativeStore) -> None:
    # Darf nicht werfen.
    store.clear("@unknown:matrix.org")


def test_only_one_initiative_per_user(store: PendingInitiativeStore) -> None:
    store.set(USER, _initiative("erster command"))
    store.set(USER, _initiative("zweiter command"))
    fetched = store.get(USER)
    assert fetched is not None
    assert fetched.proposed_command == "zweiter command"


# --- TTL / Expiry ----------------------------------------------------------


def test_default_ttl_is_five_minutes() -> None:
    assert DEFAULT_TTL_SECONDS == 300


def test_expired_initiative_is_dropped(store: PendingInitiativeStore) -> None:
    initiative = PendingInitiative(
        proposed_command="kalender erstelle Urlaub",
        created_at=time.time() - 400,  # älter als 300s TTL
        ttl=DEFAULT_TTL_SECONDS,
    )
    store.set(USER, initiative)
    assert store.get(USER) is None


def test_is_expired_property() -> None:
    fresh = PendingInitiative(proposed_command="x")
    assert fresh.is_expired is False
    old = PendingInitiative(proposed_command="x", created_at=time.time() - 999, ttl=300)
    assert old.is_expired is True


# --- check_response: confirm ----------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["ja", "ja bitte", "Ja bitte!", "JA", "mach", "mach das", "ok", "okay", "klar"],
)
def test_check_response_confirm(store: PendingInitiativeStore, text: str) -> None:
    store.set(USER, _initiative())
    response_type, initiative = store.check_response(USER, text)
    assert response_type == "confirm"
    assert initiative is not None
    assert initiative.proposed_command == "kalender erstelle 15.08. Urlaub"


def test_check_response_confirm_with_punctuation_and_comma(
    store: PendingInitiativeStore,
) -> None:
    store.set(USER, _initiative())
    response_type, _ = store.check_response(USER, "ja, bitte.")
    assert response_type == "confirm"


def test_confirm_does_not_mutate_store(store: PendingInitiativeStore) -> None:
    # check_response soll den Store nicht löschen -- Bridge räumt nach Exec auf.
    store.set(USER, _initiative())
    store.check_response(USER, "ja bitte")
    assert store.get(USER) is not None


# --- check_response: cancel ------------------------------------------------


@pytest.mark.parametrize("text", ["nein", "ne", "lass es", "abbrechen", "Nein!"])
def test_check_response_cancel(store: PendingInitiativeStore, text: str) -> None:
    store.set(USER, _initiative())
    response_type, initiative = store.check_response(USER, text)
    assert response_type == "cancel"
    assert initiative is not None


# --- check_response: other / none -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "ja das passt mir aber erst nächste woche",  # langer Satz, kein reines "ja"
        "bitte",  # nacktes bitte ist bewusst KEIN Confirm
        "wie spät ist es",
        "erzähl mir was über die mail",
    ],
)
def test_check_response_other_when_pending(
    store: PendingInitiativeStore, text: str
) -> None:
    store.set(USER, _initiative())
    response_type, initiative = store.check_response(USER, text)
    assert response_type == "other"
    assert initiative is not None


def test_check_response_none_without_pending(store: PendingInitiativeStore) -> None:
    response_type, initiative = store.check_response(USER, "ja bitte")
    assert response_type == "none"
    assert initiative is None


def test_bare_bitte_not_in_confirm_words() -> None:
    # Schutz gegen Über-Erkennung: ein nacktes "bitte" darf nie bestätigen.
    assert "bitte" not in INITIATIVE_CONFIRM_WORDS
