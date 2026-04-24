"""Tests für ActionsDB."""
import sqlite3

import pytest

from elder_berry.actions.db import ActionsDB


@pytest.fixture
def db(tmp_path):
    """In-memory-ähnliche DB in einem Temp-Verzeichnis."""
    return ActionsDB(db_path=tmp_path / "test_actions.db")


class TestActionsDB:
    def test_add_and_get(self, db):
        db.add("öffne browser", "open_app", "chrome")
        action = db.get("öffne browser")
        assert action is not None
        assert action.action_type == "open_app"
        assert action.action_payload == "chrome"
        assert action.use_count == 0

    def test_trigger_normalized_to_lowercase(self, db):
        db.add("ÖFFNE BROWSER", "open_app", "chrome")
        assert db.get("öffne browser") is not None

    def test_get_nonexistent_returns_none(self, db):
        assert db.get("unbekannter befehl") is None

    def test_record_use_increments_count(self, db):
        db.add("zeig uhrzeit", "tts", "")
        db.record_use("zeig uhrzeit")
        db.record_use("zeig uhrzeit")
        action = db.get("zeig uhrzeit")
        assert action.use_count == 2
        assert action.last_used is not None

    def test_update_payload(self, db):
        db.add("teste aktion", "ollama_query", "alt")
        db.update_payload("teste aktion", "neu")
        assert db.get("teste aktion").action_payload == "neu"

    def test_delete(self, db):
        db.add("lösch mich", "tts", "")
        db.delete("lösch mich")
        assert db.get("lösch mich") is None

    def test_list_all(self, db):
        db.add("cmd1", "open_app", "")
        db.add("cmd2", "tts", "")
        assert len(db.list_all()) == 2

    def test_top_actions_sorted_by_use_count(self, db):
        db.add("selten", "tts", "")
        db.add("häufig", "tts", "")
        db.record_use("häufig")
        db.record_use("häufig")
        db.record_use("häufig")
        top = db.top_actions(n=1)
        assert top[0].trigger == "häufig"

    def test_duplicate_trigger_raises(self, db):
        db.add("doppelt", "tts", "")
        with pytest.raises(sqlite3.IntegrityError):
            db.add("doppelt", "open_app", "")
