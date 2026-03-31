"""Tests für CardDAVSyncClient (Phase 38 Vollintegration)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# vobject ist optionale Dependency – Tests überspringen wenn nicht installiert
pytest.importorskip("vobject", reason="vobject nicht installiert")

from elder_berry.tools.carddav_sync import CardDAVSyncClient, SyncResult
from elder_berry.tools.contact_store import Contact, ContactStore

USER = "@test:matrix.org"


@pytest.fixture()
def store(tmp_path: Path) -> ContactStore:
    db = tmp_path / "contacts.db"
    s = ContactStore(db_path=db)
    yield s
    s.close()


@pytest.fixture()
def mock_secret_store() -> MagicMock:
    ss = MagicMock()
    ss.get_or_none.side_effect = lambda key: {
        "nextcloud_url": "https://nc.example.com",
        "nextcloud_user": "testuser",
        "nextcloud_app_password": "secret123",
    }.get(key)
    return ss


class TestSyncResult:
    def test_str_empty(self) -> None:
        r = SyncResult()
        assert str(r) == "keine Änderungen"

    def test_str_full(self) -> None:
        r = SyncResult(pushed=2, pulled=3, updated=1, deleted=5, conflicts=1)
        text = str(r)
        assert "2 gepusht" in text
        assert "3 gepullt" in text
        assert "1 aktualisiert" in text
        assert "5 gelöscht" in text

    def test_str_with_errors(self) -> None:
        r = SyncResult(errors=["err1", "err2"])
        assert "2 Fehler" in str(r)


class TestVcardToDict:
    """Testet das Parsen von vCards in Dicts."""

    def test_basic_vcard(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Lisa Müller\r\n"
            "UID:abc-123\r\n"
            "EMAIL;TYPE=HOME:lisa@gmail.com\r\n"
            "TEL;TYPE=CELL:+49 170 1234567\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data is not None
        assert data["name"] == "Lisa Müller"
        assert data["vcard_uid"] == "abc-123"
        emails = json.loads(data["emails"])
        assert len(emails) == 1
        assert emails[0]["email"] == "lisa@gmail.com"
        phones = json.loads(data["phones"])
        assert len(phones) == 1
        assert phones[0]["number"] == "+49 170 1234567"

    def test_multiple_tel_email(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Max\r\n"
            "UID:uid-multi\r\n"
            "EMAIL;TYPE=WORK:work@acme.de\r\n"
            "EMAIL;TYPE=HOME:home@privat.de\r\n"
            "TEL;TYPE=CELL:+49 170 111\r\n"
            "TEL;TYPE=HOME:+49 30 222\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data is not None
        emails = json.loads(data["emails"])
        assert len(emails) == 2
        assert emails[0]["type"] == "work"
        assert emails[1]["type"] == "home"
        phones = json.loads(data["phones"])
        assert len(phones) == 2

    def test_address_parsing(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Herr Müller\r\n"
            "UID:uid-adr\r\n"
            "ADR:;;Musterstr. 42;Berlin;;10115;Germany\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data is not None
        assert "Musterstr. 42" in data["address"]
        assert "Berlin" in data["address"]

    def test_org_title(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Max\r\n"
            "UID:uid-org\r\n"
            "ORG:Acme Corp\r\n"
            "TITLE:Software Engineer\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data is not None
        assert data["organization"] == "Acme Corp"
        assert data["title"] == "Software Engineer"

    def test_categories(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Lisa\r\n"
            "UID:uid-cat\r\n"
            "CATEGORIES:Familie,Freunde\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data is not None
        assert "Familie" in data["categories"]
        assert "Freunde" in data["categories"]

    def test_nickname(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Maximilian\r\n"
            "UID:uid-nick\r\n"
            "NICKNAME:Maxi\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data is not None
        assert data["nickname"] == "Maxi"

    def test_birthday_full(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Lisa\r\n"
            "UID:uid-bday\r\n"
            "BDAY:1990-06-15\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data["birthday"] == "1990-06-15"

    def test_birthday_partial(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Lisa\r\n"
            "UID:uid-bday2\r\n"
            "BDAY:--06-15\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data["birthday"] == "0000-06-15"

    def test_url(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Max\r\n"
            "UID:uid-url\r\n"
            "URL:https://max.example.com\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data["url"] == "https://max.example.com"

    def test_eb_fields_from_note(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        # In vCard, newlines within values are escaped as \n (literal backslash-n)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Lisa\r\n"
            "UID:uid-eb\r\n"
            "NOTE:Rolle: Schwester\\nhat Hund\r\n"
            "X-ELDERBERRY-FORMALITY:locker\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(vcard, USER)
        assert data["role"] == "Schwester"
        assert data["notes"] == "hat Hund"
        assert data["formality"] == "locker"

    def test_empty_fn_returns_none(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:\r\n"
            "END:VCARD\r\n"
        )
        assert client._vcard_to_dict(vcard, USER) is None


class TestContactToVcard:
    """Testet die Konvertierung Contact → vCard."""

    def test_basic_contact(self, mock_secret_store: MagicMock) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        now = datetime.now(timezone.utc)
        contact = Contact(
            id=1, user_id=USER, name="Lisa",
            emails='[{"type":"home","email":"lisa@x.de"}]',
            phones='[{"type":"cell","number":"+49 170 111"}]',
            role="Freundin", formality="locker", notes="mag Katzen",
            birthday="1990-06-15", address="Musterstr. 42",
            organization="", title="", categories="Familie",
            nickname="", anniversary="", url="",
            vcard_uid="", created_at=now, updated_at=now,
        )
        vcard_str = client._contact_to_vcard(contact)
        assert "FN:Lisa" in vcard_str
        assert "lisa@x.de" in vcard_str
        assert "+49 170 111" in vcard_str
        assert "Rolle: Freundin" in vcard_str
        assert "CATEGORIES:" in vcard_str

    def test_roundtrip(self, mock_secret_store: MagicMock) -> None:
        """vCard → Dict → Contact → vCard Roundtrip."""
        client = CardDAVSyncClient(mock_secret_store)
        original = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Max Mustermann\r\n"
            "UID:roundtrip-1\r\n"
            "EMAIL;TYPE=WORK:max@acme.de\r\n"
            "TEL;TYPE=CELL:+49 170 999\r\n"
            "ORG:Acme Corp\r\n"
            "TITLE:CTO\r\n"
            "BDAY:1985-03-20\r\n"
            "NOTE:Rolle: Chef\\nGuter Typ\r\n"
            "X-ELDERBERRY-FORMALITY:locker\r\n"
            "END:VCARD\r\n"
        )
        data = client._vcard_to_dict(original, USER)
        assert data is not None
        assert data["name"] == "Max Mustermann"
        assert data["organization"] == "Acme Corp"
        assert data["role"] == "Chef"
        assert data["notes"] == "Guter Typ"


class TestResetAndPull:
    """Tests für die Clean-Slate-Migration."""

    def test_reset_deletes_and_pulls(
        self, store: ContactStore, mock_secret_store: MagicMock,
    ) -> None:
        # Lokale Kontakte anlegen
        store.add(USER, "Alt1")
        store.add(USER, "Alt2")
        assert len(store.list_all(USER)) == 2

        client = CardDAVSyncClient(mock_secret_store)

        # Mock pull_contacts um Remote-Daten zurückzugeben
        remote_data = [
            {"name": "Neu1", "emails": "[]", "phones": "[]",
             "role": "", "formality": "förmlich", "notes": "",
             "birthday": "", "address": "", "organization": "",
             "title": "", "categories": "", "nickname": "",
             "anniversary": "", "url": "", "vcard_uid": "uid-1"},
            {"name": "Neu2", "emails": "[]", "phones": "[]",
             "role": "", "formality": "förmlich", "notes": "",
             "birthday": "", "address": "", "organization": "",
             "title": "", "categories": "", "nickname": "",
             "anniversary": "", "url": "", "vcard_uid": "uid-2"},
        ]
        with patch.object(client, "pull_contacts", return_value=remote_data):
            result = client.reset_and_pull(store, USER)

        assert result.deleted == 2
        assert result.pulled == 2
        contacts = store.list_all(USER)
        assert len(contacts) == 2
        names = {c.name for c in contacts}
        assert names == {"Neu1", "Neu2"}


class TestInjectEBFields:
    """Testet das Einfügen von EB-Feldern in bestehende vCards."""

    def test_inject_role_and_formality(
        self, mock_secret_store: MagicMock,
    ) -> None:
        client = CardDAVSyncClient(mock_secret_store)
        now = datetime.now(timezone.utc)
        contact = Contact(
            id=1, user_id=USER, name="Lisa",
            emails="[]", phones="[]",
            role="Schwester", formality="locker", notes="mag Katzen",
            birthday="", address="", organization="", title="",
            categories="", nickname="", anniversary="", url="",
            vcard_uid="", created_at=now, updated_at=now,
        )
        original_vcard = (
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            "FN:Lisa\r\n"
            "UID:test-123\r\n"
            "END:VCARD\r\n"
        )
        result = client._inject_eb_fields(original_vcard, contact)
        assert "Rolle: Schwester" in result
        assert "mag Katzen" in result
        assert "X-ELDERBERRY-FORMALITY" in result.upper()
        assert "locker" in result
        # Originale FN muss erhalten bleiben
        assert "FN:Lisa" in result
