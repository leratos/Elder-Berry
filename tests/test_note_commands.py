"""Tests: NoteCommandHandler -- Fakten (FactStore) + Notizen (Nextcloud).

Phase 91-C: Notiz-Commands laufen gegen einen Mock-NextcloudNotesClient,
Fakten-Commands gegen einen echten FactStore (lokale SQLite-DB im tmp_path).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.note_commands import (
    NOTE_ADD_PATTERN,
    NOTE_CATEGORIES_PATTERN,
    NOTE_DELETE_FACT_PATTERN,
    NOTE_DELETE_PATTERN,
    NOTE_GET_FACT_PATTERN,
    NOTE_LIST_PATTERN,
    NOTE_SEARCH_PATTERN,
    NOTE_SET_FACT_PATTERN,
    NoteCommandHandler,
    _format_note_short,
)
from elder_berry.tools.fact_store import FactStore
from elder_berry.tools.nextcloud_notes_client import NextcloudNote, NextcloudNotesError

USER_A = "@alice:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test_facts.db"
    legacy = tmp_path / "no_legacy.db"
    s = FactStore(db_path=db, legacy_notes_db=legacy)
    yield s
    s.close()


@pytest.fixture
def notes():
    """Mock-NextcloudNotesClient -- list/search liefern per Default []."""
    client = MagicMock()
    client.list_notes.return_value = []
    client.search.return_value = []
    return client


@pytest.fixture
def handler(store, notes):
    return NoteCommandHandler(
        fact_store=store,
        nextcloud_notes=notes,
        default_user_id=USER_A,
    )


@pytest.fixture
def handler_no_notes(store):
    """Handler ohne NextcloudNotesClient -- Notiz-Commands sind dann
    'nicht konfiguriert', Fakten funktionieren weiter."""
    return NoteCommandHandler(fact_store=store, default_user_id=USER_A)


def _note(note_id=1, content="Testnotiz", category="Allgemein", modified=1000):
    """Baut ein NextcloudNote.

    title = "Neue Notiz" -- so liefert die echte Nextcloud-API frisch per
    POST erstellte Notizen aus (der Titel wird nicht aus dem Content
    abgeleitet). Damit pruefen die Listen-/Such-Tests implizit, dass die
    Anzeige aus dem Content kommt und nicht aus dem Platzhalter-Titel.
    """
    return NextcloudNote(
        id=note_id,
        content=content,
        category=category,
        modified=datetime.fromtimestamp(modified, tz=timezone.utc),
        title="Neue Notiz",
    )


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

    def test_add_colon_no_category(self):
        match = NOTE_ADD_PATTERN.match("notiz: Vermieter heißt Müller")
        assert match
        assert match.group("category") is None
        assert match.group("content") == "Vermieter heißt Müller"

    def test_add_with_category(self):
        match = NOTE_ADD_PATTERN.match("notiz Einkauf: Milch kaufen")
        assert match
        assert match.group("category") == "Einkauf"
        assert match.group("content") == "Milch kaufen"

    def test_add_without_colon_no_match(self):
        """Phase 91-C: ohne ":" ist Kategorie vs. Content nicht trennbar."""
        assert NOTE_ADD_PATTERN.match("notiz Vermieter heißt Müller") is None

    def test_add_multiline(self):
        match = NOTE_ADD_PATTERN.match("notiz: Liste\n- Vodka\n- Limette")
        assert match
        assert match.group("content") == "Liste\n- Vodka\n- Limette"

    def test_add_empty_content_no_match(self):
        assert NOTE_ADD_PATTERN.match("notiz:") is None

    def test_list_plain(self):
        match = NOTE_LIST_PATTERN.match("notizen liste")
        assert match
        assert match.group("category") is None

    def test_list_with_category(self):
        match = NOTE_LIST_PATTERN.match("notizen liste Einkauf")
        assert match
        assert match.group("category") == "Einkauf"

    def test_list_bare_notizen_no_match(self):
        """``notizen`` allein ist ein simple_command, kein NOTE_LIST-Match."""
        assert NOTE_LIST_PATTERN.match("notizen") is None

    def test_categories(self):
        assert NOTE_CATEGORIES_PATTERN.match("notizen kategorien")
        assert NOTE_CATEGORIES_PATTERN.match("notiz kategorie")

    def test_get_fact(self):
        assert NOTE_GET_FACT_PATTERN.match("was ist das WLAN?")
        assert NOTE_GET_FACT_PATTERN.match("was ist WLAN Büro")

    def test_get_fact_domain_guard_route(self):
        assert NOTE_GET_FACT_PATTERN.match("was ist die route nach Leipzig?") is None

    def test_get_fact_domain_guard_rezept(self):
        assert NOTE_GET_FACT_PATTERN.match("was ist das rezept fuer Carbonara?") is None

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

    def test_keyword_speichere_excluded_avoid_collision(self, handler):
        """Regression-Guard: das einzelne Keyword 'speichere' ist zu
        generisch und schluckt 'speichere es als Notiz' -- wurde
        deshalb entfernt. Die spezifischen Varianten 'speicher dir' /
        'merk dir' decken den Fakt-Pfad ausreichend ab."""
        assert "speichere" not in handler.keywords["note_set_fact"]

    def test_keywords_note_add(self, handler):
        assert "notiz:" in handler.keywords["note_add"]
        assert "notiere" in handler.keywords["note_add"]

    def test_keywords_note_list(self, handler):
        assert "notizen liste" in handler.keywords["note_list"]

    def test_keywords_note_categories(self, handler):
        assert "notizen kategorien" in handler.keywords["note_categories"]

    def test_patterns_include_new_commands(self, handler):
        names = {cmd for _p, cmd, _o, _s in handler.patterns}
        assert "note_list" in names
        assert "note_categories" in names


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
# execute() -- notiz: (create_note)
# ---------------------------------------------------------------------------


class TestExecuteAddNote:
    def test_add_default_category(self, handler, notes):
        notes.create_note.return_value = _note(5, "Testnotiz", "Allgemein")
        result = handler.execute("note_add", "notiz: Testnotiz")
        assert result.success
        notes.create_note.assert_called_once_with("Testnotiz", category="Allgemein")
        assert "#5" in result.text

    def test_add_known_category(self, handler, notes):
        notes.create_note.return_value = _note(6, "Milch", "Einkauf")
        result = handler.execute("note_add", "notiz Einkauf: Milch kaufen")
        assert result.success
        notes.create_note.assert_called_once_with("Milch kaufen", category="Einkauf")

    def test_add_category_case_normalized(self, handler, notes):
        """``einkauf`` (lowercase) -> kanonische Whitelist-Schreibweise."""
        notes.create_note.return_value = _note(7, "Milch", "Einkauf")
        handler.execute("note_add", "notiz einkauf: Milch")
        notes.create_note.assert_called_once_with("Milch", category="Einkauf")

    def test_add_unknown_category_override(self, handler, notes):
        """Unbekannte Kategorie wird akzeptiert, Antwort enthaelt Hinweis."""
        notes.create_note.return_value = _note(8, "X", "MoscowMule")
        result = handler.execute("note_add", "notiz MoscowMule: X")
        assert result.success
        notes.create_note.assert_called_once_with("X", category="MoscowMule")
        assert "MoscowMule" in result.text
        assert "Bekannte Kategorien" in result.text

    def test_add_multiline(self, handler, notes):
        notes.create_note.return_value = _note(9, "Liste\n- A\n- B", "Allgemein")
        result = handler.execute("note_add", "notiz: Liste\n- A\n- B")
        assert result.success
        notes.create_note.assert_called_once_with(
            "Liste\n- A\n- B", category="Allgemein"
        )

    def test_add_empty_fails(self, handler, notes):
        result = handler.execute("note_add", "notiz:")
        assert not result.success
        notes.create_note.assert_not_called()

    def test_add_api_error(self, handler, notes):
        notes.create_note.side_effect = NextcloudNotesError("kaputt", status_code=500)
        result = handler.execute("note_add", "notiz: X")
        assert not result.success


# ---------------------------------------------------------------------------
# execute() -- notizen / notizen liste (list_notes)
# ---------------------------------------------------------------------------


class TestExecuteList:
    def test_list_empty(self, handler, notes):
        result = handler.execute("notizen", "notizen")
        assert result.success
        assert "Keine Notizen" in result.text
        notes.list_notes.assert_called_once_with(category=None, limit=20)

    def test_list_filled(self, handler, notes):
        notes.list_notes.return_value = [_note(1, "Erste"), _note(2, "Zweite")]
        result = handler.execute("notizen", "notizen")
        assert result.success
        assert "#1" in result.text and "#2" in result.text

    def test_list_with_category(self, handler, notes):
        notes.list_notes.return_value = [_note(1, "Milch", "Einkauf")]
        result = handler.execute("note_list", "notizen liste Einkauf")
        assert result.success
        notes.list_notes.assert_called_once_with(category="Einkauf", limit=20)

    def test_list_category_case_normalized(self, handler, notes):
        handler.execute("note_list", "notizen liste einkauf")
        notes.list_notes.assert_called_once_with(category="Einkauf", limit=20)

    def test_list_unknown_category_hint(self, handler, notes):
        result = handler.execute("note_list", "notizen liste Quatsch")
        assert "Whitelist" in result.text
        notes.list_notes.assert_called_once_with(category="Quatsch", limit=20)

    def test_list_api_error(self, handler, notes):
        notes.list_notes.side_effect = NextcloudNotesError("kaputt", status_code=500)
        result = handler.execute("notizen", "notizen")
        assert not result.success


# ---------------------------------------------------------------------------
# execute() -- notizen suche (search)
# ---------------------------------------------------------------------------


class TestExecuteSearch:
    def test_search_hit(self, handler, notes):
        notes.search.return_value = [_note(1, "Milch kaufen", "Einkauf")]
        result = handler.execute("note_search", "notizen suche Milch")
        assert result.success
        notes.search.assert_called_once_with("Milch", limit=20)
        assert result.list_type == "note_search"
        assert result.list_items == [{"id": 1, "content": "Milch kaufen"}]

    def test_search_no_match(self, handler, notes):
        result = handler.execute("note_search", "notizen suche xyz")
        assert result.success
        assert "Keine Notizen" in result.text
        assert result.list_items is None

    def test_search_missing_query(self, handler):
        result = handler.execute("note_search", "notizen suche")
        assert not result.success

    def test_search_api_error(self, handler, notes):
        notes.search.side_effect = NextcloudNotesError("kaputt", status_code=500)
        result = handler.execute("note_search", "notizen suche X")
        assert not result.success


# ---------------------------------------------------------------------------
# execute() -- notiz löschen (delete_note)
# ---------------------------------------------------------------------------


class TestExecuteDelete:
    def test_delete_success(self, handler, notes):
        result = handler.execute("note_delete", "notiz löschen #3")
        assert result.success
        notes.delete_note.assert_called_once_with(3)

    def test_delete_not_found(self, handler, notes):
        notes.delete_note.side_effect = NextcloudNotesError("weg", status_code=404)
        result = handler.execute("note_delete", "notiz löschen #99")
        assert not result.success
        assert "nicht gefunden" in result.text

    def test_delete_api_error(self, handler, notes):
        notes.delete_note.side_effect = NextcloudNotesError("kaputt", status_code=500)
        result = handler.execute("note_delete", "notiz löschen #3")
        assert not result.success

    def test_delete_missing_id(self, handler):
        result = handler.execute("note_delete", "notiz löschen")
        assert not result.success


# ---------------------------------------------------------------------------
# execute() -- notizen kategorien (list_categories-Aggregat)
# ---------------------------------------------------------------------------


class TestExecuteCategories:
    def test_categories_counts(self, handler, notes):
        notes.list_notes.return_value = [
            _note(1, "a", "Einkauf"),
            _note(2, "b", "Einkauf"),
            _note(3, "c", "Arbeit"),
            _note(4, "d", "MoscowMule"),
        ]
        result = handler.execute("note_categories", "notizen kategorien")
        assert result.success
        # Whitelist immer aufgelistet, auch ungenutzte.
        assert "Allgemein (0 Notizen)" in result.text
        assert "Einkauf (2 Notizen)" in result.text
        assert "Arbeit (1 Notiz)" in result.text
        # Freie Kategorie ausserhalb der Whitelist ist markiert.
        assert "MoscowMule (1 Notiz) — frei" in result.text

    def test_categories_empty(self, handler, notes):
        result = handler.execute("note_categories", "notizen kategorien")
        assert result.success
        assert "Allgemein (0 Notizen)" in result.text

    def test_categories_api_error(self, handler, notes):
        notes.list_notes.side_effect = NextcloudNotesError("kaputt", status_code=500)
        result = handler.execute("note_categories", "notizen kategorien")
        assert not result.success


# ---------------------------------------------------------------------------
# execute() -- ohne NextcloudNotesClient
# ---------------------------------------------------------------------------


class TestNotesNotConfigured:
    """``nextcloud_notes=None`` -> Notiz-Commands melden 'nicht
    konfiguriert'. Die Fakten-Commands bleiben unberuehrt."""

    @pytest.mark.parametrize(
        "command,raw_text",
        [
            ("note_add", "notiz: X"),
            ("note_search", "notizen suche X"),
            ("note_delete", "notiz löschen #1"),
            ("note_list", "notizen liste"),
            ("notizen", "notizen"),
            ("note_categories", "notizen kategorien"),
        ],
    )
    def test_note_command_without_client(self, handler_no_notes, command, raw_text):
        result = handler_no_notes.execute(command, raw_text)
        assert not result.success
        assert "nicht konfiguriert" in result.text

    def test_facts_still_work_without_notes_client(self, handler_no_notes):
        result = handler_no_notes.execute("note_set_fact", "merk dir: k ist v")
        assert result.success

    def test_unknown_command(self, handler):
        result = handler.execute("note_quatsch", "egal")
        assert not result.success
        assert "Unbekannter" in result.text


