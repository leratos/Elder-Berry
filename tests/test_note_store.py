"""Tests: NoteStore – SQLite + FTS5 Notizen & Wissensdatenbank (Phase 16)."""
from __future__ import annotations

import pytest
from datetime import datetime

from elder_berry.tools.note_store import NoteStore

USER_A = "@alice:matrix.org"
USER_B = "@bob:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Erstellt einen NoteStore mit temporärer DB."""
    db = tmp_path / "test_notes.db"
    s = NoteStore(db_path=db)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# DTO-Tests
# ---------------------------------------------------------------------------

class TestNoteDTO:
    def test_frozen(self, store):
        note = store.add_note(USER_A, "Test-Inhalt")
        with pytest.raises(AttributeError):
            note.content = "Changed"

    def test_is_fact_true(self, store):
        note = store.set_fact(USER_A, "key", "value")
        assert note.is_fact

    def test_is_fact_false(self, store):
        note = store.add_note(USER_A, "Freitext")
        assert not note.is_fact

    def test_format_short_fact(self, store):
        note = store.set_fact(USER_A, "wlan", "passwort123")
        short = note.format_short()
        assert "🔑" in short
        assert "wlan" in short
        assert "passwort123" in short

    def test_format_short_note(self, store):
        note = store.add_note(USER_A, "Kurzer Text")
        short = note.format_short()
        assert "📝" in short
        assert "Kurzer Text" in short

    def test_format_short_note_truncated(self, store):
        long_text = "A" * 100
        note = store.add_note(USER_A, long_text)
        short = note.format_short()
        assert "..." in short
        # Zeigt max 80 Zeichen + ...
        assert len(short) < 110

    def test_tags_empty(self, store):
        note = store.add_note(USER_A, "test")
        assert note.tags == []

    def test_tags_set(self, store):
        note = store.set_fact(USER_A, "key", "val", tags=["privat", "arbeit"])
        assert "privat" in note.tags
        assert "arbeit" in note.tags


# ---------------------------------------------------------------------------
# set_fact – Tests
# ---------------------------------------------------------------------------

class TestSetFact:
    def test_new_fact(self, store):
        note = store.set_fact(USER_A, "wlan passwort", "xyz123")
        assert note.key == "wlan passwort"
        assert note.content == "xyz123"
        assert note.user_id == USER_A
        assert note.id > 0

    def test_key_normalization(self, store):
        store.set_fact(USER_A, "  WLAN Büro  ", "passwort1")
        result = store.get_fact(USER_A, "wlan büro")
        assert result is not None
        assert result.content == "passwort1"

    def test_upsert_existing_key(self, store):
        store.set_fact(USER_A, "passwort", "alt")
        note = store.set_fact(USER_A, "passwort", "neu")
        assert note.content == "neu"
        # Nur 1 Eintrag vorhanden
        all_notes = store.list_all(USER_A)
        assert len(all_notes) == 1

    def test_upsert_different_users(self, store):
        store.set_fact(USER_A, "key", "wert_a")
        store.set_fact(USER_B, "key", "wert_b")
        # Beide Einträge existieren
        assert store.get_fact(USER_A, "key").content == "wert_a"
        assert store.get_fact(USER_B, "key").content == "wert_b"

    def test_timestamps_set(self, store):
        note = store.set_fact(USER_A, "key", "val")
        assert isinstance(note.created_at, datetime)
        assert isinstance(note.updated_at, datetime)


# ---------------------------------------------------------------------------
# add_note – Tests
# ---------------------------------------------------------------------------

class TestAddNote:
    def test_add_note_no_key(self, store):
        note = store.add_note(USER_A, "Vermieter heißt Müller")
        assert note.key is None
        assert note.content == "Vermieter heißt Müller"

    def test_multiple_notes_same_user(self, store):
        store.add_note(USER_A, "Notiz 1")
        store.add_note(USER_A, "Notiz 2")
        notes = store.list_all(USER_A)
        assert len(notes) == 2

    def test_note_always_new_entry(self, store):
        store.add_note(USER_A, "gleicher text")
        store.add_note(USER_A, "gleicher text")
        notes = store.list_all(USER_A)
        assert len(notes) == 2


# ---------------------------------------------------------------------------
# get_fact – Tests
# ---------------------------------------------------------------------------

class TestGetFact:
    def test_existing_key(self, store):
        store.set_fact(USER_A, "test-key", "test-wert")
        result = store.get_fact(USER_A, "test-key")
        assert result is not None
        assert result.content == "test-wert"

    def test_nonexistent_key(self, store):
        result = store.get_fact(USER_A, "gibts-nicht")
        assert result is None

    def test_user_isolation(self, store):
        store.set_fact(USER_A, "key", "nur für a")
        result = store.get_fact(USER_B, "key")
        assert result is None

    def test_key_case_insensitive(self, store):
        store.set_fact(USER_A, "WLAN", "passwort")
        result = store.get_fact(USER_A, "wlan")
        assert result is not None


