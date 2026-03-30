"""Tests für ContactCommandHandler (Phase 29)."""
from __future__ import annotations

from pathlib import Path

import pytest

from elder_berry.comms.commands.contact_commands import (
    CONTACT_ADD_PATTERN, CONTACT_DELETE_PATTERN, CONTACT_LOOKUP_PATTERN,
    CONTACT_SEARCH_PATTERN, CONTACT_UPDATE_PATTERN, CONTACT_WHO_PATTERN,
    ContactCommandHandler,
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

    def test_update_without_hash(self) -> None:
        m = CONTACT_UPDATE_PATTERN.search("kontakt ändern 20: rolle=Freundin")
        assert m and m.group(1) == "20"

    def test_update_with_bearbeiten(self) -> None:
        m = CONTACT_UPDATE_PATTERN.search("kontakt bearbeiten #20: name=Lisa")
        assert m and m.group(1) == "20"

    def test_update_with_update(self) -> None:
        m = CONTACT_UPDATE_PATTERN.search("kontakt update #5: email=a@b.de")
        assert m and m.group(1) == "5"

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


# ── Bug 1: Pattern-Priorität ──

class TestPatternPriority:
    def test_update_not_matched_as_add(self) -> None:
        """'kontakt ändern #20: rolle=Freundin' darf NICHT als ADD matchen."""
        text = "kontakt ändern #20: rolle=Freundin"
        assert CONTACT_ADD_PATTERN.match(text) is None
        assert CONTACT_UPDATE_PATTERN.search(text) is not None

    def test_add_still_works(self) -> None:
        """Regression: 'kontakt: Lisa, Freundin' muss weiterhin als ADD matchen."""
        m = CONTACT_ADD_PATTERN.match("kontakt: Lisa, Freundin")
        assert m and m.group(1) == "Lisa, Freundin"

    def test_pattern_priority_update_before_add(self) -> None:
        """Update-Pattern muss VOR Add-Pattern in der Liste stehen."""
        h = ContactCommandHandler()
        names = [name for _, name, _, _ in h.patterns]
        assert names.index("contact_update") < names.index("contact_add")

    def test_update_command_executed(self, handler: ContactCommandHandler,
                                    store: ContactStore) -> None:
        """'kontakt ändern #ID: rolle=X' muss als Update ausgeführt werden."""
        c = store.add(USER, "Lisa", role="Schwester")
        r = handler.execute("contact_update",
                            f"kontakt ändern #{c.id}: rolle=Freundin")
        assert r.success
        assert "Aktualisiert" in r.text
        updated = store.get_by_id(c.id)
        assert updated.role == "Freundin"


# ── Bug 2: Formality ──

class TestFormalityExtended:
    def test_formality_persoenlich(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Lisa, persönlich")
        assert r["formality"] == "locker"

    def test_formality_freundschaftlich(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Max, freundschaftlich")
        assert r["formality"] == "locker"

    def test_formality_hoeflich(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Herr Dr. Müller, höflich")
        assert r["formality"] == "förmlich"

    def test_formality_casual(self) -> None:
        h = ContactCommandHandler()
        r = h._parse_contact_fields("Tom, casual")
        assert r["formality"] == "locker"


# ── Bug 3: Feld-Aliase ──

class TestFieldAliases:
    def test_resolve_vermerk(self) -> None:
        assert ContactCommandHandler._resolve_field_key("vermerk") == "notes"

    def test_resolve_mail(self) -> None:
        assert ContactCommandHandler._resolve_field_key("mail") == "email"

    def test_resolve_startswith(self) -> None:
        assert ContactCommandHandler._resolve_field_key("noti") == "notes"

    def test_resolve_unknown(self) -> None:
        assert ContactCommandHandler._resolve_field_key("xyz") is None

    def test_update_field_alias_vermerk(self, handler: ContactCommandHandler,
                                        store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        r = handler.execute("contact_update",
                            f"kontakt ändern #{c.id}: vermerk=Lieblingsfarbe rot")
        assert r.success
        updated = store.get_by_id(c.id)
        assert updated.notes == "Lieblingsfarbe rot"

    def test_update_field_alias_mail(self, handler: ContactCommandHandler,
                                     store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        r = handler.execute("contact_update",
                            f"kontakt ändern #{c.id}: mail=lisa@x.de")
        assert r.success
        updated = store.get_by_id(c.id)
        assert updated.email == "lisa@x.de"

    def test_update_unknown_field_warning(self, handler: ContactCommandHandler,
                                          store: ContactStore) -> None:
        c = store.add(USER, "Lisa")
        r = handler.execute("contact_update",
                            f"kontakt ändern #{c.id}: noitzen=xyz")
        assert r.success
        assert "Unbekanntes Feld" in r.text
        assert "noitzen" in r.text


# ── Bug 4: Update ohne # ──

class TestUpdateWithoutHash:
    def test_update_without_hash_execution(self, handler: ContactCommandHandler,
                                           store: ContactStore) -> None:
        c = store.add(USER, "Lisa", role="Schwester")
        r = handler.execute("contact_update",
                            f"kontakt ändern {c.id}: rolle=Freundin")
        assert r.success
        updated = store.get_by_id(c.id)
        assert updated.role == "Freundin"


# ── Bug 5: Lookup-Pattern ──

class TestContactLookupPattern:
    def test_lookup_by_id(self) -> None:
        m = CONTACT_LOOKUP_PATTERN.match("kontakt #20")
        assert m is not None
        assert m.group(3) == "20"

    def test_lookup_was_weisst_du(self) -> None:
        m = CONTACT_LOOKUP_PATTERN.match("was weisst du zu Lisa")
        assert m is not None
        assert m.group(1) == "Lisa"

    def test_lookup_was_weisst_du_ueber(self) -> None:
        m = CONTACT_LOOKUP_PATTERN.match("was weisst du über meinen Kontakt Lisa")
        assert m is not None
        assert m.group(1) == "Lisa"

    def test_lookup_zeig_mir(self) -> None:
        m = CONTACT_LOOKUP_PATTERN.match("zeig mir kontakt #20")
        assert m is not None

    def test_lookup_info_zu(self) -> None:
        m = CONTACT_LOOKUP_PATTERN.match("info zu kontakt Lisa")
        assert m is not None

    def test_lookup_not_collide_with_add(self) -> None:
        """'kontakt: Lisa, Freundin' darf NICHT als Lookup matchen."""
        assert CONTACT_LOOKUP_PATTERN.match("kontakt: Lisa, Freundin") is None


class TestCmdContactLookup:
    def test_lookup_by_id(self, handler: ContactCommandHandler,
                          store: ContactStore) -> None:
        c = store.add(USER, "Lisa", role="Freundin", email="lisa@x.de")
        r = handler.execute("contact_lookup", f"kontakt #{c.id}")
        assert r.success
        assert "Lisa" in r.text
        assert "Rolle: Freundin" in r.text

    def test_lookup_by_name(self, handler: ContactCommandHandler,
                            store: ContactStore) -> None:
        store.add(USER, "Lisa", role="Freundin")
        r = handler.execute("contact_lookup", "was weisst du zu Lisa")
        assert r.success
        assert "Lisa" in r.text

    def test_lookup_not_found(self, handler: ContactCommandHandler) -> None:
        r = handler.execute("contact_lookup", "kontakt #999")
        assert not r.success
        assert r.fallthrough is True


# ── Bug 6: Detail-Ausgabe ──

class TestDetailOutput:
    def test_who_shows_detail(self, handler: ContactCommandHandler,
                              store: ContactStore) -> None:
        store.add(USER, "Lisa", role="Freundin", email="lisa@x.de",
                  formality="locker", notes="wichtig")
        r = handler.execute("contact_who", "wer ist Lisa?")
        assert r.success
        assert "Rolle: Freundin" in r.text
        assert "Email: lisa@x.de" in r.text
        assert "Anrede: locker" in r.text
        assert "📝 wichtig" in r.text

    def test_lookup_shows_detail(self, handler: ContactCommandHandler,
                                 store: ContactStore) -> None:
        c = store.add(USER, "Herr Müller", role="Vermieter",
                      email="m@x.de", formality="förmlich")
        r = handler.execute("contact_lookup", f"kontakt #{c.id}")
        assert r.success
        assert "Rolle: Vermieter" in r.text
        assert "Email: m@x.de" in r.text
        assert "Anrede: förmlich" in r.text
