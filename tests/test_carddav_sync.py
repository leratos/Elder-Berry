"""Tests für CardDAVSyncClient – CardDAV-Sync für Nextcloud Contacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# vobject ist optionale Dependency – Tests überspringen wenn nicht installiert
vobject = pytest.importorskip("vobject", reason="vobject nicht installiert")

from elder_berry.tools.carddav_sync import CardDAVSyncClient, SyncResult
from elder_berry.tools.contact_store import Contact, ContactStore


# ── Fixtures ───────────────────────────────────────────────────────────


def _make_secret_store(
    url: str = "https://cloud.example.com",
    user: str = "testuser",
    password: str = "secret",
) -> MagicMock:
    store = MagicMock()
    mapping = {
        "nextcloud_url": url,
        "nextcloud_user": user,
        "nextcloud_app_password": password,
    }
    store.get_or_none.side_effect = lambda key: mapping.get(key)
    return store


def _make_contact(
    id: int = 1,
    name: str = "Herr Müller",
    emails: str = '[{"type":"home","email":"mueller@example.com"}]',
    role: str = "Vermieter",
    formality: str = "förmlich",
    notes: str = "Hat Hund namens Rex",
    birthday: str = "1970-05-15",
    phones: str = "[]",
    user_id: str = "@user:matrix.org",
    vcard_uid: str = "",
    address: str = "",
    organization: str = "",
    title: str = "",
    categories: str = "",
    nickname: str = "",
    anniversary: str = "",
    url: str = "",
) -> Contact:
    now = datetime(2026, 3, 29, 12, 0, 0, tzinfo=timezone.utc)
    return Contact(
        id=id, user_id=user_id, name=name,
        emails=emails, phones=phones,
        role=role, formality=formality, notes=notes,
        birthday=birthday, address=address,
        organization=organization, title=title,
        categories=categories, nickname=nickname,
        anniversary=anniversary, url=url,
        vcard_uid=vcard_uid,
        created_at=now, updated_at=now,
    )


@pytest.fixture
def client() -> CardDAVSyncClient:
    return CardDAVSyncClient(secret_store=_make_secret_store())


@pytest.fixture
def client_no_creds() -> CardDAVSyncClient:
    return CardDAVSyncClient(
        secret_store=_make_secret_store(url="", user="", password=""),
    )


# ── Credentials & Verfügbarkeit ────────────────────────────────────────


class TestAvailability:

    def test_is_available_success(self, client):
        mock_resp = MagicMock(status_code=207)
        with patch("elder_berry.tools.carddav_sync.httpx.request", return_value=mock_resp):
            assert client.is_available() is True

    def test_is_available_no_credentials(self, client_no_creds):
        assert client_no_creds.is_available() is False

    def test_is_available_server_unreachable(self, client):
        import httpx as _httpx
        with patch(
            "elder_berry.tools.carddav_sync.httpx.request",
            side_effect=_httpx.ConnectError("refused"),
        ):
            assert client.is_available() is False


# ── vCard-Konvertierung ────────────────────────────────────────────────


class TestContactToVCard:

    def test_full(self, client):
        contact = _make_contact()
        vcard = client._contact_to_vcard(contact)
        assert "BEGIN:VCARD" in vcard
        assert "FN:Herr Müller" in vcard
        assert "UID:elderberry-contact-1" in vcard
        assert "mueller@example.com" in vcard
        assert "BDAY:1970-05-15" in vcard
        assert "[Rolle: Vermieter]" in vcard
        assert "Hat Hund namens Rex" in vcard
        assert "X-ELDERBERRY-FORMALITY" in vcard.upper()
        assert "förmlich" in vcard

    def test_minimal(self, client):
        contact = _make_contact(
            emails="[]", role="", notes="", birthday="", formality="",
        )
        vcard = client._contact_to_vcard(contact)
        assert "FN:Herr Müller" in vcard
        assert "EMAIL" not in vcard
        assert "BDAY" not in vcard
        assert "NOTE" not in vcard

    def test_birthday_unknown_year(self, client):
        contact = _make_contact(birthday="0000-12-25")
        vcard = client._contact_to_vcard(contact)
        assert "BDAY:--12-25" in vcard

    def test_with_role_in_note(self, client):
        contact = _make_contact(role="Schwester", notes="Mag Katzen")
        vcard = client._contact_to_vcard(contact)
        assert "[Rolle: Schwester]" in vcard
        assert "Mag Katzen" in vcard

    def test_formality_extension(self, client):
        contact = _make_contact(formality="locker")
        vcard = client._contact_to_vcard(contact)
        upper = vcard.upper()
        assert "X-ELDERBERRY-FORMALITY" in upper
        assert "locker" in vcard

    def test_phone_in_vcard(self, client):
        phones = json.dumps([{"type": "cell", "number": "+49 170 1234567"}])
        contact = _make_contact(phones=phones)
        vcard = client._contact_to_vcard(contact)
        assert "TEL" in vcard
        assert "+49 170 1234567" in vcard

    def test_no_phone_no_tel(self, client):
        contact = _make_contact(phones="[]")
        vcard = client._contact_to_vcard(contact)
        assert "TEL" not in vcard


class TestVCardToDict:

    def _make_vcard(
        self,
        fn: str = "Herr Müller",
        email: str = "mueller@example.com",
        bday: str = "1970-05-15",
        note: str = "Rolle: Vermieter\nHat Hund namens Rex",
        formality: str = "förmlich",
        uid: str = "elderberry-contact-1",
        phone: str = "",
    ) -> str:
        """Baut einen gültigen vCard-String via vobject (korrektes Escaping)."""
        import vobject

        card = vobject.vCard()
        card.add("fn").value = fn
        card.add("uid").value = uid
        if email:
            card.add("email").value = email
        if phone:
            tel = card.add("tel")
            tel.value = phone
            tel.type_param = "CELL"
        if bday:
            card.add("bday").value = bday
        if note:
            card.add("note").value = note
        if formality:
            card.add("x-elderberry-formality").value = formality
        return card.serialize()

    def test_full(self, client):
        vcard = self._make_vcard()
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert data["name"] == "Herr Müller"
        emails = json.loads(data["emails"])
        assert emails[0]["email"] == "mueller@example.com"
        assert data["role"] == "Vermieter"
        assert data["notes"] == "Hat Hund namens Rex"
        assert data["formality"] == "förmlich"
        assert data["birthday"] == "1970-05-15"
        assert data["vcard_uid"] == "elderberry-contact-1"

    def test_minimal(self, client):
        vcard = self._make_vcard(
            email="", bday="", note="", formality="",
        )
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert data["name"] == "Herr Müller"
        assert json.loads(data["emails"]) == []
        assert data["birthday"] == ""
        assert data["formality"] == "förmlich"  # Default

    def test_partial_birthday(self, client):
        vcard = self._make_vcard(bday="--12-25")
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert data["birthday"] == "0000-12-25"

    def test_role_from_note(self, client):
        vcard = self._make_vcard(note="Rolle: Zahnarzt\nTermin Dienstag")
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert data["role"] == "Zahnarzt"
        assert data["notes"] == "Termin Dienstag"

    def test_formality_from_extension(self, client):
        vcard = self._make_vcard(formality="locker")
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert data["formality"] == "locker"

    def test_no_fn_returns_none(self, client):
        vcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nEMAIL:test@x.com\r\nEND:VCARD"
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is None

    def test_external_vcard_default_formality(self, client):
        """vCard ohne X-ELDERBERRY-FORMALITY → Default förmlich."""
        vcard = self._make_vcard(formality="")
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert data["formality"] == "förmlich"

    def test_phone_from_vcard(self, client):
        vcard = self._make_vcard(phone="+49 170 1234567")
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        phones = json.loads(data["phones"])
        assert phones[0]["number"] == "+49 170 1234567"

    def test_no_phone_in_vcard(self, client):
        vcard = self._make_vcard(phone="")
        data = client._vcard_to_dict(vcard, "@user:matrix.org")
        assert data is not None
        assert json.loads(data["phones"]) == []


# ── Push ───────────────────────────────────────────────────────────────


class TestPush:

    def test_push_success(self, client):
        # Kontakte ohne vcard_uid → _create_new_vcard
        contacts = [
            _make_contact(id=1),
            _make_contact(id=2, name="Lisa"),
        ]
        mock_resp = MagicMock(status_code=201)
        with patch("elder_berry.tools.carddav_sync.httpx.put", return_value=mock_resp):
            result = client.push_contacts(contacts)
        assert result.pushed == 2
        assert result.errors == []

    def test_push_server_error(self, client):
        contacts = [_make_contact()]
        mock_resp = MagicMock(status_code=500)
        with patch("elder_berry.tools.carddav_sync.httpx.put", return_value=mock_resp):
            result = client.push_contacts(contacts)
        assert result.pushed == 0

    def test_push_empty_list(self, client):
        result = client.push_contacts([])
        assert result.pushed == 0
        assert result.pulled == 0
        assert result.errors == []

    def test_push_no_credentials(self, client_no_creds):
        contacts = [_make_contact()]
        result = client_no_creds.push_contacts(contacts)
        assert result.pushed == 0
        assert len(result.errors) == 1


# ── Pull ───────────────────────────────────────────────────────────────


_PROPFIND_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/addressbooks/users/testuser/contacts/</d:href>
    <d:propstat>
      <d:prop><d:getetag>"abc"</d:getetag></d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/addressbooks/users/testuser/contacts/uid1.vcf</d:href>
    <d:propstat>
      <d:prop><d:getetag>"def"</d:getetag></d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/addressbooks/users/testuser/contacts/uid2.vcf</d:href>
    <d:propstat>
      <d:prop><d:getetag>"ghi"</d:getetag></d:prop>
    </d:propstat>
  </d:response>
</d:multistatus>"""