# ---------------------------------------------------------------------------
# search – Tests
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_in_content(self, store):
        store.add_note(USER_A, "Vermieter heißt Müller")
        results = store.search(USER_A, "Müller")
        assert len(results) >= 1

    def test_search_in_key(self, store):
        store.set_fact(USER_A, "wlan passwort büro", "xyz")
        results = store.search(USER_A, "wlan")
        assert len(results) >= 1

    def test_search_no_results(self, store):
        store.add_note(USER_A, "Katzenfutter kaufen")
        results = store.search(USER_A, "Hund")
        assert results == []

    def test_search_user_isolation(self, store):
        store.add_note(USER_A, "Geheime Info für A")
        results = store.search(USER_B, "Geheime")
        assert results == []

    def test_search_limit(self, store):
        for i in range(15):
            store.add_note(USER_A, f"Notiz über Müller {i}")
        results = store.search(USER_A, "Müller", limit=5)
        assert len(results) <= 5

    def test_search_tags(self, store):
        store.set_fact(USER_A, "kontakt", "Müller", tags=["privat"])
        results = store.search(USER_A, "privat")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# list_all – Tests
# ---------------------------------------------------------------------------

class TestListAll:
    def test_empty(self, store):
        assert store.list_all(USER_A) == []

    def test_order_newest_first(self, store):
        store.add_note(USER_A, "Erste Notiz")
        n2 = store.add_note(USER_A, "Zweite Notiz")
        notes = store.list_all(USER_A)
        # Neueste zuerst
        assert notes[0].id == n2.id

    def test_user_isolation(self, store):
        store.add_note(USER_A, "Notiz von A")
        notes = store.list_all(USER_B)
        assert notes == []

    def test_limit_respected(self, store):
        for i in range(25):
            store.add_note(USER_A, f"Notiz {i}")
        notes = store.list_all(USER_A, limit=10)
        assert len(notes) == 10


# ---------------------------------------------------------------------------
# delete – Tests
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_existing(self, store):
        note = store.add_note(USER_A, "Zu löschen")
        deleted = store.delete(note.id)
        assert deleted
        # FTS-Index sollte aktualisiert sein
        results = store.search(USER_A, "löschen")
        assert all(r.id != note.id for r in results)

    def test_delete_nonexistent(self, store):
        assert not store.delete(99999)

    def test_delete_fact_by_key(self, store):
        store.set_fact(USER_A, "altes_wlan", "passwort")
        deleted = store.delete_fact(USER_A, "altes_wlan")
        assert deleted
        assert store.get_fact(USER_A, "altes_wlan") is None

    def test_delete_fact_nonexistent(self, store):
        assert not store.delete_fact(USER_A, "gibts nicht")


# ---------------------------------------------------------------------------
# close – Tests
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_no_error(self, tmp_path):
        db = tmp_path / "close_test.db"
        s = NoteStore(db_path=db)
        s.add_note(USER_A, "Test")
        s.close()
        # Kein Fehler beim zweiten close
        s.close()


# ---------------------------------------------------------------------------
# _normalize_key – Tests
# ---------------------------------------------------------------------------

class TestNormalizeKey:
    def test_lowercase(self):
        assert NoteStore._normalize_key("WLAN") == "wlan"

    def test_strip(self):
        assert NoteStore._normalize_key("  test  ") == "test"

    def test_multiple_spaces(self):
        assert NoteStore._normalize_key("wlan  büro  passwort") == "wlan büro passwort"


# ---------------------------------------------------------------------------
# _sanitize_fts_query – Tests
# ---------------------------------------------------------------------------

class TestSanitizeFtsQuery:
    def test_normal_query(self):
        assert NoteStore._sanitize_fts_query("Vermieter Müller") == "Vermieter Müller"

    def test_apostrophes(self):
        result = NoteStore._sanitize_fts_query(
            "Der Command 'termin' wurde nicht erkannt"
        )
        assert "'" not in result
        assert "termin" in result
        assert "erkannt" in result

    def test_parentheses(self):
        result = NoteStore._sanitize_fts_query("test (wichtig)")
        assert "(" not in result
        assert ")" not in result
        assert "test" in result
        assert "wichtig" in result

    def test_quotes(self):
        result = NoteStore._sanitize_fts_query('suche "das hier"')
        assert '"' not in result
        assert "suche" in result
        assert "das" in result

    def test_fts_operators_removed(self):
        result = NoteStore._sanitize_fts_query("NOT AND OR")
        assert result == ""

    def test_only_special_chars_empty(self):
        result = NoteStore._sanitize_fts_query("'()\"*!@#$%")
        assert result == ""

    def test_mixed_operators_and_words(self):
        result = NoteStore._sanitize_fts_query("Katze AND Hund")
        assert result == "Katze Hund"

    def test_umlauts_preserved(self):
        result = NoteStore._sanitize_fts_query("Büro Straße Ärger")
        assert "Büro" in result
        assert "Straße" in result
        assert "Ärger" in result


class TestSearchSanitized:
    """Integration: search() mit problematischen Queries crasht nicht."""

    def test_search_with_apostrophes(self, store):
        store.add_note(USER_A, "Termin um 14 Uhr")
        results = store.search(USER_A, "Der Command 'termin' wurde nicht erkannt")
        # Kein Crash – Ergebnis kann leer oder match sein
        assert isinstance(results, list)

    def test_search_with_parentheses(self, store):
        store.add_note(USER_A, "Test wichtig")
        results = store.search(USER_A, "test (wichtig)")
        assert isinstance(results, list)

    def test_search_with_quotes(self, store):
        store.add_note(USER_A, "das hier finden")
        results = store.search(USER_A, 'suche "das hier"')
        assert isinstance(results, list)

    def test_search_only_operators(self, store):
        results = store.search(USER_A, "NOT AND OR")
        assert results == []

    def test_search_only_special_chars(self, store):
        results = store.search(USER_A, "'()\"*")
        assert results == []
