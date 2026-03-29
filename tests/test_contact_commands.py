"""Tests für ContactCommandHandler (Phase 29)."""
from __future__ import annotations

from pathlib import Path

import pytest

from elder_berry.comms.commands.contact_commands import (
    CONTACT_ADD_PATTERN, CONTACT_DELETE_PATTERN, CONTACT_SEARCH_PATTERN,
    CONTACT_UPDATE_PATTERN, CONTACT_WHO_PATTERN, ContactCommandHandler,
)
from elder_berry.tools.contact_store import ContactStore

USER = "@test:matrix.org"


@pytest.fixture()
def store(tmp_path: Path) -> ContactStore:
    return ContactStore(db_path=tmp_path / "c.db")


@pytest.fixture()
def handler(store: ContactStore) -> ContactCommandHandler:
    return ContactCommandHandler(contact_store=store, default_user_id=USER)


# ── Pattern Tests ──

class TestContactAddPattern:
    def test_kontakt_with_all_fields(self) -> None:
        m = CONTACT_ADD_PATTERN.match("kontakt: Müller, Vermieter, x@y.de, förmlich")
        assert m and m.group(1) == "Müller, Vermieter, x@y.de, förmlich"

    def test_neuer_kontakt(self) -> None:
        m = CONTACT_ADD_PATTERN.match("neuer kontakt: Lisa, Schwester")
        assert m and m.group(1) == "Lisa, Schwester"

    def test_kontakt_without_email(self) -> None:
        m = CONTACT_ADD_PATTERN.match("kontakt: Dr. Weber, Zahnarzt, förmlich")
        assert m is not None

    def test_kontakt_minimal(self) -> None:
        m = CONTACT_ADD_PATTERN.match("kontakt: Max")
        assert m and m.group(1) == "Max"

    def test_no_match_kontakte(self) -> None:
        assert CONTACT_ADD_PATTERN.match("kontakte") is None


class TestContactWhoPattern:
    def test_wer_ist_name(self) -> None:
        m = CONTACT_WHO_PATTERN.match("wer ist Herr Müller?")
        assert m and m.group(1) == "Herr Müller"

    def test_wer_ist_without_question_mark(self) -> None:
        m = CONTACT_WHO_PATTERN.match("wer ist Lisa")
        assert m and m.group(1) == "Lisa"

    def test_no_match_was_ist(self) -> None:
        assert CONTACT_WHO_PATTERN.match("was ist WLAN?") is None


class TestContactSearchPattern:
    def test_kontakte_suche(self) -> None:
        m = CONTACT_SEARCH_PATTERN.match("kontakte suche Müller")
        assert m and m.group(1) == "Müller"

    def test_kontakt_suche(self) -> None:
        m = CONTACT_SEARCH_PATTERN.match("kontakt suche Zahnarzt")
        assert m and m.group(1) == "Zahnarzt"


class TestContactDeletePattern:
    def test_delete_by_id(self) -> None:
        m = CONTACT_DELETE_PATTERN.match("kontakt löschen #3")
        assert m and m.group(1) == "3"

    def test_delete_by_name(self) -> None:
        m = CONTACT_DELETE_PATTERN.match("kontakt löschen Herr Müller")
        assert m and m.group(2) == "Herr Müller"

    def test_loeschen_variation(self) -> None:
        m = CONTACT_DELETE_PATTERN.match("kontakt lösche Lisa")
        assert m is not None


class TestContactUpdatePattern:
    def test_update_by_id(self) -> None:
        m = CONTACT_UPDATE_PATTERN.search("kontakt ändern #3: email=neu@x.de")
        assert m and m.group(1) == "3"

# ── Parsing Tests ──

