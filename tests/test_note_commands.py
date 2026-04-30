"""Tests: NoteCommandHandler – Command-Parsing und Ausführung (Phase 16)."""

from __future__ import annotations

import pytest

from elder_berry.tools.note_store import NoteStore
from elder_berry.comms.commands.note_commands import (
    NoteCommandHandler,
    NOTE_SET_FACT_PATTERN,
    NOTE_ADD_PATTERN,
    NOTE_GET_FACT_PATTERN,
    NOTE_SEARCH_PATTERN,
    NOTE_DELETE_PATTERN,
    NOTE_DELETE_FACT_PATTERN,
)

USER_A = "@alice:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_notes.db"
    s = NoteStore(db_path=db)
    yield s
    s.close()


@pytest.fixture
def handler(store):
    return NoteCommandHandler(note_store=store, default_user_id=USER_A)


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
# execute() – set_fact
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


# ---------------------------------------------------------------------------
# execute() – add_note
# ---------------------------------------------------------------------------


class TestExecuteAddNote:
    def test_add_note(self, handler):
        result = handler.execute("note_add", "notiz: Vermieter Müller")
        assert result.success
        assert "#" in result.text

    def test_invalid_format(self, handler):
        result = handler.execute("note_add", "kein passendes format hier ohne prefix")
        # add_note Pattern braucht "notiz:" Prefix
        assert not result.success


# ---------------------------------------------------------------------------
# execute() – get_fact
# ---------------------------------------------------------------------------


class TestExecuteGetFact:
    def test_hit(self, handler, store):
        store.set_fact(USER_A, "wlan büro", "passwort123")
        result = handler.execute("note_get_fact", "was ist wlan büro?")
        assert result.success
        assert "passwort123" in result.text

    def test_miss_returns_false(self, handler):
        """Miss → success=False für LLM-Fallthrough."""
        result = handler.execute("note_get_fact", "was ist Photosynthese?")
        assert not result.success
        assert result.text is None

    def test_roundtrip(self, handler):
        handler.execute("note_set_fact", "merk dir: test-key ist test-wert")
        result = handler.execute("note_get_fact", "was ist test-key?")
        assert result.success
        assert "test-wert" in result.text


# ---------------------------------------------------------------------------
# execute() – search
# ---------------------------------------------------------------------------


class TestExecuteSearch:
    def test_search_found(self, handler, store):
        store.add_note(USER_A, "Vermieter heißt Müller")
        result = handler.execute("note_search", "notizen suche Müller")
        assert result.success
        assert "treffer" in result.text.lower() or "Müller" in result.text

    def test_search_not_found(self, handler):
        result = handler.execute("note_search", "notizen suche nichtexistent")
        assert result.success
        assert "keine" in result.text.lower()

    def test_search_roundtrip(self, handler):
        handler.execute("note_add", "notiz: Dachdecker Plattenburg 0123456")
        result = handler.execute("note_search", "notizen suche Dachdecker")
        assert result.success
        assert "treffer" in result.text.lower() or "1" in result.text


# ---------------------------------------------------------------------------
# execute() – list
# ---------------------------------------------------------------------------


class TestExecuteList:
    def test_empty(self, handler):
        result = handler.execute("notizen", "notizen")
        assert result.success
        assert "keine" in result.text.lower()

    def test_with_notes(self, handler, store):
        store.add_note(USER_A, "Erste Notiz")
        store.set_fact(USER_A, "schlüssel", "wert")
        result = handler.execute("notizen", "notizen")
        assert result.success
        assert "2" in result.text or "Notizen" in result.text


# ---------------------------------------------------------------------------
# execute() – delete
# ---------------------------------------------------------------------------


class TestExecuteDelete:
    def test_delete_existing(self, handler, store):
        note = store.add_note(USER_A, "Zu löschen")
        result = handler.execute("note_delete", f"notiz löschen #{note.id}")
        assert result.success
        assert str(note.id) in result.text

    def test_delete_nonexistent(self, handler):
        result = handler.execute("note_delete", "notiz löschen #99999")
        assert not result.success
        assert "nicht gefunden" in result.text.lower()

    def test_delete_fact(self, handler, store):
        store.set_fact(USER_A, "altes passwort", "geheim")
        result = handler.execute("note_delete_fact", "vergiss altes passwort")
        assert result.success

    def test_delete_fact_nonexistent(self, handler):
        result = handler.execute("note_delete_fact", "vergiss gibts nicht")
        assert not result.success
