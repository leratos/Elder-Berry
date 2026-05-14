"""Tests: FactStore -- SQLite-basierter Key-Value-Fakten-Speicher.

Phase 91-A: extrahiert aus dem alten test_note_store.py-Fakten-Teil.
Migrations-Tests pruefen den einmaligen Import aus notes.db.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from elder_berry.tools.fact_store import FactStore

USER_A = "@alice:matrix.org"
USER_B = "@bob:matrix.org"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """Erstellt einen FactStore mit temporaerer DB (keine Migration)."""
    db = tmp_path / "test_facts.db"
    legacy = tmp_path / "no_legacy.db"  # existiert nicht -> keine Migration
    s = FactStore(db_path=db, legacy_notes_db=legacy)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# DTO-Tests
# ---------------------------------------------------------------------------


class TestFactDTO:
    def test_frozen(self, store):
        fact = store.set_fact(USER_A, "key", "value")
        with pytest.raises(AttributeError):
            fact.content = "Changed"

    def test_format_short(self, store):
        fact = store.set_fact(USER_A, "wlan", "passwort123")
        short = fact.format_short()
        assert "🔑" in short
        assert "wlan" in short
        assert "passwort123" in short


# ---------------------------------------------------------------------------
# set_fact
# ---------------------------------------------------------------------------


class TestSetFact:
    def test_new_fact(self, store):
        fact = store.set_fact(USER_A, "wlan passwort", "xyz123")
        assert fact.key == "wlan passwort"
        assert fact.content == "xyz123"
        assert fact.user_id == USER_A
        assert fact.id > 0

    def test_key_normalization(self, store):
        store.set_fact(USER_A, "  WLAN Bueero  ", "passwort1")
        result = store.get_fact(USER_A, "wlan bueero")
        assert result is not None
        assert result.content == "passwort1"

    def test_upsert_existing_key(self, store):
        store.set_fact(USER_A, "passwort", "alt")
        fact = store.set_fact(USER_A, "passwort", "neu")
        assert fact.content == "neu"
        all_facts = store.list_facts(USER_A)
        assert len(all_facts) == 1

    def test_upsert_different_users(self, store):
        store.set_fact(USER_A, "key", "wert_a")
        store.set_fact(USER_B, "key", "wert_b")
        assert store.get_fact(USER_A, "key").content == "wert_a"
        assert store.get_fact(USER_B, "key").content == "wert_b"

    def test_timestamps_set(self, store):
        fact = store.set_fact(USER_A, "key", "val")
        assert isinstance(fact.created_at, datetime)
        assert isinstance(fact.updated_at, datetime)

    def test_upsert_preserves_created_at(self, store):
        first = store.set_fact(USER_A, "key", "alt")
        second = store.set_fact(USER_A, "key", "neu")
        assert second.created_at == first.created_at
        assert second.updated_at >= first.updated_at


# ---------------------------------------------------------------------------
# get_fact
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
        store.set_fact(USER_A, "key", "nur fuer a")
        result = store.get_fact(USER_B, "key")
        assert result is None

    def test_key_case_insensitive(self, store):
        store.set_fact(USER_A, "WLAN", "passwort")
        result = store.get_fact(USER_A, "wlan")
        assert result is not None


# ---------------------------------------------------------------------------
# list_facts
# ---------------------------------------------------------------------------


class TestListFacts:
    def test_empty(self, store):
        assert store.list_facts(USER_A) == []

    def test_order_newest_first(self, store):
        store.set_fact(USER_A, "alt", "1")
        store.set_fact(USER_A, "neu", "2")
        facts = store.list_facts(USER_A)
        assert facts[0].key == "neu"

    def test_user_isolation(self, store):
        store.set_fact(USER_A, "key", "val")
        assert store.list_facts(USER_B) == []

    def test_limit_respected(self, store):
        for i in range(25):
            store.set_fact(USER_A, f"key_{i}", f"val_{i}")
        facts = store.list_facts(USER_A, limit=10)
        assert len(facts) == 10


# ---------------------------------------------------------------------------
# delete_fact
# ---------------------------------------------------------------------------


class TestDeleteFact:
    def test_delete_existing(self, store):
        store.set_fact(USER_A, "altes_wlan", "passwort")
        deleted = store.delete_fact(USER_A, "altes_wlan")
        assert deleted
        assert store.get_fact(USER_A, "altes_wlan") is None

    def test_delete_nonexistent(self, store):
        assert not store.delete_fact(USER_A, "gibts nicht")

    def test_delete_normalization(self, store):
        store.set_fact(USER_A, "WLAN Bueero", "passwort")
        assert store.delete_fact(USER_A, "wlan bueero")

    def test_delete_user_isolation(self, store):
        store.set_fact(USER_A, "key", "val")
        assert not store.delete_fact(USER_B, "key")
        assert store.get_fact(USER_A, "key") is not None


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_no_error(self, tmp_path):
        db = tmp_path / "close_test.db"
        legacy = tmp_path / "no_legacy.db"
        s = FactStore(db_path=db, legacy_notes_db=legacy)
        s.set_fact(USER_A, "key", "val")
        s.close()
        # Kein Fehler beim zweiten close
        s.close()


# ---------------------------------------------------------------------------
# _normalize_key
# ---------------------------------------------------------------------------


class TestNormalizeKey:
    def test_lowercase(self):
        assert FactStore._normalize_key("WLAN") == "wlan"

    def test_strip(self):
        assert FactStore._normalize_key("  wlan  ") == "wlan"

    def test_collapse_whitespace(self):
        assert FactStore._normalize_key("wlan   bueero") == "wlan bueero"

    def test_combined(self):
        assert FactStore._normalize_key("  WLAN \t Bueero  ") == "wlan bueero"


# ---------------------------------------------------------------------------
# Migration aus alter notes.db
# ---------------------------------------------------------------------------


class TestLegacyMigration:
    """Phase 91-A: einmaliger Import von Fact-Rows aus notes.db."""

    @staticmethod
    def _create_legacy_db(path):
        """Erstellt ein notes.db-Schema-Stub mit Mix aus Facts und Notes."""
        conn = sqlite3.connect(str(path))
        conn.executescript("""
            CREATE TABLE notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                key         TEXT,
                content     TEXT NOT NULL,
                tags        TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
        return conn

    def test_migration_imports_facts(self, tmp_path):
        legacy = tmp_path / "notes.db"
        conn = self._create_legacy_db(legacy)
        conn.execute(
            "INSERT INTO notes (user_id, key, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                USER_A,
                "wlan",
                "xyz123",
                "2026-01-01T10:00:00+00:00",
                "2026-01-01T10:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        db = tmp_path / "facts.db"
        store = FactStore(db_path=db, legacy_notes_db=legacy)
        fact = store.get_fact(USER_A, "wlan")
        assert fact is not None
        assert fact.content == "xyz123"
        store.close()

    def test_migration_skips_notes(self, tmp_path):
        """Freitext-Notizen (key IS NULL) werden NICHT migriert."""
        legacy = tmp_path / "notes.db"
        conn = self._create_legacy_db(legacy)
        conn.execute(
            "INSERT INTO notes (user_id, key, content, created_at, updated_at) "
            "VALUES (?, NULL, ?, ?, ?)",
            (
                USER_A,
                "Vermieter heisst Mueller",
                "2026-01-01T10:00:00+00:00",
                "2026-01-01T10:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        db = tmp_path / "facts.db"
        store = FactStore(db_path=db, legacy_notes_db=legacy)
        assert store.list_facts(USER_A) == []
        store.close()

    def test_migration_runs_only_on_fresh_db(self, tmp_path):
        """Existiert facts.db schon -> keine Re-Migration."""
        legacy = tmp_path / "notes.db"
        conn = self._create_legacy_db(legacy)
        conn.execute(
            "INSERT INTO notes (user_id, key, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                USER_A,
                "key_legacy",
                "from_legacy",
                "2026-01-01T10:00:00+00:00",
                "2026-01-01T10:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        db = tmp_path / "facts.db"

        # 1. Lauf: Migration laeuft
        store1 = FactStore(db_path=db, legacy_notes_db=legacy)
        assert store1.get_fact(USER_A, "key_legacy") is not None
        # User aendert den Fakt manuell
        store1.set_fact(USER_A, "key_legacy", "ueberschrieben")
        store1.close()

        # 2. Lauf: Migration darf NICHT erneut laufen -> Wert bleibt ueberschrieben
        store2 = FactStore(db_path=db, legacy_notes_db=legacy)
        fact = store2.get_fact(USER_A, "key_legacy")
        assert fact.content == "ueberschrieben"
        store2.close()

    def test_migration_no_legacy_db(self, tmp_path):
        """Existiert notes.db nicht -> keine Migration, keine Exception."""
        db = tmp_path / "facts.db"
        legacy = tmp_path / "does_not_exist.db"
        store = FactStore(db_path=db, legacy_notes_db=legacy)
        assert store.list_facts(USER_A) == []
        store.close()

    def test_migration_idempotent_on_unique_conflict(self, tmp_path):
        """Wiederholtes Migrieren in dieselbe DB -> kein Crash (INSERT OR IGNORE)."""
        legacy = tmp_path / "notes.db"
        conn = self._create_legacy_db(legacy)
        conn.execute(
            "INSERT INTO notes (user_id, key, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                USER_A,
                "dupe",
                "value",
                "2026-01-01T10:00:00+00:00",
                "2026-01-01T10:00:00+00:00",
            ),
        )
        conn.commit()
        conn.close()

        db = tmp_path / "facts.db"
        store = FactStore(db_path=db, legacy_notes_db=legacy)
        store.close()

        # Manuell die DB loeschen aber den File-Marker simulieren:
        # wir koennen das einfach testen indem wir die interne Funktion
        # direkt nochmal aufrufen.
        store2 = FactStore(db_path=db, legacy_notes_db=legacy)
        # Direkt nochmal migrieren -> INSERT OR IGNORE schluckt Konflikt
        store2._migrate_legacy_facts(legacy)
        facts = store2.list_facts(USER_A)
        assert len(facts) == 1
        store2.close()