_VCARD_1 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Herr Müller\r\nUID:uid1\r\n"
    "EMAIL:mueller@example.com\r\nEND:VCARD"
)
_VCARD_2 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Lisa\r\nUID:uid2\r\n"
    "EMAIL:lisa@example.com\r\nEND:VCARD"
)


class TestPull:

    def test_pull_success(self, client):
        propfind_resp = MagicMock(status_code=207, text=_PROPFIND_RESPONSE)
        get_resp_1 = MagicMock(status_code=200, text=_VCARD_1)
        get_resp_2 = MagicMock(status_code=200, text=_VCARD_2)

        with patch("elder_berry.tools.carddav_sync.httpx.request", return_value=propfind_resp), \
             patch("elder_berry.tools.carddav_sync.httpx.get", side_effect=[get_resp_1, get_resp_2]):
            contacts = client.pull_contacts("@user:matrix.org")

        assert len(contacts) == 2
        names = {c["name"] for c in contacts}
        assert "Herr Müller" in names
        assert "Lisa" in names

    def test_pull_empty_addressbook(self, client):
        empty_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<d:multistatus xmlns:d="DAV:">'
            "<d:response>"
            "<d:href>/remote.php/dav/addressbooks/users/testuser/contacts/</d:href>"
            "</d:response>"
            "</d:multistatus>"
        )
        propfind_resp = MagicMock(status_code=207, text=empty_xml)
        with patch("elder_berry.tools.carddav_sync.httpx.request", return_value=propfind_resp):
            contacts = client.pull_contacts("@user:matrix.org")
        assert contacts == []

    def test_pull_skip_invalid_vcard(self, client):
        propfind_resp = MagicMock(status_code=207, text=_PROPFIND_RESPONSE)
        invalid_vcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nEMAIL:x@x.com\r\nEND:VCARD"
        get_resp_1 = MagicMock(status_code=200, text=invalid_vcard)
        get_resp_2 = MagicMock(status_code=200, text=_VCARD_2)

        with patch("elder_berry.tools.carddav_sync.httpx.request", return_value=propfind_resp), \
             patch("elder_berry.tools.carddav_sync.httpx.get", side_effect=[get_resp_1, get_resp_2]):
            contacts = client.pull_contacts("@user:matrix.org")

        assert len(contacts) == 1
        assert contacts[0]["name"] == "Lisa"