class TestParseContactFields:
    def test_all_fields(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Herr Müller, Vermieter, x@y.de, förmlich")
        assert r["name"] == "Herr Müller"
        assert r["role"] == "Vermieter"
        assert r["email"] == "x@y.de"
        assert r["formality"] == "förmlich"

    def test_email_detection(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Lisa, lisa@gmail.com, Schwester")
        assert r["email"] == "lisa@gmail.com"
        assert r["role"] == "Schwester"

    def test_formality_locker(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Lisa, Schwester, locker")
        assert r["formality"] == "locker"

    def test_formality_default(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Max, Kollege")
        assert r["formality"] == "förmlich"

    def test_extra_fields_to_notes(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Max, Kollege, x@y.de, hat Hund")
        assert r["notes"] == "hat Hund"


# ── Command Execution Tests ──

class TestCmdContactAdd:
    def test_add_success(self, handler: ContactCommandHandler) -> None:
        r = handler.execute("contact_add", "kontakt: Herr Müller, Vermieter, x@y.de")
        assert r.success
        assert "Herr Müller" in r.text

    def test_add_upsert(self, handler: ContactCommandHandler,
                        store: ContactStore) -> None:
        handler.execute("contact_add", "kontakt: Herr Müller, Vermieter")
        handler.execute("contact_add", "kontakt: Herr Müller, Chef")
        assert len(store.list_all(USER)) == 1

    def test_no_store(self) -> None:
        h = ContactCommandHandler(contact_store=None)
        r = h.execute("contact_add", "kontakt: Test")
        assert not r.success
        assert "nicht konfiguriert" in r.text


class TestCmdContactWho:
    def test_found(self, handler: ContactCommandHandler,
                   store: ContactStore) -> None:
        store.add(USER, "Lisa", role="Schwester")
        r = handler.execute("contact_who", "wer ist Lisa?")
        assert r.success
        assert "Lisa" in r.text

    def test_not_found_fallthrough(self, handler: ContactCommandHandler) -> None:
        r = handler.execute("contact_who", "wer ist Einstein?")
        assert not r.success
        assert r.fallthrough is True


class TestCmdContactList:
    def test_list_contacts(self, handler: ContactCommandHandler,
                           store: ContactStore) -> None:
        store.add(USER, "Alice")
        store.add(USER, "Bob")
        r = handler.execute("kontakte", "kontakte")
        assert r.success
        assert "2 Kontakte" in r.text

    def test_list_empty(self, handler: ContactCommandHandler) -> None:
        r = handler.execute("kontakte", "kontakte")
        assert r.success
        assert "Keine Kontakte" in r.text


class TestCmdContactSearch:
    def test_search_results(self, handler: ContactCommandHandler,
                            store: ContactStore) -> None:
        store.add(USER, "Herr Müller", role="Vermieter")
        r = handler.execute("contact_search", "kontakte suche Vermieter")
        assert r.success
        assert "1 Treffer" in r.text

    def test_search_no_results(self, handler: ContactCommandHandler) -> None:
        r = handler.execute("contact_search", "kontakte suche Zahnarzt")
        assert r.success
        assert "Keine Kontakte" in r.text


class TestCmdContactDelete:
    def test_delete_by_id_success(self, handler: ContactCommandHandler,
                                  store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        r = handler.execute("contact_delete", f"kontakt löschen #{c.id}")
        assert r.success
        assert "gelöscht" in r.text

    def test_delete_by_name_success(self, handler: ContactCommandHandler,
                                    store: ContactStore) -> None:
        store.add(USER, "Lisa")
        r = handler.execute("contact_delete", "kontakt löschen Lisa")
        assert r.success

    def test_delete_not_found(self, handler: ContactCommandHandler) -> None:
        r = handler.execute("contact_delete", "kontakt löschen #999")
        assert not r.success
        assert "nicht gefunden" in r.text


class TestContactKeywords:
    def test_keyword_registration(self, handler: ContactCommandHandler) -> None:
        kw = handler.keywords
        assert "kontakte" in kw
        assert "contact_add" in kw

    def test_command_descriptions(self, handler: ContactCommandHandler) -> None:
        assert len(handler.command_descriptions) >= 3


# ── Sync-Pattern Tests ──

class TestContactSyncPattern:
    def test_sync_bidirectional(self) -> None:
        from elder_berry.comms.commands.contact_commands import CONTACT_SYNC_PATTERN
        m = CONTACT_SYNC_PATTERN.match("kontakte sync")
        assert m is not None
        assert m.group(1) is None

    def test_sync_push(self) -> None:
        from elder_berry.comms.commands.contact_commands import CONTACT_SYNC_PATTERN
        m = CONTACT_SYNC_PATTERN.match("kontakte sync push")
        assert m is not None
        assert m.group(1) == "push"

    def test_sync_pull(self) -> None:
        from elder_berry.comms.commands.contact_commands import CONTACT_SYNC_PATTERN
        m = CONTACT_SYNC_PATTERN.match("kontakte sync pull")
        assert m is not None
        assert m.group(1) == "pull"

    def test_sync_singular(self) -> None:
        from elder_berry.comms.commands.contact_commands import CONTACT_SYNC_PATTERN
        m = CONTACT_SYNC_PATTERN.match("kontakt sync")
        assert m is not None


# ── Sync-Command Tests ──

class TestContactSyncCommand:
    def test_sync_no_carddav(self, store: ContactStore) -> None:
        """Kein CardDAV-Client → Fehlermeldung."""
        h = ContactCommandHandler(
            contact_store=store, default_user_id=USER,
        )
        r = h.execute("contact_sync", "kontakte sync")
        assert not r.success
        assert "nicht konfiguriert" in r.text

    def test_sync_success(self, store: ContactStore) -> None:
        """Erfolgreicher Sync mit gemocktem Client."""
        from unittest.mock import MagicMock
        from elder_berry.tools.carddav_sync import SyncResult

        mock_sync = MagicMock()
        mock_sync.sync.return_value = SyncResult(pushed=2, pulled=1)
        h = ContactCommandHandler(
            contact_store=store, default_user_id=USER,
            carddav_sync=mock_sync,
        )
        r = h.execute("contact_sync", "kontakte sync")
        assert r.success
        assert "2 gepusht" in r.text
        assert "1 gepullt" in r.text
