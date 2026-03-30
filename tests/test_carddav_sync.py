"""Tests für CardDAVSyncClient – CardDAV-Sync für Nextcloud Contacts."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# vobject ist optionale Dependency – Tests überspringen wenn nicht installiert
vobject = pytest.importorskip("vobject", reason="vobject nicht installiert")

from elder_berry.tools.carddav_sync import CardDAVSyncClient, SyncResult
from elder_berry.tools.contact_store import Contact


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
    email: str = "mueller@example.com",
    role: str = "Vermieter",
    formality: str = "förmlich",
    notes: str = "Hat Hund namens Rex",
    birthday: str = "1970-05-15",
    phone: str = "",
    user_id: str = "@user:matrix.org",
) -> Contact:
    now = datetime(2026, 3, 29, 12, 0, 0, tzinfo=timezone.utc)
    return Contact(
        id=id,
        user_id=user_id,
        name=name,
        email=email,
        role=role,
        formality=formality,
        phone=phone,
        notes=notes,
        birthday=birthday,
        created_at=now,
        updated_at=now,
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
        assert "EMAIL:mueller@example.com" in vcard
        assert "BDAY:1970-05-15" in vcard
        assert "Rolle: Vermieter" in vcard
        assert "Hat Hund namens Rex" in vcard
        assert "X-ELDERBERRY-FORMALITY" in vcard.upper()
        assert "förmlich" in vcard

    def test_minimal(self, client):
        contact = _make_contact(
            email="", role="", notes="", birthday="", formality="",
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
        assert "Rolle: Schwester" in vcard
        assert "Mag Katzen" in vcard

    def test_formality_extension(self, client):
        contact = _make_contact(formality="locker")
        vcard = client._contact_to_vcard(contact)
        upper = vcard.upper()
        assert "X-ELDERBERRY-FORMALITY" in upper
        assert "locker" in vcard

    def test_phone_in_vcard(self, client):
        contact = _make_contact(phone="+49 170 1234567")
        vcard = client._contact_to_vcard(contact)
        assert "TEL" in vcard
        assert "+49 170 1234567" in vcard

    def test_no_phone_no_tel(self, client):
        contact = _make_contact(phone="")
        vcard = client._contact_to_vcard(contact)
        assert "TEL" not in vcard


class TestVCardToContact:

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
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.name == "Herr Müller"
        assert contact.email == "mueller@example.com"
        assert contact.role == "Vermieter"
        assert contact.notes == "Hat Hund namens Rex"
        assert contact.formality == "förmlich"
        assert contact.birthday == "1970-05-15"
        assert contact.id == 0
        assert contact.user_id == "@user:matrix.org"

    def test_minimal(self, client):
        vcard = self._make_vcard(
            email="", bday="", note="", formality="",
        )
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.name == "Herr Müller"
        assert contact.email == ""
        assert contact.birthday == ""
        assert contact.formality == "förmlich"  # Default

    def test_partial_birthday(self, client):
        vcard = self._make_vcard(bday="--12-25")
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.birthday == "0000-12-25"

    def test_role_from_note(self, client):
        vcard = self._make_vcard(note="Rolle: Zahnarzt\nTermin Dienstag")
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.role == "Zahnarzt"
        assert contact.notes == "Termin Dienstag"

    def test_formality_from_extension(self, client):
        vcard = self._make_vcard(formality="locker")
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.formality == "locker"

    def test_no_fn_returns_none(self, client):
        vcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nEMAIL:test@x.com\r\nEND:VCARD"
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is None

    def test_external_vcard_default_formality(self, client):
        """vCard ohne X-ELDERBERRY-FORMALITY → Default förmlich."""
        vcard = self._make_vcard(formality="")
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.formality == "förmlich"

    def test_phone_from_vcard(self, client):
        vcard = self._make_vcard(phone="+49 170 1234567")
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.phone == "+49 170 1234567"

    def test_no_phone_in_vcard(self, client):
        vcard = self._make_vcard(phone="")
        contact = client._vcard_to_contact(vcard, "@user:matrix.org")
        assert contact is not None
        assert contact.phone == ""


# ── Push ───────────────────────────────────────────────────────────────


class TestPush:

    def test_push_success(self, client):
        contacts = [_make_contact(id=1), _make_contact(id=2, name="Lisa")]
        mock_resp = MagicMock(status_code=201)
        with patch("elder_berry.tools.carddav_sync.httpx.put", return_value=mock_resp) as mock_put:
            result = client.push_contacts(contacts)
        assert result.pushed == 2
        assert result.errors == []
        assert mock_put.call_count == 2

    def test_push_server_error(self, client):
        contacts = [_make_contact()]
        mock_resp = MagicMock(status_code=500)
        with patch("elder_berry.tools.carddav_sync.httpx.put", return_value=mock_resp):
            result = client.push_contacts(contacts)
        assert result.pushed == 0
        assert len(result.errors) == 1
        assert "HTTP 500" in result.errors[0]

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
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Herr Müller\r\n"
    "EMAIL:mueller@example.com\r\nEND:VCARD"
)
_VCARD_2 = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Lisa\r\n"
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
        names = {c.name for c in contacts}
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
        # Erste vCard ist ungültig (kein FN), zweite ist ok
        invalid_vcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nEMAIL:x@x.com\r\nEND:VCARD"
        get_resp_1 = MagicMock(status_code=200, text=invalid_vcard)
        get_resp_2 = MagicMock(status_code=200, text=_VCARD_2)

        with patch("elder_berry.tools.carddav_sync.httpx.request", return_value=propfind_resp), \
             patch("elder_berry.tools.carddav_sync.httpx.get", side_effect=[get_resp_1, get_resp_2]):
            contacts = client.pull_contacts("@user:matrix.org")

        assert len(contacts) == 1
        assert contacts[0].name == "Lisa"


# ── Sync ───────────────────────────────────────────────────────────────


class TestSync:

    def _mock_contact_store(self, contacts: list[Contact]) -> MagicMock:
        store = MagicMock()
        store.list_all.return_value = contacts
        store.add.side_effect = lambda user_id, **kw: _make_contact(
            id=99, name=kw.get("name", "?"), user_id=user_id,
        )
        return store

    def test_sync_new_local_pushed(self, client):
        """Lokaler Kontakt fehlt in NC → Push."""
        local = [_make_contact(id=1, name="Herr Müller")]
        store = self._mock_contact_store(local)

        # Pull liefert leeres Adressbuch
        with patch.object(client, "pull_contacts", return_value=[]), \
             patch.object(client, "push_contacts", return_value=SyncResult(pushed=1)) as mock_push:
            result = client.sync(store, "@user:matrix.org")

        assert result.pushed == 1
        mock_push.assert_called_once()
        pushed_contacts = mock_push.call_args[0][0]
        assert len(pushed_contacts) == 1
        assert pushed_contacts[0].name == "Herr Müller"

    def test_sync_new_remote_pulled(self, client):
        """NC-Kontakt fehlt lokal → Pull (Add lokal)."""
        store = self._mock_contact_store([])  # Lokal leer
        remote = [_make_contact(id=0, name="Lisa", user_id="@user:matrix.org")]

        with patch.object(client, "pull_contacts", return_value=remote), \
             patch.object(client, "push_contacts", return_value=SyncResult()):
            result = client.sync(store, "@user:matrix.org")

        assert result.pulled == 1
        store.add.assert_called_once()
        call_kw = store.add.call_args
        assert call_kw[1]["name"] == "Lisa"

    def test_sync_local_newer_pushes(self, client):
        """Lokal und Remote vorhanden, Felder unterschiedlich → Push (lokal gewinnt)."""
        local = [_make_contact(id=1, name="Herr Müller", email="new@example.com")]
        remote = [_make_contact(id=0, name="Herr Müller", email="old@example.com")]
        store = self._mock_contact_store(local)

        with patch.object(client, "pull_contacts", return_value=remote), \
             patch.object(client, "push_contacts", return_value=SyncResult(pushed=1)) as mock_push:
            result = client.sync(store, "@user:matrix.org")

        assert result.pushed == 1
        assert result.conflicts == 1

    def test_sync_remote_newer_pulls(self, client):
        """Remote hat neue Daten, lokal alt → lokal gewinnt trotzdem (SQLite primär)."""
        local = [_make_contact(id=1, name="Herr Müller", email="old@example.com")]
        remote = [_make_contact(id=0, name="Herr Müller", email="old@example.com")]
        store = self._mock_contact_store(local)

        with patch.object(client, "pull_contacts", return_value=remote), \
             patch.object(client, "push_contacts", return_value=SyncResult()):
            result = client.sync(store, "@user:matrix.org")

        # Gleiche Felder → kein Conflict, kein Push
        assert result.conflicts == 0
        assert result.pushed == 0

    def test_sync_both_same_skips(self, client):
        """Gleicher Stand → kein Update."""
        contact = _make_contact(id=1, name="Herr Müller")
        remote = _make_contact(id=0, name="Herr Müller")
        store = self._mock_contact_store([contact])

        with patch.object(client, "pull_contacts", return_value=[remote]), \
             patch.object(client, "push_contacts", return_value=SyncResult()):
            result = client.sync(store, "@user:matrix.org")

        assert result.pushed == 0
        assert result.pulled == 0
        assert result.conflicts == 0


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