# ── Sync ───────────────────────────────────────────────────────────────


class TestSync:

    def test_sync_pulls_new_remote(self, client, tmp_path: Path):
        """NC-Kontakt fehlt lokal → Pull (Add lokal)."""
        store = ContactStore(db_path=tmp_path / "c.db")
        remote_data = [
            {"name": "Lisa", "emails": "[]", "phones": "[]",
             "role": "", "formality": "förmlich", "notes": "",
             "birthday": "", "address": "", "organization": "",
             "title": "", "categories": "", "nickname": "",
             "anniversary": "", "url": "", "vcard_uid": "uid-lisa"},
        ]
        with patch.object(client, "pull_contacts", return_value=remote_data), \
             patch.object(client, "push_contacts", return_value=SyncResult()):
            result = client.sync(store, "@user:matrix.org")
        assert result.pulled == 1
        assert store.find_by_name("@user:matrix.org", "Lisa") is not None
        store.close()

    def test_sync_updates_existing(self, client, tmp_path: Path):
        """NC-Kontakt existiert lokal → Update NC-Felder."""
        store = ContactStore(db_path=tmp_path / "c.db")
        store.add("@user:matrix.org", "Lisa", vcard_uid="uid-lisa",
                  role="Schwester")
        remote_data = [
            {"name": "Lisa", "emails": '[{"type":"home","email":"lisa@x.de"}]',
             "phones": "[]", "role": "", "formality": "förmlich", "notes": "",
             "birthday": "1990-06-15", "address": "Musterstr. 1",
             "organization": "", "title": "", "categories": "Familie",
             "nickname": "", "anniversary": "", "url": "",
             "vcard_uid": "uid-lisa"},
        ]
        with patch.object(client, "pull_contacts", return_value=remote_data), \
             patch.object(client, "push_contacts", return_value=SyncResult()):
            result = client.sync(store, "@user:matrix.org")
        assert result.updated == 1
        lisa = store.find_by_name("@user:matrix.org", "Lisa")
        # NC-Felder überschrieben
        assert lisa.email == "lisa@x.de"
        assert lisa.birthday == "1990-06-15"
        assert lisa.categories == "Familie"
        # EB-Felder beibehalten
        assert lisa.role == "Schwester"
        store.close()

    def test_sync_pushes_eb_fields(self, client, tmp_path: Path):
        """Lokaler Kontakt mit EB-Feldern → Push EB-Felder."""
        store = ContactStore(db_path=tmp_path / "c.db")
        store.add("@user:matrix.org", "Lisa", vcard_uid="uid-lisa",
                  role="Schwester", formality="locker")
        remote_data = [
            {"name": "Lisa", "emails": "[]", "phones": "[]",
             "role": "", "formality": "förmlich", "notes": "",
             "birthday": "", "address": "", "organization": "",
             "title": "", "categories": "", "nickname": "",
             "anniversary": "", "url": "", "vcard_uid": "uid-lisa"},
        ]
        with patch.object(client, "pull_contacts", return_value=remote_data), \
             patch.object(client, "push_contacts", return_value=SyncResult(pushed=1)) as mock_push:
            result = client.sync(store, "@user:matrix.org")
        assert result.pushed == 1
        mock_push.assert_called_once()
        pushed = mock_push.call_args[0][0]
        assert len(pushed) == 1
        assert pushed[0].role == "Schwester"
        store.close()

    def test_sync_passes_uid_href_map_to_push(self, client, tmp_path: Path):
        """sync() baut uid→href Map beim Pull auf und reicht sie an Push."""
        store = ContactStore(db_path=tmp_path / "c.db")
        store.add("@user:matrix.org", "Lisa", vcard_uid="uid-lisa",
                  role="Schwester")

        def fake_pull(user_id, uid_href_map=None):
            """Simuliert Pull und befüllt die Map."""
            if uid_href_map is not None:
                uid_href_map["uid-lisa"] = "/dav/contacts/ABCD.vcf"
            return [
                {"name": "Lisa", "emails": "[]", "phones": "[]",
                 "role": "", "formality": "förmlich", "notes": "",
                 "birthday": "", "address": "", "organization": "",
                 "title": "", "categories": "", "nickname": "",
                 "anniversary": "", "url": "", "vcard_uid": "uid-lisa"},
            ]

        with patch.object(client, "pull_contacts", side_effect=fake_pull), \
             patch.object(client, "push_contacts",
                          return_value=SyncResult(pushed=1)) as mock_push:
            client.sync(store, "@user:matrix.org")

        # Prüfe dass uid_href_map an push_contacts übergeben wurde
        _, kwargs = mock_push.call_args
        uid_map = kwargs.get("uid_href_map", {})
        assert "uid-lisa" in uid_map
        assert uid_map["uid-lisa"] == "/dav/contacts/ABCD.vcf"
        store.close()