# ---------------------------------------------------------------------------
# _format_note_short -- Vorschau aus Content statt Platzhalter-Titel
# ---------------------------------------------------------------------------


class TestFormatNoteShort:
    """Nextcloud titelt per API erstellte Notizen mit dem Platzhalter
    "Neue Notiz" -- die Listen-Vorschau muss aus der ersten Content-Zeile
    kommen, nicht aus note.title."""

    def test_uses_content_first_line_not_title(self):
        note = NextcloudNote(
            id=457,
            content="Milch #dringend",
            category="Einkauf",
            modified=datetime.fromtimestamp(1000, tz=timezone.utc),
            title="Neue Notiz",
        )
        result = _format_note_short(note)
        assert result == "#457 [Einkauf] Milch #dringend"
        assert "Neue Notiz" not in result

    def test_first_nonempty_content_line(self):
        note = NextcloudNote(
            id=1,
            content="\n\nEinkaufsliste\n- Vodka\n- Limette",
            category="",
            modified=datetime.fromtimestamp(0, tz=timezone.utc),
            title="Neue Notiz",
        )
        assert _format_note_short(note) == "#1 Einkaufsliste"

    def test_falls_back_to_title_when_content_empty(self):
        note = NextcloudNote(
            id=2,
            content="",
            category="",
            modified=datetime.fromtimestamp(0, tz=timezone.utc),
            title="Alter Titel",
        )
        assert _format_note_short(note) == "#2 Alter Titel"

    def test_long_line_truncated(self):
        note = NextcloudNote(
            id=3,
            content="A" * 200,
            category="",
            modified=datetime.fromtimestamp(0, tz=timezone.utc),
            title="Neue Notiz",
        )
        result = _format_note_short(note)
        assert result.endswith("...")
        assert result.startswith("#3 ")
