"""Tests: NoteCommandHandler -- Fakten + Notiz-Stubs (Phase 91-A)."""

from __future__ import annotations

import pytest

from elder_berry.tools.fact_store import FactStore
from elder_berry.comms.commands.note_commands import (
    NOTE_ADD_PATTERN,
    NOTE_DELETE_FACT_PATTERN,
    NOTE_DELETE_PATTERN,
    NOTE_GET_FACT_PATTERN,
    NOTE_SEARCH_PATTERN,
    NOTE_SET_FACT_PATTERN,
    NoteCommandHandler,
)

USER_A = "@alice:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_facts.db"
    legacy = tmp_path / "no_legacy.db"
    s = FactStore(db_path=db, legacy_notes_db=legacy)
    yield s
    s.close()


@pytest.fixture
def handler(store):
    return NoteCommandHandler(fact_store=store, default_user_id=USER_A)


# ---------------------------------------------------------------------------
# Pattern-Tests
# ---------------------------------------------------------------------------


class TestPatterns:
    def test_set_fact_colon(self):
        assert NOTE_SET_FACT_PATTERN.match("merk dir: WLAN Büro ist xyz123")

    def test_set_fact_no_colon(self):
        assert NOTE_SET_FACT_PATTERN.match("merk dir WLAN ist xyz")

    def test_set_fact_equals(self):
        assert NOTE_SET_FACT_PATTERN.match("merk dir: Code = 1234")

    def test_merke_dir(self):
        assert NOTE_SET_FACT_PATTERN.match("merke dir: test ist wert")

    def test_add_colon(self):
        assert NOTE_ADD_PATTERN.match("notiz: Vermieter heißt Müller")

    def test_add_space(self):
        assert NOTE_ADD_PATTERN.match("notiz Vermieter heißt Müller")

    def test_get_fact(self):
        assert NOTE_GET_FACT_PATTERN.match("was ist das WLAN?")
        assert NOTE_GET_FACT_PATTERN.match("was ist WLAN Büro")

    def test_search(self):
        assert NOTE_SEARCH_PATTERN.match("notizen suche Vermieter")
        assert NOTE_SEARCH_PATTERN.match("notiz suche Müller")

    def test_delete_with_hash(self):
        assert NOTE_DELETE_PATTERN.match("notiz löschen #3")

    def test_delete_without_hash(self):
        assert NOTE_DELETE_PATTERN.match("notiz löschen 3")

    def test_delete_fact(self):
        assert NOTE_DELETE_FACT_PATTERN.match("vergiss WLAN Passwort")
        assert NOTE_DELETE_FACT_PATTERN.match("vergiss alten code")


# ---------------------------------------------------------------------------
# simple_commands + keywords
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_notizen_in_simple_commands(self, handler):
        assert "notizen" in handler.simple_commands

    def test_keywords_set_fact(self, handler):
        assert "merk dir" in handler.keywords["note_set_fact"]
        assert "speicher dir" in handler.keywords["note_set_fact"]

    def test_keywords_note_add(self, handler):
        assert "notiz:" in handler.keywords["note_add"]
        assert "notiere" in handler.keywords["note_add"]

    def test_keywords_get_fact(self, handler):
        assert "was ist" in handler.keywords["note_get_fact"]

    def test_keywords_list(self, handler):
        assert "notizen" in handler.keywords["notizen"]


# ---------------------------------------------------------------------------
# execute() -- Fakten-Commands (FactStore)
# ---------------------------------------------------------------------------


class TestExecuteSetFact:
    def test_new_fact(self, handler):
        result = handler.execute("note_set_fact", "merk dir: WLAN Büro ist xyz123")
        assert result.success
        assert "gemerkt" in result.text.lower() or "🔑" in result.text

    def test_update_fact(self, handler, store):
        store.set_fact(USER_A, "wlan", "alt")
        result = handler.execute("note_set_fact", "merk dir: WLAN ist neu")
        assert result.success
        assert "aktualisiert" in result.text.lower() or "alt" in result.text

    def test_invalid_format(self, handler):
        result = handler.execute("note_set_fact", "merk dir irgendwas")
        assert not result.success


class TestExecuteGetFact:
    def test_hit(self, handler, store):
        store.set_fact(USER_A, "wlan büro", "passwort123")
        result = handler.execute("note_get_fact", "was ist wlan büro?")
        assert result.success
        assert "passwort123" in result.text

    def test_miss_returns_false(self, handler):
        """Miss -> success=False fuer LLM-Fallthrough."""
        result = handler.execute("note_get_fact", "was ist Photosynthese?")
        assert not result.success
        assert result.text is None

    def test_roundtrip(self, handler):
        handler.execute("note_set_fact", "merk dir: test-key ist test-wert")
        result = handler.execute("note_get_fact", "was ist test-key?")
        assert result.success
        assert "test-wert" in result.text


class TestExecuteDeleteFact:
    def test_delete_fact(self, handler, store):
        store.set_fact(USER_A, "altes passwort", "geheim")
        result = handler.execute("note_delete_fact", "vergiss altes passwort")
        assert result.success

    def test_delete_fact_nonexistent(self, handler):
        result = handler.execute("note_delete_fact", "vergiss gibts nicht")
        assert not result.success


# ---------------------------------------------------------------------------
# execute() -- Notiz-Commands (Stub bis Phase 91-B/C)
# ---------------------------------------------------------------------------


class TestNoteStubs:
    """Phase 91-A: Notiz-Commands liefern Stub-Response bis Phase 91-B/C
    den NextcloudNotesClient ausrollt. Production-Luecke akzeptiert
    (Lera-Freigabe 2026-05-13)."""

    @pytest.mark.parametrize(
        "command,raw_text",
        [
            ("note_add", "notiz: Vermieter Müller"),
            ("note_search", "notizen suche Müller"),
            ("note_delete", "notiz löschen #3"),
            ("notizen", "notizen"),
        ],
    )
    def test_notiz_commands_return_stub(self, handler, command, raw_text):
        result = handler.execute(command, raw_text)
        assert not result.success
        assert "Umstellung" in result.text
        assert "Phase 91-B" in result.text

    def test_stub_does_not_touch_fact_store(self, handler, store):
        """Stub-Pfad darf den FactStore nicht modifizieren."""
        handler.execute("note_add", "notiz: ein Test")
        assert store.list_facts(USER_A) == []

    def test_stub_has_no_list_items(self, handler):
        """Stub liefert weder list_items noch list_type -- die Bridge
        wuerde sonst eine leere Liste registrieren."""
        result = handler.execute("note_search", "notizen suche egal")
        assert result.list_items is None
        assert result.list_type is None