# ── Address Parsing (Push) ──────────────────────────────────────────────


class TestParseAddressToVcard:

    def test_street_plz_city(self):
        adr = CardDAVSyncClient._parse_address_to_vcard(
            "Untere Eichstädtstraße 1g, 04299 Leipzig")
        assert adr.street == "Untere Eichstädtstraße 1g"
        assert adr.code == "04299"
        assert adr.city == "Leipzig"
        assert adr.country == ""

    def test_street_plz_city_country(self):
        adr = CardDAVSyncClient._parse_address_to_vcard(
            "Musterstr. 1, 10115 Berlin, Deutschland")
        assert adr.street == "Musterstr. 1"
        assert adr.code == "10115"
        assert adr.city == "Berlin"
        assert adr.country == "Deutschland"

    def test_street_city_without_plz(self):
        adr = CardDAVSyncClient._parse_address_to_vcard(
            "Main Street 5, New York")
        assert adr.street == "Main Street 5"
        assert adr.code == ""
        assert adr.city == "New York"

    def test_street_only(self):
        adr = CardDAVSyncClient._parse_address_to_vcard("Musterstraße 42")
        assert adr.street == "Musterstraße 42"
        assert adr.code == ""
        assert adr.city == ""

    def test_five_digit_plz(self):
        adr = CardDAVSyncClient._parse_address_to_vcard(
            "Hauptstr. 10, 80331 München")
        assert adr.code == "80331"
        assert adr.city == "München"

    def test_four_digit_plz(self):
        """Schweizer/AT PLZ mit 4 Stellen."""
        adr = CardDAVSyncClient._parse_address_to_vcard(
            "Bahnhofstrasse 1, 8001 Zürich")
        assert adr.code == "8001"
        assert adr.city == "Zürich"

    def test_roundtrip_preserves_data(self):
        """Push → Pull roundtrip: Adresse bleibt identisch."""
        original = "Untere Eichstädtstraße 1g, 04299 Leipzig"
        adr = CardDAVSyncClient._parse_address_to_vcard(original)
        # Simuliere Pull-Logik
        parts = []
        if adr.street:
            parts.append(adr.street)
        code_city = []
        if adr.code:
            code_city.append(adr.code)
        if adr.city:
            code_city.append(adr.city)
        if code_city:
            parts.append(" ".join(code_city))
        result = ", ".join(parts)
        assert result == original


# ── SyncResult ─────────────────────────────────────────────────────────


class TestSyncResult:

    def test_str_no_changes(self):
        assert str(SyncResult()) == "keine Änderungen"

    def test_str_with_changes(self):
        r = SyncResult(pushed=3, pulled=2, conflicts=1, errors=["err"])
        s = str(r)
        assert "3 gepusht" in s
        assert "2 gepullt" in s
        assert "1 Konflikte" in s
        assert "1 Fehler" in s
