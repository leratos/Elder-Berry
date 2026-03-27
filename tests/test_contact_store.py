"""Tests für ContactStore (Phase 29)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from elder_berry.tools.contact_store import Contact, ContactStore

USER = "@test:matrix.org"
USER_B = "@other:matrix.org"


@pytest.fixture()
def store(tmp_path: Path) -> ContactStore:
    db = tmp_path / "contacts.db"
    s = ContactStore(db_path=db)
    yield s
    s.close()


class TestAddAndFind:
    def test_add_and_find_by_name(self, store: ContactStore) -> None:
        c = store.add(USER, "Herr Müller", role="Vermieter")
        assert c.name == "Herr Müller"
        found = store.find_by_name(USER, "herr müller")
        assert found is not None
        assert found.id == c.id

    def test_add_and_find_by_email(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa", email="lisa@gmail.com")
        found = store.find_by_email(USER, "lisa@gmail.com")
        assert found is not None
        assert found.id == c.id

    def test_find_by_email_case_insensitive(self, store: ContactStore) -> None:
        store.add(USER, "Max", email="max@x.de")
        found = store.find_by_email(USER, "MAX@X.DE")
        assert found is not None
        assert found.name == "Max"

    def test_upsert_by_name(self, store: ContactStore) -> None:
        c1 = store.add(USER, "Herr Müller", role="Vermieter")
        c2 = store.add(USER, "Herr Müller", email="neu@x.de")
        assert c2.id == c1.id
        assert c2.email == "neu@x.de"
        assert c2.role == "Vermieter"  # beibehalten

    def test_upsert_keeps_existing_fields(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", email="a@b.de", role="Schwester",
                  formality="locker", notes="mag Katzen")
        updated = store.add(USER, "Lisa", email="new@b.de")
        assert updated.email == "new@b.de"
        assert updated.role == "Schwester"
        assert updated.formality == "locker"
        assert updated.notes == "mag Katzen"

    def test_update_by_id(self, store: ContactStore) -> None:
        c = store.add(USER, "Dr. Weber", role="Zahnarzt")
        updated = store.update(c.id, email="dr@weber.de")
        assert updated is not None
        assert updated.email == "dr@weber.de"
        assert updated.role == "Zahnarzt"

    def test_update_nonexistent(self, store: ContactStore) -> None:
        assert store.update(9999, name="Ghost") is None


class TestSearch:
    def test_search_fts(self, store: ContactStore) -> None:
        store.add(USER, "Herr Müller", role="Vermieter")
        store.add(USER, "Lisa", role="Schwester")
        results = store.search(USER, "Vermieter")
        assert len(results) == 1
        assert results[0].name == "Herr Müller"

    def test_search_no_results(self, store: ContactStore) -> None:
        store.add(USER, "Lisa", role="Schwester")
        assert store.search(USER, "Zahnarzt") == []


class TestListAll:
    def test_list_all(self, store: ContactStore) -> None:
        store.add(USER, "B-Name")
        store.add(USER, "A-Name")
        contacts = store.list_all(USER)
        assert len(contacts) == 2
        assert contacts[0].name == "A-Name"

    def test_list_all_empty(self, store: ContactStore) -> None:
        assert store.list_all(USER) == []


class TestDelete:
    def test_delete_by_id(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        assert store.delete(c.id) is True
        assert store.get_by_id(c.id) is None

    def test_delete_by_id_not_found(self, store: ContactStore) -> None:
        assert store.delete(9999) is False

    def test_delete_by_name(self, store: ContactStore) -> None:
        store.add(USER, "Herr Müller")
        assert store.delete_by_name(USER, "Herr Müller") is True
        assert store.find_by_name(USER, "Herr Müller") is None

    def test_delete_by_name_case_insensitive(self, store: ContactStore) -> None:
        store.add(USER, "Herr Müller")
        assert store.delete_by_name(USER, "herr müller") is True


class TestDefaults:
    def test_formality_default(self, store: ContactStore) -> None:
        c = store.add(USER, "Max")
        assert c.formality == "förmlich"

    def test_unique_name_upsert(self, store: ContactStore) -> None:
        store.add(USER, "Max", role="Freund")
        store.add(USER, "Max", role="Kollege")
        assert len(store.list_all(USER)) == 1


class TestFormat:
    def test_format_short(self, store: ContactStore) -> None:
        c = store.add(USER, "Herr Müller", role="Vermieter",
                      email="x@y.de", formality="förmlich")
        s = c.format_short()
        assert "Herr Müller" in s
        assert "Vermieter" in s
        assert "x@y.de" in s

    def test_format_for_llm(self, store: ContactStore) -> None:
        c = store.add(USER, "Lisa", role="Schwester",
                      formality="locker", notes="mag Katzen")
        llm = c.format_for_llm()
        assert "Kontakt: Lisa" in llm
        assert "Beziehung: Schwester" in llm
        assert "Du" in llm
        assert "mag Katzen" in llm


class TestMultiUser:
    def test_multi_user_isolation(self, store: ContactStore) -> None:
        store.add(USER, "Alice")
        store.add(USER_B, "Bob")
        assert len(store.list_all(USER)) == 1
        assert len(store.list_all(USER_B)) == 1
        assert store.find_by_name(USER, "Bob") is None


class TestClose:
    def test_close(self, tmp_path: Path) -> None:
        s = ContactStore(db_path=tmp_path / "c.db")
        s.add(USER, "Test")
        s.close()
        # Zweites close sollte nicht crashen
        s.close()
